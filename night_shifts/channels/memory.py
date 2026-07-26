"""In-memory worker channel for contract tests and local composition."""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterable

from night_shifts.models import NightShiftEvent, SandboxRecord
from night_shifts.protocol import WorkerResult, WorkerTask


class InMemoryWorkerChannel:
    """Store semantic worker messages by sandbox without performing I/O."""

    def __init__(self) -> None:
        self.sent_tasks: dict[str, list[WorkerTask]] = defaultdict(list)
        self._events: dict[str, deque[NightShiftEvent]] = defaultdict(deque)
        self._results: dict[str, WorkerResult] = {}
        self.closed: set[str] = set()

    def send_task(self, sandbox: SandboxRecord, task: WorkerTask) -> None:
        self._require_open(sandbox)
        self.sent_tasks[sandbox.sandbox_id].append(task)

    def events(self, sandbox: SandboxRecord) -> Iterable[NightShiftEvent]:
        self._require_open(sandbox)
        events = self._events[sandbox.sandbox_id]
        while events:
            yield events.popleft()

    def retrieve_result(self, sandbox: SandboxRecord) -> WorkerResult:
        self._require_open(sandbox)
        try:
            return self._results.pop(sandbox.sandbox_id)
        except KeyError as exc:
            raise RuntimeError("no worker result is available") from exc

    def queue_event(self, sandbox: SandboxRecord, event: NightShiftEvent) -> None:
        self._require_open(sandbox)
        self._events[sandbox.sandbox_id].append(event)

    def set_result(self, sandbox: SandboxRecord, result: WorkerResult) -> None:
        self._require_open(sandbox)
        if sandbox.sandbox_id in self._results:
            raise RuntimeError("a worker result is already queued")
        self._results[sandbox.sandbox_id] = result

    def close(self, sandbox: SandboxRecord) -> None:
        self.closed.add(sandbox.sandbox_id)

    def _require_open(self, sandbox: SandboxRecord) -> None:
        if sandbox.sandbox_id in self.closed:
            raise RuntimeError("worker channel is closed")
