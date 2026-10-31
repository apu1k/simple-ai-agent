"""Unwired validation-only guest worker SOURCE CANDIDATE, never a host CLI.

Only stdlib before a full support-ZIP pin and runtime/label checks. A separately
reviewed trusted entry must establish the exact VM/media, readonly RAM root,
private namespaces, zero capabilities/NNP and (for confined mode) the enforced
profile BEFORE evaluating this source. No policy transition/load, fixture setup,
mount, daemon, VM operation, retry or cleanup is implemented here.

The future supervisor must pin/control the otherwise-valid fixtures and own the
worker and two pipes. These checks cannot authenticate caller-provided context.
No runnable supervisor, media handoff or deployment inventory includes this file.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import math
import os
import platform
import re
import select
import stat
import sys
import time
from typing import Protocol, cast
from uuid import UUID

PROFILE = 'night-shift-kvp-public-probe (enforce)'
SEED = '/run/night-shift-bootstrap/support.zip'
FIXTURE_SHA256 = '20ca4e55db7e6a7010eca0fb65eca069aebeff95a8b8ad147ef46cbcd36d018d'
REPORT_FD = 3
GATE_FD = 4
_PATHS = {
    'runtime_write': '/run/night-shift-bootstrap/denied-write',
    'pool_sibling_write': '/var/lib/hyperv/.kvp_pool_denied',
    'outside_exec': '/run/night-shift-bootstrap/denied-exec',
}
_POOL_CASE = 'allowed_pools'
_POOL_PATHS = tuple('/var/lib/hyperv/.kvp_pool_' + str(index) for index in range(5))
_FIELDS = {'attempt_id', 'vm_id', 'seed_sha256', 'case_id', 'mode', 'deadline'}
_CAPS = ('CapInh', 'CapPrm', 'CapEff', 'CapBnd', 'CapAmb')


class NativeWorkerRefused(RuntimeError):
    """Fixed labels only; never emit native exception text, raw logs or files."""


class NativeWorkerUnknown(NativeWorkerRefused):
    """An operation/partial report may have happened; no retry or absence claim."""


class _LinuxDeviceStat(Protocol):
    """Only the native device fields missing from Windows stat stubs."""

    st_mode: int
    st_rdev: int


class _LinuxOs(Protocol):
    """Narrow Linux stdlib ABI, not an injectable backend or fallback."""

    O_ACCMODE: int
    O_NOFOLLOW: int
    O_CLOEXEC: int
    O_NONBLOCK: int

    def fstat(self, fd: int, /) -> _LinuxDeviceStat: ...
    def major(self, device: int, /) -> int: ...
    def minor(self, device: int, /) -> int: ...
    def pread(self, fd: int, count: int, offset: int, /) -> bytes: ...
    def pwrite(self, fd: int, data: bytes, offset: int, /) -> int: ...


class _RecordLocks(Protocol):
    LOCK_EX: int
    LOCK_NB: int
    LOCK_UN: int

    def lockf(self, fd: int, command: int, length: int, start: int, whence: int, /) -> None: ...


def _record_locks() -> _RecordLocks:
    _linux()
    import fcntl
    return cast(_RecordLocks, fcntl)


def _linux() -> _LinuxOs:
    if sys.platform != 'linux':
        raise NativeWorkerRefused('linux_required')
    return cast(_LinuxOs, os)


def _context(value: object) -> dict[str, str]:
    if (type(value) is not dict or set(value) != _FIELDS
            or any(type(item) is not str for item in value.values())):
        raise NativeWorkerRefused('context')
    if (re.fullmatch('[0-9a-f]{32}', value['attempt_id']) is None
            or re.fullmatch('[0-9a-f]{64}', value['seed_sha256']) is None
            or value['case_id'] not in (*_PATHS, _POOL_CASE) or value['mode'] not in ('control', 'confined')
            or (value['case_id'] == _POOL_CASE and value['mode'] != 'confined')):
        raise NativeWorkerRefused('context')
    try:
        vm = UUID(value['vm_id'])
        left = float(value['deadline']) - time.monotonic()
        if not vm.int or str(vm) != value['vm_id'] or not math.isfinite(left) or not 0 < left <= 5:
            raise ValueError
    except ValueError:
        raise NativeWorkerRefused('context') from None
    return dict(value)


def _remaining(context: dict[str, str]) -> float:
    left = float(context['deadline']) - time.monotonic()
    if not 0 < left <= 5:
        raise NativeWorkerUnknown('deadline_unknown')
    return left


def _read(path: str, limit: int) -> bytes:
    native = _linux()
    fd = os.open(path, os.O_RDONLY | native.O_NOFOLLOW | native.O_CLOEXEC | native.O_NONBLOCK)
    try:
        raw = bytearray()
        while True:
            chunk = os.read(fd, limit + 1 - len(raw))
            if not chunk:
                return bytes(raw)
            raw.extend(chunk)
            if len(raw) > limit:
                raise NativeWorkerRefused('input_bound')
    finally:
        os.close(fd)


def _status_and_label(context: dict[str, str]) -> None:
    fields: dict[str, str] = {}
    for line in _read('/proc/self/status', 131072).decode('ascii').splitlines():
        key, sep, value = line.partition(':')
        if not sep or key in fields:
            raise NativeWorkerRefused('capabilities')
        fields[key] = value.strip()
    if (fields.get('NoNewPrivs') != '1'
            or any(fields.get(key) != '0000000000000000' for key in _CAPS)):
        raise NativeWorkerRefused('capabilities')
    expected = PROFILE if context['mode'] == 'confined' else 'unconfined'
    if _read('/proc/self/attr/current', 256).decode('ascii').strip() != expected:
        raise NativeWorkerRefused('profile')


def _descriptors() -> None:
    native = _linux()
    # No kernel-log, fixture, directory or other privileged handle inheritance.
    active = set()
    for name in os.listdir('/proc/self/fd'):
        if not name.isdecimal():
            raise NativeWorkerRefused('descriptors')
        try:
            os.readlink('/proc/self/fd/' + name)
        except FileNotFoundError:
            continue  # listdir's own transient descriptor may already be closed
        active.add(int(name))
    if active != {0, 1, 2, REPORT_FD, GATE_FD}:
        raise NativeWorkerRefused('descriptors')
    for fd in (0, 1, 2):
        device = native.fstat(fd)
        if (not stat.S_ISCHR(device.st_mode) or native.major(device.st_rdev) != 1
                or native.minor(device.st_rdev) != 3):
            raise NativeWorkerRefused('stdio')
    pipes = []
    for fd, access in ((REPORT_FD, os.O_WRONLY), (GATE_FD, os.O_RDONLY)):
        info = os.fstat(fd)
        if (not stat.S_ISFIFO(info.st_mode) or info.st_uid or info.st_gid
                or os.get_inheritable(fd) or os.get_blocking(fd)):
            raise NativeWorkerRefused('pipes')
        fields = {}
        for line in _read('/proc/self/fdinfo/' + str(fd), 4096).decode('ascii').splitlines():
            key, sep, value = line.partition(':')
            if not sep or key in fields:
                raise NativeWorkerRefused('pipes')
            fields[key] = value.strip()
        flags = fields.get('flags', '')
        if re.fullmatch('[0-7]{1,12}', flags) is None or int(flags, 8) & native.O_ACCMODE != access:
            raise NativeWorkerRefused('pipes')
        pipes.append((info.st_dev, info.st_ino))
    if pipes[0] == pipes[1]:
        raise NativeWorkerRefused('pipes')


def _control_fixture(context: dict[str, str]) -> None:
    # Never read the denied target in confined mode: that read would itself be
    # denied and contaminate attribution. The supervisor must pin it pre/post.
    path = _PATHS[context['case_id']]
    info = os.lstat(path)
    executable = context['case_id'] == 'outside_exec'
    if (not stat.S_ISREG(info.st_mode) or info.st_uid or info.st_gid or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) != (0o700 if executable else 0o600)
            or info.st_size != (188 if executable else 1)):
        raise NativeWorkerRefused('fixture')
    raw = _read(path, 188 if executable else 1)
    if (hashlib.sha256(raw).hexdigest() != FIXTURE_SHA256 if executable else raw != b'V'):
        raise NativeWorkerRefused('fixture')


def _preflight(context: dict[str, str]) -> None:
    if (sys.platform != 'linux' or platform.machine() != 'x86_64'
            or platform.release() != '6.8.0-139-generic' or sys.version_info[:2] != (3, 12)
            or not sys.flags.isolated or not sys.flags.no_site or not sys.dont_write_bytecode):
        raise NativeWorkerRefused('runtime')
    if (os.getuid() or os.geteuid() or os.getgid() or os.getegid() or os.getgroups()
            or dict(os.environ) != {'LANG': 'C', 'LC_ALL': 'C'}):
        raise NativeWorkerRefused('identity_environment')
    _status_and_label(context)
    _remaining(context)
    raw = _read(SEED, 512 * 1024)
    if not raw or hashlib.sha256(raw).hexdigest() != context['seed_sha256']:
        raise NativeWorkerRefused('seed_digest')
    if any(name == 'night_shifts' or name.startswith('night_shifts.') for name in sys.modules):
        raise NativeWorkerRefused('import_collision')
    sys.path.insert(0, SEED)
    probe = importlib.import_module('night_shifts.guest.bootstrap_public_probe')
    # Reuse only the existing read-only checkers, never the fresh-publication
    # preflight (its empty-directory requirement must remain unchanged).
    probe.check_mounts(_read('/proc/self/mountinfo', 131072).decode('ascii'))
    blocks = tuple(sorted(os.listdir('/sys/block')))
    probe.check_devices(blocks, tuple(sorted(os.listdir('/sys/class/net'))),
                        _read('/proc/swaps', 4096).decode('ascii'))
    for name in blocks:
        _remaining(context)
        base = '/sys/class/block/' + name
        if name.startswith('loop'):
            try:
                backing = _read(base + '/loop/backing_file', 4096)
            except FileNotFoundError:
                continue
            if not backing.strip():
                raise NativeWorkerRefused('loop_backing')
        if _read(base + '/ro', 16).strip() != b'1':
            raise NativeWorkerRefused('writable_block')
    for name in ('mnt', 'net'):
        if os.readlink('/proc/self/ns/' + name) == os.readlink('/proc/1/ns/' + name):
            raise NativeWorkerRefused('namespace')
    if int(_read('/sys/class/net/lo/flags', 32).strip(), 16) & 1:
        raise NativeWorkerRefused('network')
    if str(UUID(_read('/sys/class/dmi/id/product_uuid', 128).decode('ascii').strip().lower())) != context['vm_id']:
        raise NativeWorkerRefused('guest_vm')
    for path in ('/run/night-shift-bootstrap', '/var/lib/hyperv'):
        info = os.lstat(path)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid or info.st_gid or info.st_mode & 0o022:
            raise NativeWorkerRefused('ram_directory')
    names = os.listdir('/proc')
    if len(names) > 8192:
        raise NativeWorkerRefused('process_bound')
    for name in names:
        _remaining(context)
        if name.isdecimal():
            try:
                if _read('/proc/' + name + '/comm', 256).strip() == b'hv_kvp_daemon':
                    raise NativeWorkerRefused('existing_daemon')
            except FileNotFoundError:
                pass
    _descriptors()
    if context['mode'] == 'control':
        _control_fixture(context)
    _remaining(context)


def _message(context: dict[str, str], phase: str, observation: dict[str, object]) -> None:
    _remaining(context)
    raw = (json.dumps({'phase': phase, 'case_id': context['case_id'], 'mode': context['mode'],
                       'pid': os.getpid(), **observation}, sort_keys=True, separators=(',', ':')) + '\n').encode('ascii')
    if len(raw) > 256 or os.write(REPORT_FD, raw) != len(raw):
        raise NativeWorkerUnknown('report_unknown')


def _gate(context: dict[str, str]) -> None:
    ready, _, _ = select.select([GATE_FD], [], [], _remaining(context))
    if ready != [GATE_FD] or os.read(GATE_FD, 2) != b'G':
        raise NativeWorkerRefused('gate')
    _remaining(context)


def _pool_identity(info: os.stat_result) -> tuple[int, ...]:
    if (not stat.S_ISREG(info.st_mode) or info.st_uid or info.st_gid or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size != 1):
        raise NativeWorkerRefused('allowed_pool_identity')
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid, info.st_nlink, info.st_size)


def _pool_operation(context: dict[str, str]) -> dict[str, object]:
    """Fixed confined five-file positive control; no caller paths, create or retry.

    Whole-file POSIX record locks (not flock), held together across all five
    read/write/read-back checks. This does not test interprocess contention or
    actual daemon compatibility. Closing one exact fd lifetime releases its lock.
    """
    if context['case_id'] != _POOL_CASE or context['mode'] != 'confined':
        raise NativeWorkerRefused('context')
    native, locks = _linux(), _record_locks()
    held: list[tuple[int, str, tuple[int, ...]]] = []
    locked: set[int] = set()
    unknown = False
    try:
        for path in _POOL_PATHS:
            _remaining(context)
            before = _pool_identity(os.lstat(path))
            fd = os.open(path, os.O_RDWR | native.O_NOFOLLOW | native.O_CLOEXEC | native.O_NONBLOCK)
            held.append((fd, path, before))  # Own immediately, before fallible checks.
            if (fd < 5 or os.get_inheritable(fd) or os.get_blocking(fd)
                    or _pool_identity(os.fstat(fd)) != before
                    or any(pin[:2] == before[:2] for _, _, pin in held[:-1])):
                raise NativeWorkerRefused('allowed_pool_identity')
            locks.lockf(fd, locks.LOCK_EX | locks.LOCK_NB, 0, 0, os.SEEK_SET)
            locked.add(fd)
        for fd, path, identity in held:
            _remaining(context)
            if (_pool_identity(os.lstat(path)) != identity or _pool_identity(os.fstat(fd)) != identity
                    or native.pread(fd, 2, 0) != b'V'):
                raise NativeWorkerRefused('allowed_pool_bytes')
            if native.pwrite(fd, b'V', 0) != 1:
                raise NativeWorkerUnknown('allowed_pool_write_unknown')
            _remaining(context)
            if (native.pread(fd, 2, 0) != b'V' or _pool_identity(os.fstat(fd)) != identity
                    or _pool_identity(os.lstat(path)) != identity):
                raise NativeWorkerUnknown('allowed_pool_write_unknown')
        _remaining(context)
    except BaseException:
        unknown = True
    finally:
        # Even after partial lock/write, attempt every exact-owned close once.
        # Never retry a possibly consumed fd or claim rollback of the V write.
        while held:
            fd, _, _ = held.pop()
            if fd in locked:
                try:
                    locks.lockf(fd, locks.LOCK_UN, 0, 0, os.SEEK_SET)
                except BaseException:
                    unknown = True
            try:
                os.close(fd)
            except BaseException:
                unknown = True
    if unknown:
        raise NativeWorkerUnknown('allowed_pools_unknown') from None
    _remaining(context)
    return {'observation': 'pools_checked', 'errno': 0}


def _operation(context: dict[str, str]) -> dict[str, object]:
    native = _linux()
    if context['case_id'] == _POOL_CASE:
        return _pool_operation(context)
    path = _PATHS[context['case_id']]
    try:
        if context['case_id'] == 'outside_exec':
            # Replace THIS exact worker: no grandchild/Popen or shell, and the
            # two CLOEXEC pipes close on success. Parent must observe exit(37).
            os.execve(path, [path], {})
            raise NativeWorkerUnknown('exec_returned_unknown')
        fd = os.open(path, os.O_WRONLY | native.O_NOFOLLOW | native.O_CLOEXEC | native.O_NONBLOCK)
    except OSError as error:
        if type(error.errno) is not int or not 1 <= error.errno <= 4095:
            raise NativeWorkerUnknown('errno_unknown') from None
        return {'observation': 'syscall_error', 'errno': error.errno}
    try:
        if context['mode'] == 'confined':
            return {'observation': 'unexpected_open', 'errno': 0}
        if os.write(fd, b'V') != 1:
            raise NativeWorkerUnknown('control_write_unknown')
        return {'observation': 'control_written', 'errno': 0}
    finally:
        os.close(fd)


def run_fixed_case(value: object) -> int:
    """Future trusted guest entry only; caller cannot supply paths or commands.

    FD 3: nonblocking CLOEXEC result pipe; FD 4: separate nonblocking CLOEXEC
    one-byte start gate; stdio: /dev/null. Parent ownership, full fixture pins,
    paired controls, audit collection and exact-child lifetime are NOT supplied
    here. No observation returned/reported is overall success or a host receipt.
    """
    context = _context(value)
    try:
        _preflight(context)
        try:
            _message(context, 'ready', {})
            _gate(context)
            _status_and_label(context)
            _remaining(context)
            observation = _operation(context)
            _message(context, 'result', observation)
            return 0
        finally:
            try:
                os.close(GATE_FD)
            finally:
                os.close(REPORT_FD)
    except NativeWorkerRefused:
        raise
    except Exception:
        raise NativeWorkerUnknown('worker_unknown') from None
