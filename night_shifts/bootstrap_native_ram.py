"""Fixed native-validator RAM fixture acquisition; unwired, guest-only candidate.

Creates only the eight reviewed fixtures in an already-established isolated RAM
layout. Never creates mounts/directories, changes permissions, executes the ELF,
loads policy, deletes artifacts or activates a boot entry. Caller/guest identity
checks cannot authenticate the host or authorize execution. Keep all descriptors
out of children; independently bounded trusted launch/cleanup is still required.
"""
from __future__ import annotations

import hashlib
import math
import os
import platform
import re
import stat
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, cast
from uuid import UUID

from night_shifts.bootstrap_native_fixture import inert_fixture_bytes
from night_shifts.guest.bootstrap_public_probe import check_devices, check_mounts
from night_shifts.maintenance_tls_prototype import AttemptBinding

_RUNTIME = '/run/night-shift-bootstrap'
_POOL = '/var/lib/hyperv'
_MAX_SEED = 512 * 1024
# No caller-selected path, bytes, mode, command or executable interface.
_FILES = (
    (_RUNTIME, 'denied-write', 0o600, b'V'),
    (_RUNTIME, 'denied-exec', 0o700, inert_fixture_bytes()),
    (_POOL, '.kvp_pool_denied', 0o600, b'V'),
    *((_POOL, '.kvp_pool_' + str(i), 0o600, b'V') for i in range(5)),
)


class NativeRamRefused(RuntimeError):
    """Fixed label only, without paths, bytes or native exception text."""


class NativeRamUnknown(NativeRamRefused):
    """No retry, rollback, artifact absence or cleanup claim is implied."""


class _LinuxOs(Protocol):
    """Native Linux stdlib ABI, not a selectable backend or Windows fallback."""

    O_CLOEXEC: int
    O_NOFOLLOW: int
    O_NONBLOCK: int
    O_DIRECTORY: int

    def getuid(self) -> int: ...
    def geteuid(self) -> int: ...
    def getgid(self) -> int: ...
    def getegid(self) -> int: ...
    def getgroups(self) -> list[int]: ...
    def major(self, device: int, /) -> int: ...
    def minor(self, device: int, /) -> int: ...
    def pread(self, fd: int, count: int, offset: int, /) -> bytes: ...
    def pwrite(self, fd: int, data: bytes, offset: int, /) -> int: ...


def _linux() -> _LinuxOs:
    if sys.platform != 'linux':
        raise NativeRamRefused('linux_required')
    return cast(_LinuxOs, os)


class _Budget:
    def __init__(self, deadline: float, cancelled: Callable[[], bool]) -> None:
        if (type(deadline) not in (int, float) or not 0 <= deadline <= 1e15
                or not math.isfinite(deadline) or not callable(cancelled)):
            raise NativeRamRefused('context')
        self.deadline, self.cancelled = deadline, cancelled
        self.last = 0.0
        self.check()
        if not 0 < deadline - self.last <= 5:
            raise NativeRamRefused('context')

    def check(self) -> None:
        try:
            stopped, now = self.cancelled(), time.monotonic()
        except Exception:
            raise NativeRamUnknown('budget_unknown') from None
        if (type(stopped) is not bool or type(now) not in (int, float)
                or not 0 <= now <= 1e15 or not math.isfinite(now) or now < self.last):
            raise NativeRamUnknown('budget_unknown')
        self.last = float(now)
        if stopped or now >= self.deadline:
            raise NativeRamUnknown('budget_unknown')


def _read_system(path: str, limit: int, budget: _Budget) -> bytes:
    native = _linux()
    budget.check()
    fd = os.open(path, os.O_RDONLY | native.O_CLOEXEC | native.O_NOFOLLOW | native.O_NONBLOCK)
    try:
        raw = bytearray()
        while True:
            budget.check()
            chunk = os.read(fd, limit + 1 - len(raw))
            if not chunk:
                return bytes(raw)
            raw.extend(chunk)
            if len(raw) > limit:
                raise NativeRamRefused('input_bound')
    finally:
        # POSIX close can have consumed the fd even when it reports an error.
        # Never retry the same integer, including from an outer cleanup path.
        try:
            os.close(fd)
        except OSError:
            raise NativeRamUnknown('descriptor_cleanup_unknown') from None


