"""SQLite persistence for orchestration records.

Chat history remains in ``runtime.chat_store``. This database stores operational
state and audit data only; temporary tool-call rows have their own expiry.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from night_shifts.models import (
    ArtifactRecord,
    JobBudget,
    JobStatus,
    NightShiftEvent,
    NightShiftJob,
    ToolCallRecord,
    ToolCallStatus,
    utc_now,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    objective TEXT NOT NULL,
    worker_profile TEXT NOT NULL,
    repository_id TEXT,
    starting_revision TEXT,
    acceptance_criteria_json TEXT NOT NULL,
    budget_json TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    cancellation_requested INTEGER NOT NULL,
    result_summary TEXT
);
CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    job_id TEXT,
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_job_created_idx ON events(job_id, created_at);
CREATE TABLE IF NOT EXISTS tool_calls (
    call_id TEXT PRIMARY KEY,
    job_id TEXT,
    session_id TEXT,
    agent_profile TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    arguments_json TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    duration_ms INTEGER,
    result_preview TEXT,
    error TEXT,
    expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS tool_calls_expiry_idx ON tool_calls(expires_at);
CREATE INDEX IF NOT EXISTS tool_calls_job_started_idx ON tool_calls(job_id, started_at);
CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    path TEXT NOT NULL,
    content_type TEXT,
    size_bytes INTEGER,
    sha256 TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS artifacts_job_created_idx ON artifacts(job_id, created_at);
"""

_SENSITIVE_KEYS = frozenset({
    "api_key", "apikey", "authorization", "cookie", "password", "secret", "token"
})
_PREVIEW_LIMIT = 4000


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if str(key).lower() in _SENSITIVE_KEYS else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return [_redact(item) for item in value]
    return value


def _preview(value: str | None) -> str | None:
    if value is None or len(value) <= _PREVIEW_LIMIT:
        return value
    return value[:_PREVIEW_LIMIT] + "…[truncated]"


class _SQLiteStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=10000")
        return connection


class JobStore(_SQLiteStore):
    def create(self, job: NightShiftJob) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                _job_values(job),
            )

    def update(self, job: NightShiftJob) -> None:
        values = _job_values(job)
        with self._connect() as connection:
            cursor = connection.execute(
                """UPDATE jobs SET title=?, objective=?, worker_profile=?, repository_id=?,
                starting_revision=?, acceptance_criteria_json=?, budget_json=?, status=?,
                created_at=?, updated_at=?, cancellation_requested=?, result_summary=?
                WHERE job_id=?""",
                (*values[1:], values[0]),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Unknown night-shift job: {job.job_id}")

    def get(self, job_id: str) -> NightShiftJob | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        return _job_from_row(row) if row else None

    def list(self, *, limit: int = 100) -> list[NightShiftJob]:
        sql = "SELECT * FROM jobs ORDER BY created_at DESC"
        params: tuple[Any, ...] = ()
        if limit > 0:
            sql += " LIMIT ?"
            params = (limit,)
        with self._connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [_job_from_row(row) for row in rows]


class EventStore(_SQLiteStore):
    def append(self, event: NightShiftEvent) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO events VALUES (?, ?, ?, ?, ?, ?)",
                (
                    event.event_id,
                    event.job_id,
                    event.event_type,
                    event.actor,
                    _json(event.payload),
                    event.created_at.isoformat(),
                ),
            )

    def list(self, *, job_id: str | None = None, limit: int = 200) -> list[NightShiftEvent]:
        where = " WHERE job_id=?" if job_id is not None else ""
        params: list[Any] = [job_id] if job_id is not None else []
        sql = f"SELECT * FROM events{where} ORDER BY created_at ASC"
        if limit > 0:
            sql += " LIMIT ?"
            params.append(limit)
        with self._connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [
            NightShiftEvent(
                event_id=row["event_id"],
                job_id=row["job_id"],
                event_type=row["event_type"],
                actor=row["actor"],
                payload=json.loads(row["payload_json"]),
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]


class ToolCallStore(_SQLiteStore):
    """Seven-day-by-default, redacted tool execution audit store."""

    def start(self, record: ToolCallRecord) -> str:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO tool_calls VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record.call_id,
                    record.job_id,
                    record.session_id,
                    record.agent_profile,
                    record.tool_name,
                    _json(_redact(record.arguments)),
                    record.status.value,
                    record.started_at.isoformat(),
                    record.completed_at.isoformat() if record.completed_at else None,
                    record.duration_ms,
                    _preview(record.result_preview),
                    _preview(record.error),
                    record.expires_at.isoformat(),
                ),
            )
        return record.call_id

    def complete(
        self,
        call_id: str,
        *,
        status: ToolCallStatus,
        result: str | None = None,
        error: str | None = None,
        completed_at: datetime | None = None,
    ) -> None:
        completed = completed_at or utc_now()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT started_at FROM tool_calls WHERE call_id=?", (call_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"Unknown tool call: {call_id}")
            started = datetime.fromisoformat(row["started_at"])
            duration_ms = max(0, int((completed - started).total_seconds() * 1000))
            connection.execute(
                """UPDATE tool_calls SET status=?, completed_at=?, duration_ms=?,
                result_preview=?, error=? WHERE call_id=?""",
                (
                    status.value,
                    completed.isoformat(),
                    duration_ms,
                    _preview(result),
                    _preview(error),
                    call_id,
                ),
            )

    def list_recent(self, *, job_id: str | None = None, limit: int = 100) -> list[ToolCallRecord]:
        where = " WHERE job_id=?" if job_id is not None else ""
        params: list[Any] = [job_id] if job_id is not None else []
        sql = f"SELECT * FROM tool_calls{where} ORDER BY started_at DESC"
        if limit > 0:
            sql += " LIMIT ?"
            params.append(limit)
        with self._connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [_tool_call_from_row(row) for row in rows]

    def purge_expired(self, *, now: datetime | None = None) -> int:
        cutoff = (now or utc_now()).isoformat()
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM tool_calls WHERE expires_at <= ?", (cutoff,))
            return cursor.rowcount


