"""Durable single-host state. No provider credentials or privileged grants live here."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
import json
import sys
from pathlib import Path
import sqlite3
from threading import RLock
from typing import Any, ContextManager, Iterator, Protocol, get_args

from editing.model import FileEdit, PendingEdit
from llm.responses_transcript import SEQUENCE_KEY
from runtime.state import ANTHROPIC_REASONING_EFFORTS, ApiType


class PersistenceError(RuntimeError):
    pass


class RuntimeStateStore(Protocol):
    def check(self) -> None: ...
    def load(self) -> dict[str, Any] | None: ...
    def save(self, checkpoint: dict[str, Any]) -> None: ...
    def save_proposal(self, proposal: PendingEdit) -> None: ...
    def recover_proposals(self) -> list[PendingEdit]: ...
    def execution(self, identity: str, run_id: str, payload: dict[str, Any]) -> None: ...
    def recover_executions(self, run_id: str) -> list[dict[str, Any]]: ...
    def transaction(self) -> ContextManager[sqlite3.Connection]: ...
    def close(self) -> None: ...


class RuntimeStore:
    """One process owns a state database; OS locks are released even after a crash.

    Runtime checkpoints/events commit together. Proposal and execution intents
    commit independently *before* filesystem operations or tool dispatch. This
    deliberately does not promise exactly-once external effects.
    """

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._failed = False
        self._closed = False
        self._lease = self.path.with_suffix(self.path.suffix + ".lock").open("a+b")
        self._db: sqlite3.Connection | None = None
        try:
            self._lease.seek(0, 2)
            if not self._lease.tell():
                self._lease.write(b"0")
                self._lease.flush()
            self._lease.seek(0)
            if sys.platform == "win32":
                import msvcrt
                msvcrt.locking(self._lease.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self._lease.close()
            raise PersistenceError("Runtime state is already owned by another backend") from error
        try:
            self._db = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=FULL")
            version = self._db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2, 3):
                raise PersistenceError("Unsupported runtime database version; refusing to overwrite state")
            with self.transaction() as db:
                db.execute("CREATE TABLE IF NOT EXISTS checkpoint (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)")
                db.execute("CREATE TABLE IF NOT EXISTS proposals (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)")
                db.execute("CREATE TABLE IF NOT EXISTS executions (id TEXT PRIMARY KEY, run_id TEXT NOT NULL, payload TEXT NOT NULL)")
                db.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
                db.execute(f"PRAGMA user_version={max(version, 1)}")
        except Exception:
            self.close()
            raise

    def check(self) -> None:
        if self._closed or self._failed:
            raise PersistenceError("Durable state is unavailable; no further work may start. Inspect storage and restart.")

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self.check()
            assert self._db is not None
            try:
                with self._db:
                    # sqlite3's implicit transactions do not include leading
                    # DDL. Explicit BEGIN keeps schema/data migration atomic too.
                    self._db.execute("BEGIN IMMEDIATE")
                    yield self._db
            except Exception as error:
                self._failed = True
                raise PersistenceError("Runtime state could not be committed; inspect storage before restarting") from error

    def load(self) -> dict[str, Any] | None:
        with self.transaction() as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='conversation_meta'").fetchone():
                raise PersistenceError("Multi-chat state requires the conversation manager; refusing a single-chat downgrade")
            row = db.execute("SELECT payload FROM checkpoint WHERE id=1").fetchone()
            if row is None:
                return None
            saved = json.loads(row[0])
            if not isinstance(saved, dict):
                raise ValueError("Invalid runtime checkpoint object; refusing to discard saved state")
            return saved

    def save(self, checkpoint: dict[str, Any]) -> None:
        with self.transaction() as db:
            db.execute("INSERT OR REPLACE INTO checkpoint VALUES (1, ?)", (_encode(checkpoint),))
            if checkpoint.get("run"):
                run = dict(checkpoint["run"], session_id=checkpoint.get("chat_session_id"))
                db.execute("INSERT OR REPLACE INTO runs VALUES (?, ?)", (run["run_id"], _encode(run)))

    def save_proposal(self, proposal: PendingEdit) -> None:
        with self.transaction() as db:
            db.execute("INSERT OR REPLACE INTO proposals VALUES (?, ?)", (proposal.id, _encode(asdict(proposal))))

    def recover_proposals(self) -> list[PendingEdit]:
        with self.transaction() as db:
            proposals = []
            for (payload,) in db.execute("SELECT payload FROM proposals ORDER BY id").fetchall():
                item = json.loads(payload)
                if item["status"] == "applying":
                    item["status"] = "outcome_unknown"
                    db.execute("UPDATE proposals SET payload=? WHERE id=?", (_encode(item), item["id"]))
                item["path"] = Path(item["path"])
                if item["destination_path"] is not None:
                    item["destination_path"] = Path(item["destination_path"])
                item["edits"] = [FileEdit(**edit) for edit in item["edits"]]
                proposals.append(PendingEdit(**item))
            return proposals

    def execution(self, identity: str, run_id: str, payload: dict[str, Any]) -> None:
        with self.transaction() as db:
            db.execute("INSERT OR REPLACE INTO executions VALUES (?, ?, ?)", (identity, run_id, _encode(payload)))

    def recover_executions(self, run_id: str) -> list[dict[str, Any]]:
        with self.transaction() as db:
            records = []
            for identity, payload in db.execute(
                "SELECT id, payload FROM executions WHERE run_id=? ORDER BY rowid", (run_id,),
            ).fetchall():
                record = json.loads(payload)
                if record["status"] == "running":
                    record["status"] = "outcome_unknown"
                    db.execute("UPDATE executions SET payload=? WHERE id=?", (_encode(record), identity))
                records.append(record)
            return records

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            try:
                if self._db is not None:
                    self._db.close()
            finally:
                # Explicit unlock is necessary with Windows byte-range locks.
                try:
                    if sys.platform == "win32":
                        import msvcrt
                        self._lease.seek(0)
                        msvcrt.locking(self._lease.fileno(), msvcrt.LK_UNLCK, 1)
                finally:
                    self._lease.close()


def validate_checkpoint(saved: dict[str, Any]) -> None:
    """Reject malformed state, rather than silently treating it as a new session."""
    def require(condition: bool) -> None:
        if not condition:
            raise ValueError("Malformed checkpoint")

    def identity(value: Any) -> bool:
        return value is None or (isinstance(value, str) and len(value) == 32
                                 and all(c in "0123456789abcdef" for c in value))

    def pairs(value: Any) -> bool:
        return isinstance(value, list) and all(
            isinstance(pair, list) and len(pair) == 2 and all(isinstance(s, str) for s in pair)
            for pair in value
        )

    try:
        require(saved["version"] == 1)
        require(type(saved["sequence"]) is int and saved["sequence"] >= 0)
        require(isinstance(saved["cwd"], str) and Path(saved["cwd"]).is_absolute())
        require(identity(saved["chat_session_id"]) and identity(saved["context_run_id"]))
        require(pairs(saved["messages"]))
        model, settings, context = saved["model"], saved["model_settings"], saved["context"]
        require(isinstance(model, dict) and isinstance(settings, dict) and isinstance(context, dict))
        require(all(isinstance(model[key], str) and bool(model[key]) for key in ("provider_key", "model")))
        require(model["api_type"] in get_args(ApiType))
        require(type(settings["include_diff"]) is bool or settings["include_diff"] == "model")
        require(type(settings["openai_flex"]) is bool)
        require(settings["openai_reasoning_effort"] in (None, "none", "minimal", "low", "medium", "high", "xhigh", "max"))
        # Version 1 checkpoints written before Claude support lack this field.
        require(settings.get("anthropic_reasoning_effort") in (None, *ANTHROPIC_REASONING_EFFORTS))
        require(isinstance(context["messages"], list))
        require(all(isinstance(message, dict) and message.get("role") in ("user", "assistant", "tool")
                    for message in context["messages"]))
        sequence = 0
        for message in context["messages"]:
            if SEQUENCE_KEY in message:
                current = message[SEQUENCE_KEY]
                require(type(current) is int and current > sequence)
                sequence = current
        require(context["provider"] is None or isinstance(context["provider"], dict))
        run = saved["run"]
        if run is not None:
            require(isinstance(run, dict) and run["run_id"] is not None and identity(run["run_id"]))
            require(isinstance(run["user_text"], str))
            require(run["status"] in ("running", "completed", "failed", "interrupted"))
            require(all(run[key] is None or isinstance(run[key], str) for key in ("reply", "error")))
        events = saved["events"]
        require(isinstance(events, list))
        previous = saved["sequence"] - len(events)
        require(previous >= 0)
        for event in events:
            require(isinstance(event, dict) and type(event["sequence"]) is int)
            require(event["sequence"] == previous + 1)
            require(all(isinstance(event[key], str) for key in ("kind", "role", "text")))
            require(identity(event["run_id"]) and pairs(event["messages"]))
            previous = event["sequence"]
    except (KeyError, TypeError, ValueError) as error:
        raise PersistenceError("Invalid runtime checkpoint; refusing to discard saved state") from error


def _encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=_json_default)


def _json_default(value: Any) -> str:
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Unsupported durable value: {type(value).__name__}")
