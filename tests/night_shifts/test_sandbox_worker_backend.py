import threading
from collections.abc import Iterable
from pathlib import Path

import pytest

from night_shifts.backends.sandbox_worker import SandboxWorkerBackend
from night_shifts.models import NightShiftEvent, SandboxRecord, SandboxSpec, SandboxStatus
from night_shifts.protocol import WorkerOutcome, WorkerResult, WorkerTask
from night_shifts.storage import EventStore


class FakeSandboxProvider:
    def __init__(
        self,
        *,
        statuses: list[SandboxStatus] | None = None,
        destroy_error: str | None = None,
    ):
        self.statuses = statuses or [SandboxStatus.RUNNING]
        self.destroy_error = destroy_error
        self.release_events = threading.Event()
        self.calls: list[str] = []
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

    def pause(self, sandbox: SandboxRecord) -> None:
        self.calls.append("pause")

    def stop(self, sandbox: SandboxRecord) -> None:
        self.calls.append("stop")

    def destroy(self, sandbox: SandboxRecord) -> None:
        self.calls.append("destroy")
        self.release_events.set()
        if self.destroy_error is not None:
            raise RuntimeError(self.destroy_error)


class FakeWorkerChannel:
    def __init__(
        self,
        *,
        event: NightShiftEvent | None = None,
        result: WorkerResult | None = None,
        block_events: bool = False,
        event_error: str | None = None,
        close_error: str | None = None,
        release_events: threading.Event | None = None,
    ) -> None:
        self.event = event
        self.result = result or WorkerResult(
            "job-1", WorkerOutcome.SUCCESS, "completed"
        )
        self.block_events = block_events
        self.event_error = event_error
        self.close_error = close_error
        self.release_events = release_events or threading.Event()
        self.calls: list[str] = []
        self.sent_task: WorkerTask | None = None

    def send_task(self, sandbox: SandboxRecord, task: WorkerTask) -> None:
        self.calls.append("send_task")
        self.sent_task = task

    def events(self, sandbox: SandboxRecord) -> Iterable[NightShiftEvent]:
        self.calls.append("events")
        if self.block_events:
            self.release_events.wait(timeout=2)
        if self.event_error is not None:
            raise RuntimeError(self.event_error)
        if self.event is not None:
            yield self.event

    def retrieve_result(self, sandbox: SandboxRecord) -> WorkerResult:
        self.calls.append("retrieve_result")
        return self.result

    def close(self, sandbox: SandboxRecord) -> None:
        self.calls.append("close")
        self.release_events.set()
        if self.close_error is not None:
            raise RuntimeError(self.close_error)


def task() -> WorkerTask:
    return WorkerTask("job-1", "Implement feature", "coding-worker")


def components(**channel_options):
    provider = FakeSandboxProvider()
    channel = FakeWorkerChannel(release_events=provider.release_events, **channel_options)
    return provider, channel


def test_backend_composes_lifecycle_provider_and_independent_channel():
    event = NightShiftEvent("progress_updated", "worker", {}, "job-1")
    result = WorkerResult("job-1", WorkerOutcome.SUCCESS, "completed")
    provider, channel = components(event=event, result=result)
    backend = SandboxWorkerBackend(provider, channel, poll_interval=0.001)

    observed = backend.run(task(), timeout_seconds=1)

    assert observed == result
    assert channel.calls == ["send_task", "events", "retrieve_result", "close"]
    assert provider.calls[-1] == "destroy"
    assert not hasattr(provider, "send_task")
    assert not hasattr(provider, "events")
    assert not hasattr(provider, "retrieve_results")


