#!/usr/bin/env python3
"""Fixed offline maintenance of ONE copied guest; never execute target programs.

Only main() mounts a disk. Host-controlled CIDATA supplies the request and exact
payload. Library functions exist for synthetic offline tests, not agent tools.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import select
import shutil
import stat
import subprocess
import time
from pathlib import Path
from typing import Any

try:
    from night_shifts.guest import protocol_test_bootstrap as serial
    from night_shifts.guest import review_protocol_test_target as audit
except ModuleNotFoundError:  # Standalone, checksum-verified recovery media.
    import importlib

    serial = importlib.import_module('protocol_test_bootstrap')
    audit = importlib.import_module('review_protocol_test_target')

ROOT = Path('/run/night-shift-finalize-target')
MEDIA = Path('/run/night-shift-finalize-media')
UNIT = 'etc/systemd/system/night-shift-protocol-test.service'
DEBUG = 'etc/systemd/system/debug-shell.service'
DEBUG_LINKS = tuple('etc/systemd/system/' + name + '/debug-shell.service' for name in (
    'sysinit.target.wants', 'multi-user.target.wants',
))
TREES = ('var/log', 'var/cache/apt', 'var/lib/cloud', 'var/lib/dhcp')
FILES = ('var/lib/systemd/random-seed', 'root/.bash_history', 'root/.lesshst',
         'root/.python_history', 'root/.wget-hsts', 'etc/cloud/cloud.cfg.d/99-installer.cfg')
DIGEST = re.compile(r'^[0-9a-f]{64}$')


class FinalizationError(RuntimeError):
    """Refuse drift; only fixed failure labels may cross the serial channel."""


def require(value: bool) -> None:
    if not value:
        raise FinalizationError('maintenance policy differs')


def artifact_name(name: str) -> bool:
    """Allow reviewed diagnostic files, never arbitrary guest deletion paths."""
    return bool(re.fullmatch(
        r'(?:etc/systemd/system/(?:debug-shell\.service(?:\.d/[a-zA-Z0-9_.-]+\.conf)?|'
        r'night-shift-protocol-test\.service(?:\.[a-zA-Z0-9_.-]+|\.d/[a-zA-Z0-9_.-]+\.conf))|'
        r'root/(?:nsdiag027|night-shift-diagnostic)[a-zA-Z0-9_.-]*|'
        r'etc/night-shift-diagnostic-027/(?:original-night-shift-protocol-test\.service|operation\.json|prepared\.json))', name,
    )) and name != UNIT


def validate_request(request: Any) -> dict[str, Any]:
    require(isinstance(request, dict) and set(request) == {'version', 'id', 'mode', 'artifacts', 'payload'})
    require(type(request['version']) is int and request['version'] == 1)
    require(isinstance(request['id'], str) and re.fullmatch(r'[0-9a-f]{32}', request['id']) is not None)
    require(request['mode'] in ('inspect', 'finalize'))
    require(isinstance(request['artifacts'], dict) and len(request['artifacts']) <= 32)
    for name, digest in request['artifacts'].items():
        require(isinstance(name, str) and artifact_name(name))
        require(isinstance(digest, str) and DIGEST.fullmatch(digest) is not None)
    require(isinstance(request['payload'], dict) and set(request['payload']) == {'bootstrap', 'unit'})
    require(all(isinstance(d, str) and DIGEST.fullmatch(d) for d in request['payload'].values()))
    return request


def path(root: Path, name: str) -> Path:
    require(not name.startswith('/') and '..' not in name.split('/'))
    target = root / name
    for parent in (root, *reversed(target.parent.relative_to(root).parents), target.parent):
        candidate = parent if parent.is_absolute() else root / parent
        info = candidate.lstat()
        require(stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode) and info.st_uid == 0)
    return target


def present(target: Path) -> bool:
    return target.exists() or target.is_symlink()


def regular(root: Path, name: str, limit: int = 1024 * 1024) -> bytes:
    target = path(root, name)
    info = target.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == 0)
    require(0 <= info.st_size <= limit)
    data = target.read_bytes()
    require(len(data) == info.st_size)
    return data


def initialized(root: Path) -> None:
    require(bool(regular(root, 'etc/cloud/cloud-init.disabled', 4096)))
    status = json.loads(regular(root, 'var/lib/cloud/data/status.json'))['v1']
    result = json.loads(regular(root, 'var/lib/cloud/data/result.json'))['v1']
    require(result['errors'] == [])
    for stage in ('init-local', 'init', 'modules-config', 'modules-final'):
        entry = status[stage]
        require(isinstance(entry, dict) and entry.get('start') is not None and entry.get('finished') is not None)
        require(entry.get('errors') == [] and entry.get('recoverable_errors', {}) in ({}, []))


def inventory(root: Path) -> dict[str, Any]:
    """Only diagnostic names/code hashes, never keys, histories or log contents."""
    found: dict[str, Any] = {}
    entries = list((root / 'etc/systemd/system').rglob('*'))
    entries += list((root / 'root').iterdir())
    diagnostic = root / 'etc/night-shift-diagnostic-027'
    if present(diagnostic):
        path(root, 'etc/night-shift-diagnostic-027/.probe')
        entries += list(diagnostic.iterdir())
    require(len(entries) <= 4096)
    for target in entries:
        name = target.relative_to(root).as_posix()
        if name == UNIT or name == 'etc/systemd/system/multi-user.target.wants/night-shift-protocol-test.service':
            continue
        if 'debug-shell.service' in name or 'night-shift-protocol-test.service' in name or artifact_name(name) or name.startswith('etc/night-shift-diagnostic-027/'):
            path(root, name)  # Refuse symlinked parents before reading anything.
            info = target.lstat()
            if name in (DEBUG + '.d', UNIT + '.d') and stat.S_ISDIR(info.st_mode):
                continue
            if (not artifact_name(name) and name not in DEBUG_LINKS) or stat.S_ISDIR(info.st_mode):
                found[name] = {'kind': 'unreviewed'}
                continue
            if stat.S_ISLNK(info.st_mode):
                destination = os.readlink(target)
                require(len(destination) <= 256)
                if name == DEBUG and destination == '/dev/null':
                    continue
                found[name] = {'kind': 'link', 'target': destination}
            else:
                found[name] = {'kind': 'file', 'sha256': hashlib.sha256(regular(root, name)).hexdigest()}
    return found


def prepare(root: Path, request: dict[str, Any]) -> dict[str, Any]:
    """Validate the WHOLE deletion plan before the first write."""
    validate_request(request)
    initialized(root)
    audit._TARGET = root
    audit._accounts()
    audit._prerequisites()
    audit._serial_boot()
    require(hashlib.sha256(regular(root, audit._BOOTSTRAP)).hexdigest() == request['payload']['bootstrap'])
    unit = path(root, UNIT)
    require(unit.is_symlink() and os.readlink(unit) == '/dev/null')
    require(audit._link('etc/systemd/system/multi-user.target.wants/night-shift-protocol-test.service') == '/' + UNIT)
    require(audit._link('etc/systemd/system/serial-getty@ttyS0.service') == '/dev/null')
    require(not present(path(root, 'usr/sbin/sshd')))
    # Empty authorized_keys is harmless but must not survive in the base.
    ssh = root / 'root/.ssh'
    if present(ssh):
        path(root, 'root/.ssh/authorized_keys')
        require({p.name for p in ssh.iterdir()} <= {'authorized_keys'})
        if present(ssh / 'authorized_keys'):
            require(regular(root, 'root/.ssh/authorized_keys') == b'')
    path(root, 'etc/ssh/.probe')  # Never follow a target directory into the live OS.
    discovered = inventory(root)
    backup = 'etc/night-shift-diagnostic-027/original-night-shift-protocol-test.service'
    if backup in discovered:
        require(discovered[backup] == {'kind': 'file', 'sha256': request['payload']['unit']})
    for name, item in discovered.items():
        if name in DEBUG_LINKS:
            require(item['kind'] == 'link' and item['target'] in (
                '/usr/lib/systemd/system/debug-shell.service', '/lib/systemd/system/debug-shell.service',
            ))
        else:
            require(item == {'kind': 'file', 'sha256': request['artifacts'].get(name)})
    require(set(request['artifacts']) == set(discovered) - set(DEBUG_LINKS))
    for name in (*TREES, *FILES, 'etc/machine-id', 'var/lib/dbus/machine-id'):
        target = path(root, name)
        if not present(target):
            continue
        info = target.lstat()
        if name in TREES:
            require(stat.S_ISDIR(info.st_mode))
        elif name == 'var/lib/dbus/machine-id' and target.is_symlink():
            require(os.readlink(target) == '/etc/machine-id')
        else:
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1)
    for target in (root / 'etc/ssh').iterdir():
        if target.name.startswith('ssh_host_'):
            require(re.fullmatch(r'ssh_host_(rsa|ecdsa|ed25519)_key(?:\.pub)?', target.name) is not None)
            info = target.lstat()
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1)
    return discovered


def finalize(root: Path, request: dict[str, Any], unit_bytes: bytes) -> dict[str, Any]:
    require(request['mode'] == 'finalize')
    require(hashlib.sha256(unit_bytes).hexdigest() == request['payload']['unit'])
    discovered = prepare(root, request)
    for name in (*request['artifacts'], *DEBUG_LINKS, *FILES):
        target = path(root, name)
        if present(target):
            target.unlink()
    for name in TREES:
        target = path(root, name)
        if present(target):
            for child in target.iterdir():
                if child.is_dir() and not child.is_symlink():
                    shutil.rmtree(child)  # fd-safe on Linux; never follows target symlinks.
                else:
                    child.unlink()
    diagnostic = root / 'etc/night-shift-diagnostic-027'
    if present(diagnostic):
        diagnostic.rmdir()
    for directory in ('debug-shell.service.d', 'night-shift-protocol-test.service.d'):
        target = root / 'etc/systemd/system' / directory
        if present(target):
            target.rmdir()  # Nonempty/unreviewed directories fail closed.
    for target in (root / 'etc/ssh').glob('ssh_host_*'):
        target.unlink()  # Names/types already checked, contents never read.
    ssh = root / 'root/.ssh'
    if present(ssh / 'authorized_keys'):
        (ssh / 'authorized_keys').unlink()
    unit = path(root, UNIT)
    unit.unlink()
    with unit.open('xb') as stream:
        stream.write(unit_bytes)
        stream.flush()
        os.fsync(stream.fileno())
    unit.chmod(0o644)
    debug = path(root, DEBUG)
    if present(debug):
        debug.unlink()
    os.symlink('/dev/null', debug)
    machine = path(root, 'etc/machine-id')
    machine.write_bytes(b'')
    machine.chmod(0o444)
    dbus = path(root, 'var/lib/dbus/machine-id')
    if present(dbus):
        dbus.unlink()
    os.symlink('/etc/machine-id', dbus)
    audit._payload(request['payload']['bootstrap'], request['payload']['unit'])
    for check in (audit._accounts, audit._prerequisites, audit._service_links,
                  audit._serial_boot, audit._ssh_hygiene):
        check()
    require(inventory(root) == {})
    require(bool(regular(root, 'etc/cloud/cloud-init.disabled', 4096)))
    require(regular(root, 'etc/machine-id') == b'')
    require(all(not present(path(root, name)) for name in FILES))
    require(all(not present(path(root, name)) or not any(path(root, name).iterdir()) for name in TREES))
    return {'removed_diagnostics': sorted(discovered), 'audit': 'pass'}


def command(*argv: str) -> str:
    result = subprocess.run(argv, check=True, capture_output=True, text=True, timeout=30)
    require(len(result.stdout) <= 128 * 1024)
    return result.stdout


def read_line(channel: Any, limit: int, timeout: float) -> bytes:
    deadline = time.monotonic() + timeout
    data = bytearray()
    while time.monotonic() < deadline:
        ready, _, _ = select.select([channel], [], [], max(0, deadline - time.monotonic()))
        require(bool(ready))
        byte = channel.read(1)
        require(bool(byte))
        if byte == b'\n':
            return bytes(data)
        data.extend(byte)
        require(len(data) <= limit)
    raise FinalizationError('controller handshake timed out')


def main() -> int:
    require(os.name == 'posix' and getattr(os, 'geteuid', lambda: -1)() == 0)
    require(Path('/sys/class/dmi/id/sys_vendor').read_text().strip() == 'Microsoft Corporation')
    cmdline = Path('/proc/cmdline').read_text()
    # Ubuntu live GRUB does not always emit a boot=casper argument.
    # The overlay-root and exact NoCloud identity guards below remain mandatory.
    require('autoinstall' not in cmdline)
    require(sorted(p.name for p in Path('/sys/class/net').iterdir()) == ['lo'])
    live_root = json.loads(command('/usr/bin/findmnt', '--json', '--mountpoint', '/', '-o', 'FSTYPE'))
    require(live_root['filesystems'][0]['fstype'] == 'overlay')
    request = validate_request(json.loads((MEDIA / 'request.json').read_bytes()))
    require(Path('/var/lib/cloud/data/instance-id').read_text().strip() == 'night-shift-finalize-' + request['id'])
    with serial._open_serial('/dev/ttyS0') as channel:
        require(json.loads(read_line(channel, 256, 120)) == {'id': request['id'], 'mode': request['mode']})
        receipt: dict[str, Any] = {'version': 1, 'id': request['id'], 'mode': request['mode'], 'status': 'failed', 'unmounted_read_only': False}
        mounted = False
        try:
            disks = json.loads(command('/usr/bin/lsblk', '--json', '--tree', '-b', '-e', '7', '-o', 'PATH,TYPE,SIZE,FSTYPE,MOUNTPOINTS'))['blockdevices']
            writable = [d for d in disks if d['type'] == 'disk']
            require(len(writable) == 1 and writable[0]['path'] == '/dev/sda' and int(writable[0]['size']) == 20 * 1024**3)
            parts = writable[0].get('children', [])
            require([(p['path'], p['type'], p['fstype']) for p in parts] == [('/dev/sda1', 'part', 'vfat'), ('/dev/sda2', 'part', 'ext4')])
            require(all(not any(p.get('mountpoints', [])) for p in [writable[0], *parts]))
            # No source partition may already be mounted by the live installer.
            mounts = json.loads(command('/usr/bin/findmnt', '--json', '-o', 'TARGET,SOURCE'))
            require('/dev/sda' not in json.dumps(mounts))
            ROOT.mkdir(mode=0o700)
            for device in ('/dev/sda', '/dev/sda1', '/dev/sda2'):
                command('/usr/sbin/blockdev', '--setro', device)
            command('/usr/bin/mount', '-t', 'ext4', '-o', 'ro,noload,nodev,nosuid,noexec', '/dev/sda2', str(ROOT))
            mounted = True
            if request['mode'] == 'inspect':
                initialized(ROOT)
                receipt['diagnostics'] = inventory(ROOT)
                receipt['audit'] = 'inspection_only'
            else:
                prepare(ROOT, request)
                command('/usr/bin/umount', str(ROOT))
                mounted = False
                for device in ('/dev/sda', '/dev/sda1', '/dev/sda2'):
                    command('/usr/sbin/blockdev', '--setrw', device)
                command('/usr/bin/mount', '-t', 'ext4', '-o', 'rw,nodev,nosuid,noexec', '/dev/sda2', str(ROOT))
                mounted = True
                receipt.update(finalize(ROOT, request, (MEDIA / 'night-shift-protocol-test.service').read_bytes()))
                command('/usr/bin/sync')
            receipt['status'] = 'success'
        except Exception:
            receipt['error'] = 'maintenance refused or failed; copy not accepted'
        finally:
            try:
                if mounted:
                    command('/usr/bin/umount', str(ROOT))
                for device in ('/dev/sda', '/dev/sda1', '/dev/sda2'):
                    command('/usr/sbin/blockdev', '--setro', device)
                    require(command('/usr/sbin/blockdev', '--getro', device).strip() == '1')
                require('/dev/sda' not in command('/usr/bin/findmnt', '--json', '-o', 'TARGET,SOURCE'))
                receipt['unmounted_read_only'] = True
            except Exception:
                receipt['status'] = 'failed'
                receipt['error'] = 'unmount/read-only state unknown; copy not accepted'
        encoded = json.dumps(receipt, sort_keys=True, separators=(',', ':')).encode('utf-8')
        require(len(encoded) <= 32768)
        channel.write(encoded + b'\n')
        channel.flush()
        return 0 if receipt['status'] == 'success' else 1


if __name__ == '__main__':
    raise SystemExit(main())
