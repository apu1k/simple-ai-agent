"""Synthetic Linux read/namespace prerequisites; NO native tools or kernel calls."""
from __future__ import annotations

import hashlib
import stat
from types import SimpleNamespace

import pytest

from night_shifts.guest import bootstrap_recovery_launcher as launcher


def context():
    return dict(attempt_id='1' * 32, vm_id='00000000-0000-4000-8000-000000000001',
                seed_sha256='1' * 64, policy_sha256='2' * 64)


@pytest.mark.parametrize('chunks,limit,expected', [
    ([b'ab', b'cd', b''], 4, b'abcd'), ([b'', b'CANARY'], 4, b''),
])
def test_short_native_reads_continue_to_eof_with_aggregate_bound(monkeypatch, chunks, limit, expected):
    closed = []
    chunks = iter(chunks)
    monkeypatch.setattr(launcher, 'sys', SimpleNamespace(platform='linux'))
    monkeypatch.setattr(launcher, 'os', SimpleNamespace(
        O_RDONLY=1, O_NOFOLLOW=2, O_CLOEXEC=4, O_NONBLOCK=8,
        open=lambda *a: 99, read=lambda fd, count: next(chunks), close=lambda fd: closed.append(fd)))
    assert launcher._read('/synthetic', limit) == expected
    assert closed == [99]


def test_read_bound_closes_descriptor_without_returning_partial_data(monkeypatch):
    closed = []
    monkeypatch.setattr(launcher, 'sys', SimpleNamespace(platform='linux'))
    monkeypatch.setattr(launcher, 'os', SimpleNamespace(
        O_RDONLY=1, O_NOFOLLOW=2, O_CLOEXEC=4, O_NONBLOCK=8,
        open=lambda *a: 99, read=lambda fd, count: b'12345', close=lambda fd: closed.append(fd)))
    with pytest.raises(launcher.RecoveryLaunchRefused, match='^input_bound$'):
        launcher._read('/synthetic', 4)
    assert closed == [99]


def test_aggregate_read_overflow_closes_without_returning_prefix(monkeypatch):
    closed, requests = [], []
    chunks = iter([b'ab', b'cd', b'e'])

    def read(fd, count):
        requests.append(count)
        return next(chunks)

    monkeypatch.setattr(launcher, 'sys', SimpleNamespace(platform='linux'))
    monkeypatch.setattr(launcher, 'os', SimpleNamespace(
        O_RDONLY=1, O_NOFOLLOW=2, O_CLOEXEC=4, O_NONBLOCK=8,
        open=lambda *a: 99, read=read, close=lambda fd: closed.append(fd)))
    with pytest.raises(launcher.RecoveryLaunchRefused, match='^input_bound$'):
        launcher._read('/synthetic', 4)
    assert requests == [5, 3, 1] and closed == [99]


def test_read_error_closes_without_returning_prefix(monkeypatch):
    closed = []

    def read(fd, count):
        raise BlockingIOError('SYNTHETIC_CANARY')

    monkeypatch.setattr(launcher, 'sys', SimpleNamespace(platform='linux'))
    monkeypatch.setattr(launcher, 'os', SimpleNamespace(
        O_RDONLY=1, O_NOFOLLOW=2, O_CLOEXEC=4, O_NONBLOCK=8,
        open=lambda *a: 99, read=read, close=lambda fd: closed.append(fd)))
    with pytest.raises(BlockingIOError):
        launcher._read('/synthetic', 4)
    assert closed == [99]


def test_partial_write_is_unknown_and_never_retried(monkeypatch):
    writes, closed = [], []
    monkeypatch.setattr(launcher, 'sys', SimpleNamespace(platform='linux'))
    monkeypatch.setattr(launcher, 'os', SimpleNamespace(
        O_WRONLY=1, O_CREAT=2, O_EXCL=4, O_NOFOLLOW=8, O_CLOEXEC=16,
        open=lambda *a: 99, write=lambda fd, data: writes.append(data) or 1,
        close=lambda fd: closed.append(fd)))
    monkeypatch.setattr(launcher, '_read', lambda *a: pytest.fail('must not read back short write'))
    with pytest.raises(launcher.RecoveryLaunchUnknown, match='^write_unknown$'):
        launcher._new('/synthetic', b'ab')
    assert writes == [b'ab'] and closed == [99]


