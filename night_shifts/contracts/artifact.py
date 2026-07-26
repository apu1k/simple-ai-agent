"""Contract for retrieving untrusted worker artifacts before sandbox destruction."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from night_shifts.models import SandboxRecord


@dataclass(frozen=True)
class RetrievedArtifacts:
    """Temporary host staging area populated from one sandbox."""

    staging_root: Path
    references: tuple[str, ...]


@runtime_checkable
class ArtifactRetriever(Protocol):
    """Retrieve referenced outputs into a temporary, untrusted staging area."""

    def retrieve(
        self,
        sandbox: SandboxRecord,
        references: Sequence[str],
    ) -> RetrievedArtifacts: ...

    def cleanup(self, artifacts: RetrievedArtifacts) -> None: ...