def test_sandbox_backend_runs_task_streams_events_and_destroys(tmp_path: Path):
    worker_event = NightShiftEvent(
        "progress_updated", "worker", {"percent": 50}, "job-1"
    )
    provider = FakeSandboxProvider(
        statuses=[SandboxStatus.STARTING, SandboxStatus.RUNNING]
    )
    channel = FakeWorkerChannel(event=worker_event, release_events=provider.release_events)
    store = EventStore(tmp_path / "operations.sqlite3")
    observed: list[NightShiftEvent] = []
    backend = SandboxWorkerBackend(
        provider,
        channel,
        event_store=store,
        poll_interval=0.001,
    )

    result = backend.run(task(), timeout_seconds=1, on_event=observed.append)

    assert result.outcome is WorkerOutcome.SUCCESS
    assert channel.sent_task == task()
    assert provider.calls == ["create", "start", "status", "status", "destroy"]
    assert channel.calls == ["send_task", "events", "retrieve_result", "close"]
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
    provider, channel = components()
    backend = SandboxWorkerBackend(provider, channel)

    result = backend.run(
        task(),
        timeout_seconds=1,
        cancellation_requested=lambda: True,
    )

    assert result.outcome is WorkerOutcome.CANCELLED
    assert provider.calls == ["create", "destroy"]
    assert channel.calls == ["close"]


def test_sandbox_backend_times_out_during_startup_and_destroys():
    provider = FakeSandboxProvider(statuses=[SandboxStatus.STARTING])
    channel = FakeWorkerChannel(release_events=provider.release_events)
    backend = SandboxWorkerBackend(provider, channel, poll_interval=0.001)

    result = backend.run(task(), timeout_seconds=0.01)

    assert result.outcome is WorkerOutcome.TIMED_OUT
    assert provider.calls[0:2] == ["create", "start"]
    assert provider.calls[-1] == "destroy"
    assert "send_task" not in channel.calls


def test_sandbox_backend_cancels_while_event_reader_is_blocked():
    provider, channel = components(block_events=True)
    backend = SandboxWorkerBackend(provider, channel, poll_interval=0.001)
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
    assert "events" in channel.calls
    assert channel.calls[-1] == "close"
    assert provider.calls[-1] == "destroy"
    assert provider.release_events.is_set()


def test_sandbox_backend_reports_protocol_error_and_destroys():
    provider, channel = components(event_error="invalid guest frame")
    backend = SandboxWorkerBackend(provider, channel, poll_interval=0.001)

    result = backend.run(task(), timeout_seconds=1)

    assert result.outcome is WorkerOutcome.FAILED
    assert result.error == "invalid guest frame"
    assert channel.calls[-1] == "close"
    assert provider.calls[-1] == "destroy"


def test_cleanup_failure_overrides_successful_worker_result():
    provider = FakeSandboxProvider(destroy_error="could not remove VM")
    channel = FakeWorkerChannel(release_events=provider.release_events)
    backend = SandboxWorkerBackend(provider, channel, poll_interval=0.001)

    result = backend.run(task(), timeout_seconds=1)

    assert result.outcome is WorkerOutcome.FAILED
    assert result.summary == "Sandbox cleanup failed."
    assert result.error == "sandbox destroy failed: could not remove VM"


def test_channel_close_failure_does_not_bypass_sandbox_destruction():
    provider, channel = components(close_error="could not close channel")
    backend = SandboxWorkerBackend(provider, channel, poll_interval=0.001)

    result = backend.run(task(), timeout_seconds=1)

    assert result.outcome is WorkerOutcome.FAILED
    assert result.error == "channel close failed: could not close channel"
    assert provider.calls[-1] == "destroy"


def test_callback_failure_cannot_bypass_sandbox_destruction():
    provider, channel = components()
    backend = SandboxWorkerBackend(provider, channel)

    def broken_callback(event: NightShiftEvent) -> None:
        raise RuntimeError("event sink failed")

    with pytest.raises(RuntimeError, match="event sink failed"):
        backend.run(task(), timeout_seconds=1, on_event=broken_callback)

    assert channel.calls == ["close"]
    assert provider.calls == ["create", "destroy"]
