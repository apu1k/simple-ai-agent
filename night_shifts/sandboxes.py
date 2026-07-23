"""Backend-independent lifecycle contract for disposable worker sandboxes."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable

from night_shifts.models import NightShiftEvent, SandboxRecord, SandboxSpec, SandboxStatus
from night_shifts.protocol import WorkerResult, WorkerTask


class SandboxController(ABC):
    """Control one kind of isolated worker environment from the trusted host."""

    @property
    @abstractmethod
    def backend_name(self) -> str:
        """Return the stable backend identifier persisted with sandbox records."""

    @abstractmethod
    def create(self, *, job_id: str, spec: SandboxSpec) -> SandboxRecord:
        """Create sandbox resources without starting worker execution."""

    @abstractmethod
    def start(self, sandbox: SandboxRecord) -> None:
        """Start an existing sandbox."""

    @abstractmethod
    def status(self, sandbox: SandboxRecord) -> SandboxStatus:
        """Return host-observed sandbox state."""

    @abstractmethod
    def send_task(self, sandbox: SandboxRecord, task: WorkerTask) -> None:
        """Send one versioned task message over the narrow guest transport."""

    @abstractmethod
    def events(self, sandbox: SandboxRecord) -> Iterable[NightShiftEvent]:
        """Yield structured worker events received from the guest."""

    @abstractmethod
    def retrieve_results(self, sandbox: SandboxRecord) -> WorkerResult:
        """Retrieve and validate the final structured result."""

    @abstractmethod
    def pause(self, sandbox: SandboxRecord) -> None:
        """Pause execution while retaining sandbox resources."""

    @abstractmethod
    def stop(self, sandbox: SandboxRecord) -> None:
        """Force the sandbox to stop execution."""

    @abstractmethod
    def destroy(self, sandbox: SandboxRecord) -> None:
        """Permanently remove all disposable sandbox resources."""
