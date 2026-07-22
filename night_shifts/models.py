"""Serializable domain models for night-shift orchestration."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any


def utc_now() -> datetime:
    """Return an aware UTC timestamp."""
    return datetime.now(timezone.utc)


class JobStatus(str, Enum):
    DRAFT = "draft"
    QUEUED = "queued"
    PROVISIONING = "provisioning"
    RUNNING = "running"
    WAITING_FOR_INPUT = "waiting_for_input"
    PAUSED = "paused"
    FAILED = "failed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    AWAITING_REVIEW = "awaiting_review"
    REVISION_REQUESTED = "revision_requested"
    REJECTED = "rejected"
    APPROVED = "approved"
    PUBLISHED = "published"
    MERGED = "merged"


class ToolCallStatus(str, Enum):
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class JobBudget:
    """Limits enforced by a future worker backend."""

    timeout_seconds: int = 14_400
    max_tool_calls: int = 500
    max_cost_usd: float | None = None

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0 or self.max_tool_calls <= 0:
            raise ValueError("Job timeout and tool-call budget must be positive")
        if self.max_cost_usd is not None and self.max_cost_usd < 0:
            raise ValueError("Job cost budget must not be negative")


@dataclass
class NightShiftJob:
    title: str
    objective: str
    worker_profile: str
    repository_id: str | None = None
    starting_revision: str | None = None
    acceptance_criteria: tuple[str, ...] = ()
    budget: JobBudget = field(default_factory=JobBudget)
    job_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    status: JobStatus = JobStatus.DRAFT
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    cancellation_requested: bool = False
    result_summary: str | None = None


@dataclass(frozen=True)
class NightShiftEvent:
    event_type: str
    actor: str
    payload: dict[str, Any] = field(default_factory=dict)
    job_id: str | None = None
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: datetime = field(default_factory=utc_now)


@dataclass
class ToolCallRecord:
    tool_name: str
    arguments: dict[str, Any]
    agent_profile: str
    call_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    job_id: str | None = None
    session_id: str | None = None
    status: ToolCallStatus = ToolCallStatus.RUNNING
    started_at: datetime = field(default_factory=utc_now)
    completed_at: datetime | None = None
    duration_ms: int | None = None
    result_preview: str | None = None
    error: str | None = None
    expires_at: datetime = field(default_factory=lambda: utc_now() + timedelta(days=7))


@dataclass(frozen=True)
class ArtifactRecord:
    job_id: str
    kind: str
    path: str
    artifact_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    content_type: str | None = None
    size_bytes: int | None = None
    sha256: str | None = None
    created_at: datetime = field(default_factory=utc_now)
