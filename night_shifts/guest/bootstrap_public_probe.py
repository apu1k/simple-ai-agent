"""Fixed opt-in Linux RAM-only public probe. No CLI, mounts or service setup.

NOT deployed or approved for execution. A future reviewed launcher must establish
and pin the namespaces, mounts, enforced AppArmor policy and code BEFORE import.
Native observations are refusal checks, not proof of that launcher's provenance.
The daemon's host-mutation/IP code is not made read-only by this supervisor.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path, PurePath, PurePosixPath
from typing import Protocol, cast
from uuid import UUID

from night_shifts.bootstrap_probe_seed import (
    ProbeSeedRefused, synthetic_public_value, validate_public_probe_seed,
)
from night_shifts.guest.publish_public_bootstrap import publish_public_bootstrap
from night_shifts.maintenance_tls_prototype import AttemptBinding
from night_shifts.public_bootstrap_kvp import BootstrapKvpRefused, Budget

# Lexical Linux paths stay POSIX even in offline Windows model tests.
RUNTIME = PurePosixPath('/run/night-shift-bootstrap')
POOL = PurePosixPath('/var/lib/hyperv')
DAEMON = RUNTIME / 'hv_kvp_daemon'
PROFILE = 'night-shift-kvp-public-probe (enforce)'
POOLS = {'.kvp_pool_' + str(i) for i in range(5)}
_WRITABLE = {
    '/run/night-shift-bootstrap': 'tmpfs', '/var/lib/hyperv': 'tmpfs',
    '/dev': 'devtmpfs', '/dev/pts': 'devpts', '/dev/shm': 'tmpfs',
}


class GuestProbeRefused(RuntimeError):
    """Fixed labels only, never daemon stdout, native exceptions or seed text."""


class _LinuxOs(Protocol):
    """Linux stdlib ABI only; no production backend/fallback injection."""

    O_CLOEXEC: int
    O_NOFOLLOW: int
    O_NONBLOCK: int

    def killpg(self, pgid: int, sig: int, /) -> None: ...


class _LinuxSignals(Protocol):
    SIGTERM: int
    SIGKILL: int


def _linux() -> _LinuxOs:
    if sys.platform != 'linux':
        raise GuestProbeRefused('linux_required')
    return cast(_LinuxOs, os)


def check_mounts(raw: str) -> None:
    """Require a readonly view except the fixed RAM/device pseudo-filesystems.

    No overlay-backing inference or mount/permission repair. A stricter-than-live
    default requires the future launcher to provide a private readonly view.
    Duplicate mountpoints/overmounts and escaped paths refuse this candidate.
    """
    if type(raw) is not str or not 0 < len(raw) <= 131072:
        raise GuestProbeRefused('mounts')
    mounts: dict[str, tuple[str, set[str]]] = {}
    for line in raw.splitlines():
        fields = line.split(' ')
        try:
            split = fields.index('-')
            if (len(fields) != split + 4 or split < 6 or not fields[0].isdigit()
                    or not fields[1].isdigit() or not re.fullmatch(r'[0-9]+:[0-9]+', fields[2])
                    or any('\\' in word for word in fields) or not fields[4].startswith('/')):
                raise ValueError
            path, options, fs = fields[4], set(fields[5].split(',')), fields[split + 1]
            if path in mounts or ('rw' in options) == ('ro' in options):
                raise ValueError
            mounts[path] = fs, options
        except (ValueError, IndexError):
            raise GuestProbeRefused('mounts') from None
        if 'rw' in options and _WRITABLE.get(path) != fs:
            raise GuestProbeRefused('persistent_write_view')
    if '/' not in mounts or 'ro' not in mounts['/'][1]:
        raise GuestProbeRefused('root_view')
    for path in (str(RUNTIME), str(POOL)):
        if path not in mounts or mounts[path][0] != 'tmpfs':
            raise GuestProbeRefused('ram_mounts')
        required = {'rw', 'nodev', 'nosuid'} | ({'noexec'} if path == str(POOL) else set())
        if not required <= mounts[path][1] or (path == str(RUNTIME) and 'noexec' in mounts[path][1]):
            raise GuestProbeRefused('ram_mounts')
    # No nested mount can redirect a fixed writable directory or its children.
    if any(p.startswith(str(RUNTIME) + '/') or p.startswith(str(POOL) + '/') for p in mounts):
        raise GuestProbeRefused('ram_mounts')


def check_status(raw: str) -> None:
    values: dict[str, str] = {}
    for line in raw.splitlines():
        key, sep, value = line.partition(':')
        if not sep or key in values:
            raise GuestProbeRefused('confinement')
        values[key] = value.strip()
    if (values.get('NoNewPrivs') != '1'
            or any(values.get(k) != '0000000000000000'
                   for k in ('CapInh', 'CapPrm', 'CapEff', 'CapBnd', 'CapAmb'))):
        raise GuestProbeRefused('confinement')


def check_devices(blocks: tuple[str, ...], interfaces: tuple[str, ...], swaps: str) -> None:
    if (type(blocks) is not tuple or not blocks
            or len(blocks) > 64 or any(type(n) is not str or not re.fullmatch(r'(loop|sr)[0-9]+', n)
                                     for n in blocks)):
        raise GuestProbeRefused('target_disk')
    if interfaces != ('lo',):
        raise GuestProbeRefused('network')
    lines = swaps.splitlines()
    if len(lines) != 1 or lines[0].split() != ['Filename', 'Type', 'Size', 'Used', 'Priority']:
        raise GuestProbeRefused('swap')


def _read(path: PurePath, limit: int = 131072) -> bytes:
    native = _linux()
    fd = os.open(path, os.O_RDONLY | native.O_CLOEXEC | native.O_NOFOLLOW | native.O_NONBLOCK)
    try:
        raw = os.read(fd, limit + 1)
        if len(raw) > limit:
            raise GuestProbeRefused('input_bound')
        return raw
    finally:
        os.close(fd)


def _directory(path: PurePath) -> None:
    _linux()
    info = Path(path).lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_gid != 0
            or info.st_mode & 0o022):
        raise GuestProbeRefused('ram_security')


def preflight(binding: AttemptBinding) -> None:
    """Read only. Refuse rather than establish/repair a missing prerequisite."""
    if (sys.platform != 'linux' or platform.machine() != 'x86_64'
            or platform.release() != '6.8.0-139-generic'):
        raise GuestProbeRefused('runtime')
    if (os.getuid() != 0 or os.geteuid() != 0 or os.getgid() != 0 or os.getegid() != 0
            or not sys.flags.isolated or not sys.dont_write_bytecode):
        raise GuestProbeRefused('execution_context')
    check_status(_read(Path('/proc/self/status')).decode('ascii'))
    if _read(Path('/proc/self/attr/current')).decode('ascii').strip() != PROFILE:
        raise GuestProbeRefused('apparmor')
    for namespace in ('mnt', 'net'):
        if os.readlink('/proc/self/ns/' + namespace) == os.readlink('/proc/1/ns/' + namespace):
            raise GuestProbeRefused('namespace')
    check_mounts(_read(Path('/proc/self/mountinfo')).decode('ascii'))
    check_devices(tuple(sorted(os.listdir('/sys/block'))), tuple(sorted(os.listdir('/sys/class/net'))),
                  _read(Path('/proc/swaps')).decode('ascii'))
    # Also refuse an active loopback; the launcher supplies a fresh private netns.
    if int(_read(Path('/sys/class/net/lo/flags'), 32).strip(), 16) & 1:
        raise GuestProbeRefused('network')
    observed = _read(Path('/sys/class/dmi/id/product_uuid'), 128).decode('ascii').strip().lower()
    if str(UUID(observed)) != binding.vm_id:
        raise GuestProbeRefused('guest_vm')
    for path in (RUNTIME, POOL):
        _directory(path)
    if set(os.listdir(RUNTIME)) != {'support.zip'} or os.listdir(POOL):
        raise GuestProbeRefused('fresh_ram')
    device = Path('/dev/vmbus/hv_kvp').lstat()
    if (not stat.S_ISCHR(device.st_mode) or device.st_uid != 0 or device.st_gid != 0
            or device.st_mode & 0o002):
        raise GuestProbeRefused('kvp_device')
    # No existing daemon may share the fixed pools/device, including outside our
    # mount view. PID namespace isolation is NOT used; /proc must be complete.
    for name in os.listdir('/proc'):
        if name.isdecimal():
            try:
                if _read(Path('/proc') / name / 'comm', 256).strip() == b'hv_kvp_daemon':
                    raise GuestProbeRefused('existing_daemon')
            except FileNotFoundError:
                pass  # unrelated process exited during observation


def _write_daemon(raw: bytes) -> None:
    native = _linux()
    fd = os.open(DAEMON, os.O_WRONLY | os.O_CREAT | os.O_EXCL | native.O_NOFOLLOW | native.O_CLOEXEC, 0o500)
    try:
        if os.write(fd, raw) != len(raw):
            raise GuestProbeRefused('daemon_write_unknown')
    finally:
        os.close(fd)
    if _read(DAEMON, 65536) != raw:
        raise GuestProbeRefused('daemon_write_unknown')


def _ready() -> bool:
    _linux()
    names = set(os.listdir(POOL))
    if not names <= POOLS:
        raise GuestProbeRefused('pool_shape')
    for name in names:
        info = Path(POOL / name).lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != 0
                or info.st_gid != 0 or info.st_mode & 0o022 or info.st_size != 0):
            raise GuestProbeRefused('pool_shape')
    return names == POOLS


def _stop(child: subprocess.Popen[bytes]) -> bool:
    # Only this new exact child/session. No name lookup or broad process cleanup.
    native = _linux()
    signals = cast(_LinuxSignals, signal)
    if child.poll() is not None:
        return True
    try:
        native.killpg(child.pid, signals.SIGTERM)
        child.wait(timeout=1)
        return True
    except ProcessLookupError:
        return child.poll() is not None
    except subprocess.TimeoutExpired:
        try:
            native.killpg(child.pid, signals.SIGKILL)
            child.wait(timeout=1)
            return True
        except (ProcessLookupError, subprocess.TimeoutExpired):
            return child.poll() is not None


def run_guest_probe(raw: bytes, binding: AttemptBinding, *, expected_sha256: str) -> bytes:
    """One explicit foreground attempt after independent launch authorization.

    Reuses the existing locked publisher exactly once; keeps daemon alive for
    15 seconds for host read-back, then stops only that child. No retry, rollback,
    file deletion, poweroff or host-VM operation. Success means LOCAL publication
    and direct-child exit only, NOT host receipt, process-tree absence or VM cleanup.
    Native filesystem/process calls still require an external protected watchdog.
    """
    entries = validate_public_probe_seed(raw, binding, expected_sha256=expected_sha256)
    child: subprocess.Popen[bytes] | None = None
    started = time.monotonic()
    failure: str | None = None
    stopped: bool | None = None  # None is NOT a confirmed child exit.
    spawn_attempted = False
    publication = 'not_attempted'
    budget = Budget(25, lambda: False)
    try:
        preflight(binding)
        if _read(RUNTIME / 'support.zip', len(raw)) != raw:
            raise GuestProbeRefused('seed_path')
        budget.check()
        _write_daemon(entries['hv_kvp_daemon'])
        spawn_attempted = True
        child = subprocess.Popen(
            [str(DAEMON), '-n'], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, cwd=RUNTIME, env={'PATH': '', 'LANG': 'C', 'LC_ALL': 'C'},
            close_fds=True, start_new_session=True,
        )
        ready_until = time.monotonic() + 5
        while not _ready():
            budget.check()
            if child.poll() is not None or time.monotonic() >= ready_until:
                raise GuestProbeRefused('daemon_not_ready')
            time.sleep(0.02)
        if child.poll() is not None:
            raise GuestProbeRefused('daemon_exited')
        budget.check()
        publication = 'unknown'  # never turn a possibly mutated pool into no-write
        publish_public_bootstrap(synthetic_public_value(binding), timeout_seconds=min(3, budget.check()))
        publication = 'local_readback'
        until = time.monotonic() + 15
        while time.monotonic() < until:
            budget.check()
            if child.poll() is not None:
                raise GuestProbeRefused('daemon_exited')
            time.sleep(0.02)
    except (GuestProbeRefused, BootstrapKvpRefused, ProbeSeedRefused) as error:
        failure = str(error)
    except (OSError, ValueError, UnicodeError):
        failure = 'native_refused'
    finally:
        if child is not None:
            try:
                stopped = _stop(child)
            except OSError:
                stopped = False
    unconfirmed = spawn_attempted and stopped is not True
    unknown_reason = 'spawn_unknown' if child is None else 'daemon_stop_unknown'
    result = {
        'version': 1, 'purpose': 'public-plumbing-only', 'attempt_id': binding.attempt_id,
        'vm_id': binding.vm_id, 'seed_sha256': expected_sha256,
        'public_sha256': hashlib.sha256(entries['public.json']).hexdigest(),
        'outcome': 'unknown' if unconfirmed else ('refused' if failure else 'local_published'),
        'reason': unknown_reason if unconfirmed else failure,
        'publication': publication, 'spawn_attempted': spawn_attempted,
        'direct_child_started': child is not None, 'direct_child_stopped': stopped,
        'host_observed': False, 'vm_cleanup_confirmed': False,
        'elapsed_ms': max(0, int((time.monotonic() - started) * 1000)),
    }
    report = (json.dumps(result, sort_keys=True, separators=(',', ':')) + '\n').encode('ascii')
    if len(report) > 3000:
        raise GuestProbeRefused('report_bound')
    return report
