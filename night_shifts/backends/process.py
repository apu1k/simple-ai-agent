"""Disposable local-process backend used to validate worker orchestration."""

from __future__ import annotations

import queue
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TextIO

from night_shifts.backends.base import WorkerBackend
from night_shifts.models import NightShiftEvent
from night_shifts.protocol import (
    ProtocolError,
    WorkerOutcome,
    WorkerResult,
    WorkerTask,
    decode_worker_message,
    encode_task,
)
from night_shifts.storage import EventStore


class ProcessWorkerBackend(WorkerBackend):
    """Run one worker in a child Python process using JSONL over stdio."""

    def __init__(
        self,
        *,
        event_store: EventStore | None = None,
        command: Sequence[str] | None = None,
        cwd: Path | None = None,
        poll_interval: float = 0.02,
        terminate_grace_seconds: float = 0.5,
    ):
        self.event_store = event_store
        self.command = tuple(command or (sys.executable, "-m", "night_shifts.worker_process"))
        self.cwd = cwd or Path(__file__).resolve().parents[2]
        self.poll_interval = poll_interval
        self.terminate_grace_seconds = terminate_grace_seconds

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

        process = subprocess.Popen(
            self.command,
            cwd=self.cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        assert process.stdin is not None
        assert process.stdout is not None
        assert process.stderr is not None

        output: queue.Queue[tuple[str, str | None]] = queue.Queue()
        stderr_lines: list[str] = []
        threading.Thread(
            target=_pump_lines,
            args=(process.stdout, "stdout", output),
            daemon=True,
        ).start()
        threading.Thread(
            target=_pump_stderr,
            args=(process.stderr, stderr_lines),
            daemon=True,
        ).start()

        try:
            process.stdin.write(encode_task(task) + "\n")
            process.stdin.flush()
            process.stdin.close()
        except Exception:
            self._terminate(process)
            raise

        deadline = time.monotonic() + timeout_seconds
        result: WorkerResult | None = None
        stdout_closed = False

        while True:
            try:
                source, line = output.get(timeout=self.poll_interval)
            except queue.Empty:
                source, line = "", None

            if source == "stdout" and line is None:
                stdout_closed = True
            elif source == "stdout" and line is not None:
                try:
                    message = decode_worker_message(line)
                except ProtocolError as exc:
                    self._terminate(process)
                    return self._failure(
                        task,
                        "worker_protocol_error",
                        f"Invalid worker message: {exc}",
                        on_event,
                    )
                if message.job_id != task.job_id:
                    self._terminate(process)
                    return self._failure(
                        task,
                        "worker_protocol_error",
                        f"Worker message job ID {message.job_id!r} does not match {task.job_id!r}",
                        on_event,
                    )
                if isinstance(message, NightShiftEvent):
                    if message.actor != "worker":
                        self._terminate(process)
                        return self._failure(
                            task,
                            "worker_protocol_error",
                            f"Worker event used forbidden actor {message.actor!r}",
                            on_event,
                        )
                    self._record_event(message, on_event)
                elif result is not None:
                    self._terminate(process)
                    return self._failure(
                        task,
                        "worker_protocol_error",
                        "Worker emitted more than one result",
                        on_event,
                    )
                else:
                    result = message

            if cancellation_requested is not None and cancellation_requested():
                self._terminate(process)
                event = self._host_event(task.job_id, "worker_cancelled", {})
                self._record_event(event, on_event)
                return WorkerResult(
                    job_id=task.job_id,
                    outcome=WorkerOutcome.CANCELLED,
                    summary="Worker process was cancelled.",
                )

            if time.monotonic() >= deadline:
                self._terminate(process)
                event = self._host_event(
                    task.job_id,
                    "worker_timed_out",
                    {"timeout_seconds": timeout_seconds},
                )
                self._record_event(event, on_event)
                return WorkerResult(
                    job_id=task.job_id,
                    outcome=WorkerOutcome.TIMED_OUT,
                    summary=f"Worker exceeded its {timeout_seconds:g}-second timeout.",
                )

            return_code = process.poll()
            if return_code is not None and stdout_closed:
                if result is not None:
                    self._record_event(
                        self._host_event(
                            task.job_id,
                            "worker_result_received",
                            {"outcome": result.outcome.value, "return_code": return_code},
                        ),
                        on_event,
                    )
                    return result
                stderr = "".join(stderr_lines).strip()
                detail = stderr or f"Worker exited with code {return_code} without a result"
                return self._failure(task, "worker_failed", detail, on_event)

    def _failure(
        self,
        task: WorkerTask,
        event_type: str,
        error: str,
        on_event: Callable[[NightShiftEvent], None] | None,
    ) -> WorkerResult:
        self._record_event(self._host_event(task.job_id, event_type, {"error": error}), on_event)
        return WorkerResult(
            job_id=task.job_id,
            outcome=WorkerOutcome.FAILED,
            summary="Worker process failed.",
            error=error,
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

    @staticmethod
    def _host_event(job_id: str, event_type: str, payload: dict) -> NightShiftEvent:
        return NightShiftEvent(
            job_id=job_id,
            event_type=event_type,
            actor="orchestrator",
            payload=payload,
        )

    def _terminate(self, process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=self.terminate_grace_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def _pump_lines(stream: TextIO, source: str, output: queue.Queue[tuple[str, str | None]]) -> None:
    try:
        for line in stream:
            output.put((source, line.rstrip("\r\n")))
    finally:
        output.put((source, None))
        stream.close()


def _pump_stderr(stream: TextIO, lines: list[str]) -> None:
    try:
        for line in stream:
            if sum(map(len, lines)) < 16_000:
                lines.append(line)
    finally:
        stream.close()
