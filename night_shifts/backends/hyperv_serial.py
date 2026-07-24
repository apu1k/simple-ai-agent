"""Linux-compatible Hyper-V COM-port transport over a Windows named pipe.

The VM's COM1 port is attached to a host named pipe. A Linux guest consumes the
same byte stream through ``/dev/ttyS0``. Messages remain versioned JSONL; this
module supplies framing and sequencing, not a second protocol.
"""

from __future__ import annotations

import os
import re
import time
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import BinaryIO, Protocol

from night_shifts.backends.hyperv import HyperVError
from night_shifts.models import NightShiftEvent, SandboxRecord
from night_shifts.protocol import WorkerResult, decode_worker_message

_SANDBOX_ID = re.compile(r"^[0-9a-f]{32}$")
_PIPE_PREFIX = "night-shift-"
_RETRYABLE_PIPE_ERRORS = {2, 53, 231}


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
    buffer: bytearray = field(default_factory=bytearray)
    pending_events: deque[str] = field(default_factory=deque)
    result: str | None = None
    task_sent: bool = False


class HyperVSerialTransport:
    """Carry one task, worker events, and one result over a VM COM port."""

    def __init__(
        self,
        *,
        connector: NamedPipeConnector | None = None,
        connect_timeout_seconds: float = 30.0,
        max_message_bytes: int = 1024 * 1024,
        read_size: int = 4096,
    ):
        if connect_timeout_seconds <= 0:
            raise ValueError("Serial connection timeout must be positive")
        if max_message_bytes <= 0 or read_size <= 0:
            raise ValueError("Serial frame and read sizes must be positive")
        self.connector = connector or WindowsNamedPipeConnector()
        self.connect_timeout_seconds = connect_timeout_seconds
        self.max_message_bytes = max_message_bytes
        self.read_size = read_size
        self._sessions: dict[str, _SerialSession] = {}

    def send(self, sandbox: SandboxRecord, message: str) -> None:
        session = self._session(sandbox)
        if session.task_sent:
            raise HyperVError("A task has already been sent to this sandbox")
        if not message or "\n" in message or "\r" in message:
            raise HyperVError("Hyper-V serial messages must be one non-empty JSONL frame")
        payload = message.encode("utf-8")
        if len(payload) > self.max_message_bytes:
            raise HyperVError("Hyper-V serial message exceeds the configured size limit")
        try:
            session.channel.write(payload + b"\n")
            session.channel.flush()
        except OSError as exc:
            self.close(sandbox)
            raise HyperVError(f"Could not write to Hyper-V serial pipe: {exc}") from exc
        session.task_sent = True

    def event_messages(self, sandbox: SandboxRecord) -> Iterable[str]:
        session = self._session(sandbox)
        while session.pending_events:
            yield session.pending_events.popleft()
        while session.result is None:
            line = self._read_message(sandbox, session)
            message = decode_worker_message(line)
            if isinstance(message, WorkerResult):
                session.result = line
                return
            if not isinstance(message, NightShiftEvent):  # pragma: no cover - defensive
                raise HyperVError("Unsupported message on Hyper-V serial transport")
            yield line

    def result_message(self, sandbox: SandboxRecord) -> str:
        session = self._session(sandbox)
        while session.result is None:
            line = self._read_message(sandbox, session)
            message = decode_worker_message(line)
            if isinstance(message, WorkerResult):
                session.result = line
            else:
                session.pending_events.append(line)
        return session.result

    def close(self, sandbox: SandboxRecord) -> None:
        """Close and forget a sandbox channel; safe to call repeatedly."""
        session = self._sessions.pop(sandbox.sandbox_id, None)
        if session is not None:
            try:
                session.channel.close()
            except OSError:
                pass

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

    def _read_message(self, sandbox: SandboxRecord, session: _SerialSession) -> str:
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
                    self.close(sandbox)
                    raise HyperVError("Hyper-V serial transport returned an empty frame")
                try:
                    return raw.decode("utf-8")
                except UnicodeDecodeError as exc:
                    self.close(sandbox)
                    raise HyperVError(
                        "Hyper-V serial transport returned invalid UTF-8"
                    ) from exc

            if len(session.buffer) > self.max_message_bytes:
                self.close(sandbox)
                raise HyperVError(
                    "Hyper-V serial message exceeds the configured size limit"
                )
            try:
                chunk = session.channel.read(self.read_size)
            except OSError as exc:
                self.close(sandbox)
                raise HyperVError(f"Could not read from Hyper-V serial pipe: {exc}") from exc
            if not chunk:
                self.close(sandbox)
                raise HyperVError("Hyper-V guest serial pipe closed before a result")
            session.buffer.extend(chunk)
