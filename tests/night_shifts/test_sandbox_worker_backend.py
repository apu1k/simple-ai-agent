import threading
from collections.abc import Iterable
from pathlib import Path

import pytest

from night_shifts.backends.sandbox_worker import SandboxWorkerBackend
from night_shifts.models import NightShiftEvent, SandboxRecord, SandboxSpec, SandboxStatus
from night_shifts.protocol import WorkerOutcome, WorkerResult, WorkerTask
from night_shifts.sandboxes import SandboxController
from night_shifts.storage import EventStore


class FakeSandboxController(SandboxController):
    def __init__(
        self,
        *,
        statuses: list[SandboxStatus] | None = None,
        events: list[NightShiftEvent] | None = None,
        result: WorkerResult | None = None,
        block_events: bool = False,
        destroy_error: str | None = None,
    ):
        self.statuses = statuses or [SandboxStatus.RUNNING]
        self.worker_events = events or []
        self.result = result or WorkerResult(
            "job-1", WorkerOutcome.SUCCESS, "completed"
        )
        self.block_events = block_events
        self.destroy_error = destroy_error
        self.release_events = threading.Event()
        self.calls: list[str] = []
        self.sent_task: WorkerTask | None = None
        self.record: SandboxRecord | None = None

    @property
    def backend_name(self) -> str:
        return "fake-vm"

    def create(self, *, job_id: str, spec: SandboxSpec) -> SandboxRecord:
        self.calls.append("create")
        self.record = SandboxRecord(job_id=job_id, backend=self.backend_name, spec=spec)
        return self.record

    def start(self, sandbox: SandboxRecord) -> None:
        self.calls.append("start")

    def status(self, sandbox: SandboxRecord) -> SandboxStatus:
        self.calls.append("status")
        if len(self.statuses) > 1:
            return self.statuses.pop(0)
        return self.statuses[0]

    def send_task(self, sandbox: SandboxRecord, task: WorkerTask) -> None:
        self.calls.append("send_task")
        self.sent_task = task

    def events(self, sandbox: SandboxRecord) -> Iterable[NightShiftEvent]:
        self.calls.append("events")
        if self.block_events:
            self.release_events.wait(timeout=2)
        yield from self.worker_events

    def retrieve_results(self, sandbox: SandboxRecord) -> WorkerResult:
        self.calls.append("retrieve_results")
        return self.result

    def pause(self, sandbox: SandboxRecord) -> None:
        self.calls.append("pause")

    def stop(self, sandbox: SandboxRecord) -> None:
        self.calls.append("stop")

    def destroy(self, sandbox: SandboxRecord) -> None:
        self.calls.append("destroy")
        self.release_events.set()
        if self.destroy_error is not None:
            raise RuntimeError(self.destroy_error)


def task() -> WorkerTask:
    return WorkerTask("job-1", "Implement feature", "coding-worker")


def test_sandbox_backend_runs_task_streams_events_and_destroys(tmp_path: Path):
    worker_event = NightShiftEvent(
        "progress_updated", "worker", {"percent": 50}, "job-1"
    )
    controller = FakeSandboxController(
        statuses=[SandboxStatus.STARTING, SandboxStatus.RUNNING],
        events=[worker_event],
    )
    store = EventStore(tmp_path / "operations.sqlite3")
    observed: list[NightShiftEvent] = []
    backend = SandboxWorkerBackend(
        controller,
        event_store=store,
        poll_interval=0.001,
    )

    result = backend.run(task(), timeout_seconds=1, on_event=observed.append)

    assert result.outcome is WorkerOutcome.SUCCESS
    assert controller.sent_task == task()
    assert controller.calls == [
        "create",
        "start",
        "status",
        "status",
        "send_task",
        "events",
        "retrieve_results",
        "destroy",
    ]
    event_types = [event.event_type for event in observed]
    assert event_types == [
        "sandbox_created",
        "sandbox_started",
        "sandbox_running",
        "sandbox_task_sent",
        "progress_updated",
        "worker_result_received",
        "sandbox_destroyed",
    ]
    stored_types = [event.event_type for event in store.list(job_id="job-1")]
    assert sorted(stored_types) == sorted(event_types)


def test_sandbox_backend_cancels_before_start_and_still_destroys():
    controller = FakeSandboxController()
    backend = SandboxWorkerBackend(controller)

    result = backend.run(
        task(),
        timeout_seconds=1,
        cancellation_requested=lambda: True,
    )

    assert result.outcome is WorkerOutcome.CANCELLED
    assert controller.calls == ["create", "destroy"]


def test_sandbox_backend_times_out_during_startup_and_destroys():
    controller = FakeSandboxController(statuses=[SandboxStatus.STARTING])
    backend = SandboxWorkerBackend(controller, poll_interval=0.001)

    result = backend.run(task(), timeout_seconds=0.01)

    assert result.outcome is WorkerOutcome.TIMED_OUT
    assert controller.calls[0:2] == ["create", "start"]
    assert controller.calls[-1] == "destroy"
    assert "send_task" not in controller.calls


def test_sandbox_backend_cancels_while_event_reader_is_blocked():
    controller = FakeSandboxController(block_events=True)
    backend = SandboxWorkerBackend(controller, poll_interval=0.001)
    checks = 0

    def cancellation_requested() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 4

    result = backend.run(
        task(),
        timeout_seconds=1,
        cancellation_requested=cancellation_requested,
    )

    assert result.outcome is WorkerOutcome.CANCELLED
    assert "events" in controller.calls
    assert controller.calls[-1] == "destroy"
    assert controller.release_events.is_set()


def test_sandbox_backend_reports_protocol_error_and_destroys():
    class BrokenController(FakeSandboxController):
        def events(self, sandbox: SandboxRecord) -> Iterable[NightShiftEvent]:
            raise RuntimeError("invalid guest frame")
            yield  # pragma: no cover

    controller = BrokenController()
    backend = SandboxWorkerBackend(controller, poll_interval=0.001)

    result = backend.run(task(), timeout_seconds=1)

    assert result.outcome is WorkerOutcome.FAILED
    assert result.error == "invalid guest frame"
    assert controller.calls[-1] == "destroy"


def test_cleanup_failure_overrides_successful_worker_result():
    controller = FakeSandboxController(destroy_error="could not remove VM")
    backend = SandboxWorkerBackend(controller, poll_interval=0.001)

    result = backend.run(task(), timeout_seconds=1)

    assert result.outcome is WorkerOutcome.FAILED
    assert result.summary == "Sandbox cleanup failed."
    assert result.error == "could not remove VM"


def test_callback_failure_cannot_bypass_sandbox_destruction():
    controller = FakeSandboxController()
    backend = SandboxWorkerBackend(controller)

    def broken_callback(event: NightShiftEvent) -> None:
        raise RuntimeError("event sink failed")

    with pytest.raises(RuntimeError, match="event sink failed"):
        backend.run(task(), timeout_seconds=1, on_event=broken_callback)

    assert controller.calls == ["create", "destroy"]