def _layout(binding: AttemptBinding, budget: _Budget) -> bytes:
    native = _linux()
    budget.check()
    if (platform.machine() != 'x86_64' or platform.release() != '6.8.0-139-generic'
            or sys.version_info[:2] != (3, 12) or not sys.flags.isolated
            or not sys.flags.no_site or not sys.dont_write_bytecode):
        raise NativeRamRefused('runtime')
    if (native.getuid() or native.geteuid() or native.getgid() or native.getegid()
            or native.getgroups() or dict(os.environ) != {'LANG': 'C', 'LC_ALL': 'C'}):
        raise NativeRamRefused('identity_environment')
    if _read_system('/proc/self/attr/current', 256, budget).strip() != b'unconfined':
        raise NativeRamRefused('supervisor_label')
    for name in ('mnt', 'net'):
        if os.readlink('/proc/self/ns/' + name) == os.readlink('/proc/1/ns/' + name):
            raise NativeRamRefused('namespace')
    observed = _read_system('/sys/class/dmi/id/product_uuid', 128, budget).decode('ascii').strip().lower()
    if str(UUID(observed)) != binding.vm_id:
        raise NativeRamRefused('guest_vm')
    raw = _read_system('/proc/self/mountinfo', 131072, budget)
    check_mounts(raw.decode('ascii'))
    blocks = tuple(sorted(os.listdir('/sys/block')))
    check_devices(blocks, tuple(sorted(os.listdir('/sys/class/net'))),
                  _read_system('/proc/swaps', 4096, budget).decode('ascii'))
    for name in blocks:
        budget.check()
        base = '/sys/class/block/' + name
        if name.startswith('loop'):
            try:
                backing = _read_system(base + '/loop/backing_file', 4096, budget)
            except FileNotFoundError:
                continue  # Only an unconfigured loop is exempt from its ro bit.
            if not backing.strip():
                raise NativeRamRefused('loop_backing')
        if _read_system(base + '/ro', 16, budget).strip() != b'1':
            raise NativeRamRefused('writable_block')
    if int(_read_system('/sys/class/net/lo/flags', 32, budget).strip(), 16) & 1:
        raise NativeRamRefused('network')
    names = os.listdir('/proc')
    if len(names) > 8192:
        raise NativeRamRefused('process_bound')
    for name in names:
        budget.check()
        if name.isdecimal():
            try:
                if _read_system('/proc/' + name + '/comm', 256, budget).strip() == b'hv_kvp_daemon':
                    raise NativeRamRefused('existing_daemon')
            except FileNotFoundError:
                pass
    budget.check()
    return raw


def _directory(info: os.stat_result) -> tuple[int, ...]:
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid or info.st_gid or info.st_mode & 0o022):
        raise NativeRamRefused('directory_security')
    return info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid


def _file(info: os.stat_result, mode: int, size: int) -> tuple[int, ...]:
    if (not stat.S_ISREG(info.st_mode) or info.st_uid or info.st_gid or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) != mode or info.st_size != size):
        raise NativeRamRefused('file_security')
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_nlink, info.st_size)


@dataclass(frozen=True)
class _Directory:
    parent: int | None
    name: str
    fd: int
    identity: tuple[int, ...]


@dataclass(frozen=True)
class _File:
    parent: int
    name: str
    fd: int
    mode: int
    raw: bytes
    identity: tuple[int, ...]
    mount_path: str


