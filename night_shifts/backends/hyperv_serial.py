"""Linux-compatible Hyper-V COM-port transport over a Windows named pipe.

The VM's COM1 port is attached to a host named pipe. A Linux guest consumes the
same byte stream through ``/dev/ttyS0``. Messages remain versioned JSONL; this
module supplies framing and sequencing, not a second protocol.
"""

from __future__ import annotations

import os
import re
import threading
import time
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import BinaryIO, Protocol

from night_shifts.backends.hyperv import HyperVError
from night_shifts.models import NightShiftEvent, SandboxRecord
from night_shifts.protocol import (
    ProtocolError,
    WorkerResult,
    WorkerTask,
    decode_worker_message,
    encode_task,
    is_ready_message,
)

_SANDBOX_ID = re.compile(r"^[0-9a-f]{32}$")
_PIPE_PREFIX = "night-shift-"
_RETRYABLE_PIPE_ERRORS = {2, 53, 231}
_CLOSE_WAIT_SECONDS = 5.0
_MAX_PRE_READY_NOISE_LINES = 64
_MAX_LATE_READY_FRAMES = 16


def _os_handle(channel: object) -> int | None:
    """Return the Win32 handle behind a real pipe channel, or None for fakes."""
    if os.name != "nt":
        return None
    fileno = getattr(channel, "fileno", None)
    if fileno is None:
        return None
    try:
        import msvcrt

        return int(msvcrt.get_osfhandle(fileno()))
    except (OSError, ValueError):
        return None


def _cancel_io(handle: int) -> None:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    cancel = kernel32.CancelIoEx
    cancel.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    cancel.restype = wintypes.BOOL
    cancel(wintypes.HANDLE(handle), None)


def close_channel(channel: BinaryIO, *, wait_seconds: float = _CLOSE_WAIT_SECONDS) -> bool:
    """Close a pipe channel without deadlocking on another thread's blocked read.

    On Windows, closing a synchronous handle waits for any pending ReadFile on
    it. A silent guest therefore made close() hang forever and teardown never
    ran. The close runs on a helper thread while pending I/O is cancelled with
    CancelIoEx. Returns False if the close did not finish in time; teardown
    then proceeds anyway and stopping the VM releases the pipe.
    """
    handle = _os_handle(channel)
    if handle is None:
        try:
            channel.close()
        except OSError:
            pass
        return True

    state_lock = threading.Lock()
    closed = threading.Event()

    def closer() -> None:
        try:
            channel.close()
        except OSError:
            pass
        finally:
            with state_lock:
                closed.set()

    thread = threading.Thread(target=closer, name="serial-pipe-close", daemon=True)
    with state_lock:
        _cancel_io(handle)
    thread.start()
    deadline = time.monotonic() + wait_seconds
    while not closed.wait(0.05):
        if time.monotonic() >= deadline:
            return False
        with state_lock:
            if not closed.is_set():
                _cancel_io(handle)
    return True


def serial_pipe_path(sandbox_id: str) -> str:
    """Return the trusted COM1 pipe path for a validated sandbox ID."""
    if not _SANDBOX_ID.fullmatch(sandbox_id):
        raise HyperVError("Sandbox ID is not a trusted 32-character hexadecimal ID")
    return rf"\\.\pipe\{_PIPE_PREFIX}{sandbox_id}-com1"


class NamedPipeConnector(Protocol):
    """Open one duplex byte channel to a VM's COM-port named pipe."""

    def connect(self, path: str, *, timeout_seconds: float) -> BinaryIO: ...


