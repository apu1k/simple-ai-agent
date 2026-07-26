"""Stable contracts shared by night-shift modules."""

from night_shifts.contracts.artifact import ArtifactRetriever, RetrievedArtifacts
from night_shifts.contracts.channel import WorkerChannel
from night_shifts.contracts.sandbox import SandboxProvider
from night_shifts.contracts.workspace import (
    PreparedWorkspace,
    WorkspaceInjector,
    WorkspaceProvider,
)

__all__ = [
    "ArtifactRetriever",
    "PreparedWorkspace",
    "RetrievedArtifacts",
    "SandboxProvider",
    "WorkerChannel",
    "WorkspaceInjector",
    "WorkspaceProvider",
]