class NativeRamFixtures:
    """Retain all directory/file pins until explicitly closed by the supervisor.

    Construction and verify perform native I/O in the fixed guest layout. No
    trusted observation/receipt is returned. Holding these fds does not prevent
    hostile root changes or replace before/after checks and exact-child ownership.
    The future child launcher MUST close them all before evaluating worker code.
    """

    def __init__(
        self, binding: AttemptBinding, *, seed_sha256: str, deadline: float,
        cancelled: Callable[[], bool] = lambda: False,
    ) -> None:
        self._fds: list[int] = []
        self._directories: list[_Directory] = []
        self._files: list[_File] = []
        self._parents: dict[str, int] = {}
        self._failed = self._closed = self._close_unknown = False
        if (type(binding) is not AttemptBinding or type(seed_sha256) is not str
                or re.fullmatch('[0-9a-f]{64}', seed_sha256) is None):
            raise NativeRamRefused('context')
        self._binding = binding
        budget = _Budget(deadline, cancelled)
        try:
            self._mountinfo = _layout(binding, budget)
            self._acquire_directories(budget)
            self._names(fresh=True)
            parent = self._parents[_RUNTIME]
            seed = self._open_file(parent, 'support.zip', create=False, mode=0o400)
            info = os.fstat(seed)
            if not 0 < info.st_size <= _MAX_SEED:
                raise NativeRamRefused('seed_bound')
            _file(info, 0o400, info.st_size)
            raw = _linux().pread(seed, info.st_size + 1, 0)
            if len(raw) != info.st_size or hashlib.sha256(raw).hexdigest() != seed_sha256:
                raise NativeRamRefused('seed_digest')
            self._files.append(_File(parent, 'support.zip', seed, 0o400, raw,
                                     _file(info, 0o400, len(raw)), _RUNTIME))
            self._verify(budget, fresh=True)
            for path, name, mode, data in _FILES:
                budget.check()
                # No truncate/reuse, chmod/chown, fallback write or retry.
                fd = self._open_file(self._parents[path], name, create=True, mode=mode)
                _file(os.fstat(fd), mode, 0)
                self._mount(fd, path, budget)
                if _linux().pwrite(fd, data, 0) != len(data):
                    raise NativeRamUnknown('fixture_write_unknown')
                self._files.append(_File(self._parents[path], name, fd, mode, data,
                                         _file(os.fstat(fd), mode, len(data)), path))
                self._check_file(self._files[-1], budget)
            self._verify(budget, fresh=False)
        except BaseException as error:
            self._failed = True
            self.close()  # Close only descriptors, retaining even partial RAM artifacts.
            if isinstance(error, NativeRamRefused):
                raise
            if isinstance(error, (KeyboardInterrupt, SystemExit)):
                raise
            raise NativeRamUnknown('fixture_io_unknown') from None

    def _own(self, fd: int) -> int:
        self._fds.append(fd)  # Track immediately, before any fallible metadata call.
        if os.get_inheritable(fd):
            raise NativeRamRefused('descriptor_security')
        return fd

    def _acquire_directories(self, budget: _Budget) -> None:
        native = _linux()
        flags = os.O_RDONLY | native.O_DIRECTORY | native.O_NOFOLLOW | native.O_CLOEXEC | native.O_NONBLOCK
        root = self._own(os.open('/', flags))
        self._directories.append(_Directory(None, '/', root, _directory(os.fstat(root))))
        for path in (_RUNTIME, _POOL):
            parent = root
            for name in path.strip('/').split('/'):
                budget.check()
                fd = self._own(os.open(name, flags, dir_fd=parent))
                self._directories.append(_Directory(parent, name, fd, _directory(os.fstat(fd))))
                parent = fd
            self._parents[path] = parent
            self._mount(parent, path, budget)

    def _open_file(self, parent: int, name: str, *, create: bool, mode: int) -> int:
        native = _linux()
        flags = (os.O_RDWR if create else os.O_RDONLY) | native.O_NOFOLLOW | native.O_CLOEXEC | native.O_NONBLOCK
        if create:
            flags |= os.O_CREAT | os.O_EXCL
        return self._own(os.open(name, flags, mode, dir_fd=parent))

    def _mount(self, fd: int, path: str, budget: _Budget) -> None:
        native = _linux()
        lines = [line.split(' ') for line in self._mountinfo.decode('ascii').splitlines()]
        entry = next(line for line in lines if line[4] == path)
        fields: dict[str, str] = {}
        for line in _read_system('/proc/self/fdinfo/' + str(fd), 4096, budget).decode('ascii').splitlines():
            key, separator, value = line.partition(':')
            if not separator or key in fields:
                raise NativeRamRefused('mount_identity')
            fields[key] = value.strip()
        info = os.fstat(fd)
        if (fields.get('mnt_id') != entry[0]
                or entry[2] != str(native.major(info.st_dev)) + ':' + str(native.minor(info.st_dev))):
            raise NativeRamRefused('mount_identity')

    def _names(self, *, fresh: bool) -> None:
        runtime = {'support.zip'} if fresh else {'support.zip', 'denied-write', 'denied-exec'}
        pool = set() if fresh else {name for path, name, _, _ in _FILES if path == _POOL}
        if (set(os.listdir(self._parents[_RUNTIME])) != runtime
                or set(os.listdir(self._parents[_POOL])) != pool):
            raise NativeRamRefused('ram_inventory')

    def _check_file(self, item: _File, budget: _Budget) -> None:
        budget.check()
        before = os.fstat(item.fd)
        if (_file(before, item.mode, len(item.raw)) != item.identity
                or _file(os.stat(item.name, dir_fd=item.parent, follow_symlinks=False),
                         item.mode, len(item.raw)) != item.identity):
            raise NativeRamRefused('file_identity')
        self._mount(item.fd, item.mount_path, budget)
        if _linux().pread(item.fd, len(item.raw) + 1, 0) != item.raw:
            raise NativeRamRefused('file_bytes')
        after = os.fstat(item.fd)
        if (_file(after, item.mode, len(item.raw)) != item.identity
                or (before.st_mtime_ns, before.st_ctime_ns) != (after.st_mtime_ns, after.st_ctime_ns)):
            raise NativeRamRefused('file_changed')
        budget.check()

    def _verify(self, budget: _Budget, *, fresh: bool) -> None:
        if _layout(self._binding, budget) != self._mountinfo:
            raise NativeRamRefused('mount_changed')
        for item in self._directories:
            budget.check()
            if (_directory(os.fstat(item.fd)) != item.identity
                    or _directory(os.stat(item.name, dir_fd=item.parent, follow_symlinks=False)) != item.identity):
                raise NativeRamRefused('directory_identity')
        self._names(fresh=fresh)
        for file_pin in self._files:
            self._check_file(file_pin, budget)
        self._names(fresh=fresh)
        budget.check()

    def verify(self, *, deadline: float, cancelled: Callable[[], bool] = lambda: False) -> None:
        """Check around EACH worker; a new bounded check is not a retry of a probe.

        Controls may rewrite V and change mtime/ctime between checks. Identity,
        bytes, metadata, mount and path resolution must still agree; times must
        remain stable during each individual read. This is not continuous attestation.
        """
        if self._closed or self._failed:
            raise NativeRamRefused('terminal')
        try:
            self._verify(_Budget(deadline, cancelled), fresh=False)
        except BaseException as error:
            self._failed = True
            if isinstance(error, NativeRamRefused):
                raise
            if isinstance(error, (KeyboardInterrupt, SystemExit)):
                raise
            raise NativeRamUnknown('fixture_io_unknown') from None

    def close(self) -> None:
        """Release held fds once; NEVER unlink fixtures or retry uncertain close.

        Successful descriptor closure is not file/child/tree/VM cleanup evidence.
        After an error, still attempt every other exact-owned fd once. A later
        close call preserves UNKNOWN rather than declaring cleanup successful.
        """
        self._closed = True
        while self._fds:
            fd = self._fds.pop()
            try:
                os.close(fd)
            except OSError:
                self._close_unknown = True
        if self._close_unknown:
            raise NativeRamUnknown('descriptor_cleanup_unknown') from None
