"""Explicit Unix filesystem model. No mount, serial device or real image used."""
from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from night_shifts.guest import finalize_image_copy as guest


@pytest.fixture
def model(tmp_path, monkeypatch):
    root = tmp_path / 'synthetic-offline-copy'
    links = {}
    modes = {}
    real_lstat, real_unlink, real_chmod = Path.lstat, Path.unlink, Path.chmod
    real_is_symlink, real_readlink, real_symlink = Path.is_symlink, os.readlink, os.symlink

    def put(name, content=b'fixture', mode=0o644):
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        modes[target] = mode
        return target

    def link(destination, target):
        target = Path(target)
        if not target.is_relative_to(root):
            return real_symlink(destination, target)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b'link placeholder')
        links[target] = destination

    def metadata(target, *args, **kwargs):
        info = real_lstat(target, *args, **kwargs)
        if not target.is_relative_to(root):
            return info
        directory = stat.S_ISDIR(info.st_mode)
        kind = stat.S_IFLNK if target in links else stat.S_IFDIR if directory else stat.S_IFREG
        return SimpleNamespace(st_mode=kind | (0o777 if target in links else 0o755 if directory else modes.get(target, 0o644)),
                               st_uid=0, st_gid=0, st_nlink=1, st_size=info.st_size)

    def unlink(target, *args, **kwargs):
        links.pop(target, None)
        return real_unlink(target, *args, **kwargs)

    def chmod(target, mode, *args, **kwargs):
        if target.is_relative_to(root):
            modes[target] = mode
        return real_chmod(target, mode, *args, **kwargs)

    monkeypatch.setattr(Path, 'lstat', metadata)
    monkeypatch.setattr(Path, 'is_symlink', lambda p: p in links or real_is_symlink(p))
    monkeypatch.setattr(Path, 'unlink', unlink)
    monkeypatch.setattr(Path, 'chmod', chmod)
    monkeypatch.setattr(os, 'readlink', lambda p: links[Path(p)] if Path(p) in links else real_readlink(p))
    monkeypatch.setattr(os, 'symlink', link)
    monkeypatch.setattr(guest.audit, '_TARGET', root)
    cmdline = tmp_path / 'live-cmdline'
    cmdline.write_text('boot=casper fixture')
    monkeypatch.setattr(guest.audit, '_CMDLINE', cmdline)
    bootstrap, unit = b'fixture bootstrap', b'fixture original service'
    put(guest.audit._BOOTSTRAP, bootstrap)
    put('etc/passwd', b'root:x:0:0:root:/root:/bin/bash\nnight-shift:x:999:988::/nonexistent:/usr/sbin/nologin\nnobody:x:65534:65534::/nonexistent:/usr/sbin/nologin\n')
    put('etc/shadow', b'root:!:0:0:99999:7:::\nnight-shift:!:0:0:99999:7:::\nnobody:!:0:0:99999:7:::\n', 0o640)
    put('etc/group', b'root:x:0:\nnight-shift:x:988:\ndialout:x:20:night-shift\nnogroup:x:65534:\n')
    put('etc/default/grub', b'fixture')
    put('boot/grub/grub.cfg', b'fixture', 0o444)
    put('usr/bin/python3.12', b'\x7fELFfixture', 0o755)
    put('usr/bin/systemctl', b'\x7fELFfixture', 0o755)
    put('var/lib/dpkg/status', b'Package: openssh-client\nStatus: install ok installed\n')
    put('etc/cloud/cloud-init.disabled', b'preserve-completed-initialization')
    put('etc/cloud/cloud.cfg.d/99-installer.cfg', b'fixture installer instance state')
    put('etc/machine-id', b'original-machine-id')
    put('var/lib/dbus/machine-id', b'original-machine-id')
    put('var/lib/systemd/random-seed', b'PRIVATE_CANARY')
    put('root/.ssh/authorized_keys', b'')
    put('root/.bash_history', b'PRIVATE_CANARY')
    key = put('etc/ssh/ssh_host_ed25519_key', b'PRIVATE_CANARY')
    put('var/log/cloud-init.log', b'PRIVATE_CANARY')
    for name in ('var/cache/apt', 'var/lib/dhcp', 'home', 'usr/sbin'):
        (root / name).mkdir(parents=True, exist_ok=True)
    status = {'v1': {name: {'start': 1, 'finished': 2, 'errors': [], 'recoverable_errors': {}}
                     for name in ('init-local', 'init', 'modules-config', 'modules-final')}}
    put('var/lib/cloud/data/status.json', json.dumps(status).encode())
    put('var/lib/cloud/data/result.json', b'{"v1":{"errors":[]}}')
    profile = {}
    for name, data in (
        ('original-night-shift-protocol-test.service', unit),
        ('operation.json', b'{"fixture":true}'), ('prepared.json', b'{"fixture":true}'),
    ):
        relative = 'etc/night-shift-diagnostic-027/' + name
        put(relative, data, 0o600 if name.endswith('.json') else 0o644)
        profile[relative] = hashlib.sha256(data).hexdigest()
    for name, destination in ((guest.UNIT, '/dev/null'),
                              ('etc/systemd/system/multi-user.target.wants/night-shift-protocol-test.service', '/' + guest.UNIT),
                              ('etc/systemd/system/serial-getty@ttyS0.service', '/dev/null'),
                              (guest.DEBUG_LINKS[0], '/usr/lib/systemd/system/debug-shell.service'),
                              ('usr/bin/python3', 'python3.12')):
        link(destination, root / name)
    request = {'version': 1, 'id': 'a' * 32, 'mode': 'finalize', 'artifacts': profile,
               'payload': {'bootstrap': hashlib.sha256(bootstrap).hexdigest(), 'unit': hashlib.sha256(unit).hexdigest()}}
    return SimpleNamespace(root=root, links=links, put=put, request=request, unit=unit, key=key)


