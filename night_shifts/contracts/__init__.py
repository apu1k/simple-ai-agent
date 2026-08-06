"""Stable contracts shared by night-shift modules."""

from night_shifts.contracts.artifact import ArtifactRetriever, RetrievedArtifacts
from night_shifts.contracts.channel import WorkerChannel
from night_shifts.contracts.inference import (
    InferenceMessage,
    InferenceRequest,
    InferenceResponse,
    InferenceToolCall,
    WorkerInferenceClient,
)
from night_shifts.contracts.sandbox import SandboxProvider
from night_shifts.contracts.worker_tool import (
    WorkerToolCall,
    WorkerToolProvider,
    WorkerToolResult,
    WorkerToolSpec,
)
from night_shifts.contracts.workspace import (
    PreparedWorkspace,
    WorkspaceInjector,
    WorkspaceProvider,
)

__all__ = [
    "ArtifactRetriever",
    "InferenceMessage",
    "InferenceRequest",
    "InferenceResponse",
    "InferenceToolCall",
    "PreparedWorkspace",
    "RetrievedArtifacts",
    "SandboxProvider",
    "WorkerChannel",
    "WorkerInferenceClient",
    "WorkerToolCall",
    "WorkerToolProvider",
    "WorkerToolResult",
    "WorkerToolSpec",
    "WorkspaceInjector",
    "WorkspaceProvider",
]
