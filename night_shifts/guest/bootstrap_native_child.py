"""Standalone fixed child entry candidate; no CLI, spawn or boot activation.

Only stdlib here. A fresh isolated interpreter must already have been exec'd
through the fixed setpriv launch plan. No support import or worker evaluation
before zero capabilities/NNP, descriptor isolation and the exact profile check.
No fallback transition, source/path/command selection, retry or native receipt.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import re
import stat
import sys
import time
from typing import NoReturn, Protocol, cast
from uuid import UUID

WORKER_SHA256 = '2b6fc9a513525eb2d39a6a4c50ef050620228fc4ff596925c9a279fd86a9d3d2'
MAX_SOURCE_BYTES = 64 * 1024
MAX_CONTEXT_BYTES = 4096
PROFILE = 'night-shift-kvp-public-probe'
_FIELDS = {'attempt_id', 'vm_id', 'seed_sha256', 'case_id', 'mode', 'deadline'}
_CASES = ('runtime_write', 'pool_sibling_write', 'outside_exec', 'allowed_pools')
_CAPS = ('CapInh', 'CapPrm', 'CapEff', 'CapBnd', 'CapAmb')
_MAX_FD = (1 << 20) - 1


class NativeChildRefused(RuntimeError):
    """Fixed labels only; never native exceptions, source or context bytes."""


class NativeChildUnknown(NativeChildRefused):
    """No retry, restored state or child/tree/VM-cleanup assertion."""


class _DeviceInfo(Protocol):
    st_mode: int
    st_rdev: int


class _LinuxOs(Protocol):
    O_NOFOLLOW: int
    O_CLOEXEC: int
    O_NONBLOCK: int
    O_ACCMODE: int

    def getuid(self) -> int: ...
    def geteuid(self) -> int: ...
    def getgid(self) -> int: ...
    def getegid(self) -> int: ...
    def getgroups(self) -> list[int]: ...
    def fstat(self, fd: int, /) -> _DeviceInfo: ...
    def major(self, device: int, /) -> int: ...
    def minor(self, device: int, /) -> int: ...


class _Fcntl(Protocol):
    F_GETFL: int
    F_DUPFD_CLOEXEC: int

    def fcntl(self, fd: int, command: int, arg: int = 0, /) -> int: ...


def _linux() -> _LinuxOs:
    if sys.platform != 'linux':
        raise NativeChildRefused('linux_required')
    return cast(_LinuxOs, os)


def _fcntl() -> _Fcntl:
    _linux()
    import fcntl
    return cast(_Fcntl, fcntl)


class _Deadline:
    def __init__(self, value: str) -> None:
        try:
            self.end = float(value)
            self.last = 0.0
            self.check()
            if not 0 < self.end - self.last <= 5:
                raise ValueError
        except (ValueError, OverflowError):
            raise NativeChildRefused('context') from None

    def check(self) -> None:
        now = time.monotonic()
        if (type(now) not in (int, float) or not math.isfinite(now)
                or not 0 <= now <= 1e15 or now < self.last
                or not math.isfinite(self.end) or not 0 <= self.end <= 1e15
                or now >= self.end):
            raise NativeChildUnknown('deadline_unknown')
        self.last = float(now)


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _constant(_: str) -> NoReturn:
    raise ValueError


def _context(raw: bytes) -> tuple[dict[str, str], int, int]:
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_CONTEXT_BYTES:
        raise NativeChildRefused('context')
    try:
        value = json.loads(raw.decode('ascii'), object_pairs_hook=_unique, parse_constant=_constant)
        if (type(value) is not dict or set(value) != _FIELDS | {'report_fd', 'gate_fd'}
                or any(type(value[key]) is not str for key in _FIELDS)
                or any(type(value[key]) is not int or not 3 <= value[key] <= _MAX_FD
                       for key in ('report_fd', 'gate_fd'))
                or value['report_fd'] == value['gate_fd']):
            raise ValueError
        if (re.fullmatch('[0-9a-f]{32}', value['attempt_id']) is None
                or re.fullmatch('[0-9a-f]{64}', value['seed_sha256']) is None
                or value['case_id'] not in _CASES or value['mode'] not in ('control', 'confined')
                or (value['case_id'] == 'allowed_pools' and value['mode'] != 'confined')):
            raise ValueError
        vm = UUID(value['vm_id'])
        if not vm.int or str(vm) != value['vm_id']:
            raise ValueError
        return {key: value[key] for key in _FIELDS}, value['report_fd'], value['gate_fd']
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise NativeChildRefused('context') from None


def _read(path: str, limit: int, deadline: _Deadline) -> bytes:
    native = _linux()
    deadline.check()
    fd = os.open(path, os.O_RDONLY | native.O_NOFOLLOW | native.O_CLOEXEC | native.O_NONBLOCK)
    try:
        raw = bytearray()
        while True:
            deadline.check()
            chunk = os.read(fd, limit + 1 - len(raw))
            if not chunk:
                return bytes(raw)
            raw.extend(chunk)
            if len(raw) > limit:
                raise NativeChildRefused('input_bound')
    finally:
        try:
            os.close(fd)
        except OSError:
            raise NativeChildUnknown('descriptor_cleanup_unknown') from None


def _status(deadline: _Deadline) -> None:
    fields: dict[str, str] = {}
    for line in _read('/proc/self/status', 131072, deadline).decode('ascii').splitlines():
        key, separator, value = line.partition(':')
        if not separator or key in fields:
            raise NativeChildRefused('capabilities')
        fields[key] = value.strip()
    if (fields.get('NoNewPrivs') != '1'
            or any(fields.get(key) != '0000000000000000' for key in _CAPS)):
        raise NativeChildRefused('capabilities')


def _label(expected: str, deadline: _Deadline) -> None:
    if _read('/proc/self/attr/current', 256, deadline).decode('ascii').strip() != expected:
        raise NativeChildRefused('profile')


def _runtime(deadline: _Deadline) -> None:
    native = _linux()
    deadline.check()
    if (platform.machine() != 'x86_64' or platform.release() != '6.8.0-139-generic'
            or sys.version_info[:2] != (3, 12) or not sys.flags.isolated
            or not sys.flags.no_site or not sys.dont_write_bytecode):
        raise NativeChildRefused('runtime')
    if (native.getuid() or native.geteuid() or native.getgid() or native.getegid()
            or native.getgroups() or dict(os.environ) != {'LANG': 'C', 'LC_ALL': 'C'}):
        raise NativeChildRefused('identity_environment')
    if sorted(os.listdir('/proc/self/task')) != [str(os.getpid())]:
        raise NativeChildRefused('single_thread_required')
    if any(name == 'night_shifts' or name.startswith('night_shifts.') for name in sys.modules):
        raise NativeChildRefused('import_collision')
    _status(deadline)
    _label('unconfined', deadline)


def _stdio() -> None:
    native = _linux()
    for fd in (0, 1, 2):
        info = native.fstat(fd)
        if not stat.S_ISCHR(info.st_mode) or (native.major(info.st_rdev), native.minor(info.st_rdev)) != (1, 3):
            raise NativeChildRefused('stdio')


def _pipe(fd: int, access: int, *, private: bool) -> tuple[int, int]:
    native, control = _linux(), _fcntl()
    info = os.fstat(fd)
    flags = control.fcntl(fd, control.F_GETFL)
    if (not stat.S_ISFIFO(info.st_mode) or info.st_uid or info.st_gid
            or stat.S_IMODE(info.st_mode) != 0o600 or os.get_blocking(fd)
            or flags & native.O_ACCMODE != access or not flags & native.O_NONBLOCK
            or (private and os.get_inheritable(fd))):
        raise NativeChildRefused('pipe_security')
    return info.st_dev, info.st_ino


def _fds() -> set[int]:
    names = os.listdir('/proc/self/fd')
    if len(names) > 8192:
        raise NativeChildRefused('descriptor_bound')
    result: set[int] = set()
    for name in names:
        if not name.isdecimal() or len(name) > 7 or not 0 <= int(name) <= _MAX_FD or str(int(name)) != name:
            raise NativeChildRefused('descriptors')
        try:
            os.readlink('/proc/self/fd/' + name)
        except FileNotFoundError:
            continue  # Only the already-closed transient listdir fd is expected.
        result.add(int(name))
    return result


def _inventory(report: tuple[int, int], gate: tuple[int, int]) -> None:
    _stdio()
    if (_fds() != {0, 1, 2, 3, 4}
            or _pipe(3, os.O_WRONLY, private=True) != report
            or _pipe(4, os.O_RDONLY, private=True) != gate or report == gate):
        raise NativeChildRefused('descriptors')


def _map(report_fd: int, gate_fd: int, deadline: _Deadline) -> tuple[tuple[int, int], tuple[int, int]]:
    deadline.check()
    _stdio()
    active = _fds()
    if not {0, 1, 2, report_fd, gate_fd} <= active:
        raise NativeChildRefused('descriptors')
    report = _pipe(report_fd, os.O_WRONLY, private=False)
    gate = _pipe(gate_fd, os.O_RDONLY, private=False)
    if report == gate:
        raise NativeChildRefused('pipe_identity')
    control = _fcntl()
    # Copy BOTH before touching 3/4: handles 3<->4 swaps and occupied targets.
    # No preexec_fn, shared-process fd repair or inheritable staging copy.
    report_copy = control.fcntl(report_fd, control.F_DUPFD_CLOEXEC, 5)
    gate_copy = control.fcntl(gate_fd, control.F_DUPFD_CLOEXEC, 5)
    os.dup2(report_copy, 3, inheritable=False)
    os.dup2(gate_copy, 4, inheritable=False)
    unknown = False
    for fd in sorted(_fds() - {0, 1, 2, 3, 4}, reverse=True):
        try:
            os.close(fd)  # Exact fd once; a failed POSIX close is never retried.
        except OSError:
            unknown = True
    if unknown:
        raise NativeChildUnknown('descriptor_cleanup_unknown')
    _inventory(report, gate)
    deadline.check()
    return report, gate


def _transition(deadline: _Deadline) -> None:
    native = _linux()
    deadline.check()
    fd = os.open('/proc/self/attr/current', os.O_WRONLY | native.O_NOFOLLOW | native.O_CLOEXEC)
    try:
        raw = ('changeprofile ' + PROFILE).encode('ascii')
        if os.write(fd, raw) != len(raw):
            raise NativeChildUnknown('profile_transition_unknown')
    finally:
        try:
            os.close(fd)
        except OSError:
            raise NativeChildUnknown('descriptor_cleanup_unknown') from None
    deadline.check()


def _evaluate(source: bytes, context: dict[str, str]) -> int:
    namespace: dict[str, object] = {'__name__': '_night_shift_fixed_native_worker',
                                   '__file__': '<fixed-native-worker>'}
    exec(compile(source, '<fixed-native-worker>', 'exec', dont_inherit=True), namespace)
    run = namespace.get('run_fixed_case')
    if not callable(run):
        raise NativeChildRefused('worker_entry')
    result = run(context)
    if type(result) is not int or result != 0:
        raise NativeChildUnknown('worker_exit_unknown')
    return 0


def enter(raw_context: bytes, worker_source: bytes) -> int:
    """Only the fixed fresh-interpreter wrapper; never call in the supervisor.

    setpriv must already have removed capabilities/set NNP. This entry CHECKS
    that before fd mapping, never attempts capability repair. A confined worker
    transitions after those checks and before any worker compile/evaluation.
    On any failure the wrapper must immediately os._exit(125), not reuse this
    partially transformed process or treat EOF as a worker success.
    """
    try:
        context, report_fd, gate_fd = _context(raw_context)
        deadline = _Deadline(context['deadline'])
        if (type(worker_source) is not bytes or not 0 < len(worker_source) <= MAX_SOURCE_BYTES
                or hashlib.sha256(worker_source).hexdigest() != WORKER_SHA256):
            raise NativeChildRefused('worker_digest')
        _runtime(deadline)
        report, gate = _map(report_fd, gate_fd, deadline)
        if context['mode'] == 'confined':
            _transition(deadline)
        _status(deadline)
        _label(PROFILE + ' (enforce)' if context['mode'] == 'confined' else 'unconfined', deadline)
        _inventory(report, gate)
        deadline.check()
        return _evaluate(worker_source, context)
    except NativeChildRefused:
        raise
    except Exception:
        raise NativeChildUnknown('child_entry_unknown') from None