def test_finalization_restores_service_preserves_disabled_marker_and_removes_diagnostics(model, monkeypatch):
    original_read = Path.read_bytes

    def read(target):
        assert target != model.key, 'guest-generated private keys must never be read'
        return original_read(target)

    monkeypatch.setattr(Path, 'read_bytes', read)
    result = guest.finalize(model.root, model.request, model.unit)
    assert result['audit'] == 'pass'
    assert (model.root / guest.UNIT).read_bytes() == model.unit
    assert guest.UNIT not in {str(p.relative_to(model.root)) for p in model.links}
    assert model.links[model.root / guest.DEBUG] == '/dev/null'
    assert (model.root / 'etc/cloud/cloud-init.disabled').read_bytes() == b'preserve-completed-initialization'
    assert (model.root / 'etc/machine-id').read_bytes() == b''
    assert not (model.root / 'etc/night-shift-diagnostic-027').exists()
    assert not model.key.exists() and not (model.root / 'var/lib/systemd/random-seed').exists()
    assert list((model.root / 'var/log').iterdir()) == []
    assert list((model.root / 'var/lib/cloud').iterdir()) == []


@pytest.mark.parametrize('fault', ['hash', 'unknown-artifact', 'incomplete-init', 'ssh-credentials', 'symlink-parent'])
def test_refusal_before_mutations_keeps_diagnostic_copy(model, fault):
    if fault == 'hash':
        model.request['artifacts']['etc/night-shift-diagnostic-027/prepared.json'] = 'f' * 64
    elif fault == 'unknown-artifact':
        model.put('etc/night-shift-diagnostic-027/unreviewed', b'PRIVATE_CANARY')
    elif fault == 'incomplete-init':
        model.put('var/lib/cloud/data/result.json', b'{"v1":{"errors":["PRIVATE_CANARY"]}}')
    elif fault == 'ssh-credentials':
        model.put('root/.ssh/authorized_keys', b'PRIVATE_CANARY')
    else:
        model.links[model.root / 'etc/ssh'] = '/etc/ssh'
    before = (model.root / 'etc/machine-id').read_bytes()
    with pytest.raises((guest.FinalizationError, guest.audit.AuditFailure)):
        guest.finalize(model.root, model.request, model.unit)
    assert model.links[model.root / guest.UNIT] == '/dev/null'
    assert (model.root / 'etc/machine-id').read_bytes() == before
    assert model.key.exists() and (model.root / 'var/lib/systemd/random-seed').exists()