class WindowsNamedPipeConnector:
    """Connect to a Hyper-V-created named pipe without shelling out."""

    def __init__(self, *, poll_interval_seconds: float = 0.05):
        if poll_interval_seconds <= 0:
            raise ValueError("Named-pipe poll interval must be positive")
        self.poll_interval_seconds = poll_interval_seconds

    def connect(self, path: str, *, timeout_seconds: float) -> BinaryIO:
        if os.name != "nt":
            raise HyperVError("The Hyper-V serial transport requires Windows")
        if timeout_seconds <= 0:
            raise ValueError("Named-pipe connection timeout must be positive")

        deadline = time.monotonic() + timeout_seconds
        while True:
            try:
                return open(path, "r+b", buffering=0)
            except OSError as exc:
                if getattr(exc, "winerror", None) not in _RETRYABLE_PIPE_ERRORS:
                    raise HyperVError(f"Could not open Hyper-V serial pipe: {exc}") from exc
                if time.monotonic() >= deadline:
                    raise HyperVError(
                        "Timed out waiting for the Hyper-V guest serial pipe"
                    ) from exc
                time.sleep(min(self.poll_interval_seconds, deadline - time.monotonic()))


@dataclass
class _SerialSession:
    channel: BinaryIO
    closing: bool = False
    buffer: bytearray = field(default_factory=bytearray)
    pending_events: deque[NightShiftEvent] = field(default_factory=deque)
    result: WorkerResult | None = None
    task_sent: bool = False
    pending_task: bytes | None = None  # Held until the guest says it is ready.
    late_ready_frames: int = 0


