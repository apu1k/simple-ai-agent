"""Bounded /dev/kmsg and fixed single-worker orchestration, guest-only candidate.

UNWIRED. Construction would read native logs; observe_fixed_worker would spawn
one fixed native worker. No CLI, policy/media/VM action or native pass/receipt.
Never deploy/run without complete immutable-media and independent host review.
"""
from __future__ import annotations

import errno
import math
import os
import platform
import re
import stat
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol, cast

from night_shifts.bootstrap_native_denials import (
    MAX_CAPTURE_BYTES, MAX_COUNTER, MAX_RECORD_BYTES, MAX_RECORDS, MAX_WINDOW_US,
    LocalDenialCorrelation, correlate_local_denial,
)
from night_shifts.bootstrap_native_owner import NativeWorkerOwner, _pause, _system
from night_shifts.bootstrap_native_ram import NativeRamFixtures
from night_shifts.bootstrap_native_supervision import CASES, LocalWorkerObservation

MAX_BASELINE_RECORDS = 4096
MAX_BASELINE_BYTES = 4 * 1024 * 1024
QUIET_TAIL_NS = 100_000_000
_HEADER = re.compile(rb'([0-9]{1,3}),([0-9]{1,20}),([0-9]{1,20}),-;([ -~]+)\n')
# Historical bodies/continuations are discarded, not attributed. Native kmsg
# returns whole records (which can include device metadata lines). Only actual
# capture uses the strict single-line grammar required by the correlator.
_BASELINE_HEADER = re.compile(rb'([0-9]{1,3}),([0-9]{1,20}),([0-9]{1,20}),[-c];(.*)\n', re.DOTALL)
_SUPPRESSION = (b'suppressed', b'rate limit', b'ratelimit', b'audit_lost=', b'backlog limit')


class NativeCaptureRefused(RuntimeError):
    """Fixed labels only, never log bytes, paths or native exception text."""


class NativeCaptureUnknown(NativeCaptureRefused):
    """No attribution, pass, rollback, retry or process/VM absence implied."""


@dataclass(frozen=True)
class LocalKernelInterval:
    """Local bounded data, forgeable by callers, NOT authentic native evidence.

    Raw records stay in trusted supervisor memory for the existing correlator.
    Never serialize/forward them as the guest summary or include them in errors.
    """

    baseline_sequence: int
    start_us: int
    end_us: int
    records: tuple[bytes, ...] = field(repr=False)


@dataclass(frozen=True)
class LocalCapturedWorker:
    """ONE local worker/interval, not paired controls or a validator/cleanup pass."""

    worker: LocalWorkerObservation
    interval: LocalKernelInterval = field(repr=False)
    denial: LocalDenialCorrelation | None


class _LinuxDeviceInfo(Protocol):
    """Linux stat field absent from Windows-hosted stat_result declarations."""

    @property
    def st_rdev(self) -> int: ...


class _Linux(Protocol):
    O_CLOEXEC: int
    O_NONBLOCK: int
    O_NOFOLLOW: int

    def getuid(self) -> int: ...
    def geteuid(self) -> int: ...
    def getgid(self) -> int: ...
    def getegid(self) -> int: ...
    def getgroups(self) -> list[int]: ...
    def major(self, device: int, /) -> int: ...
    def minor(self, device: int, /) -> int: ...
    def get_blocking(self, fd: int, /) -> bool: ...


def _linux() -> _Linux:
    if sys.platform != 'linux':
        raise NativeCaptureRefused('linux_required')
    return cast(_Linux, os)


def _runtime() -> None:
    native = _linux()
    if (platform.machine() != 'x86_64' or platform.release() != '6.8.0-139-generic'
            or sys.version_info[:2] != (3, 12) or not sys.flags.isolated
            or not sys.flags.no_site or not sys.dont_write_bytecode
            or native.getuid() or native.geteuid() or native.getgid() or native.getegid()
            or native.getgroups() or dict(os.environ) != {'LANG': 'C', 'LC_ALL': 'C'}
            or os.listdir('/proc/self/task') != [str(os.getpid())]
            or _system('/proc/self/attr/current', 256).strip() != b'unconfined'):
        raise NativeCaptureRefused('runtime')


def _identity(info: os.stat_result) -> tuple[int, ...]:
    native = _linux()
    device = cast(_LinuxDeviceInfo, info)
    if (not stat.S_ISCHR(info.st_mode) or info.st_uid or info.st_gid or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) != 0o600
            or (native.major(device.st_rdev), native.minor(device.st_rdev)) != (1, 11)):
        raise NativeCaptureRefused('log_device')
    return (info.st_dev, info.st_ino, device.st_rdev, info.st_mode, info.st_uid,
            info.st_gid, info.st_nlink, info.st_ctime_ns)


