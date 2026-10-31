"""Exact-child native owner candidate; unwired, Linux guest only.

No CLI, arbitrary plan/command interface, audit capture, policy/media/VM action or
native-validation receipt. Constructor WOULD spawn one fixed child. This module
must remain outside deployed inventories until complete-media/runner review.
"""
from __future__ import annotations

import math
import os
import platform
import re
import select
import signal
import stat
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Protocol, cast

from night_shifts.bootstrap_native_child_plan import render_native_child_plan
from night_shifts.bootstrap_native_supervision import POOL_CASE, WORKER_CASES, LocalWorkerObservation, WorkerReportSession
from night_shifts.maintenance_tls_prototype import AttemptBinding

# Prevent Popen.__del__ from polling/reaping an uncertain child. Only a verified
# exact reap removes this strong reference and sets returncode. No global reaper.
_RETAINED: list[subprocess.Popen[bytes]] = []
_CLEANUP_SECONDS = 1.0  # Separate failure cleanup only, never renews worker budget.


class NativeOwnerRefused(RuntimeError):
    """Fixed label only; no argv, report, PID, source or native exception text."""


class NativeOwnerUnknown(NativeOwnerRefused):
    """No child/tree/VM absence, rollback, retry or execution authority implied."""


class _Wait(Protocol):
    si_pid: int
    si_code: int
    si_status: int


class _Linux(Protocol):
    O_CLOEXEC: int
    O_NONBLOCK: int
    O_NOFOLLOW: int
    P_PIDFD: int
    P_PID: int
    WEXITED: int
    WNOHANG: int
    WNOWAIT: int
    CLD_EXITED: int
    CLD_KILLED: int
    CLD_DUMPED: int

    def getuid(self) -> int: ...
    def geteuid(self) -> int: ...
    def getgid(self) -> int: ...
    def getegid(self) -> int: ...
    def getgroups(self) -> list[int]: ...
    def pipe2(self, flags: int, /) -> tuple[int, int]: ...
    def pidfd_open(self, pid: int, flags: int = 0, /) -> int: ...
    def waitid(self, kind: int, identity: int, options: int, /) -> _Wait | None: ...
    def get_blocking(self, fd: int, /) -> bool: ...


class _Signals(Protocol):
    SIGCHLD: int
    SIGKILL: int
    SIG_DFL: int

    def getsignal(self, sig: int, /) -> object: ...
    def pidfd_send_signal(self, fd: int, sig: int, info: None, flags: int, /) -> None: ...


class _Poll(Protocol):
    def register(self, fd: int, eventmask: int, /) -> None: ...
    def poll(self, timeout: int, /) -> list[tuple[int, int]]: ...


class _Select(Protocol):
    POLLIN: int

    def poll(self) -> _Poll: ...


def _linux() -> _Linux:
    if sys.platform != 'linux':
        raise NativeOwnerRefused('linux_required')
    return cast(_Linux, os)


def _signals() -> _Signals:
    _linux()
    return cast(_Signals, signal)


def _pause(fd: int, seconds: float) -> None:
    # poll has no selector fd to leak and no FD_SETSIZE limit. Every wait is
    # <=20ms so cancellation is checked even when a pipe/PID never becomes ready.
    native = cast(_Select, select)
    poller = native.poll()
    poller.register(fd, native.POLLIN)
    poller.poll(max(0, min(20, math.ceil(seconds * 1000))))


def _system(path: str, limit: int) -> bytes:
    native = _linux()
    fd = os.open(path, os.O_RDONLY | native.O_CLOEXEC | native.O_NONBLOCK | native.O_NOFOLLOW)
    try:
        raw = os.read(fd, limit + 1)
        if len(raw) > limit:
            raise NativeOwnerRefused('runtime_bound')
        return raw
    finally:
        try:
            os.close(fd)
        except BaseException:
            # Never retry a possibly consumed fd number.
            raise NativeOwnerUnknown('descriptor_cleanup_unknown') from None


