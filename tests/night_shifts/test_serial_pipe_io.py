"""Deterministic ownership/fault tests; no native handles, VM or credentials."""
from __future__ import annotations

import ctypes
from collections import deque

import pytest

from night_shifts import serial_pipe_io as m

PATH = r"\\.\pipe\night-shift-0123456789abcdef0123456789abcdef-com1"


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        assert 0 < seconds <= 0.01
        self.now += seconds


class API:
    def __init__(self):
        self.opens = []
        self.open_errors = deque()
        self.reads = deque([b"abc"])
        self.write_counts = deque()
        self.written = bytearray()
        self.handles = set()
        self.closes = []
        self.begins = []
        self.cancels = []
        self.completions = {}
        self.next_event = 100
        self.hold = False
        self.settle_cancel = True
        self.cancel_error = None
        self.begin_error = None
        self.event_error = False
        self.close_error = None
        self.poll_error = False
        self.cancelled = set()
        self.on_begin = lambda: None
        self.on_poll = lambda: None

    def open(self, path):
        self.opens.append(path)
        if self.open_errors:
            raise m._NativeFailure(self.open_errors.popleft())
        self.handles.add(11)
        return 11

    def event(self):
        if self.event_error:
            raise m._NativeFailure(8)
        self.next_event += 1
        self.handles.add(self.next_event)
        return self.next_event

    def begin(self, handle, pending, size, write):
        assert handle == 11
        self.begins.append(pending)
        if self.begin_error is not None:
            raise m._NativeFailure(self.begin_error)
        if write:
            count = self.write_counts.popleft() if self.write_counts else size
            if type(count) is int and 0 <= count <= size:
                self.written.extend(pending.buffer.raw[:count])
        else:
            data = self.reads.popleft() if self.reads else b""
            assert len(data) <= size
            ctypes.memmove(pending.buffer, data, len(data))
            count = len(data)
        self.completions[pending.event] = m._Completion(count)
        self.on_begin()

    def poll(self, handle, pending):
        assert handle == 11
        self.on_poll()
        if self.poll_error:
            raise m._NativeFailure(6)
        if pending.event in self.cancelled:
            return m._Completion(0, 995) if self.settle_cancel else None
        return None if self.hold else self.completions[pending.event]

    def cancel(self, handle, pending):
        assert handle == 11
        self.cancels.append(pending)
        self.cancelled.add(pending.event)
        if self.cancel_error is not None:
            raise m._NativeFailure(self.cancel_error)

    def close(self, handle):
        if handle == self.close_error:
            raise m._NativeFailure(6)
        assert handle in self.handles, "double close or foreign handle"
        self.handles.remove(handle)
        self.closes.append(handle)


def connected(*, timeout=0.05, api=None, clock=None):
    clock = clock or Clock()
    api = api or API()
    budget = m.IOBudget(timeout, clock=clock)
    channel = m.BoundedPipe._connect(
        PATH, budget, api, _sleep=clock.sleep, _cleanup_clock=clock,
        cleanup_timeout_seconds=0.03,
    )
    return channel, api, clock


def assert_released(channel, api):
    assert channel.closed and not channel.cleanup_unknown
    assert channel._handle is None and channel._pending is None
    assert not api.handles
    assert id(channel) not in m._QUARANTINE


@pytest.mark.parametrize("value", [0, -1, True, False, float("inf"), float("nan"), 901, "1", None])
def test_invalid_budgets(value):
    with pytest.raises(ValueError, match="invalid_timeout"):
        m.IOBudget(value)


@pytest.mark.parametrize("path", [
    "", "relative", r"\\server\pipe\night-shift-" + "a" * 32 + "-com1",
    r"\\.\pipe\personal", PATH + "\n", PATH + "\\child", PATH.upper(), None, 4,
])
def test_invalid_paths_never_load_native_api(path, monkeypatch):
    monkeypatch.setattr(m, "_Windows", lambda: pytest.fail("native API reached"))
    with pytest.raises(ValueError, match="invalid_local_pipe_path"):
        m.BoundedPipe.connect(path, m.IOBudget(1))


@pytest.mark.parametrize("seconds", [0, -1, 6, float("nan"), True])
def test_invalid_cleanup_allowance_precedes_native_load(seconds, monkeypatch):
    monkeypatch.setattr(m, "_Windows", lambda: pytest.fail("native API reached"))
    with pytest.raises(ValueError, match="invalid_timeout"):
        m.BoundedPipe.connect(PATH, m.IOBudget(1), cleanup_timeout_seconds=seconds)


def test_non_windows_refuses(monkeypatch):
    monkeypatch.setattr(m.sys, "platform", "linux")
    with pytest.raises(m.PipeIOError, match="^windows_required$"):
        m.BoundedPipe.connect(PATH, m.IOBudget(1))


