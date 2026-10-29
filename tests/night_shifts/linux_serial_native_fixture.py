"""Test-only, process-isolated Linux PTY validation; never opens ttyS0.

Only private test seams select a newly owned PTY. Native termios, flock,
ioctls, read/write, poll and close remain real. No deployment/guest entry point.
A parent timeout is a test failure, not proof of graceful native cleanup.
"""
from __future__ import annotations

import errno
import importlib
import json
import multiprocessing
import stat
import sys
import time

from night_shifts.guest import serial_device_io as serial
from night_shifts.serial_pipe_io import IOBudget, PipeIOError

SERIAL_CASES = (
    "raw_round_trip", "identity_refusal", "fragmented_input", "silent_read",
    "stalled_write", "cancel_read", "cancel_write", "shared_deadline",
    "claim_and_recycled_fd",
)
_FIXTURE_CASES = ("fixture_ok", "fixture_failure", "fixture_malformed", "fixture_missing", "fixture_hang")
# Retain exact process ownership if even terminate/kill cannot be observed.
_UNREAPED = []
_RECEIPT_LIMIT = 1024


def _require(condition, label):
    if not condition:
        raise AssertionError(label)


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate")
        value[key] = item
    return value


def decode_receipt(raw, case):
    """Validate only bounded fixed-schema JSON; never deserialize child pickle."""
    try:
        if type(raw) is not bytes or not 0 < len(raw) <= _RECEIPT_LIMIT:
            raise ValueError("size")
        value = json.loads(raw.decode("ascii"), object_pairs_hook=_unique)
        fields = {"case", "state", "native", "released", "restored", "polls", "accepted"}
        if (type(value) is not dict or set(value) != fields or value["case"] != case
                or value["state"] != "passed" or type(value["native"]) is not bool
                or value["native"] is not (case in SERIAL_CASES)
                or value["released"] is not True or value["restored"] is not True
                or type(value["polls"]) is not int or not 0 <= value["polls"] <= 10000
                or type(value["accepted"]) is not int or not 0 <= value["accepted"] <= 4 * 1024 * 1024):
            raise ValueError("schema")
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise RuntimeError("fixture_receipt_invalid") from None
    return value


class _PtyAPI(serial._Linux):
    """Test-only substitute for open/identity, NOT a production device fallback."""

    def __init__(self, path, observer):
        super().__init__()
        self.path = path
        self.expected = self.os.fstat(observer)
        self.fd = None
        self.polls = 0
        self.accepted = bytearray()
        self.short_writes = 0
        self.cancel_after_poll = False
        self.cancelled = False

    def open(self):
        native = self.os
        self.fd = native.open(self.path, native.O_RDWR | native.O_NOCTTY | native.O_NONBLOCK
                              | native.O_CLOEXEC | native.O_NOFOLLOW)
        return self.fd

    def validate(self, fd):
        actual = self.os.fstat(fd)
        _require(stat.S_ISCHR(actual.st_mode), "pty_character_device")
        _require((actual.st_dev, actual.st_ino, actual.st_rdev)
                 == (self.expected.st_dev, self.expected.st_ino, self.expected.st_rdev),
                 "pty_exact_identity")
        _require(not self.os.get_inheritable(fd) and not self.os.get_blocking(fd), "pty_flags")

    def wait(self, fd, writing, seconds):
        self.polls += 1
        super().wait(fd, writing, seconds)
        if self.cancel_after_poll:
            self.cancelled = True

    def write(self, fd, data):
        count = super().write(fd, data)
        _require(len(self.accepted) + count <= 4 * 1024 * 1024, "trace_limit")
        self.accepted.extend(data[:count])
        self.short_writes += int(count < len(data))
        return count


def _closed(native, fd):
    try:
        native.fstat(fd)
    except OSError as error:
        _require(error.errno == errno.EBADF, "unexpected_fd_error")
    else:
        raise AssertionError("owned_fd_still_open")


def _expect_label(action, label):
    try:
        action()
    except PipeIOError as error:
        _require(str(error) == label, "unexpected_error_label")
    else:
        raise AssertionError("expected_terminal_failure")


