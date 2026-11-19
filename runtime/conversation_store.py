"""Chat-scoped state on one SQLite connection and one backend writer lease."""
from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from typing import Any

from editing.model import FileEdit, GitCommitPlan, PendingEdit
from llm.responses_transcript import (
    EXECUTION_REFS_KEY,
    REPLAY_KEY,
    RESULT_OVERRIDES_KEY,
    RESULT_STATUSES_KEY,
    SEQUENCE_KEY,
    execution_output,
)
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
                db.execute("""CREATE TABLE IF NOT EXISTS chat_transcript (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id TEXT NOT NULL, run_id TEXT NOT NULL, payload TEXT NOT NULL
                )""")
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
                db.execute("PRAGMA user_version=3")
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
            if row is None:
                return None
            checkpoint = json.loads(row[0])
            validate_checkpoint(checkpoint)
            messages = checkpoint["context"]["messages"]
            for index, message in enumerate(messages):
                if SEQUENCE_KEY not in message:
                    continue
                owner = db.execute(
                    "SELECT run_id,payload FROM chat_transcript WHERE sequence=? AND chat_id=?",
                    (message[SEQUENCE_KEY], self.identity),
                ).fetchone()
                if owner is None:
                    raise PersistenceError("Checkpoint refers to missing transcript evidence")
                payload = json.loads(owner[1])
                if payload.get("role") != message["role"] or SEQUENCE_KEY in payload or RESULT_OVERRIDES_KEY in payload:
                    raise PersistenceError("Invalid stored transcript entry")
                bodies: dict[str, str] = {}
                for result in payload.get("content", []) if isinstance(payload.get("content"), list) else []:
                    if not isinstance(result, dict) or result.get("type") != "function_call_output":
                        continue
                    if EXECUTION_REFS_KEY in result:
                        if "output" in result:
                            raise PersistenceError("Ambiguous stored tool result")
                        stored = self._transcript_execution_result(db, owner[0], result.pop(EXECUTION_REFS_KEY))
                        if stored is None:
                            raise PersistenceError("Transcript refers to missing or unfinished execution evidence")
                        result["output"], status = stored
                        # Older replay rows did not store status alongside the results.
                        payload.setdefault(RESULT_STATUSES_KEY, {}).setdefault(result["call_id"], status)
                    if isinstance(result.get("call_id"), str) and isinstance(result.get("output"), str):
                        bodies[result["call_id"]] = result["output"]
                if RESULT_OVERRIDES_KEY in message:
                    overrides = message[RESULT_OVERRIDES_KEY]
                    if payload.get(REPLAY_KEY, {}).get("kind") != "results" or any(
                        call_id not in bodies or len(body) >= len(bodies[call_id])
                        for call_id, body in overrides.items()
                    ):
                        raise PersistenceError("Checkpoint has an invalid Responses result override")
                    payload[RESULT_OVERRIDES_KEY] = overrides
                messages[index] = {**payload, SEQUENCE_KEY: message[SEQUENCE_KEY]}
            return checkpoint

    def _transcript_execution_result(self, db, run_id: str, identity: str) -> tuple[str, str] | None:
        row = db.execute(
            "SELECT payload FROM chat_executions WHERE chat_id=? AND run_id=? AND id=?",
            (self.identity, run_id, identity),
        ).fetchone()
        if row is None:
            return None
        record = json.loads(row[0])
        status = record.get("status")
        if status not in {"success", "failed"}:
            return None
        return execution_output(status, record.get("observation"), record.get("error")), status

    def stage_transcript(self, run_id: str, message: dict) -> int:
        """Retain an original even if the run never advances the safe checkpoint."""
        if RESULT_OVERRIDES_KEY in message:
            raise PersistenceError("Cannot stage a replay override as original transcript evidence")
        with self.transaction() as db:
            payload = {key: value for key, value in message.items() if key != EXECUTION_REFS_KEY}
            references = message.get(EXECUTION_REFS_KEY)
            if references is not None:
                results = []
                for result, identity in zip(message["content"], references, strict=True):
                    stored = self._transcript_execution_result(db, run_id, identity) if identity else None
                    if stored is not None and stored[0] == result["output"]:
                        copy = {key: value for key, value in result.items() if key != "output"}
                        copy[EXECUTION_REFS_KEY] = identity
                        results.append(copy)
                    else:
                        results.append(result)
                payload["content"] = results
            cursor = db.execute(
                "INSERT INTO chat_transcript (chat_id,run_id,payload) VALUES (?,?,?)",
                (self.identity, run_id, _encode(payload)),
            )
            assert cursor.lastrowid is not None
            return cursor.lastrowid

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
                if item.get("git_commit") is not None:
                    item["git_commit"] = GitCommitPlan(**item["git_commit"])
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