@pytest.fixture
def early_model(monkeypatch):
    values = {
        'blocks': ['loop0', 'sr0'], 'interfaces': ['lo'], 'loop_active': False,
        '/sys/class/dmi/id/product_uuid': context()['vm_id'].encode(),
        '/sys/class/block/sr0/ro': b'1\n', '/sys/class/block/loop0/ro': b'0\n',
        '/sys/class/block/loop0/loop/backing_file': b'/reviewed-recovery.iso\n',
        '/proc/swaps': b'Filename Type Size Used Priority\n',
        '/proc/self/mountinfo': b'1 0 0:1 / /run rw - tmpfs tmpfs rw\n',
        '/sys/module/apparmor/parameters/enabled': b'Y\n',
        '/sys/kernel/security/apparmor/profiles': b'other-profile (enforce)\n',
    }
    reads = []

    def read(path, limit):
        reads.append(path)
        if path.endswith('/loop/backing_file') and not values['loop_active']:
            raise FileNotFoundError
        return values[path]

    monkeypatch.setattr(launcher, '_read', read)
    monkeypatch.setattr(launcher, 'platform', SimpleNamespace(machine=lambda: 'x86_64',
                                                             release=lambda: '6.8.0-139-generic'))
    monkeypatch.setattr(launcher, 'sys', SimpleNamespace(
        platform='linux', version_info=(3, 12, 3), flags=SimpleNamespace(isolated=True, no_site=True),
        dont_write_bytecode=True))
    monkeypatch.setattr(launcher, 'os', SimpleNamespace(
        getuid=lambda: 0, geteuid=lambda: 0, getgid=lambda: 0, getegid=lambda: 0,
        listdir=lambda p: values['blocks'] if p == '/sys/block' else values['interfaces'],
        stat=lambda p: SimpleNamespace(st_mode=stat.S_IFREG | 0o755, st_uid=0, st_gid=0),
        lstat=lambda p: SimpleNamespace(st_mode=stat.S_IFDIR | 0o700, st_uid=0, st_gid=0)))
    return values, reads


def test_unused_loop_is_not_mistaken_for_writable_backing(early_model):
    values, reads = early_model
    launcher._early_checks(context())
    assert '/sys/class/block/loop0/ro' not in reads


def test_configured_writable_loop_refuses(early_model):
    values, reads = early_model
    values['loop_active'] = True
    with pytest.raises(launcher.RecoveryLaunchRefused, match='^writable_block$'):
        launcher._early_checks(context())


def test_configured_readonly_loop_requires_observed_readonly_flag(early_model):
    values, reads = early_model
    values['loop_active'] = True
    values['/sys/class/block/loop0/ro'] = b'1\n'
    launcher._early_checks(context())
    assert '/sys/class/block/loop0/loop/backing_file' in reads
    assert '/sys/class/block/loop0/ro' in reads


def test_empty_backing_attribute_is_not_an_unused_loop(early_model):
    values, reads = early_model
    values['loop_active'] = True
    values['/sys/class/block/loop0/loop/backing_file'] = b'\n'
    with pytest.raises(launcher.RecoveryLaunchRefused, match='^loop_backing$'):
        launcher._early_checks(context())


def test_backing_permission_error_is_not_absence(early_model, monkeypatch):
    original = launcher._read

    def read(path, limit):
        if path.endswith('/loop/backing_file'):
            raise PermissionError('SYNTHETIC_CANARY')
        return original(path, limit)

    monkeypatch.setattr(launcher, '_read', read)
    with pytest.raises(PermissionError):
        launcher._early_checks(context())


@pytest.mark.parametrize('changes,reason', [
    ({'blocks': ['nvme0n1']}, 'target_disk'),
    ({'interfaces': ['eth0', 'lo']}, 'network'),
    ({'/proc/swaps': b'Filename Type Size Used Priority\n/swap file 1 0 -2\n'}, 'swap'),
    ({'/sys/kernel/security/apparmor/profiles': b'night-shift-kvp-public-probe (enforce)\n'}, 'profile_collision'),
    ({'/sys/module/apparmor/parameters/enabled': b'N\n'}, 'apparmor_unavailable'),
    ({'/proc/self/mountinfo': b'1 0 8:1 / /run rw - ext4 /dev/sda1 rw\n'}, 'run_not_ram'),
])
def test_early_checks_stop_for_missing_isolation_not_repair_it(early_model, changes, reason):
    values, reads = early_model
    values.update(changes)
    with pytest.raises(launcher.RecoveryLaunchRefused, match='^' + reason + '$'):
        launcher._early_checks(context())


def test_private_network_uses_fresh_readonly_sysfs_not_old_namespace_bind(monkeypatch):
    commands = []
    raw = b'PINNED_SYNTHETIC_ONLY'
    c = {**context(), 'seed_sha256': hashlib.sha256(raw).hexdigest(),
         'deadline': str(launcher.time.monotonic() + 70)}
    monkeypatch.setattr(launcher, 'sys', SimpleNamespace(platform='linux'))
    monkeypatch.setattr(launcher, '_read', lambda p, n: raw)
    monkeypatch.setattr(launcher, '_policy', lambda b, c: b'SYNTHETIC_POLICY')
    monkeypatch.setattr(launcher, '_new', lambda *a: None)
    monkeypatch.setattr(launcher, '_command', lambda a, c, **k: commands.append(a))
    monkeypatch.setattr(launcher, 'os', SimpleNamespace(
        geteuid=lambda: 0, readlink=lambda p: p, mkdir=lambda *a: None,
        symlink=lambda *a: None, chroot=lambda *a: None, chdir=lambda *a: None))
    launcher.namespace(c)
    assert ['/usr/bin/mount', '-t', 'sysfs', '-o', 'ro,nodev,nosuid,noexec',
            'sysfs', launcher.STAGE + '/root/sys'] in commands
    assert not any(c[:3] == ['/usr/bin/mount', '--bind', '/sys'] for c in commands)