def _runtime() -> None:
    native, signals = _linux(), _signals()
    if (platform.machine() != 'x86_64' or platform.release() != '6.8.0-139-generic'
            or sys.version_info[:2] != (3, 12) or not sys.flags.isolated
            or not sys.flags.no_site or not sys.dont_write_bytecode
            or native.getuid() or native.geteuid() or native.getgid() or native.getegid()
            or native.getgroups() or dict(os.environ) != {'LANG': 'C', 'LC_ALL': 'C'}):
        raise NativeOwnerRefused('runtime')
    # Exclusive single-threaded supervisor is mandatory: no SIGCHLD handler,
    # ignored/autoreaped children, other child or competing wait/poll consumer.
    if (os.listdir('/proc/self/task') != [str(os.getpid())]
            or signals.getsignal(signals.SIGCHLD) != signals.SIG_DFL
            or _system('/proc/self/task/' + str(os.getpid()) + '/children', 4096).strip()
            or _system('/proc/self/attr/current', 256).strip() != b'unconfined'):
        raise NativeOwnerRefused('exclusive_owner')
    rows = _system('/proc/self/status', 16384).splitlines()
    for name in (b'SigIgn:', b'SigCgt:', b'SigBlk:'):
        values = [row.split()[1:] for row in rows if row.startswith(name)]
        if (len(values) != 1 or len(values[0]) != 1
                or re.fullmatch(b'[0-9a-fA-F]{16}', values[0][0]) is None
                or int(values[0][0], 16) & (1 << (signals.SIGCHLD - 1))):
            raise NativeOwnerRefused('sigchld')
    if _RETAINED:
        raise NativeOwnerUnknown('prior_child_unknown')


