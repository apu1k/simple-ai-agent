"""Deterministic guest tty ABI/ownership models; NOT native Linux execution."""
from __future__ import annotations

import copy
import stat
from collections import deque
from types import SimpleNamespace

import pytest

from night_shifts.guest import serial_device_io as m
from night_shifts.serial_pipe_io import IOBudget, PipeIOError


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class API:
    def __init__(self, clock):
        self.clock = clock
        self.calls = []
        self.hooks = {}
        self.failure = None
        self.reads = deque([b"abc"])
        self.counts = deque()
        self.written = bytearray()
        self.closed = False

    def step(self, name):
        self.calls.append(name)
        if name in self.hooks:
            self.hooks[name]()
        if name == self.failure:
            raise OSError("PRIVATE_NATIVE_CANARY")

    def open(self):
        self.step("open")
        return 7

    def validate(self, fd):
        assert fd == 7
        self.step("validate")

    def claim(self, fd):
        assert fd == 7
        self.step("claim")

    def attributes(self, fd):
        assert fd == 7
        self.step("attributes")
        return ["original"]

    def raw(self, fd, original):
        assert fd == 7 and original == ["original"]
        self.step("raw")

    def restore(self, fd, original):
        assert fd == 7 and original == ["original"]
        self.step("restore")

    def release(self, fd):
        assert fd == 7
        self.step("release")

    def read(self, fd, size):
        assert fd == 7 and 1 <= size <= m.MAX_TRANSFER_BYTES
        self.step("read")
        if not self.reads:
            raise BlockingIOError()
        value = self.reads.popleft()
        if isinstance(value, BaseException):
            raise value
        return value

    def write(self, fd, data):
        assert fd == 7 and len(data) <= m.MAX_TRANSFER_BYTES
        self.step("write")
        value = self.counts.popleft() if self.counts else len(data)
        if isinstance(value, BaseException):
            raise value
        if type(value) is int and 0 < value <= len(data):
            self.written.extend(data[:value])
        return value

    def wait(self, fd, writing, seconds):
        assert fd == 7 and type(writing) is bool and 0 < seconds <= 0.05
        self.step("wait")
        self.clock.now += seconds

    def close(self, fd):
        assert fd == 7 and not self.closed, "repeated/recycled descriptor close"
        self.closed = True
        self.step("close")


def opened(*, timeout=1, cancelled=lambda: False):
    clock = Clock()
    api = API(clock)
    budget = IOBudget(timeout, clock=clock, cancelled=cancelled)
    channel = m.SerialDevice._open(budget, api)
    return channel, api, clock


def test_open_order_short_reads_partial_writes_and_exact_release():
    channel, api, _ = opened()
    assert api.calls == ["open", "validate", "claim", "attributes", "raw"]
    with channel:
        assert channel.read(8) == b"abc"
        api.counts.extend([2, 1])
        channel.write_all(b"abcdef")
        assert bytes(api.written) == b"abcdef"
    assert channel.closed and not channel.cleanup_unknown and api.closed
    assert api.calls[-3:] == ["restore", "release", "close"]
    channel.close()
    assert api.calls.count("close") == 1


@pytest.mark.parametrize("stage", ["open", "validate", "claim", "attributes", "raw"])
def test_open_failures_are_terminal_and_close_only_acquired_descriptor(stage):
    clock = Clock()
    api = API(clock)
    api.failure = stage
    with pytest.raises(PipeIOError, match="^serial_open$"):
        m.SerialDevice._open(IOBudget(1, clock=clock), api)
    assert api.calls.count("open") == 1
    assert api.calls.count("close") == (0 if stage == "open" else 1)
    assert ("release" in api.calls) is (stage in ("attributes", "raw"))
    assert ("restore" in api.calls) is (stage == "raw")


@pytest.mark.parametrize("stage", ["restore", "release", "close"])
def test_cleanup_failure_never_retries_possibly_recycled_fd(stage):
    channel, api, _ = opened()
    api.failure = stage
    with pytest.raises(m.SerialCleanupUnknown, match="^cleanup_unknown$") as failure:
        channel.close()
    assert failure.value.channel is channel
    assert channel.closed and channel.cleanup_unknown and channel._fd is None
    assert api.calls[-3:] == ["restore", "release", "close"]
    with pytest.raises(m.SerialCleanupUnknown):
        channel.close()
    assert api.calls.count("close") == 1


@pytest.mark.parametrize("stage", ["raw", "read", "write"])
def test_late_operation_is_rejected_and_exact_state_is_released(stage):
    clock = Clock()
    api = API(clock)

    def expire():
        clock.now = 1

    api.hooks[stage] = expire
    budget = IOBudget(1, clock=clock)
    if stage == "raw":
        with pytest.raises(PipeIOError, match="^deadline$"):
            m.SerialDevice._open(budget, api)
    else:
        channel = m.SerialDevice._open(budget, api)
        with pytest.raises(PipeIOError, match="^deadline$"):
            if stage == "read":
                channel.read(8)
            else:
                channel.write_all(b"abc")
        assert channel.closed
    assert api.closed and api.calls.count("close") == 1
    assert api.calls[-3:] == ["restore", "release", "close"]


def test_silent_read_uses_original_budget_and_bounded_poll_slices():
    channel, api, clock = opened(timeout=0.12)
    api.reads.clear()
    with pytest.raises(PipeIOError, match="^deadline$"):
        channel.read(8)
    assert clock.now == pytest.approx(0.12)
    assert api.closed and api.calls.count("wait") == 3


def test_cancellation_after_would_block_closes_owned_descriptor():
    stopped = []
    channel, api, _ = opened(cancelled=lambda: bool(stopped))
    api.reads.clear()
    api.hooks["wait"] = lambda: stopped.append(True)
    with pytest.raises(PipeIOError, match="^cancelled$"):
        channel.read(8)
    assert api.closed and api.calls.count("wait") == 1