def test_pending_layout_has_pointer_sized_fields():
    pointer = ctypes.sizeof(ctypes.c_void_p)
    assert ctypes.sizeof(m._OVERLAPPED) == (32 if pointer == 8 else 20)
    assert m._OVERLAPPED.hEvent.offset == pointer * 2 + 8


def test_retries_only_missing_or_busy_pipe_under_same_budget():
    api = API()
    api.open_errors.extend([2, 231])
    channel, api, clock = connected(api=api)
    assert api.opens == [PATH] * 3
    assert clock.now == pytest.approx(0.02)
    channel.close()
    assert_released(channel, api)


@pytest.mark.parametrize("code", [5, 53, 87, 109])
def test_open_errors_are_terminal_and_sanitized(code):
    api = API()
    api.open_errors.append(code)
    with pytest.raises(m.PipeIOError, match="^connect_failed$"):
        connected(api=api)
    assert api.opens == [PATH]
    assert not api.handles


def test_missing_pipe_connection_expires():
    api = API()
    api.open_errors.extend([2] * 20)
    clock = Clock()
    with pytest.raises(m.PipeIOError, match="^deadline$"):
        connected(api=api, clock=clock)
    assert clock.now == pytest.approx(0.05)
    assert not api.handles


def test_partial_writes_are_retried_without_duplication():
    channel, api, _ = connected()
    api.write_counts.extend([2, 1, 3])
    channel.write_all(b"abcdef")
    assert api.written == b"abcdef"
    assert len(api.begins) == 3
    assert not api.cancels
    channel.close()
    channel.close()
    assert_released(channel, api)


def test_large_write_is_chunked_and_empty_write_does_no_io():
    channel, api, _ = connected()
    channel.write_all(b"")
    assert not api.begins
    data = b"x" * (m.MAX_TRANSFER_BYTES + 3)
    channel.write_all(data)
    assert [len(p.buffer) for p in api.begins] == [m.MAX_TRANSFER_BYTES, 3]
    assert api.written == data
    channel.close()
    assert_released(channel, api)


def test_fragmented_reads_and_eof_do_not_reset_budget():
    channel, api, clock = connected(timeout=0.025)
    api.reads = deque([b"a", b"bc", b""])
    assert channel.read(3) == b"a"
    clock.now += 0.01
    assert channel.read(3) == b"bc"
    assert channel.read(3) == b""
    clock.now += 0.02
    with pytest.raises(m.PipeIOError, match="^deadline$"):
        channel.read(3)
    assert len(api.begins) == 3
    assert_released(channel, api)


@pytest.mark.parametrize("write", [False, True])
def test_stalled_io_cancels_exact_request_and_releases_after_completion(write):
    channel, api, clock = connected()
    api.hold = True
    with pytest.raises(m.PipeIOError, match="^deadline$"):
        channel.write_all(b"abc") if write else channel.read(3)
    assert clock.now == pytest.approx(0.05)
    assert api.cancels == api.begins
    assert api.closes == [api.begins[0].event, 11]
    assert_released(channel, api)
    with pytest.raises(m.PipeIOError, match="^closed$"):
        channel.read(1)
    assert len(api.opens) == 1


@pytest.mark.parametrize("write", [False, True])
def test_cancellation_after_submission_is_terminal(write):
    channel, api, _ = connected()
    api.hold = True
    channel._budget._cancelled = lambda: bool(api.begins)
    with pytest.raises(m.PipeIOError, match="^cancelled$"):
        channel.write_all(b"abc") if write else channel.read(3)
    assert api.cancels == api.begins
    assert_released(channel, api)


@pytest.mark.parametrize("write", [False, True])
def test_late_success_is_not_accepted(write):
    channel, api, clock = connected()
    api.on_poll = lambda: setattr(clock, "now", 0.06)
    with pytest.raises(m.PipeIOError, match="^deadline$"):
        channel.write_all(b"abc") if write else channel.read(3)
    assert_released(channel, api)


@pytest.mark.parametrize("code", [1168, 5])
def test_cancel_failure_still_checks_actual_completion(code):
    channel, api, _ = connected()
    api.hold = True
    api.cancel_error = code
    with pytest.raises(m.PipeIOError, match="^deadline$"):
        channel.read(3)
    assert_released(channel, api)


def test_unsettled_cancellation_retains_live_memory_and_forbids_io():
    channel, api, clock = connected()
    api.hold = True
    api.settle_cancel = False
    with pytest.raises(m.PipeCleanupUnknown, match="^cleanup_unknown$") as caught:
        channel.read(3)
    assert caught.value.channel is channel
    assert channel.closed and channel.cleanup_unknown
    assert clock.now == pytest.approx(0.08)
    assert channel._pending is api.begins[0]
    assert channel._pending.submitted
    assert m._QUARANTINE[id(channel)] is channel
    assert not api.closes and len(api.handles) == 2
    with pytest.raises(m.PipeIOError, match="^closed$"):
        channel.write_all(b"x")
    assert len(api.cancels) == 1  # No implicit cleanup retry.
    # Explicit same-owner observation only; no reconnect or operation replay.
    api.settle_cancel = True
    channel.close()
    assert len(api.opens) == 1
    assert_released(channel, api)


