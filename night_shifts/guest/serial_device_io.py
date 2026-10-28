"""Unwired Linux ttyS0 candidate; no CLI, service activation or guest dispatch.

Nonblocking byte I/O under one existing IOBudget. Native dependencies are loaded
only after a Linux guard. The budget/error imports do not initialize Win32 I/O.
No arbitrary device path, fd adoption, reconnect, flush, or background thread.
"""
from __future__ import annotations

import copy
import importlib
import math
import stat
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Protocol

from night_shifts.serial_pipe_io import (
    MAX_TRANSFER_BYTES,
    MAX_WRITE_BYTES,
    IOBudget,
    PipeIOError,
)

DEVICE = "/dev/ttyS0"
_POLL_SECONDS = 0.05


class SerialCleanupUnknown(PipeIOError):
    """Cleanup failed; never retry close on a possibly recycled POSIX fd."""

    def __init__(self, channel: SerialDevice):
        super().__init__("cleanup_unknown")
        self.channel = channel


class _API(Protocol):
    def open(self) -> int: ...
    def validate(self, fd: int) -> None: ...
    def claim(self, fd: int) -> None: ...
    def attributes(self, fd: int) -> Any: ...
    def raw(self, fd: int, original: Any) -> None: ...
    def restore(self, fd: int, original: Any) -> None: ...
    def release(self, fd: int) -> None: ...
    def read(self, fd: int, size: int) -> bytes: ...
    def write(self, fd: int, data: bytes) -> int: ...
    def wait(self, fd: int, writing: bool, seconds: float) -> None: ...
    def close(self, fd: int) -> None: ...


class _Linux:
    # Explicit dynamic ABI declarations keep Windows/Linux stub checks honest;
    # these modules are never imported as a non-Linux fallback.
    os: Any
    term: Any
    fcntl: Any
    select: Any

    def __init__(self) -> None:
        if sys.platform != "linux":
            raise PipeIOError("linux_required")
        self.os = importlib.import_module("os")
        self.term = importlib.import_module("termios")
        self.fcntl = importlib.import_module("fcntl")
        self.select = importlib.import_module("select")

    def open(self) -> int:
        native = self.os
        return int(native.open(DEVICE, native.O_RDWR | native.O_NOCTTY | native.O_NONBLOCK
                               | native.O_CLOEXEC | native.O_NOFOLLOW))

    def validate(self, fd: int) -> None:
        native = self.os
        info = native.fstat(fd)
        if (not stat.S_ISCHR(info.st_mode)
                or (native.major(info.st_rdev), native.minor(info.st_rdev)) != (4, 64)
                or native.get_inheritable(fd) or native.get_blocking(fd)):
            raise PipeIOError("serial_identity")

    def claim(self, fd: int) -> None:
        self.fcntl.flock(fd, self.fcntl.LOCK_EX | self.fcntl.LOCK_NB)
        self.fcntl.ioctl(fd, self.term.TIOCEXCL)

    def attributes(self, fd: int) -> Any:
        return self.term.tcgetattr(fd)

    def raw(self, fd: int, original: Any) -> None:
        term = self.term
        value = copy.deepcopy(original)
        value[0] = value[1] = value[3] = 0
        value[2] = term.CS8 | term.CREAD | term.CLOCAL
        value[4] = value[5] = term.B115200
        # VMIN=1 plus O_NONBLOCK: no-data is EAGAIN, not a spurious zero read.
        value[6][term.VMIN] = 1
        value[6][term.VTIME] = 0
        term.tcsetattr(fd, term.TCSANOW, value)
        actual = term.tcgetattr(fd)
        mask = (term.CSIZE | term.CSTOPB | term.PARENB | term.PARODD | term.CRTSCTS
                | term.HUPCL | term.CREAD | term.CLOCAL)
        if (actual[0] != 0 or actual[1] != 0 or actual[3] != 0
                or actual[2] & mask != term.CS8 | term.CREAD | term.CLOCAL
                or actual[4] != term.B115200 or actual[5] != term.B115200
                or actual[6][term.VMIN] != 1 or actual[6][term.VTIME] != 0):
            raise PipeIOError("serial_configuration")

    def restore(self, fd: int, original: Any) -> None:
        self.term.tcsetattr(fd, self.term.TCSANOW, original)

    def release(self, fd: int) -> None:
        self.fcntl.ioctl(fd, self.term.TIOCNXCL)

    def read(self, fd: int, size: int) -> bytes:
        return bytes(self.os.read(fd, size))

    def write(self, fd: int, data: bytes) -> int:
        return int(self.os.write(fd, data))

    def wait(self, fd: int, writing: bool, seconds: float) -> None:
        native = self.select
        desired = native.POLLOUT if writing else native.POLLIN
        poller = native.poll()
        poller.register(fd, desired | native.POLLERR | native.POLLHUP | native.POLLNVAL)
        for observed_fd, flags in poller.poll(max(1, math.ceil(seconds * 1000))):
            if observed_fd != fd or flags & native.POLLNVAL:
                raise PipeIOError("serial_poll")
            if flags & desired:
                return
            if flags & (native.POLLERR | native.POLLHUP):
                raise PipeIOError("channel_closed")

    def close(self, fd: int) -> None:
        self.os.close(fd)


