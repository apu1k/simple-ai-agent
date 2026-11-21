"""Standalone NoCloud entry for the reviewed offline Ubuntu recovery VM.

Only stdlib before checking the complete read-only ZIP against the pin embedded
in user-data. The host must independently hold and pin the live ISO and this
seed. Neither a guest exit nor a local publish proves host cleanup.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import platform
import re
import stat
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from uuid import UUID

ENTRY = '/run/night-shift-finalize-entry.py'
_STAGE = Path('/run/night-shift-finalize-stage')
_MEDIA = Path('/run/night-shift-finalize-media')
_POOL = Path('/var/lib/hyperv')
_ENV = {'LANG': 'C', 'LC_ALL': 'C'}
_OPTICAL = Path('/dev/disk/by-label/CIDATA')
_O_NAMES = {f'.kvp_pool_{i}' for i in range(5)}
MAX_ARCHIVE = 512 * 1024
_MAX_FILE = 128 * 1024
_GUEST_SECONDS = 180
_ZIP = 'recovery.zip'
_UNIT = 'night-shift-protocol-test.service'


class RecoveryEntryRefused(RuntimeError):
    """Bounded local labels; no diagnostics, peer data or keys on stdout."""


def parse_context(attempt_id: str, vm_id: str, payload_sha256: str) -> tuple[str, str, str]:
    try:
        checked = UUID(vm_id)
        if (not checked.int or str(checked) != vm_id or re.fullmatch('[0-9a-f]{32}', attempt_id) is None
                or re.fullmatch('[0-9a-f]{64}', payload_sha256) is None):
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise RecoveryEntryRefused('binding') from None
    return attempt_id, vm_id, payload_sha256


def _read(path: Path, limit: int) -> bytes:
    if sys.platform != 'linux':
        raise RecoveryEntryRefused('runtime')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise RecoveryEntryRefused('file_type')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            value = stream.read(limit + 1)
        if len(value) > limit:
            raise RecoveryEntryRefused('file_bound')
        return value
    finally:
        os.close(fd)


def _system(argv: list[str], deadline: float, *, read_mount: bool = False) -> bytes:
    left = deadline - time.monotonic()
    if left <= 0:
        raise RecoveryEntryRefused('deadline')
    result = subprocess.run(argv, env=_ENV, cwd='/', stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE if read_mount else subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, timeout=min(5, left), check=True)
    output = result.stdout if read_mount else b''
    if len(output) > 4096:
        raise RecoveryEntryRefused('mount_observation')
    return output


def _mount_info(path: Path, filesystem: str, deadline: float, *, source: Path | None = None) -> set[str]:
    data = _system(['/usr/bin/findmnt', '--json', '--first-only', '--mountpoint', str(path),
                    '--output', 'TARGET,SOURCE,FSTYPE,OPTIONS'], deadline, read_mount=True)
    rows = json.loads(data)['filesystems']
    if (len(rows) != 1 or rows[0]['target'] != str(path) or rows[0]['fstype'] != filesystem
            or (source is not None and rows[0]['source'] != str(source))):
        raise RecoveryEntryRefused('mount_observation')
    return set(rows[0]['options'].split(','))


def _directory(path: Path) -> None:
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid or info.st_gid or info.st_mode & 0o022:
        raise RecoveryEntryRefused('directory')


def _boot_guard(attempt: str, vm_id: str, deadline: float) -> Path:
    if (sys.platform != 'linux' or platform.machine() != 'x86_64' or sys.version_info[:2] != (3, 12)
            or not sys.flags.isolated or not sys.flags.no_site or not sys.dont_write_bytecode
            or dict(os.environ) != _ENV or any((os.getuid(), os.geteuid(), os.getgid(), os.getegid()))):
        raise RecoveryEntryRefused('runtime')
    if (any(os.readlink('/proc/self/ns/' + ns) == os.readlink('/proc/1/ns/' + ns) for ns in ('mnt', 'net'))
            or os.listdir('/sys/class/net') != ['lo']
            or _read(Path('/proc/swaps'), 4096).split() != [b'Filename', b'Type', b'Size', b'Used', b'Priority']
            or str(UUID(_read(Path('/sys/class/dmi/id/product_uuid'), 128).decode('ascii').strip())) != vm_id
            or _read(Path('/sys/class/dmi/id/sys_vendor'), 128).strip() != b'Microsoft Corporation'
            or _read(Path('/var/lib/cloud/data/instance-id'), 128).strip() != ('night-shift-finalize-' + attempt).encode('ascii')
            or b'autoinstall' in _read(Path('/proc/cmdline'), 4096)):
        raise RecoveryEntryRefused('recovery_context')
    _mount_info(Path('/'), 'overlay', deadline)
    if 'rw' not in _mount_info(Path('/run'), 'tmpfs', deadline):
        raise RecoveryEntryRefused('ram')
    _directory(Path('/run'))
    optical = _OPTICAL.resolve(strict=True)
    if (optical.parent != Path('/dev') or re.fullmatch('sr[0-9]+', optical.name) is None
            or not stat.S_ISBLK(optical.lstat().st_mode)
            or _read(Path('/sys/class/block') / optical.name / 'device/type', 16).strip() != b'5'):
        raise RecoveryEntryRefused('optical_device')
    return optical


def pin_archive(raw: bytes, *, expected_sha256: str) -> dict[str, bytes]:
    """Verify the full pin before opening the ZIP. Nothing is extracted."""
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_ARCHIVE or hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise RecoveryEntryRefused('payload_pin')
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            infos = archive.infolist()
            names = {item.filename for item in infos}
            needed = {'controller.json', 'request.json', _UNIT, 'hv_kvp_daemon'}
            if len(infos) != len(names) or not len(needed) <= len(infos) <= 32 or not needed <= names:
                raise RecoveryEntryRefused('payload_shape')
            for item in infos:
                if (item.compress_type != zipfile.ZIP_STORED or item.flag_bits
                        or not 0 <= item.file_size <= _MAX_FILE
                        or item.compress_size != item.file_size or item.is_dir()):
                    raise RecoveryEntryRefused('payload_shape')
            return {name: archive.read(name) for name in sorted(needed)}
    except (zipfile.BadZipFile, KeyError, ValueError):
        raise RecoveryEntryRefused('payload_shape') from None


def _start_daemon(raw: bytes, deadline: float) -> subprocess.Popen[bytes]:
    if sys.platform != 'linux':
        raise RecoveryEntryRefused('runtime')
    device = Path('/dev/vmbus/hv_kvp').lstat()
    if not stat.S_ISCHR(device.st_mode) or device.st_uid or device.st_gid or device.st_mode & 0o022:
        raise RecoveryEntryRefused('kvp_device')
    pids = os.listdir('/proc')
    if len(pids) > 8192:
        raise RecoveryEntryRefused('process_bound')
    for entry in pids:
        if entry.isdecimal():
            try:
                if _read(Path('/proc') / entry / 'comm', 256).strip() == b'hv_kvp_daemon':
                    raise RecoveryEntryRefused('daemon_exists')
            except FileNotFoundError:
                pass
    _directory(_POOL.parent)
    _POOL.mkdir(mode=0o700, exist_ok=True)
    _directory(_POOL)
    if os.listdir(_POOL):
        raise RecoveryEntryRefused('pools_not_fresh')
    # New RAM backing under a private mount namespace; no existing pool is reused.
    _system(['/usr/bin/mount', '-t', 'tmpfs', '-o', 'nodev,nosuid,noexec,mode=0700,size=1m',
             'tmpfs', str(_POOL)], deadline)
    _directory(_POOL)
    if not {'rw', 'nodev', 'nosuid', 'noexec'} <= _mount_info(_POOL, 'tmpfs', deadline):
        raise RecoveryEntryRefused('pool_mount')
    executable = _STAGE / 'hv_kvp_daemon'
    fd = os.open(executable, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o500)
    try:
        if os.write(fd, raw) != len(raw):
            raise RecoveryEntryRefused('daemon_copy')
    finally:
        os.close(fd)
    if _read(executable, _MAX_FILE) != raw or time.monotonic() >= deadline:
        raise RecoveryEntryRefused('daemon_copy')
    return subprocess.Popen([str(executable), '-n'], cwd='/', env=_ENV, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)


def _stop_daemon(child: subprocess.Popen[bytes]) -> None:
    if child.poll() is not None:
        return
    child.terminate()
    try:
        child.wait(timeout=1)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait(timeout=1)


def _wait_daemon(child: subprocess.Popen[bytes], deadline: float) -> None:
    cutoff = min(deadline, time.monotonic() + 5)
    while child.poll() is None and time.monotonic() < cutoff:
        names = set(os.listdir(_POOL))
        if not names <= _O_NAMES:
            raise RecoveryEntryRefused('pool_shape')
        for name in names:
            info = (_POOL / name).lstat()
            if (not stat.S_ISREG(info.st_mode) or info.st_uid or info.st_gid or info.st_nlink != 1
                    or info.st_size or info.st_mode & 0o022):
                raise RecoveryEntryRefused('pool_shape')
        if names == _O_NAMES and child.poll() is None and time.monotonic() < cutoff:
            return
        time.sleep(0.02)
    raise RecoveryEntryRefused('daemon_not_ready')


def run_once(attempt: str, vm_id: str, digest: str) -> bool:
    attempt, vm_id, digest = parse_context(attempt, vm_id, digest)
    os.umask(0o077)
    deadline = time.monotonic() + _GUEST_SECONDS
    optical = _boot_guard(attempt, vm_id, deadline)
    _STAGE.mkdir(mode=0o700)  # A pre-existing marker prevents a second attempt.
    _MEDIA.mkdir(mode=0o700)
    _system(['/usr/bin/mount', '-t', 'iso9660', '-o', 'ro,nodev,nosuid,noexec', str(optical), str(_MEDIA)], deadline)
    options = _mount_info(_MEDIA, 'iso9660', deadline, source=optical)
    if not {'ro', 'nodev', 'nosuid', 'noexec'} <= options or 'rw' in options:
        raise RecoveryEntryRefused('recovery_mount')
    archive = _MEDIA / _ZIP
    files = pin_archive(_read(archive, MAX_ARCHIVE), expected_sha256=digest)
    for name in ('request.json', _UNIT):
        if _read(_MEDIA / name, _MAX_FILE) != files[name]:
            raise RecoveryEntryRefused('media_mismatch')
    if any(key == 'night_shifts' or key.startswith('night_shifts.') for key in sys.modules):
        raise RecoveryEntryRefused('preloaded_package')
    # Import only from the pinned ZIP, on a read-only optical mount in this namespace.
    sys.path.insert(0, str(archive))
    from night_shifts.finalization_tls_identity import decode_controller_trust
    from night_shifts.guest.finalization_bootstrap import _check_live_boot, serve_fresh_guest_once
    from night_shifts.maintenance_tls_prototype import FINALIZATION_OPERATION, AttemptBinding

    binding = AttemptBinding(attempt, vm_id, FINALIZATION_OPERATION)
    controller = decode_controller_trust(files['controller.json'], binding)
    _check_live_boot(binding)
    child = _start_daemon(files['hv_kvp_daemon'], deadline)
    try:
        _wait_daemon(child, deadline)
        return serve_fresh_guest_once(controller, deadline=deadline, cancelled=lambda: child.poll() is not None)
    finally:
        _stop_daemon(child)


def main() -> int:
    if len(sys.argv) != 4:
        return 1
    try:
        return 0 if run_once(sys.argv[1], sys.argv[2], sys.argv[3]) is True else 1
    except Exception:
        # No stdout/stderr with raw boot, process or peer details. The authenticated
        # exchange and independent host teardown are the only acceptance evidence.
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
