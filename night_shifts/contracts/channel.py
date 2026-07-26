"""Backend-independent contract for a worker communication channel."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, runtime_checkable

from night_shifts.models import NightShiftEvent, SandboxRecord
from night_shifts.protocol import WorkerResult, WorkerTask


@runtime_checkable
class WorkerChannel(Protocol):
    """Exchange semantic task messages with one sandboxed worker.

    A channel owns protocol serialization and transport framing. It does not own
    sandbox lifecycle or interpret whether a submitted result should be accepted.
    """

    def send_task(self, sandbox: SandboxRecord, task: WorkerTask) -> None: ...

    def events(self, sandbox: SandboxRecord) -> Iterable[NightShiftEvent]: ...

    def retrieve_result(self, sandbox: SandboxRecord) -> WorkerResult: ...

    def close(self, sandbox: SandboxRecord) -> None: ...
