"""Unwired Windows byte-pipe I/O candidate; NOT authentication or a VM runner.

One owning thread, one outstanding OVERLAPPED, one shared session budget. No
background reader, FlushFileBuffers, ACL mutation, TLS or Hyper-V operation.
Uncertain cancellation retains the buffers/handles and reports cleanup_unknown.
Win32/provider calls themselves cannot be preempted here: a separately protected
process/VM watchdog is still required before unattended live integration.
"""
from __future__ import annotations

import ctypes
import math
import re
import sys
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, NoReturn, Protocol

MAX_TRANSFER_BYTES = 64 * 1024
MAX_WRITE_BYTES = 4 * 1024 * 1024
_POLL_SECONDS = 0.01
_PIPE_PATH = re.compile(r"\\\\\.\\pipe\\night-shift-[0-9a-f]{32}-com1")
_RETRYABLE_OPEN = frozenset((2, 231))
_EOF = frozenset((38, 109, 232, 233))


class PipeIOError(RuntimeError):
    """Fixed-label terminal I/O error, without peer data or native paths."""


class PipeCleanupUnknown(PipeIOError):
    """Exact resources remain retained; never count this as successful cleanup."""

    def __init__(self, channel: BoundedPipe):
        super().__init__("cleanup_unknown")
        self.channel = channel


