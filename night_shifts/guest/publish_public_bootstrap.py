"""Opt-in Linux public-only pool-1 publisher; NOT installed or called at import.

No key generation, CLI, daemon/service management, path arguments, pool creation,
replacement, truncation, cleanup or retries. Intended only for reviewed trusted
live recovery code BEFORE exposing a target filesystem. A caller must separately
establish the live ISO/runtime, daemon version/state and fresh attempt/VM binding.
"""
from __future__ import annotations

import errno
import os
import stat
import sys
import time
from collections.abc import Callable
from contextlib import ExitStack
from typing import Protocol, cast

from night_shifts.maintenance_credentials_prototype import PublicBootstrap
from night_shifts.public_bootstrap_kvp import (
    MAX_ITEMS, POOL_RECORD_BYTES, BootstrapKvpRefused, Budget,
    check_pool_for_append, pool_record,
)

_POOL = '.kvp_pool_1'
_PARTS = ('var', 'lib', 'hyperv')


class _PositionalIo(Protocol):
    """Linux-only stdlib ABI; not an injected production backend/fallback."""

    def pread(self, fd: int, count: int, offset: int, /) -> bytes: ...
    def pwrite(self, fd: int, data: bytes, offset: int, /) -> int: ...


class _RecordLocks(Protocol):
    LOCK_EX: int
    LOCK_NB: int
    LOCK_UN: int

    def lockf(self, fd: int, command: int, length: int, start: int, whence: int, /) -> None: ...


def _profile(info: os.stat_result, *, directory: bool) -> tuple[int, ...]:
    shape = stat.S_ISDIR if directory else stat.S_ISREG
    if (not shape(info.st_mode) or info.st_uid != 0 or info.st_gid != 0
            or info.st_mode & 0o022 or (not directory and info.st_nlink != 1)):
        raise BootstrapKvpRefused('pool_security')
    # Directory storage length/link count are NOT file-content invariants.
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid)


def _version(info: os.stat_result) -> tuple[int, ...]:
    # pread can legitimately update atime; never compare entire stat_result.
    return (*_profile(info, directory=False), info.st_nlink, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def _check_names(held: list[tuple[int, str, int, tuple[int, ...]]]) -> None:
    for parent, name, descriptor, baseline in held:
        if (_profile(os.fstat(descriptor), directory=True) != baseline
                or _profile(os.stat(name, dir_fd=parent, follow_symlinks=False),
                            directory=True) != baseline):
            raise BootstrapKvpRefused('pool_identity')


def _append_locked(fd: int, parent: int, record: bytes, budget: Budget) -> None:
    """One whole-file POSIX record lock; append once, never roll back on failure.

    Closing ANY other fd to this inode in the process releases POSIX locks.
    Trusted caller must serialize this operation and not open/close pool 1 in
    another thread. This is not a hostile-root or concurrent-writer transaction.
    """
    import fcntl

    locks = cast(_RecordLocks, fcntl)
    native = cast(_PositionalIo, os)
    if type(record) is not bytes or len(record) != POOL_RECORD_BYTES:
        raise BootstrapKvpRefused('public_record')
    baseline = _profile(os.fstat(fd), directory=False)
    locked = False
    mutated = False
    try:
        while True:
            remaining = budget.check()
            try:
                # F_SETLK on the whole file, matching daemon fcntl record locks;
                # flock is a different lock namespace on Linux and is NOT used.
                locks.lockf(fd, locks.LOCK_EX | locks.LOCK_NB, 0, 0, os.SEEK_SET)
                locked = True
                break
            except OSError as error:
                if error.errno not in (errno.EACCES, errno.EAGAIN, errno.EINTR):
                    raise BootstrapKvpRefused('pool_lock') from None
                time.sleep(min(0.02, remaining))
        budget.check()
        before = os.fstat(fd)
        if (_profile(before, directory=False) != baseline
                or _profile(os.stat(_POOL, dir_fd=parent, follow_symlinks=False),
                            directory=False) != baseline
                or not 0 <= before.st_size < MAX_ITEMS * POOL_RECORD_BYTES):
            raise BootstrapKvpRefused('pool_identity')
        raw = native.pread(fd, MAX_ITEMS * POOL_RECORD_BYTES + 1, 0)
        if len(raw) != before.st_size:
            raise BootstrapKvpRefused('pool_changed')
        check_pool_for_append(raw)
        budget.check()
        if _version(os.fstat(fd)) != _version(before):
            raise BootstrapKvpRefused('pool_changed')
        # Single bounded append. A short/error write is UNKNOWN, not retryable.
        mutated = True
        if native.pwrite(fd, record, len(raw)) != POOL_RECORD_BYTES:
            raise BootstrapKvpRefused('publication_unknown')
        budget.check()
        after = os.fstat(fd)
        expected = raw + record
        if (_profile(after, directory=False) != baseline
                or after.st_size != len(expected)
                or _profile(os.stat(_POOL, dir_fd=parent, follow_symlinks=False),
                            directory=False) != baseline
                or native.pread(fd, len(expected) + 1, 0) != expected):
            raise BootstrapKvpRefused('publication_unknown')
        budget.check()
    except BootstrapKvpRefused:
        # Cancellation/timeout after a possible write cannot imply no publication.
        if mutated:
            raise BootstrapKvpRefused('publication_unknown') from None
        raise
    except OSError:
        raise BootstrapKvpRefused('publication_unknown' if mutated else 'pool_io') from None
    finally:
        if locked:
            # A failed unlock also refuses the call; outer ExitStack closes fd.
            try:
                locks.lockf(fd, locks.LOCK_UN, 0, 0, os.SEEK_SET)
            except OSError:
                raise BootstrapKvpRefused('publication_unknown' if mutated else 'pool_lock') from None


def publish_public_bootstrap(
    value: PublicBootstrap, *, timeout_seconds: float = 3.0,
    cancelled: Callable[[], bool] = lambda: False,
) -> None:
    """Append the fixed public item to the EXISTING fixed guest pool, once.

    Success is local locked read-back only, not host observation/authentication.
    Public KVP can persist/cache. Private keys must never be put in this file.
    Blocking native file calls still require the future outer process watchdog.
    """
    if sys.platform != 'linux':
        raise BootstrapKvpRefused('linux_required')
    if os.geteuid() != 0 or os.getuid() != 0:
        raise BootstrapKvpRefused('root_required')
    budget = Budget(timeout_seconds, cancelled)
    record = pool_record(value)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        with ExitStack() as stack:
            root = os.open('/', flags)
            stack.callback(os.close, root)
            root_profile = _profile(os.fstat(root), directory=True)
            held: list[tuple[int, str, int, tuple[int, ...]]] = []
            parent = root
            for name in _PARTS:
                budget.check()
                child = os.open(name, flags, dir_fd=parent)
                stack.callback(os.close, child)
                held.append((parent, name, child, _profile(os.fstat(child), directory=True)))
                parent = child
            budget.check()
            _check_names(held)
            fd = os.open(_POOL, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                         dir_fd=parent)
            stack.callback(os.close, fd)
            _profile(os.fstat(fd), directory=False)
            _append_locked(fd, parent, record, budget)
            # Ancestor failure after publication is not evidence of a safe result.
            try:
                _check_names(held)
                if _profile(os.fstat(root), directory=True) != root_profile:
                    raise BootstrapKvpRefused('pool_identity')
                budget.check()
            except (OSError, BootstrapKvpRefused):
                raise BootstrapKvpRefused('publication_unknown') from None
    except OSError:
        raise BootstrapKvpRefused('pool_io') from None