class NativeWorkerOwner:
    """One fixed child, two owned pipes and unreaped PID through caller capture.

    Required order: await_ready -> caller fresh audit cursor -> release_gate ->
    observe_exit -> caller capture/fixture checks -> reap_after_capture. This
    component does not authenticate those caller actions or collect audit data.
    On ANY error call abort once in a finally block. Do not use Popen APIs, a
    SIGCHLD handler, another waiter or this class concurrently. No retry API.
    """

    def __init__(
        self, binding: AttemptBinding, case_id: str, mode: str, *, seed_sha256: str,
        deadline: float, cancelled: Callable[[], bool] = lambda: False,
    ) -> None:
        self._fds: set[int] = set()
        self._process: subprocess.Popen[bytes] | None = None
        self._pidfd: int | None = None
        self._report = self._gate = -1
        self._last = 0.0
        self._failed = self._close_unknown = self._cleanup_attempted = False
        self._lifetime_unknown = False
        self._state = 'acquiring'
        self._observed: _Wait | None = None
        if (type(binding) is not AttemptBinding or type(case_id) is not str or case_id not in WORKER_CASES
                or type(mode) is not str or mode not in ('control', 'confined')
                or (case_id == POOL_CASE and mode != 'confined')
                or type(seed_sha256) is not str or re.fullmatch('[0-9a-f]{64}', seed_sha256) is None
                or type(deadline) not in (int, float) or not 0 <= deadline <= 1e15
                or not math.isfinite(deadline) or not callable(cancelled)):
            raise NativeOwnerRefused('context')
        self._deadline, self._cancelled = float(deadline), cancelled
        try:
            self._check()
            if deadline - self._last > 5:
                raise NativeOwnerRefused('context')
            _runtime()
            self._check()
            native = _linux()
            self._report, report_write = self._pipe()
            gate_read, self._gate = self._pipe()
            plan = render_native_child_plan(binding, case_id, mode, seed_sha256=seed_sha256,
                                            deadline=deadline, report_fd=report_write, gate_fd=gate_read)
            self._check()
            # Internal renderer only; no accepted caller plan, shell or preexec_fn.
            self._process = subprocess.Popen(
                plan.argv, shell=False, close_fds=True, pass_fds=plan.pass_fds,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                env=dict(plan.environment), cwd=plan.cwd, start_new_session=False,
            )
            _RETAINED.append(self._process)
            if type(self._process.pid) is not int or not 1 <= self._process.pid < 1 << 22:
                self._lifetime_unknown = True
                raise NativeOwnerUnknown('spawn_identity_unknown')
            self._pidfd = native.pidfd_open(self._process.pid, 0)
            self._fds.add(self._pidfd)
            if self._pidfd < 3 or os.get_inheritable(self._pidfd):
                raise NativeOwnerUnknown('pidfd_unknown')
            # Never let the parent keep a child report-write or gate-read end.
            self._close(report_write)
            self._close(gate_read)
            self._check()
            self._session = WorkerReportSession(binding, case_id, mode, self._process.pid,
                                                deadline=deadline, clock=time.monotonic, cancelled=cancelled)
            self._state = 'started'
        except BaseException as error:
            self._failed = True
            if self._process is not None and self._process not in _RETAINED:
                _RETAINED.append(self._process)
            try:
                self.abort()
            except NativeOwnerRefused:
                raise NativeOwnerUnknown('cleanup_unknown') from None
            if isinstance(error, NativeOwnerRefused):
                raise error from None
            raise NativeOwnerUnknown('acquisition_unknown') from None

    def _check(self) -> None:
        if self._failed or self._state in ('closed', 'cleanup_unknown'):
            raise NativeOwnerRefused('terminal')
        stopped, now = self._cancelled(), time.monotonic()
        if (type(stopped) is not bool or type(now) not in (int, float)
                or not 0 <= now <= 1e15 or not math.isfinite(now) or now < self._last):
            raise NativeOwnerUnknown('budget_unknown')
        self._last = float(now)
        if stopped or now >= self._deadline:
            raise NativeOwnerUnknown('budget_unknown')

    @contextmanager
    def _operation(self, state: str) -> Iterator[None]:
        try:
            self._check()
            if self._state != state:
                raise NativeOwnerRefused('order')
            yield
            self._check()
        except BaseException as error:
            self._failed = True
            if isinstance(error, NativeOwnerRefused):
                raise error from None
            raise NativeOwnerUnknown('operation_unknown') from None

    def _pipe(self) -> tuple[int, int]:
        native = _linux()
        ends = native.pipe2(native.O_CLOEXEC | native.O_NONBLOCK)
        self._fds.update(ends)
        if len(set(ends)) != 2:
            raise NativeOwnerRefused('pipe')
        identities = []
        for fd in ends:
            info = os.fstat(fd)
            if (not 3 <= fd < 1 << 20 or not stat.S_ISFIFO(info.st_mode)
                    or info.st_uid or info.st_gid or stat.S_IMODE(info.st_mode) != 0o600
                    or os.get_inheritable(fd) or native.get_blocking(fd)):
                raise NativeOwnerRefused('pipe')
            identities.append((info.st_dev, info.st_ino))
        if identities[0] != identities[1]:
            raise NativeOwnerRefused('pipe')
        return ends

    def _close(self, fd: int) -> None:
        if fd not in self._fds:
            return
        self._fds.remove(fd)  # Relinquish BEFORE close, including uncertain close.
        try:
            os.close(fd)
        except BaseException:
            self._close_unknown = True
            raise NativeOwnerUnknown('descriptor_cleanup_unknown') from None

    def _read(self) -> bool:
        self._check()
        try:
            data = os.read(self._report, 512)
        except BlockingIOError:
            return False
        if not data:
            self._session.end_of_reports()
            self._state = 'eof'
        else:
            self._session.feed(data)
        return True

    def await_ready(self) -> None:
        with self._operation('started'):
            while not self._session.ready_for_release:
                if not self._read():
                    _pause(self._report, self._deadline - self._last)
            self._state = 'ready'

    def release_gate(self) -> None:
        """Only after caller establishes authentic fresh audit cursor; write once."""
        with self._operation('ready'):
            # Reject queued/partial/pre-gate extra reports; never discard them.
            while self._read():
                pass
            if not self._session.ready_for_release:
                raise NativeOwnerRefused('gate_order')
            self._check()
            if os.write(self._gate, b'G') != 1:
                raise NativeOwnerUnknown('gate_write_unknown')
            self._close(self._gate)
            self._session.mark_gate_released()
            self._state = 'released'

    def _wait(self) -> _Wait | None:
        native = _linux()
        if self._lifetime_unknown:
            raise NativeOwnerUnknown('exit_identity_unknown')
        if self._process is None:
            return None
        # Numeric PID ONLY for observing/reaping our unreaped direct child when
        # pidfd acquisition failed. Never a numerical signal or broad wait(-1).
        kind = native.P_PIDFD if self._pidfd is not None else native.P_PID
        identity = self._pidfd if self._pidfd is not None else self._process.pid
        try:
            result = native.waitid(kind, identity, native.WEXITED | native.WNOHANG | native.WNOWAIT)
            if result is not None and (result.si_pid != self._process.pid
                                      or result.si_code not in (native.CLD_EXITED, native.CLD_KILLED, native.CLD_DUMPED)
                                      or type(result.si_status) is not int or not 0 <= result.si_status <= 255):
                raise ValueError
            return result
        except BaseException:
            self._lifetime_unknown = True
            raise NativeOwnerUnknown('exit_identity_unknown') from None

    def observe_exit(self) -> LocalWorkerObservation:
        """Observe normal exit WITHOUT reaping. Keep owner alive through capture."""
        with self._operation('released'):
            while self._state != 'eof':
                if not self._read():
                    _pause(self._report, self._deadline - self._last)
            self._close(self._report)
            while True:
                self._check()
                result = self._wait()
                if result is not None:
                    break
                assert self._pidfd is not None
                _pause(self._pidfd, self._deadline - self._last)
            self._observed = result
            if result.si_code != _linux().CLD_EXITED:
                raise NativeOwnerUnknown('abnormal_exit_unknown')
            value = self._session.finish_exit(worker_pid=result.si_pid, exit_code=result.si_status)
            self._state = 'held'
        return value

    def _reap(self, observed: _Wait) -> None:
        native = _linux()
        if self._lifetime_unknown:
            raise NativeOwnerUnknown('reap_unknown')
        assert self._process is not None
        kind = native.P_PIDFD if self._pidfd is not None else native.P_PID
        identity = self._pidfd if self._pidfd is not None else self._process.pid
        # A consuming wait MAY already have reaped even if it raises or returns
        # inconsistent data. Latch BEFORE the call; never retry that lifetime.
        self._lifetime_unknown = True
        try:
            result = native.waitid(kind, identity, native.WEXITED | native.WNOHANG)
            if (result is None or (result.si_pid, result.si_code, result.si_status)
                    != (observed.si_pid, observed.si_code, observed.si_status)):
                raise ValueError
            self._process.returncode = result.si_status if result.si_code == native.CLD_EXITED else -result.si_status
            _RETAINED.remove(self._process)
            self._process = None
            self._lifetime_unknown = False
        except BaseException:
            raise NativeOwnerUnknown('reap_unknown') from None

    def reap_after_capture(self) -> None:
        """Caller must finish authentic capture and fixture checks FIRST; no receipt."""
        with self._operation('held'):
            assert self._observed is not None
            self._reap(self._observed)
            for fd in tuple(self._fds):
                self._close(fd)
        self._state = 'closed'

    def abort(self) -> None:
        """One failure-cleanup attempt; exact pidfd SIGKILL then bounded exact reap.

        Does not consult cancellation (which must not suppress cleanup), and does
        not turn a failed/expired operation into success. Missing pidfd on a live
        child, signal/wait/close error or cleanup timeout remains UNKNOWN. Retained
        Popen prevents automatic reaping; the independent VM watchdog is required.
        """
        if self._state == 'closed':
            return
        if self._cleanup_attempted:
            raise NativeOwnerUnknown('cleanup_unknown')
        self._cleanup_attempted = self._failed = True
        unknown = self._close_unknown
        try:
            start = time.monotonic()
            if type(start) not in (int, float) or not 0 <= start <= 1e15 or not math.isfinite(start):
                raise NativeOwnerUnknown('cleanup_unknown')
            last, end = float(start), float(start) + _CLEANUP_SECONDS
            if self._lifetime_unknown:
                raise NativeOwnerUnknown('cleanup_unknown')
            if self._process is not None:
                result = self._wait()
                if result is None:
                    if self._pidfd is None:
                        raise NativeOwnerUnknown('cleanup_unknown')
                    signals = _signals()
                    signals.pidfd_send_signal(self._pidfd, signals.SIGKILL, None, 0)
                    while result is None:
                        now = time.monotonic()
                        if (type(now) not in (int, float) or not math.isfinite(now)
                                or not last <= now < end):
                            raise NativeOwnerUnknown('cleanup_unknown')
                        last = float(now)
                        result = self._wait()
                        if result is None:
                            _pause(self._pidfd, end - now)
                self._reap(result)
        except BaseException:
            unknown = True
        finally:
            # Attempt all remaining exact-owned closes once, even after failure.
            for fd in tuple(self._fds):
                try:
                    self._close(fd)
                except NativeOwnerRefused:
                    unknown = True
            self._pidfd = None
            self._state = 'cleanup_unknown' if unknown else 'closed'
        if unknown:
            raise NativeOwnerUnknown('cleanup_unknown') from None