def _native_case(case):
    if sys.platform != "linux":
        raise RuntimeError("linux_required")
    pty = importlib.import_module("pty")
    native = importlib.import_module("os")
    master, observer = pty.openpty()
    channel = None
    api = None
    try:
        native.set_inheritable(master, False)
        native.set_inheritable(observer, False)
        native.set_blocking(master, False)
        native.set_blocking(observer, False)
        path = native.ttyname(observer)
        _require(path.startswith("/dev/pts/") and path.rsplit("/", 1)[1].isdigit(), "pty_path")
        api = _PtyAPI(path, observer)
        original = api.attributes(observer)
        timeout = 0.3 if case in ("silent_read", "stalled_write", "shared_deadline") else 3
        budget = IOBudget(timeout, cancelled=lambda: api.cancelled)
        started = time.monotonic()
        channel = serial.SerialDevice._open(budget, api)
        fd = api.fd
        _require(fd is not None and fd == channel._fd, "exact_descriptor")
        active = api.attributes(observer)
        term = api.term
        _require(active[0] == active[1] == active[3] == 0, "native_raw_flags")
        _require(active[4] == active[5] == term.B115200, "native_speed")
        _require(active[6][term.VMIN] == 1 and active[6][term.VTIME] == 0, "native_min_time")
        _require(original == channel._original, "saved_attributes")

        def master_write(data):
            offset = 0
            while offset < len(data):
                budget.remaining()
                try:
                    count = native.write(master, data[offset:])
                except BlockingIOError:
                    api.wait(master, True, min(0.05, budget.remaining()))
                    continue
                _require(count > 0, "master_zero_write")
                offset += count

        def master_read(size):
            result = bytearray()
            while len(result) < size:
                budget.remaining()
                try:
                    data = native.read(master, size - len(result))
                except BlockingIOError:
                    api.wait(master, False, min(0.05, budget.remaining()))
                    continue
                _require(bool(data), "master_eof")
                result.extend(data)
            return bytes(result)

        def serial_read(size):
            result = bytearray()
            while len(result) < size:
                data = channel.read(size - len(result))
                _require(bool(data), "serial_eof")
                result.extend(data)
            return bytes(result)

        if case == "raw_round_trip":
            payload = bytes(range(256)) * 4
            master_write(payload)
            _require(serial_read(len(payload)) == payload, "raw_input_changed")
            channel.write_all(payload)
            _require(master_read(len(payload)) == payload, "raw_output_changed")
        elif case == "identity_refusal":
            # The actual production validator MUST reject the PTY. Never patch
            # DEVICE, stat(), or a native syscall to pretend this is ttyS0.
            _expect_label(lambda: serial._Linux().validate(fd), "serial_identity")
            _require(serial.DEVICE == "/dev/ttyS0", "production_device_changed")
        elif case == "fragmented_input":
            chunks = [b"a", b"\x00\r\n\x11\x13\xff", bytes(range(256)), b"end"]
            for chunk in chunks:
                master_write(chunk)
                _require(serial_read(len(chunk)) == chunk, "fragment_changed")
        elif case in ("silent_read", "cancel_read"):
            api.cancel_after_poll = case == "cancel_read"
            _expect_label(lambda: channel.read(8), "cancelled" if api.cancel_after_poll else "deadline")
            _require(api.polls > 0, "native_read_not_polled")
        elif case in ("stalled_write", "cancel_write"):
            api.cancel_after_poll = case == "cancel_write"
            payload = bytes(range(256)) * 4096  # 1 MiB, never drained by peer.
            _expect_label(lambda: channel.write_all(payload),
                          "cancelled" if api.cancel_after_poll else "deadline")
            _require(api.polls > 0 and 0 < len(api.accepted) < len(payload), "no_backpressure")
            _require(api.short_writes > 0, "no_native_partial_write")
            _require(bytes(api.accepted) == payload[:len(api.accepted)], "partial_write_replayed")
        elif case == "shared_deadline":
            master_write(b"first")
            _require(serial_read(5) == b"first", "first_read")
            deadline = budget._deadline
            _expect_label(lambda: channel.read(1), "deadline")
            _require(budget._deadline == deadline, "budget_renewed")
            _require(api.polls > 0, "native_second_read_not_polled")
        elif case == "claim_and_recycled_fd":
            try:
                api.fcntl.flock(observer, api.fcntl.LOCK_EX | api.fcntl.LOCK_NB)
            except BlockingIOError:
                pass
            else:
                raise AssertionError("claim_not_held")
        else:
            raise AssertionError("unknown_native_case")

        if case in ("silent_read", "stalled_write", "shared_deadline"):
            _require(timeout <= time.monotonic() - started < timeout + 1.5, "native_deadline_bound")
        if case in ("cancel_read", "cancel_write"):
            _require(api.cancelled and channel.closed, "native_cancellation_not_observed")
        channel.close()
        _require(channel.closed and not channel.cleanup_unknown and channel._fd is None, "channel_release")
        _closed(native, fd)  # Before opening anything which could reuse fd.
        _require(api.attributes(observer) == original, "attributes_not_restored")
        api.fcntl.flock(observer, api.fcntl.LOCK_EX | api.fcntl.LOCK_NB)
        api.fcntl.flock(observer, api.fcntl.LOCK_UN)
        # A new open succeeds after TIOCNXCL. This is not a claim that privileged
        # users/pre-existing opens cannot bypass TIOCEXCL during the session.
        reopened = native.open(path, native.O_RDWR | native.O_NOCTTY | native.O_NONBLOCK
                               | native.O_CLOEXEC | native.O_NOFOLLOW)
        try:
            channel.close()  # Must not close a newly reused descriptor number.
            native.fstat(reopened)
        finally:
            native.close(reopened)
        return dict(case=case, state="passed", native=True, released=True, restored=True,
                    polls=api.polls, accepted=len(api.accepted))
    finally:
        try:
            if channel is not None and not channel.cleanup_unknown:
                channel.close()
        finally:
            # No retry of an uncertain close, no process/name/device search.
            try:
                native.close(observer)
            finally:
                native.close(master)