def test_failed_completion_observation_retains_resources():
    channel, api, _ = connected()
    api.poll_error = True
    with pytest.raises(m.PipeCleanupUnknown):
        channel.read(3)
    assert channel.cleanup_unknown and not api.closes
    api.poll_error = False
    channel.close()
    assert_released(channel, api)


@pytest.mark.parametrize("which", ["event", "pipe"])
def test_close_failure_is_unknown_until_explicit_observation(which):
    channel, api, _ = connected()
    api.close_error = 101 if which == "event" else 11
    with pytest.raises(m.PipeCleanupUnknown):
        channel.read(3) if which == "event" else channel.close()
    assert channel.cleanup_unknown
    assert len(api.cancels) == 0
    api.close_error = None
    channel.close()
    assert_released(channel, api)


@pytest.mark.parametrize("code", [38, 109, 232, 233])
def test_immediate_native_eof_releases_event(code):
    channel, api, _ = connected()
    api.begin_error = code
    assert channel.read(3) == b""
    assert not api.cancels
    channel.close()
    assert_released(channel, api)


def test_event_creation_failure_closes_channel():
    channel, api, _ = connected()
    api.event_error = True
    with pytest.raises(m.PipeIOError, match="^event_failed$"):
        channel.read(3)
    assert_released(channel, api)


@pytest.mark.parametrize("count", [0, -1, 4, True])
def test_zero_or_invalid_write_completions_fail(count):
    channel, api, _ = connected()
    api.write_counts.append(count)
    label = "zero_write" if count == 0 else "invalid_completion"
    with pytest.raises(m.PipeIOError, match=f"^{label}$"):
        channel.write_all(b"abc")
    assert_released(channel, api)


@pytest.mark.parametrize("size", [0, -1, True, 1.5, m.MAX_TRANSFER_BYTES + 1])
def test_read_sizes_refuse_without_issuing_io(size):
    channel, api, _ = connected()
    with pytest.raises(ValueError, match="invalid_read_size"):
        channel.read(size)
    assert not api.begins
    channel.close()
    assert_released(channel, api)


@pytest.mark.parametrize(
    "data", ["x", bytearray(b"x"), None, b"x" * (m.MAX_WRITE_BYTES + 1)],
    ids=["text", "mutable-bytes", "none", "oversized"],
)
def test_write_limits_refuse_without_issuing_io(data):
    channel, api, _ = connected()
    with pytest.raises(ValueError, match="invalid_write"):
        channel.write_all(data)
    assert not api.begins
    channel.close()
    assert_released(channel, api)


def test_wrong_owner_cannot_close_or_issue_io(monkeypatch):
    channel, api, _ = connected()
    with monkeypatch.context() as patch:
        patch.setattr(m.threading, "get_ident", lambda: -1)
        for operation in [channel.close, lambda: channel.read(3), lambda: channel.write_all(b"x")]:
            with pytest.raises(m.PipeIOError, match="^wrong_thread$"):
                operation()
    assert not api.begins and not api.closes
    channel.close()
    assert_released(channel, api)


def test_reentrant_close_cannot_free_pending_buffer():
    channel, api, _ = connected()
    def reentrant_close():
        with pytest.raises(m.PipeIOError, match="^busy$"):
            channel.close()
        assert channel._pending is api.begins[-1]
        assert not api.closes
    api.on_poll = reentrant_close
    assert channel.read(3) == b"abc"
    channel.close()
    assert_released(channel, api)


@pytest.mark.parametrize("value", [1, None, "yes"])
def test_invalid_cancellation_callback_result_fails_closed(value):
    channel, api, _ = connected()
    channel._budget._cancelled = lambda: value
    with pytest.raises(m.PipeIOError, match="^cancel_check_failed$"):
        channel.read(3)
    assert_released(channel, api)


def test_cancellation_callback_exception_is_sanitized():
    channel, api, _ = connected()
    def failed():
        raise RuntimeError("SECRET-DIAGNOSTIC")
    channel._budget._cancelled = failed
    with pytest.raises(m.PipeIOError, match="^cancel_check_failed$") as caught:
        channel.read(3)
    assert "SECRET" not in str(caught.value)
    assert caught.value.__suppress_context__
    assert_released(channel, api)


def test_context_manager_closes_on_caller_failure():
    channel, api, _ = connected()
    with pytest.raises(ValueError, match="caller"):
        with channel:
            raise ValueError("caller")
    assert_released(channel, api)