def test_interrupted_and_would_block_transfers_never_restart_budget_or_duplicate_bytes():
    channel, api, clock = opened()
    with channel:
        api.reads = deque([InterruptedError(), BlockingIOError(), b"ok"])
        assert channel.read(8) == b"ok"
        api.counts.extend([InterruptedError(), BlockingIOError(), 1, 1])
        channel.write_all(b"abcdef")
        assert bytes(api.written) == b"abcdef"
        assert clock.now == pytest.approx(0.1)


@pytest.mark.parametrize("count", [0, -1, True, 4])
def test_invalid_write_count_is_terminal_without_replay(count):
    channel, api, _ = opened()
    api.counts.append(count)
    with pytest.raises(PipeIOError, match="^invalid_write_count$"):
        channel.write_all(b"abc")
    assert api.closed and api.calls.count("write") == 1


@pytest.mark.parametrize("size", [0, -1, True, 65537])
def test_bad_read_size_does_not_start_native_io(size):
    channel, api, _ = opened()
    try:
        with pytest.raises(ValueError, match="^invalid_read_size$"):
            channel.read(size)
        assert "read" not in api.calls and not channel.closed
    finally:
        channel.close()


def test_write_limits_chunking_eof_and_zero_length_write():
    channel, api, _ = opened()
    with channel:
        with pytest.raises(ValueError, match="^invalid_write$"):
            channel.write_all(b"x" * (m.MAX_WRITE_BYTES + 1))
        channel.write_all(b"")
        assert "write" not in api.calls
        channel.write_all(b"x" * (m.MAX_TRANSFER_BYTES + 1))
        assert api.calls.count("write") == 2
        api.reads = deque([b""])
        assert channel.read(1) == b""


def test_terminal_native_failure_is_sanitized_and_cleanup_unknown_takes_precedence():
    channel, api, _ = opened()
    api.failure = "read"
    with pytest.raises(PipeIOError, match="^serial_read$") as failure:
        channel.read(8)
    assert "PRIVATE_NATIVE_CANARY" not in str(failure.value)
    channel, api, _ = opened()
    api.reads = deque([OSError("PRIVATE_NATIVE_CANARY")])
    api.failure = "close"
    with pytest.raises(m.SerialCleanupUnknown):
        channel.read(8)
    assert api.closed and api.calls.count("close") == 1


def test_wrong_owner_and_reentry_leave_active_descriptor_untouched(monkeypatch):
    channel, api, _ = opened()
    try:
        with monkeypatch.context() as patch:
            patch.setattr(m.threading, "get_ident", lambda: -1)
            for action in (channel.close, lambda: channel.read(8)):
                with pytest.raises(PipeIOError, match="^wrong_thread$"):
                    action()
        channel._busy = True
        try:
            with pytest.raises(PipeIOError, match="^busy$"):
                channel.close()
        finally:
            channel._busy = False
        assert not api.closed and channel.read(8) == b"abc"
    finally:
        channel.close()


def test_non_linux_refuses_before_native_modules_or_device_open(monkeypatch):
    monkeypatch.setattr(m.sys, "platform", "win32")
    with pytest.raises(PipeIOError, match="^linux_required$"):
        m.SerialDevice.open(IOBudget(1))


def test_native_open_intent_is_fixed_no_follow_nonblocking_and_cloexec():
    calls = []

    def open_device(path, flags):
        calls.append((path, flags))
        return 7

    native = m._Linux.__new__(m._Linux)
    native.os = SimpleNamespace(open=open_device, O_RDWR=1, O_NOCTTY=2,
                                O_NONBLOCK=4, O_CLOEXEC=8, O_NOFOLLOW=16)
    assert native.open() == 7
    assert calls == [("/dev/ttyS0", 31)]


@pytest.mark.parametrize("fault", ["mode", "major", "minor", "inherit", "blocking"])
def test_native_identity_model_refuses_wrong_device_or_descriptor_flags(fault):
    native = m._Linux.__new__(m._Linux)
    native.os = SimpleNamespace(
        fstat=lambda fd: SimpleNamespace(st_mode=stat.S_IFREG if fault == "mode" else stat.S_IFCHR,
                                        st_rdev=1),
        major=lambda value: 5 if fault == "major" else 4,
        minor=lambda value: 65 if fault == "minor" else 64,
        get_inheritable=lambda fd: fault == "inherit",
        get_blocking=lambda fd: fault == "blocking",
    )
    with pytest.raises(PipeIOError, match="^serial_identity$"):
        native.validate(7)


def test_raw_mode_model_preserves_original_and_uses_immediate_non_flushing_change():
    original = [9, 9, 9, 9, 9, 9, [b"x", b"x"]]
    saved = copy.deepcopy(original)
    applied = []

    def set_attributes(fd, when, value):
        assert fd == 7 and when == 0
        applied.append(copy.deepcopy(value))

    native = m._Linux.__new__(m._Linux)
    native.term = SimpleNamespace(
        CS8=3, CSIZE=3, CREAD=1024, CLOCAL=512, CSTOPB=16, PARENB=32, PARODD=64,
        CRTSCTS=128, HUPCL=256, B115200=4098, VMIN=0, VTIME=1, TCSANOW=0,
        tcsetattr=set_attributes, tcgetattr=lambda fd: copy.deepcopy(applied[-1]),
    )
    native.raw(7, original)
    assert original == saved and applied[0][0:2] == [0, 0]
    assert applied[0][3] == 0 and applied[0][4:6] == [4098, 4098]
    assert applied[0][6] == [1, 0]
    native.restore(7, original)
    assert applied[-1] == saved
