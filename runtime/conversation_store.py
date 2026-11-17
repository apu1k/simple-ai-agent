"""Chat-scoped state on one SQLite connection and one backend writer lease."""
from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from typing import Any

from editing.model import FileEdit, PendingEdit
from runtime.chat_store import ChatStore
from runtime.persistence import PersistenceError, RuntimeStore, _encode, validate_checkpoint


def validate_chat_id(identity: str) -> str:
    if (not isinstance(identity, str) or len(identity) != 32
            or any(c not in "0123456789abcdef" for c in identity)):
        raise ValueError("Invalid chat ID")
    return identity


class ConversationStorage:
    def __init__(self, path: Path, history: ChatStore):
        self.root = RuntimeStore(path)
        try:
            with self.root.transaction() as db:
                db.execute("CREATE TABLE IF NOT EXISTS chat_checkpoints (chat_id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
                db.execute("CREATE TABLE IF NOT EXISTS chat_proposals (chat_id TEXT NOT NULL, id INTEGER NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(chat_id,id))")
                db.execute("CREATE TABLE IF NOT EXISTS chat_executions (chat_id TEXT NOT NULL, id TEXT NOT NULL, run_id TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(chat_id,id))")
                db.execute("CREATE TABLE IF NOT EXISTS chat_runs (chat_id TEXT NOT NULL, id TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(chat_id,id))")
                db.execute("CREATE TABLE IF NOT EXISTS conversation_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
                legacy = db.execute("SELECT payload FROM checkpoint WHERE id=1").fetchone()
                if legacy is not None:
                    if db.execute("SELECT 1 FROM chat_checkpoints LIMIT 1").fetchone():
                        raise PersistenceError("Both legacy and multi-chat checkpoints exist; inspect storage")
                    saved = json.loads(legacy[0])
                    validate_checkpoint(saved)
                    identity = saved["chat_session_id"] or history.new_session(title="Recovered conversation")
                    validate_chat_id(identity)
                    saved["chat_session_id"] = identity
                    db.execute("INSERT INTO chat_checkpoints VALUES (?,?)", (identity, _encode(saved)))
                    db.execute("INSERT INTO chat_proposals SELECT ?,id,payload FROM proposals", (identity,))
                    db.execute("INSERT INTO chat_executions SELECT ?,id,run_id,payload FROM executions", (identity,))
                    db.execute("INSERT INTO chat_runs SELECT ?,id,payload FROM runs", (identity,))
                    db.execute("INSERT OR REPLACE INTO conversation_meta VALUES ('default_chat',?)", (identity,))
                    for table in ("checkpoint", "proposals", "executions", "runs"):
                        db.execute(f"DELETE FROM {table}")
                elif any(db.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone()
                         for table in ("proposals", "executions", "runs")):
                    raise PersistenceError("Legacy execution/proposal evidence has no checkpoint; inspect storage")
                # Validate every chat before any runtime performs recovery writes.
                for identity, payload in db.execute("SELECT chat_id,payload FROM chat_checkpoints"):
                    validate_chat_id(identity)
                    saved = json.loads(payload)
                    validate_checkpoint(saved)
                    if saved["chat_session_id"] != identity:
                        raise PersistenceError("Checkpoint belongs to another chat")
                db.execute("PRAGMA user_version=2")
        except Exception:
            self.root.close()
            raise

    def ids(self) -> list[str]:
        with self.root.transaction() as db:
            return [row[0] for row in db.execute("SELECT chat_id FROM chat_checkpoints ORDER BY rowid")]

    def default_chat(self) -> str | None:
        with self.root.transaction() as db:
            row = db.execute("SELECT value FROM conversation_meta WHERE key='default_chat'").fetchone()
            return validate_chat_id(row[0]) if row else None

    def set_default(self, identity: str) -> None:
        validate_chat_id(identity)
        with self.root.transaction() as db:
            db.execute("INSERT OR REPLACE INTO conversation_meta VALUES ('default_chat',?)", (identity,))

    def scope(self, identity: str) -> ChatRuntimeStore:
        return ChatRuntimeStore(self.root, validate_chat_id(identity))

    def close(self) -> None:
        self.root.close()


class ChatRuntimeStore:
    """A runtime cannot read or overwrite another chat's numeric proposal IDs."""

    def __init__(self, root: RuntimeStore, identity: str):
        self.root, self.identity = root, identity

    def transaction(self):
        return self.root.transaction()

    def check(self) -> None:
        self.root.check()

    def load(self) -> dict[str, Any] | None:
        with self.transaction() as db:
            row = db.execute("SELECT payload FROM chat_checkpoints WHERE chat_id=?", (self.identity,)).fetchone()
            return json.loads(row[0]) if row else None

    def save(self, checkpoint: dict[str, Any]) -> None:
        if checkpoint["chat_session_id"] != self.identity:
            raise PersistenceError("Refusing to move runtime state between chats")
        with self.transaction() as db:
            db.execute("INSERT OR REPLACE INTO chat_checkpoints VALUES (?,?)", (self.identity, _encode(checkpoint)))
            if checkpoint.get("run"):
                run = dict(checkpoint["run"], session_id=self.identity)
                db.execute("INSERT OR REPLACE INTO chat_runs VALUES (?,?,?)", (self.identity, run["run_id"], _encode(run)))

    def save_proposal(self, proposal: PendingEdit) -> None:
        with self.transaction() as db:
            db.execute("INSERT OR REPLACE INTO chat_proposals VALUES (?,?,?)", (self.identity, proposal.id, _encode(asdict(proposal))))

    def recover_proposals(self) -> list[PendingEdit]:
        with self.transaction() as db:
            proposals = []
            rows = db.execute("SELECT payload FROM chat_proposals WHERE chat_id=? ORDER BY id", (self.identity,)).fetchall()
            for (payload,) in rows:
                item = json.loads(payload)
                if item["status"] == "applying":
                    item["status"] = "outcome_unknown"
                    db.execute("UPDATE chat_proposals SET payload=? WHERE chat_id=? AND id=?", (_encode(item), self.identity, item["id"]))
                item["path"] = Path(item["path"])
                if item["destination_path"] is not None:
                    item["destination_path"] = Path(item["destination_path"])
                item["edits"] = [FileEdit(**edit) for edit in item["edits"]]
                proposals.append(PendingEdit(**item))
            return proposals

    def execution(self, identity: str, run_id: str, payload: dict[str, Any]) -> None:
        with self.transaction() as db:
            db.execute("INSERT OR REPLACE INTO chat_executions VALUES (?,?,?,?)", (self.identity, identity, run_id, _encode(payload)))

    def recover_executions(self, run_id: str) -> list[dict[str, Any]]:
        with self.transaction() as db:
            records = []
            rows = db.execute("SELECT id,payload FROM chat_executions WHERE chat_id=? AND run_id=? ORDER BY rowid", (self.identity, run_id)).fetchall()
            for identity, payload in rows:
                record = json.loads(payload)
                if record["status"] == "running":
                    record["status"] = "outcome_unknown"
                    db.execute("UPDATE chat_executions SET payload=? WHERE chat_id=? AND id=?", (_encode(record), self.identity, identity))
                records.append(record)
            return records

    def close(self) -> None:
        pass  # Only the conversation manager releases the shared writer lease.