def _header(raw: bytes, *, baseline: bool = False) -> tuple[int, int]:
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_RECORD_BYTES:
        raise NativeCaptureUnknown('record_bound_unknown')
    match = (_BASELINE_HEADER if baseline else _HEADER).fullmatch(raw)
    if match is None:
        raise NativeCaptureUnknown('record_shape_unknown')
    priority, sequence, stamp = (int(match[n]) for n in (1, 2, 3))
    if priority > 191 or sequence > MAX_COUNTER or stamp > MAX_COUNTER:
        raise NativeCaptureUnknown('record_shape_unknown')
    if any(token in match[4].lower() for token in _SUPPRESSION):
        raise NativeCaptureUnknown('log_loss_unknown')
    return sequence, stamp


def _context(deadline: float, cancelled: Callable[[], bool]) -> None:
    if (type(deadline) not in (int, float) or not 0 <= deadline <= 1e15
            or not math.isfinite(deadline) or not callable(cancelled)):
        raise NativeCaptureRefused('context')


class NativeKernelCapture:
    """One cursor, acquired AFTER readiness and before gate release.

    Read-only fixed device, no dmesg/journal fallback or userspace marker write.
    Initial bounded drain establishes the actual last sequence; SEEK_END alone
    cannot supply it. Caller must retain exact child WNOWAIT through finish and
    correlation. Finite quiet tail cannot prove absence of all future audit logs.
    """

    def __init__(self, *, deadline: float, cancelled: Callable[[], bool] = lambda: False) -> None:
        self._fd: int | None = None
        self._failed = self._finished = self._closed = self._close_unknown = False
        self._last_ns = 0
        _context(deadline, cancelled)
        self._deadline, self._cancelled = float(deadline), cancelled
        try:
            now = self._check()
            if deadline - now / 1e9 > 5:
                raise NativeCaptureRefused('context')
            _runtime()
            self._check()
            native = _linux()
            self._identity = _identity(os.stat('/dev/kmsg', follow_symlinks=False))
            self._fd = os.open('/dev/kmsg', os.O_RDONLY | native.O_CLOEXEC | native.O_NONBLOCK | native.O_NOFOLLOW)
            self._device()
            if os.lseek(self._fd, 0, os.SEEK_SET) != 0:
                raise NativeCaptureUnknown('cursor_unknown')
            self._baseline()
            self._device()
            self._check()
        except BaseException as error:
            self._failed = True
            self.close()
            if isinstance(error, NativeCaptureRefused):
                raise error from None
            raise NativeCaptureUnknown('acquisition_unknown') from None

    def _check(self) -> int:
        stopped, now = self._cancelled(), time.monotonic_ns()
        if (type(stopped) is not bool or type(now) is not int
                or not self._last_ns <= now <= MAX_COUNTER * 1000):
            raise NativeCaptureUnknown('budget_unknown')
        self._last_ns = now
        if stopped or now / 1e9 >= self._deadline:
            raise NativeCaptureUnknown('budget_unknown')
        return now

    def _device(self) -> None:
        assert self._fd is not None
        if (self._fd < 3 or os.get_inheritable(self._fd) or _linux().get_blocking(self._fd)
                or _identity(os.fstat(self._fd)) != self._identity
                or _identity(os.stat('/dev/kmsg', follow_symlinks=False)) != self._identity):
            raise NativeCaptureUnknown('log_identity_unknown')

    def _read(self) -> bytes | None:
        assert self._fd is not None
        try:
            # Linux kmsg reads are whole-record or fail (e.g. EINVAL/EPIPE).
            # Never assemble fragments or retry with a larger buffer after error.
            raw = os.read(self._fd, MAX_RECORD_BYTES + 1)
        except BlockingIOError as error:
            if error.errno != errno.EAGAIN:  # Linux EAGAIN == EWOULDBLOCK.
                raise NativeCaptureUnknown('log_read_unknown') from None
            return None
        if not raw:
            raise NativeCaptureUnknown('log_eof_unknown')
        return raw

    def _baseline(self) -> None:
        count = size = 0
        previous: tuple[int, int] | None = None
        while True:
            before = self._check()
            raw = self._read()
            after = self._check()
            if raw is None:
                if previous is None or previous[0] > MAX_COUNTER - MAX_RECORDS:
                    raise NativeCaptureUnknown('baseline_unknown')
                self._baseline_sequence, self._start_us = previous[0], before // 1000
                return
            count, size = count + 1, size + len(raw)
            if count > MAX_BASELINE_RECORDS or size > MAX_BASELINE_BYTES:
                raise NativeCaptureUnknown('baseline_bound_unknown')
            sequence, stamp = _header(raw, baseline=True)
            if (stamp > after // 1000 or (previous is not None
                    and (sequence != previous[0] + 1 or stamp < previous[1]))):
                raise NativeCaptureUnknown('baseline_gap_unknown')
            previous = sequence, stamp

    def finish(self) -> LocalKernelInterval:
        """Collect through 100ms quiet while exact exited child remains unreaped.

        No raw forwarding or audit authenticity is conferred by the return type.
        Delayed/missing attribution is not guessed, injected or retried.
        """
        if self._failed or self._finished or self._closed:
            raise NativeCaptureRefused('terminal')
        try:
            self._device()
            records: list[bytes] = []
            size = 0
            sequence, stamp = self._baseline_sequence, self._start_us
            quiet_since: int | None = None
            while True:
                before = self._check()
                raw = self._read()
                after = self._check()
                if raw is None:
                    if quiet_since is None:
                        quiet_since = before
                    if before - quiet_since >= QUIET_TAIL_NS:
                        # Sample BEFORE the final empty read, not later after
                        # more records might have arrived beyond this cursor cut.
                        end_us = before // 1000
                        if not 0 <= end_us - self._start_us <= MAX_WINDOW_US:
                            raise NativeCaptureUnknown('capture_window_unknown')
                        self._device()
                        self._check()
                        self._finished = True
                        return LocalKernelInterval(self._baseline_sequence, self._start_us, end_us, tuple(records))
                    assert self._fd is not None
                    _pause(self._fd, self._deadline - after / 1e9)
                    continue
                quiet_since = None
                size += len(raw)
                if len(records) >= MAX_RECORDS or size > MAX_CAPTURE_BYTES:
                    raise NativeCaptureUnknown('capture_bound_unknown')
                next_sequence, next_stamp = _header(raw)
                if (next_sequence != sequence + 1 or not stamp <= next_stamp <= after // 1000):
                    raise NativeCaptureUnknown('capture_gap_unknown')
                sequence, stamp = next_sequence, next_stamp
                records.append(raw)
        except BaseException as error:
            self._failed = True
            if isinstance(error, NativeCaptureRefused):
                raise error from None
            raise NativeCaptureUnknown('capture_unknown') from None

    def close(self) -> None:
        """Close once even after failure/cancellation; no device/child absence proof."""
        self._closed = True
        fd, self._fd = self._fd, None
        if fd is not None:
            try:
                os.close(fd)
            except BaseException:
                self._close_unknown = True
        if self._close_unknown:
            raise NativeCaptureUnknown('descriptor_cleanup_unknown') from None


def observe_fixed_worker(
    fixtures: NativeRamFixtures, case_id: str, mode: str, *, deadline: float,
    cancelled: Callable[[], bool] = lambda: False,
) -> LocalCapturedWorker:
    """Native SINGLE worker sequence, not the full paired/nine-worker validator.

    Would spawn. Caller must own reviewed guest isolation/held fixtures and the
    independent host lifetime bound. Child binding/seed are derived from those
    fixture pins, not caller-supplied alternative identity. No retry or receipt.
    """
    _context(deadline, cancelled)
    if (type(fixtures) is not NativeRamFixtures or type(case_id) is not str or case_id not in CASES
            or type(mode) is not str or mode not in ('control', 'confined')):
        raise NativeCaptureRefused('context')
    child: NativeWorkerOwner | None = None
    capture: NativeKernelCapture | None = None
    result: LocalCapturedWorker | None = None
    failure: str | None = None
    try:
        binding, seed_sha256 = fixtures.launch_context()
        fixtures.verify(deadline=deadline, cancelled=cancelled)
        child = NativeWorkerOwner(binding, case_id, mode, seed_sha256=seed_sha256,
                                  deadline=deadline, cancelled=cancelled)
        child.await_ready()
        fixtures.verify(deadline=deadline, cancelled=cancelled)
        capture = NativeKernelCapture(deadline=deadline, cancelled=cancelled)
        child.release_gate()
        worker = child.observe_exit()  # WNOWAIT: PID remains owned through below.
        interval = capture.finish()
        fixtures.verify(deadline=deadline, cancelled=cancelled)
        denial = None
        if mode == 'confined':
            denial = correlate_local_denial(
                case_id, worker_pid=worker.worker_pid, syscall_errno=worker.syscall_errno,
                baseline_sequence=interval.baseline_sequence, start_us=interval.start_us,
                end_us=interval.end_us, records=interval.records,
            )
        capture.close()  # An uncertain log close must not yield a local result.
        child.reap_after_capture()
        result = LocalCapturedWorker(worker, interval, denial)
    except BaseException:
        failure = 'worker_observation_unknown'
    finally:
        # Always attempt BOTH cleanups; no uncertain wait/reap/close is retried
        # by the components. Caller-owned fixture handles/artifacts are retained.
        if capture is not None:
            try:
                capture.close()
            except BaseException:
                failure = 'cleanup_unknown'
        if child is not None:
            try:
                child.abort()
            except BaseException:
                failure = 'cleanup_unknown'
    if failure is not None:
        raise NativeCaptureUnknown(failure) from None
    assert result is not None
    return result