class HyperVSerialTransport:
    """Carry one task, worker events, and one result over a VM COM port."""

    def __init__(
        self,
        *,
        connector: NamedPipeConnector | None = None,
        connect_timeout_seconds: float = 30.0,
        max_message_bytes: int = 1024 * 1024,
        read_size: int = 4096,
        await_guest_ready: bool = False,
    ):
        if connect_timeout_seconds <= 0:
            raise ValueError("Serial connection timeout must be positive")
        if max_message_bytes <= 0 or read_size <= 0:
            raise ValueError("Serial frame and read sizes must be positive")
        self.connector = connector or WindowsNamedPipeConnector()
        self.connect_timeout_seconds = connect_timeout_seconds
        self.max_message_bytes = max_message_bytes
        self.read_size = read_size
        # The guest only hears bytes sent after it opens ttyS0; with this set the
        # task is written by the reader once the guest's ready frame arrives.
        self.await_guest_ready = await_guest_ready
        self._sessions: dict[str, _SerialSession] = {}

    def send_task(self, sandbox: SandboxRecord, task: WorkerTask) -> None:
        if task.job_id != sandbox.job_id:
            raise ProtocolError("Task job ID does not match sandbox job ID")
        session = self._session(sandbox)
        if session.task_sent:
            raise HyperVError("A task has already been sent to this sandbox")
        message = encode_task(task)
        payload = message.encode("utf-8")
        if len(payload) > self.max_message_bytes:
            raise HyperVError("Hyper-V serial message exceeds the configured size limit")
        if self.await_guest_ready:
            session.pending_task = payload + b"\n"
            session.task_sent = True
            return
        try:
            session.channel.write(payload + b"\n")
            session.channel.flush()
        except OSError as exc:
            self.close(sandbox)
            raise HyperVError(f"Could not write to Hyper-V serial pipe: {exc}") from exc
        session.task_sent = True

    def events(self, sandbox: SandboxRecord) -> Iterable[NightShiftEvent]:
        session = self._session(sandbox)
        while session.pending_events:
            event = session.pending_events.popleft()
            self._validate_event(sandbox, event)
            yield event
        while session.result is None:
            message = self._next_message(sandbox, session)
            if isinstance(message, WorkerResult):
                session.result = message
                return
            if not isinstance(message, NightShiftEvent):  # pragma: no cover - defensive
                raise HyperVError("Unsupported message on Hyper-V serial transport")
            self._validate_event(sandbox, message)
            yield message

    def retrieve_result(self, sandbox: SandboxRecord) -> WorkerResult:
        session = self._session(sandbox)
        while session.result is None:
            message = self._next_message(sandbox, session)
            if isinstance(message, WorkerResult):
                session.result = message
            else:
                session.pending_events.append(message)
        if session.result.job_id != sandbox.job_id:
            raise ProtocolError("Guest result job ID does not match sandbox job ID")
        return session.result

    @staticmethod
    def _validate_event(sandbox: SandboxRecord, event: NightShiftEvent) -> None:
        if event.job_id != sandbox.job_id or event.actor != "worker":
            raise ProtocolError("Guest event has a mismatched job ID or forbidden actor")

    def close(self, sandbox: SandboxRecord) -> None:
        """Close and forget a sandbox channel; safe to call repeatedly."""
        session = self._sessions.pop(sandbox.sandbox_id, None)
        if session is not None:
            session.closing = True
            close_channel(session.channel)

    def _session(self, sandbox: SandboxRecord) -> _SerialSession:
        session = self._sessions.get(sandbox.sandbox_id)
        if session is None:
            path = serial_pipe_path(sandbox.sandbox_id)
            channel = self.connector.connect(
                path,
                timeout_seconds=self.connect_timeout_seconds,
            )
            session = _SerialSession(channel)
            self._sessions[sandbox.sandbox_id] = session
        return session

    def _next_message(
        self, sandbox: SandboxRecord, session: _SerialSession
    ) -> NightShiftEvent | WorkerResult:
        """Return the next worker message, handling the guest's ready frames."""
        noise = 0
        while True:
            awaiting = session.pending_task is not None
            line = self._read_message(sandbox, session, lenient=awaiting)
            try:
                ready = is_ready_message(line)
            except ProtocolError:
                if not awaiting:
                    raise
                ready = False
            if awaiting:
                if ready:
                    self._write_pending_task(sandbox, session)
                    continue
                noise += 1  # e.g. boot output before the service opened ttyS0
                if noise > _MAX_PRE_READY_NOISE_LINES:
                    self.close(sandbox)
                    raise HyperVError("Hyper-V guest sent unexpected output before it was ready")
                continue
            if ready:  # The guest repeats "ready" until it sees the task.
                session.late_ready_frames += 1
                if session.late_ready_frames > _MAX_LATE_READY_FRAMES:
                    self.close(sandbox)
                    raise HyperVError("Hyper-V guest kept announcing readiness after the task")
                continue
            return decode_worker_message(line)

    def _write_pending_task(self, sandbox: SandboxRecord, session: _SerialSession) -> None:
        payload = session.pending_task
        assert payload is not None
        session.pending_task = None
        try:
            session.channel.write(payload)
            session.channel.flush()
        except (OSError, ValueError) as exc:
            if session.closing:
                raise HyperVError("Hyper-V serial channel was closed by the host") from exc
            self.close(sandbox)
            raise HyperVError(f"Could not write to Hyper-V serial pipe: {exc}") from exc

    def _read_message(
        self, sandbox: SandboxRecord, session: _SerialSession, *, lenient: bool = False
    ) -> str:
        while True:
            newline = session.buffer.find(b"\n")
            if newline >= 0:
                if newline > self.max_message_bytes:
                    self.close(sandbox)
                    raise HyperVError(
                        "Hyper-V serial message exceeds the configured size limit"
                    )
                raw = bytes(session.buffer[:newline])
                del session.buffer[: newline + 1]
                if raw.endswith(b"\r"):
                    raw = raw[:-1]
                if not raw:
                    if lenient:
                        return ""
                    self.close(sandbox)
                    raise HyperVError("Hyper-V serial transport returned an empty frame")
                try:
                    return raw.decode("utf-8")
                except UnicodeDecodeError as exc:
                    if lenient:
                        return ""
                    self.close(sandbox)
                    raise HyperVError(
                        "Hyper-V serial transport returned invalid UTF-8"
                    ) from exc

            if len(session.buffer) > self.max_message_bytes:
                self.close(sandbox)
                raise HyperVError(
                    "Hyper-V serial message exceeds the configured size limit"
                )
            if session.closing:
                raise HyperVError("Hyper-V serial channel was closed by the host")
            try:
                chunk = session.channel.read(self.read_size)
            except (OSError, ValueError) as exc:
                if session.closing:
                    raise HyperVError("Hyper-V serial channel was closed by the host") from exc
                self.close(sandbox)
                raise HyperVError(f"Could not read from Hyper-V serial pipe: {exc}") from exc
            if not chunk:
                self.close(sandbox)
                raise HyperVError("Hyper-V guest serial pipe closed before a result")
            session.buffer.extend(chunk)
