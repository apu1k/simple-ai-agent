"""Trusted stable-ID composition for approved night-shift implementations."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TypeVar

from night_shifts.artifacts import ArtifactCollector
from night_shifts.backends.sandbox_worker import SandboxWorkerBackend
from night_shifts.contracts import (
    ArtifactRetriever,
    SandboxProvider,
    WorkerChannel,
    WorkspaceInjector,
    WorkspaceProvider,
)
from night_shifts.models import SandboxSpec
from night_shifts.storage import EventStore

_COMPONENT_ID = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_Component = TypeVar("_Component")
_OtherComponent = TypeVar("_OtherComponent")


class CompositionError(ValueError):
    """Raised when trusted component selection is incomplete or unknown."""


@dataclass(frozen=True)
class ExecutionComponentSelection:
    """Stable administrator-selected implementation IDs for one backend."""

    sandbox_provider: str
    worker_channel: str
    workspace_provider: str | None = None
    workspace_injector: str | None = None
    artifact_retriever: str | None = None
    artifact_collector: str | None = None


class TrustedExecutionRegistry:
    """Resolve only preconstructed, administrator-approved implementations."""

    def __init__(
        self,
        *,
        sandbox_providers: Mapping[str, SandboxProvider],
        worker_channels: Mapping[str, WorkerChannel],
        workspace_providers: Mapping[str, WorkspaceProvider] | None = None,
        workspace_injectors: Mapping[str, WorkspaceInjector] | None = None,
        artifact_retrievers: Mapping[str, ArtifactRetriever] | None = None,
        artifact_collectors: Mapping[str, ArtifactCollector] | None = None,
    ) -> None:
        self._sandbox_providers = self._validated(sandbox_providers)
        self._worker_channels = self._validated(worker_channels)
        self._workspace_providers = self._validated(workspace_providers or {})
        self._workspace_injectors = self._validated(workspace_injectors or {})
        self._artifact_retrievers = self._validated(artifact_retrievers or {})
        self._artifact_collectors = self._validated(artifact_collectors or {})

    def build_backend(
        self,
        selection: ExecutionComponentSelection,
        *,
        spec: SandboxSpec | None = None,
        event_store: EventStore | None = None,
        poll_interval: float = 0.05,
        reader_join_seconds: float = 0.5,
    ) -> SandboxWorkerBackend:
        """Compose one backend without imports, paths, or classes from task text."""

        workspace_provider, workspace_injector = self._optional_pair(
            selection.workspace_provider,
            selection.workspace_injector,
            self._workspace_providers,
            self._workspace_injectors,
            "workspace",
        )
        artifact_retriever, artifact_collector = self._optional_pair(
            selection.artifact_retriever,
            selection.artifact_collector,
            self._artifact_retrievers,
            self._artifact_collectors,
            "artifact",
        )
        return SandboxWorkerBackend(
            self._require(
                self._sandbox_providers,
                selection.sandbox_provider,
                "sandbox provider",
            ),
            self._require(
                self._worker_channels,
                selection.worker_channel,
                "worker channel",
            ),
            spec=spec,
            event_store=event_store,
            workspace_provider=workspace_provider,
            workspace_injector=workspace_injector,
            artifact_retriever=artifact_retriever,
            artifact_collector=artifact_collector,
            poll_interval=poll_interval,
            reader_join_seconds=reader_join_seconds,
        )

    @staticmethod
    def _validated(
        components: Mapping[str, _Component],
    ) -> dict[str, _Component]:
        selected = dict(components)
        invalid = sorted(key for key in selected if not _COMPONENT_ID.fullmatch(key))
        if invalid:
            raise CompositionError(f"Invalid trusted component ID: {invalid[0]!r}")
        return selected

    @staticmethod
    def _require(
        components: Mapping[str, _Component],
        component_id: str,
        kind: str,
    ) -> _Component:
        if not _COMPONENT_ID.fullmatch(component_id):
            raise CompositionError(f"Invalid {kind} ID")
        try:
            return components[component_id]
        except KeyError as exc:
            raise CompositionError(f"Unknown approved {kind} ID: {component_id!r}") from exc

    @classmethod
    def _optional_pair(
        cls,
        first_id: str | None,
        second_id: str | None,
        first_components: Mapping[str, _Component],
        second_components: Mapping[str, _OtherComponent],
        kind: str,
    ) -> tuple[_Component | None, _OtherComponent | None]:
        if (first_id is None) != (second_id is None):
            raise CompositionError(f"{kind.title()} components must be selected together")
        if first_id is None or second_id is None:
            return None, None
        return (
            cls._require(first_components, first_id, f"{kind} provider"),
            cls._require(second_components, second_id, f"{kind} adapter"),
        )