def _worker(case, sender):
    try:
        if case == "fixture_hang":
            time.sleep(60)  # Deliberate test of the parent's exact-child cap.
            return
        if case == "fixture_missing":
            return
        if case == "fixture_malformed":
            raw = b"not-json"
        elif case == "fixture_failure":
            raise RuntimeError("synthetic_failure")
        else:
            value = (dict(case=case, state="passed", native=False, released=True, restored=True,
                          polls=0, accepted=0) if case == "fixture_ok" else _native_case(case))
            raw = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("ascii")
        _require(len(raw) <= _RECEIPT_LIMIT, "receipt_limit")
        # At most 1024 bytes, sent once before exit. Parent joins before reading;
        # this fits a Linux pipe's minimum atomic-write capacity with its header.
        sender.send_bytes(raw)
    except BaseException:
        # No native paths, exceptions, data, credentials or traceback in receipt.
        sender.send_bytes(b'{"state":"failed"}')
    finally:
        sender.close()


def run_case(case, *, timeout=8):
    """Fixed test cases only; bounded wait and exact-child reaping on every path."""
    if case not in SERIAL_CASES + _FIXTURE_CASES:
        raise ValueError("unknown_fixture_case")
    if type(timeout) not in (int, float) or not 0 < timeout <= 15:
        raise ValueError("invalid_fixture_timeout")
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_worker, args=(case, sender))
    started = False
    forced = False
    try:
        process.start()
        started = True
        sender.close()
        process.join(timeout)
        if process.is_alive():
            raise RuntimeError("fixture_deadline")
        _require(process.exitcode == 0, "fixture_process_failed")
        # Only after exact-child exit: a partial/missing record cannot strand a
        # blocking recv while a child still owns the write endpoint.
        try:
            raw = receiver.recv_bytes(_RECEIPT_LIMIT)
        except (OSError, EOFError):
            raise RuntimeError("fixture_receipt_missing") from None
        return decode_receipt(raw, case)
    finally:
        sender.close()
        receiver.close()
        if started and process.is_alive():
            forced = True
            process.terminate()
            process.join(2)
            if process.is_alive():
                process.kill()
                process.join(2)
            if process.is_alive():
                _UNREAPED.append(process)
                raise RuntimeError("fixture_process_cleanup_unknown")
        process.close()
        if forced:
            raise RuntimeError("fixture_required_termination")
