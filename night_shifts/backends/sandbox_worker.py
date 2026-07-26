"""Worker backend that executes one task in one disposable sandbox."""

from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable

from night_shifts.backends.base import WorkerBackend
from night_shifts.contracts import SandboxProvider, WorkerChannel
from night_shifts.models import NightShiftEvent, SandboxRecord, SandboxSpec, SandboxStatus
from night_shifts.protocol import WorkerOutcome, WorkerResult, WorkerTask
from night_shifts.sandboxes import SandboxController
from night_shifts.storage import EventStore

_StreamItem = tuple[str, NightShiftEvent | Exception | None]


class SandboxWorkerBackend(WorkerBackend):
    """Run a worker through a sandbox controller with deadline-safe cleanup."""

    def __init__(
        self,
        provider: SandboxProvider,
        channel: WorkerChannel | None = None,
        *,
        spec: SandboxSpec | None = None,
        event_store: EventStore | None = None,
        poll_interval: float = 0.05,
        reader_join_seconds: float = 0.5,
    ):
        if poll_interval <= 0:
            raise ValueError("Sandbox poll interval must be positive")
        if reader_join_seconds < 0:
            raise ValueError("Sandbox reader join timeout must not be negative")
        self.provider = provider
        if channel is None:
            if not isinstance(provider, SandboxController):
                raise ValueError("A worker channel is required for this sandbox provider")
            channel = _LegacyControllerChannel(provider)
        self.channel = channel
        self.spec = spec or SandboxSpec()
        self.event_store = event_store
        self.poll_interval = poll_interval
        self.reader_join_seconds = reader_join_seconds

    def run(
        self,
        task: WorkerTask,
        *,
        timeout_seconds: float,
        cancellation_requested: Callable[[], bool] | None = None,
        on_event: Callable[[NightShiftEvent], None] | None = None,
    ) -> WorkerResult:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

        deadline = time.monotonic() + timeout_seconds
        sandbox: SandboxRecord | None = None
        reader: threading.Thread | None = None
        result: WorkerResult

        cleanup_error: str | None = None
        try:
            try:
                sandbox = self.provider.create(job_id=task.job_id, spec=self.spec)
                self._record_host_event(
                    task.job_id,
                    "sandbox_created",
                    {"sandbox_id": sandbox.sandbox_id, "backend": sandbox.backend},
                    on_event,
                )

                abort = self._abort_result(
                    task,
                    deadline,
                    timeout_seconds,
                    cancellation_requested,
                    on_event,
                )
                if abort is not None:
                    result = abort
                else:
                    self.provider.start(sandbox)
                    self._record_host_event(
                        task.job_id,
                        "sandbox_started",
                        {"sandbox_id": sandbox.sandbox_id},
                        on_event,
                    )
                    result, reader = self._run_started(
                        sandbox,
                        task,
                        deadline=deadline,
                        timeout_seconds=timeout_seconds,
                        cancellation_requested=cancellation_requested,
                        on_event=on_event,
                    )
            except Exception as exc:
                result = self._failure(
                    task,
                    "sandbox_worker_failed",
                    str(exc),
                    on_event,
                )
        finally:
            cleanup_error = self._destroy(sandbox, task, on_event)
            if reader is not None:
                reader.join(timeout=self.reader_join_seconds)

        if cleanup_error is not None:
            return WorkerResult(
                job_id=task.job_id,
                outcome=WorkerOutcome.FAILED,
                summary="Sandbox cleanup failed.",
                error=cleanup_error,
            )
        return result

    def _run_started(
        self,
        sandbox: SandboxRecord,
        task: WorkerTask,
        *,
        deadline: float,
        timeout_seconds: float,
        cancellation_requested: Callable[[], bool] | None,
        on_event: Callable[[NightShiftEvent], None] | None,
    ) -> tuple[WorkerResult, threading.Thread | None]:
        while True:
            abort = self._abort_result(
                task,
                deadline,
                timeout_seconds,
                cancellation_requested,
                on_event,
            )
            if abort is not None:
                return abort, None
            status = self.provider.status(sandbox)
            if status is SandboxStatus.RUNNING:
                break
            if status in {
                SandboxStatus.ERROR,
                SandboxStatus.STOPPED,
                SandboxStatus.DESTROYED,
            }:
                return (
                    self._failure(
                        task,
                        "sandbox_start_failed",
                        f"Sandbox entered unexpected state {status.value!r} during startup",
                        on_event,
                    ),
                    None,
                )
            self._sleep_until_poll(deadline)

        self._record_host_event(
            task.job_id,
            "sandbox_running",
            {"sandbox_id": sandbox.sandbox_id},
            on_event,
        )
        self.channel.send_task(sandbox, task)
        self._record_host_event(
            task.job_id,
            "sandbox_task_sent",
            {"sandbox_id": sandbox.sandbox_id},
            on_event,
        )

        output: queue.Queue[_StreamItem] = queue.Queue()
        reader = threading.Thread(
            target=_pump_sandbox_events,
            args=(self.channel, sandbox, output),
            daemon=True,
        )
        reader.start()

        while True:
            abort = self._abort_result(
                task,
                deadline,
                timeout_seconds,
                cancellation_requested,
                on_event,
            )
            if abort is not None:
                return abort, reader

            remaining = max(0.0, deadline - time.monotonic())
            try:
                kind, value = output.get(timeout=min(self.poll_interval, remaining))
            except queue.Empty:
                continue

            if kind == "event":
                assert isinstance(value, NightShiftEvent)
                self._record_event(value, on_event)
            elif kind == "error":
                assert isinstance(value, Exception)
                return (
                    self._failure(
                        task,
                        "sandbox_protocol_error",
                        str(value),
                        on_event,
                    ),
                    reader,
                )
            else:
                result = self.channel.retrieve_result(sandbox)
                self._record_host_event(
                    task.job_id,
                    "worker_result_received",
                    {"outcome": result.outcome.value},
                    on_event,
                )
                return result, reader

    def _abort_result(
        self,
        task: WorkerTask,
        deadline: float,
        timeout_seconds: float,
        cancellation_requested: Callable[[], bool] | None,
        on_event: Callable[[NightShiftEvent], None] | None,
    ) -> WorkerResult | None:
        if cancellation_requested is not None and cancellation_requested():
            self._record_host_event(task.job_id, "worker_cancelled", {}, on_event)
            return WorkerResult(
                job_id=task.job_id,
                outcome=WorkerOutcome.CANCELLED,
                summary="Sandbox worker was cancelled.",
            )
        if time.monotonic() >= deadline:
            self._record_host_event(
                task.job_id,
                "worker_timed_out",
                {"timeout_seconds": timeout_seconds},
                on_event,
            )
            return WorkerResult(
                job_id=task.job_id,
                outcome=WorkerOutcome.TIMED_OUT,
                summary=f"Sandbox worker exceeded its {timeout_seconds:g}-second timeout.",
            )
        return None

    def _destroy(
        self,
        sandbox: SandboxRecord | None,
        task: WorkerTask,
        on_event: Callable[[NightShiftEvent], None] | None,
    ) -> str | None:
        if sandbox is None:
            return None
        channel_error: str | None = None
        destroy_error: str | None = None
        try:
            self.channel.close(sandbox)
        except Exception as exc:
            channel_error = str(exc)
        try:
            self.provider.destroy(sandbox)
        except Exception as exc:
            destroy_error = str(exc)
        if channel_error is not None or destroy_error is not None:
            if channel_error is not None and destroy_error is not None:
                error = (
                    f"channel close failed: {channel_error}; "
                    f"sandbox destroy failed: {destroy_error}"
                )
            elif channel_error is not None:
                error = f"channel close failed: {channel_error}"
            else:
                assert destroy_error is not None
                error = destroy_error
            self._record_host_event(
                task.job_id,
                "sandbox_cleanup_failed",
                {"sandbox_id": sandbox.sandbox_id, "error": error},
                on_event,
            )
            return error
        self._record_host_event(
            task.job_id,
            "sandbox_destroyed",
            {"sandbox_id": sandbox.sandbox_id},
            on_event,
        )
        return None

    def _failure(
        self,
        task: WorkerTask,
        event_type: str,
        error: str,
        on_event: Callable[[NightShiftEvent], None] | None,
    ) -> WorkerResult:
        self._record_host_event(task.job_id, event_type, {"error": error}, on_event)
        return WorkerResult(
            job_id=task.job_id,
            outcome=WorkerOutcome.FAILED,
            summary="Sandbox worker failed.",
            error=error,
        )

    def _record_host_event(
        self,
        job_id: str,
        event_type: str,
        payload: dict,
        on_event: Callable[[NightShiftEvent], None] | None,
    ) -> None:
        self._record_event(
            NightShiftEvent(
                job_id=job_id,
                event_type=event_type,
                actor="orchestrator",
                payload=payload,
            ),
            on_event,
        )

    def _record_event(
        self,
        event: NightShiftEvent,
        on_event: Callable[[NightShiftEvent], None] | None,
    ) -> None:
        if self.event_store is not None:
            self.event_store.append(event)
        if on_event is not None:
            on_event(event)

    def _sleep_until_poll(self, deadline: float) -> None:
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(self.poll_interval, remaining))


class _LegacyControllerChannel:
    """Temporary adapter for controllers that still combine lifecycle and I/O."""

    def __init__(self, controller: SandboxController) -> None:
        self.controller = controller

    def send_task(self, sandbox: SandboxRecord, task: WorkerTask) -> None:
        self.controller.send_task(sandbox, task)

    def events(self, sandbox: SandboxRecord):
        return self.controller.events(sandbox)

    def retrieve_result(self, sandbox: SandboxRecord) -> WorkerResult:
        return self.controller.retrieve_results(sandbox)

    def close(self, sandbox: SandboxRecord) -> None:
        return None


def _pump_sandbox_events(
    channel: WorkerChannel,
    sandbox: SandboxRecord,
    output: queue.Queue[_StreamItem],
) -> None:
    try:
        for event in channel.events(sandbox):
            output.put(("event", event))
    except Exception as exc:
        output.put(("error", exc))
    else:
        output.put(("done", None))
