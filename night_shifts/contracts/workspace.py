"""Contracts for preparing and delivering trusted repository workspaces."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from night_shifts.models import SandboxRecord


@dataclass(frozen=True)
class PreparedWorkspace:
    """Trusted host workspace pinned to one repository revision for one job."""

    job_id: str
    repository_id: str
    revision: str
    path: Path


@runtime_checkable
class WorkspaceProvider(Protocol):
    """Prepare and remove trusted host-side repository content."""

    def prepare(
        self,
        *,
        job_id: str,
        repository_id: str,
        revision: str,
    ) -> PreparedWorkspace: ...

    def destroy(self, workspace: PreparedWorkspace) -> None: ...


@runtime_checkable
class WorkspaceInjector(Protocol):
    """Deliver a prepared workspace to an existing, stopped sandbox."""

    def inject(
        self,
        sandbox: SandboxRecord,
        workspace: PreparedWorkspace,
        *,
        read_only: bool,
    ) -> None: ...