class SerialDevice:
    """One exact-owned Linux serial descriptor. Construct through open().

    Private _open/API injection is for deterministic tests, not a path or fd
    selection interface. A trusted caller owns callbacks, thread and process.
    """

    def __init__(self, budget: IOBudget, api: _API):
        self._budget = budget
        self._api = api
        self._owner = threading.get_ident()
        self._fd: int | None = None
        self._original: Any = None
        self._claimed = False
        self._closed = False
        self._unknown = False
        self._busy = False

    @classmethod
    def open(cls, budget: IOBudget) -> SerialDevice:
        if not isinstance(budget, IOBudget):
            raise ValueError("invalid_budget")
        budget.remaining()
        return cls._open(budget, _Linux())

    @classmethod
    def _open(cls, budget: IOBudget, api: _API) -> SerialDevice:
        if not isinstance(budget, IOBudget):
            raise ValueError("invalid_budget")
        channel = cls(budget, api)
        with channel._operation():
            try:
                channel._fd = api.open()
                if type(channel._fd) is not int or channel._fd < 0:
                    raise PipeIOError("serial_descriptor")
                budget.remaining()
                api.validate(channel._fd)
                budget.remaining()
                api.claim(channel._fd)
                channel._claimed = True
                budget.remaining()
                channel._original = api.attributes(channel._fd)
                budget.remaining()
                api.raw(channel._fd, channel._original)
            except OSError:
                raise PipeIOError("serial_open") from None
        return channel

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
    def _operation(self) -> Iterator[None]:
        self._require_owner()
        if self._busy:
            raise PipeIOError("busy")
        if self._closed:
            raise PipeIOError("closed")
        self._busy = True
        try:
            self._budget.remaining()
            yield
            self._budget.remaining()
        except SerialCleanupUnknown:
            raise
        except BaseException:
            self._dispose()
            raise
        finally:
            self._busy = False

    def _wait(self, writing: bool) -> None:
        assert self._fd is not None
        try:
            self._api.wait(self._fd, writing, min(_POLL_SECONDS, self._budget.remaining()))
        except InterruptedError:
            pass
        except OSError:
            raise PipeIOError("serial_poll") from None
        self._budget.remaining()

    def read(self, size: int) -> bytes:
        if type(size) is not int or not 1 <= size <= MAX_TRANSFER_BYTES:
            raise ValueError("invalid_read_size")
        with self._operation():
            assert self._fd is not None
            while True:
                self._budget.remaining()
                try:
                    data = self._api.read(self._fd, size)
                except InterruptedError:
                    continue
                except BlockingIOError:
                    self._wait(False)
                    continue
                except OSError:
                    raise PipeIOError("serial_read") from None
                if type(data) is not bytes or len(data) > size:
                    raise PipeIOError("invalid_read")
                self._budget.remaining()
                return data

    def write_all(self, data: bytes) -> None:
        if type(data) is not bytes or len(data) > MAX_WRITE_BYTES:
            raise ValueError("invalid_write")
        with self._operation():
            assert self._fd is not None
            offset = 0
            while offset < len(data):
                self._budget.remaining()
                chunk = data[offset:offset + MAX_TRANSFER_BYTES]
                try:
                    count = self._api.write(self._fd, chunk)
                except InterruptedError:
                    continue
                except BlockingIOError:
                    self._wait(True)
                    continue
                except OSError:
                    raise PipeIOError("serial_write") from None
                if type(count) is not int or not 0 < count <= len(chunk):
                    raise PipeIOError("invalid_write_count")
                self._budget.remaining()
                offset += count

    def _dispose(self) -> None:
        self._closed = True
        if self._unknown:
            raise SerialCleanupUnknown(self)
        fd, self._fd = self._fd, None
        if fd is None:
            return
        # Detach before close. Linux can release an fd even when close raises;
        # retrying that number could close an unrelated, subsequently reused fd.
        failed = False
        if self._original is not None:
            try:
                self._api.restore(fd, self._original)
            except BaseException:
                failed = True
        if self._claimed:
            try:
                self._api.release(fd)
            except BaseException:
                failed = True
        try:
            self._api.close(fd)
        except BaseException:
            failed = True
        self._original = None
        self._claimed = False
        if failed:
            self._unknown = True
            raise SerialCleanupUnknown(self) from None

    def close(self) -> None:
        self._require_owner()
        if self._busy:
            raise PipeIOError("busy")
        self._dispose()

    def __enter__(self) -> SerialDevice:
        with self._operation():
            return self

    def __exit__(self, *_: object) -> None:
        self.close()