class ArtifactStore(_SQLiteStore):
    def add(self, artifact: ArtifactRecord) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO artifacts VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    artifact.artifact_id,
                    artifact.job_id,
                    artifact.kind,
                    artifact.path,
                    artifact.content_type,
                    artifact.size_bytes,
                    artifact.sha256,
                    artifact.created_at.isoformat(),
                ),
            )

    def list(self, job_id: str) -> list[ArtifactRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM artifacts WHERE job_id=? ORDER BY created_at ASC", (job_id,)
            ).fetchall()
        return [
            ArtifactRecord(
                artifact_id=row["artifact_id"], job_id=row["job_id"], kind=row["kind"],
                path=row["path"], content_type=row["content_type"], size_bytes=row["size_bytes"],
                sha256=row["sha256"], created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]


def _job_values(job: NightShiftJob) -> tuple[Any, ...]:
    return (
        job.job_id,
        job.title,
        job.objective,
        job.worker_profile,
        job.repository_id,
        job.starting_revision,
        _json(job.acceptance_criteria),
        _json({
            "timeout_seconds": job.budget.timeout_seconds,
            "max_tool_calls": job.budget.max_tool_calls,
            "max_cost_usd": job.budget.max_cost_usd,
        }),
        job.status.value,
        job.created_at.isoformat(),
        job.updated_at.isoformat(),
        int(job.cancellation_requested),
        job.result_summary,
    )


def _job_from_row(row: sqlite3.Row) -> NightShiftJob:
    budget = json.loads(row["budget_json"])
    return NightShiftJob(
        job_id=row["job_id"],
        title=row["title"],
        objective=row["objective"],
        worker_profile=row["worker_profile"],
        repository_id=row["repository_id"],
        starting_revision=row["starting_revision"],
        acceptance_criteria=tuple(json.loads(row["acceptance_criteria_json"])),
        budget=JobBudget(**budget),
        status=JobStatus(row["status"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        cancellation_requested=bool(row["cancellation_requested"]),
        result_summary=row["result_summary"],
    )


def _tool_call_from_row(row: sqlite3.Row) -> ToolCallRecord:
    return ToolCallRecord(
        call_id=row["call_id"],
        job_id=row["job_id"],
        session_id=row["session_id"],
        agent_profile=row["agent_profile"],
        tool_name=row["tool_name"],
        arguments=json.loads(row["arguments_json"]),
        status=ToolCallStatus(row["status"]),
        started_at=datetime.fromisoformat(row["started_at"]),
        completed_at=_dt(row["completed_at"]),
        duration_ms=row["duration_ms"],
        result_preview=row["result_preview"],
        error=row["error"],
        expires_at=datetime.fromisoformat(row["expires_at"]),
    )
