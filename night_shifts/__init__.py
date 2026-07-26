"""Trusted host-side orchestration primitives for night-shift jobs."""

from night_shifts.artifacts import ArtifactCollector, ArtifactRetrievalError
from night_shifts.channels import (
    InMemoryWorkerChannel,
    MarkdownMailboxChannel,
    MarkdownMailboxError,
)
from night_shifts.composition import (
    CompositionError,
    ExecutionComponentSelection,
    TrustedExecutionRegistry,
)
from night_shifts.contracts import (
    ArtifactRetriever,
    PreparedWorkspace,
    RetrievedArtifacts,
    SandboxProvider,
    WorkerChannel,
    WorkspaceInjector,
    WorkspaceProvider,
)
from night_shifts.models import (
    AgentPlan,
    ArtifactRecord,
    JobBudget,
    JobStatus,
    NightShiftEvent,
    NightShiftJob,
    SandboxRecord,
    SandboxSpec,
    SandboxStatus,
    ToolCallRecord,
    ToolCallStatus,
)
from night_shifts.protocol import WorkerOutcome, WorkerResult, WorkerTask
from night_shifts.service import NightShiftService
from night_shifts.worker_policy import ApprovedCommand, WorkerPolicyError, approve_worker_command
from night_shifts.workspaces import (
    RepositoryRegistry,
    TrustedRepository,
    WorkspaceError,
    WorkspacePreparer,
)

__all__ = [
    "AgentPlan",
    "ArtifactCollector",
    "ArtifactRetrievalError",
    "ArtifactRecord",
    "ArtifactRetriever",
    "CompositionError",
    "ExecutionComponentSelection",
    "InMemoryWorkerChannel",
    "JobBudget",
    "JobStatus",
    "MarkdownMailboxChannel",
    "MarkdownMailboxError",
    "NightShiftEvent",
    "NightShiftJob",
    "NightShiftService",
    "SandboxProvider",
    "SandboxRecord",
    "SandboxSpec",
    "SandboxStatus",
    "RetrievedArtifacts",
    "ToolCallRecord",
    "ToolCallStatus",
    "TrustedExecutionRegistry",
    "WorkerChannel",
    "WorkerOutcome",
    "WorkerResult",
    "WorkerTask",
    "ApprovedCommand",
    "WorkerPolicyError",
    "approve_worker_command",
    "PreparedWorkspace",
    "RepositoryRegistry",
    "TrustedRepository",
    "WorkspaceError",
    "WorkspaceInjector",
    "WorkspacePreparer",
    "WorkspaceProvider",
]
