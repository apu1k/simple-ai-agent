"""Serializable domain models for night-shift orchestration."""

from __future__ import annotations

import math
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


class AgentPlan(str, Enum):
    """Requested worker inference latency/cost policy."""

    FLEX = "flex"
    NORMAL = "normal"


class SandboxStatus(str, Enum):
    """Host-observed lifecycle state for one disposable sandbox."""

    CREATED = "created"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    DESTROYED = "destroyed"
    ERROR = "error"


@dataclass(frozen=True)
class JobBudget:
    """Persisted upper bounds; strict spending requires a trusted pricing adapter."""

    timeout_seconds: int = 14_400
    max_tool_calls: int = 500
    max_cost_usd: float | None = None
    max_model_requests: int = 24
    max_input_bytes: int = 512 * 1024
    max_output_bytes: int = 128 * 1024
    max_command_seconds: int = 300

    def __post_init__(self) -> None:
        bounds = {
            "timeout_seconds": (self.timeout_seconds, 86_400),
            "max_tool_calls": (self.max_tool_calls, 500),
            "max_model_requests": (self.max_model_requests, 128),
            "max_input_bytes": (self.max_input_bytes, 4 * 1024 * 1024),
            "max_output_bytes": (self.max_output_bytes, 1024 * 1024),
            "max_command_seconds": (self.max_command_seconds, 3_600),
        }
        for name, (value, maximum) in bounds.items():
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError(f"{name} must be an integer between 1 and {maximum}")
        if self.max_cost_usd is not None and (
            isinstance(self.max_cost_usd, bool)
            or not isinstance(self.max_cost_usd, (int, float))
            or not math.isfinite(self.max_cost_usd)
            or self.max_cost_usd < 0
        ):
            raise ValueError("Job cost budget must be finite and non-negative")


@dataclass
class NightShiftJob:
    title: str
    objective: str
    worker_profile: str
    repository_id: str | None = None
    starting_revision: str | None = None
    acceptance_criteria: tuple[str, ...] = ()
    budget: JobBudget = field(default_factory=JobBudget)
    plan: AgentPlan = AgentPlan.FLEX
    job_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    status: JobStatus = JobStatus.DRAFT
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    cancellation_requested: bool = False
    result_summary: str | None = None


@dataclass(frozen=True)
class SandboxSpec:
    """Resource and network policy enforced by a sandbox controller."""

    cpu_count: int = 2
    memory_mb: int = 4096
    disk_gb: int = 20
    network_enabled: bool = False

    def __post_init__(self) -> None:
        if self.cpu_count <= 0 or self.memory_mb <= 0 or self.disk_gb <= 0:
            raise ValueError("Sandbox CPU, memory, and disk limits must be positive")


@dataclass
class SandboxRecord:
    """Durable host-side identity and state for a job sandbox."""

    job_id: str
    backend: str
    spec: SandboxSpec = field(default_factory=SandboxSpec)
    sandbox_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    external_id: str | None = None
    status: SandboxStatus = SandboxStatus.CREATED
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    last_error: str | None = None


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
