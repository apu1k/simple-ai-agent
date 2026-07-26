"""Backend-independent contract for disposable sandbox lifecycle."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from night_shifts.models import SandboxRecord, SandboxSpec, SandboxStatus


@runtime_checkable
class SandboxProvider(Protocol):
    """Own sandbox resources without owning worker communication."""

    @property
    def backend_name(self) -> str: ...

    def create(self, *, job_id: str, spec: SandboxSpec) -> SandboxRecord: ...

    def start(self, sandbox: SandboxRecord) -> None: ...

    def status(self, sandbox: SandboxRecord) -> SandboxStatus: ...

    def pause(self, sandbox: SandboxRecord) -> None: ...

    def stop(self, sandbox: SandboxRecord) -> None: ...

    def destroy(self, sandbox: SandboxRecord) -> None: ...