def _seconds(value: float, maximum: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("invalid_timeout")
    if not math.isfinite(value) or not 0 < value <= maximum:
        raise ValueError("invalid_timeout")


class IOBudget:
    """Trusted monotonic clock/cancellation callback; never reset per fragment."""

    def __init__(
        self,
        timeout_seconds: float,
        *,
        cancelled: Callable[[], bool] = lambda: False,
        clock: Callable[[], float] = time.monotonic,
    ):
        _seconds(timeout_seconds, 900)
        self._clock = clock
        self._cancelled = cancelled
        self._deadline = clock() + timeout_seconds

    def remaining(self) -> float:
        try:
            cancelled = self._cancelled()
        except Exception:
            raise PipeIOError("cancel_check_failed") from None
        if type(cancelled) is not bool:
            raise PipeIOError("cancel_check_failed")
        if cancelled:
            raise PipeIOError("cancelled")
        remaining = self._deadline - self._clock()
        if not math.isfinite(remaining) or remaining <= 0:
            raise PipeIOError("deadline")
        return remaining


class _OVERLAPPED(ctypes.Structure):
    _fields_ = [
        ("Internal", ctypes.c_size_t),
        ("InternalHigh", ctypes.c_size_t),
        ("Offset", ctypes.c_uint32),
        ("OffsetHigh", ctypes.c_uint32),
        ("hEvent", ctypes.c_void_p),
    ]


@dataclass
class _Pending:
    buffer: ctypes.Array[ctypes.c_char]
    overlapped: _OVERLAPPED
    event: int = 0
    # True includes an interrupted submission whose result is not yet known.
    submitted: bool = False


@dataclass(frozen=True)
class _Completion:
    count: int
    error: int = 0


class _NativeFailure(Exception):
    def __init__(self, code: int):
        self.code = code
        super().__init__("native_failure")


class _API(Protocol):
    def open(self, path: str) -> int: ...
    def event(self) -> int: ...
    def begin(self, handle: int, pending: _Pending, size: int, write: bool) -> None: ...
    def poll(self, handle: int, pending: _Pending) -> _Completion | None: ...
    def cancel(self, handle: int, pending: _Pending) -> None: ...
    def close(self, handle: int) -> None: ...


class _Windows:
    # Dynamic ctypes bindings are already Any. Declare their shape outside the
    # Windows-only initialization branch so non-Windows type checking can see it.
    # This does not load a DLL, add a fallback or change any native signature.
    _dll: Any
    _open: Any
    _event: Any
    _read: Any
    _write: Any
    _result: Any
    _cancel: Any
    _close: Any

    def __init__(self) -> None:
        loader = getattr(ctypes, "WinDLL", None)
        last_error = getattr(ctypes, "get_last_error", None)
        if sys.platform != "win32" or loader is None or last_error is None:
            raise PipeIOError("windows_required")
        self._last_error: Callable[[], int] = last_error
        self._dll = loader("kernel32", use_last_error=True)
        h, d, b = ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int
        p = ctypes.POINTER(_OVERLAPPED)
        self._open = self._bind("CreateFileW", [ctypes.c_wchar_p, d, d, h, d, d, h], h)
        self._event = self._bind("CreateEventW", [h, b, b, ctypes.c_wchar_p], h)
        args = [h, h, d, ctypes.POINTER(d), p]
        self._read = self._bind("ReadFile", args, b)
        self._write = self._bind("WriteFile", args, b)
        self._result = self._bind("GetOverlappedResult", [h, p, ctypes.POINTER(d), b], b)
        self._cancel = self._bind("CancelIoEx", [h, p], b)
        self._close = self._bind("CloseHandle", [h], b)

    def _bind(self, name: str, arguments: list[Any], result: Any) -> Any:
        function = getattr(self._dll, name)
        function.argtypes = arguments
        function.restype = result
        return function

    def open(self, path: str) -> int:
        # Exact data bits, not GENERIC_WRITE (which includes pipe-instance creation).
        # Non-inheritable handle; overlapped; at most identification impersonation.
        handle = self._open(path, 0x3, 0, None, 3, 0x40000000 | 0x100000 | 0x10000, None)
        if handle == ctypes.c_void_p(-1).value:
            raise _NativeFailure(self._last_error())
        if not handle:
            raise _NativeFailure(6)
        return int(handle)

    def event(self) -> int:
        handle = self._event(None, True, False, None)
        if not handle:
            raise _NativeFailure(self._last_error())
        return int(handle)

    def begin(self, handle: int, pending: _Pending, size: int, write: bool) -> None:
        function = self._write if write else self._read
        # Modern Windows asynchronous I/O: no stack-local byte-count output.
        # Completion bytes come ONLY from GetOverlappedResult, never this call.
        ok = function(handle, pending.buffer, size, None, ctypes.byref(pending.overlapped))
        if not ok:
            error = self._last_error()
            if error != 997:  # ERROR_IO_PENDING is successful asynchronous submission.
                raise _NativeFailure(error)

    def poll(self, handle: int, pending: _Pending) -> _Completion | None:
        transferred = ctypes.c_uint32()
        if self._result(handle, ctypes.byref(pending.overlapped),
                        ctypes.byref(transferred), False):
            return _Completion(transferred.value)
        error = self._last_error()
        if error == 996:  # ERROR_IO_INCOMPLETE; do not release OVERLAPPED/buffer/event.
            return None
        if error in (6, 87):  # Invalid handle/parameter cannot establish completion.
            raise _NativeFailure(error)
        return _Completion(0, error)

    def cancel(self, handle: int, pending: _Pending) -> None:
        if not self._cancel(handle, ctypes.byref(pending.overlapped)):
            error = self._last_error()
            if error != 1168:  # ERROR_NOT_FOUND: completion may have won the race.
                raise _NativeFailure(error)

    def close(self, handle: int) -> None:
        if not self._close(handle):
            raise _NativeFailure(self._last_error())


# Strong references prevent GC from freeing kernel-visible memory on uncertainty.
# Only same-owner close() can retry observation/release of these exact resources.
_QUARANTINE: dict[int, BoundedPipe] = {}


class BoundedPipe:
    """Experimental byte stream. No BinaryIO compatibility or automatic live caller.

    Construct through connect(). Use read()/write_all() under the SAME IOBudget.
    On terminal I/O failure the session is closed, never reconnected. close() has
    a separate cancellation-drain allowance (default 2 seconds, maximum 5).
    A cleanup_unknown exception exposes .channel for explicit same-owner close
    re-observation; it does not authorize retrying the operation or touching VMs.
    """

    def __init__(
        self,
        budget: IOBudget,
        api: _API,
        *,
        cleanup_timeout_seconds: float = 2,
        _sleep: Callable[[float], None] = time.sleep,
        _cleanup_clock: Callable[[], float] = time.monotonic,
    ):
        _seconds(cleanup_timeout_seconds, 5)
        self._budget = budget
        self._api = api
        self._sleep = _sleep
        self._cleanup_clock = _cleanup_clock
        self._cleanup_seconds = cleanup_timeout_seconds
        self._owner = threading.get_ident()
        self._handle: int | None = None
        self._pending: _Pending | None = None
        self._busy = False
        self._closed = False
        self._unknown = False

    @classmethod
    def connect(
        cls, path: str, budget: IOBudget, *, cleanup_timeout_seconds: float = 2,
    ) -> BoundedPipe:
        cls._validate(path, budget, cleanup_timeout_seconds)
        budget.remaining()
        return cls._connect(path, budget, _Windows(),
                            cleanup_timeout_seconds=cleanup_timeout_seconds)

    @staticmethod
    def _validate(path: str, budget: IOBudget, cleanup_seconds: float) -> None:
        if not isinstance(path, str) or _PIPE_PATH.fullmatch(path) is None:
            raise ValueError("invalid_local_pipe_path")
        if not isinstance(budget, IOBudget):
            raise ValueError("invalid_budget")
        _seconds(cleanup_seconds, 5)

    @classmethod
    def _connect(
        cls, path: str, budget: IOBudget, api: _API, **options: Any,
    ) -> BoundedPipe:
        cls._validate(path, budget, options.get("cleanup_timeout_seconds", 2))
        channel = cls(budget, api, **options)
        with channel._operation(require_handle=False):
            while True:
                budget.remaining()
                try:
                    channel._handle = api.open(path)
                except _NativeFailure as exc:
                    if exc.code not in _RETRYABLE_OPEN:
                        raise PipeIOError("connect_failed") from None
                else:
                    budget.remaining()  # A late native return is never success.
                    return channel
                channel._sleep(min(_POLL_SECONDS, budget.remaining()))

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def cleanup_unknown(self) -> bool:
        return self._unknown

    def _require_owner(self) -> None:
        if threading.get_ident() != self._owner:
            raise PipeIOError("wrong_thread")

    @contextmanager
    def _operation(self, *, require_handle: bool = True) -> Iterator[None]:
        self._require_owner()
        if self._closed or (require_handle and self._handle is None):
            raise PipeIOError("closed")
        if self._busy:
            raise PipeIOError("busy")
        self._busy = True
        try:
            self._budget.remaining()
            yield
        except PipeCleanupUnknown:
            raise  # Do not implicitly retry a failed cleanup observation.
        except BaseException:
            # Cleanup uncertainty takes precedence over the original failure.
            self._dispose()
            raise
        finally:
            self._busy = False

    def read(self, size: int) -> bytes:
        if type(size) is not int or not 1 <= size <= MAX_TRANSFER_BYTES:
            raise ValueError("invalid_read_size")
        with self._operation():
            return self._transfer(None, size)

    def write_all(self, data: bytes) -> None:
        if not isinstance(data, bytes) or len(data) > MAX_WRITE_BYTES:
            raise ValueError("invalid_write")
        with self._operation():
            offset = 0
            while offset < len(data):
                self._budget.remaining()
                chunk = data[offset:offset + MAX_TRANSFER_BYTES]
                count = len(self._transfer(chunk, len(chunk)))
                if not count:
                    raise PipeIOError("zero_write")
                offset += count
            self._budget.remaining()

    def _transfer(self, payload: bytes | None, size: int) -> bytes:
        assert self._handle is not None and self._pending is None
        self._budget.remaining()
        # Allocate kernel-visible structures BEFORE acquiring the event handle.
        pending = _Pending(ctypes.create_string_buffer(size), _OVERLAPPED())
        if payload is not None:
            pending.buffer.raw = payload
        try:
            pending.event = self._api.event()
        except _NativeFailure:
            raise PipeIOError("event_failed") from None
        self._pending = pending
        pending.overlapped.hEvent = pending.event
        self._budget.remaining()  # Do not submit after a late event/allocation step.
        pending.submitted = True  # Also retains ownership on interrupted submission.
        try:
            self._api.begin(self._handle, pending, size, payload is not None)
        except _NativeFailure as exc:
            # A documented non-pending submission failure queued no request.
            pending.submitted = False
            self._release_event()
            if payload is None and exc.code in _EOF:
                self._budget.remaining()
                return b""
            raise PipeIOError("native_io") from None
        while True:
            self._budget.remaining()
            try:
                completion = self._api.poll(self._handle, pending)
            except _NativeFailure:
                raise PipeIOError("completion_failed") from None
            if completion is not None:
                pending.submitted = False
                self._release_event()
                self._budget.remaining()
                if completion.error:
                    if payload is None and completion.error in _EOF:
                        return b""
                    raise PipeIOError("native_io")
                if type(completion.count) is not int or not 0 <= completion.count <= size:
                    raise PipeIOError("invalid_completion")
                # For writes this communicates a short-write count internally.
                return bytes(pending.buffer.raw[:completion.count])
            self._sleep(min(_POLL_SECONDS, self._budget.remaining()))

    def _release_event(self) -> None:
        assert self._pending is not None and not self._pending.submitted
        try:
            self._api.close(self._pending.event)
        except BaseException:
            self._mark_unknown()
        self._pending = None

    def _mark_unknown(self) -> NoReturn:
        self._closed = True
        self._unknown = True
        _QUARANTINE[id(self)] = self
        raise PipeCleanupUnknown(self) from None

    def close(self) -> None:
        """Cancel/drain exact owned I/O before releasing any kernel-visible buffer."""
        self._require_owner()
        if self._busy:
            raise PipeIOError("busy")
        self._dispose()

    def _dispose(self) -> None:
        self._closed = True
        deadline = self._cleanup_clock() + self._cleanup_seconds
        pending = self._pending
        if pending is not None and pending.submitted:
            if self._handle is None:
                self._mark_unknown()
            assert self._handle is not None
            try:
                self._api.cancel(self._handle, pending)
            except _NativeFailure:
                pass  # Cancellation failure is not evidence of pending/completed I/O.
            except BaseException:
                self._mark_unknown()
            while True:
                try:
                    completion = self._api.poll(self._handle, pending)
                except BaseException:
                    self._mark_unknown()
                if completion is not None:
                    pending.submitted = False
                    break
                remaining = deadline - self._cleanup_clock()
                if remaining <= 0:
                    self._mark_unknown()
                try:
                    self._sleep(min(_POLL_SECONDS, remaining))
                except BaseException:
                    self._mark_unknown()
        if self._pending is not None:
            self._release_event()
        if self._handle is not None:
            try:
                self._api.close(self._handle)
            except BaseException:
                self._mark_unknown()
            self._handle = None
        self._unknown = False
        _QUARANTINE.pop(id(self), None)

    def __enter__(self) -> BoundedPipe:
        self._require_owner()
        if self._closed:
            raise PipeIOError("closed")
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
