"""OFFLINE CONTRACT MODEL ONLY: no Linux tools, mounts, policy or daemon.

Drive the real launcher's Python control flow through synthetic native adapters.
Model only the explicitly recorded mount argv; this is NOT Linux mountinfo,
AppArmor parsing/enforcement, chroot visibility or evidence of a successful boot.
The seed/policy parser is substituted here; full-pin tests live in the existing
handoff suite. No synthetic result is accepted by a deployment/runtime API.
"""
from __future__ import annotations

import hashlib
import io
from types import SimpleNamespace

import pytest

from night_shifts.guest import bootstrap_public_probe as probe
from night_shifts.guest import bootstrap_recovery_launcher as launcher

RAW = b'SYNTHETIC_NOT_A_SUPPORT_ARCHIVE'
POLICY = b'SYNTHETIC_NOT_AN_APPARMOR_POLICY'
SOURCE = b'# synthetic, never executed\n'
ROOT = launcher.STAGE + '/root'


def context(*, internal=False):
    value = dict(attempt_id='1' * 32, vm_id='00000000-0000-4000-8000-000000000001',
                 seed_sha256=hashlib.sha256(RAW).hexdigest(),
                 policy_sha256=hashlib.sha256(POLICY).hexdigest())
    if internal:
        value['deadline'] = str(launcher.time.monotonic() + 70)
    return value


def status():
    return ('NoNewPrivs:\t1\n' + ''.join(name + ':\t0000000000000000\n'
            for name in ('CapInh', 'CapPrm', 'CapEff', 'CapBnd', 'CapAmb'))).encode()


def forbidden(*args, **kwargs):
    pytest.fail('native execution/import is forbidden in this offline harness')


@pytest.fixture
def model(monkeypatch):
    state = SimpleNamespace(commands=[], events=[], stdout=io.StringIO())

    def read(path, limit):
        values = {
            launcher.STAGE + '/media/support.zip': RAW,
            launcher.STAGE + '/launcher.py': SOURCE,
            launcher.SEED_PATH: RAW,
            '/sys/class/block/sr1/device/type': b'5\n',
            '/proc/self/status': status(),
            '/proc/self/attr/current': (launcher.PROFILE + ' (enforce)\n').encode(),
        }
        assert path in values and len(values[path]) <= limit
        return values[path]

    def policy(raw, value):
        assert raw == RAW and value['seed_sha256'] == context()['seed_sha256']
        state.events.append(('policy', None))
        return POLICY

    def command(argv, value, **options):
        state.commands.append(list(argv))
        state.events.append(('command', list(argv)))
        assert 0 < float(value['deadline']) - launcher.time.monotonic() <= 70
        assert options == ({'worker': True} if argv[0] in
                           ('/usr/bin/setpriv', '/usr/bin/unshare') else {})

    monkeypatch.setattr(launcher, '_read', read)
    monkeypatch.setattr(launcher, '_policy', policy)
    monkeypatch.setattr(launcher, '_new', lambda path, raw: state.events.append(('write', path)))
    monkeypatch.setattr(launcher, '_command', command)
    monkeypatch.setattr(launcher, '_early_checks', lambda value: state.events.append(('early', None)))
    monkeypatch.setattr(launcher, 'subprocess', SimpleNamespace(run=forbidden))
    monkeypatch.setattr(launcher, 'importlib', SimpleNamespace(import_module=forbidden))
    monkeypatch.setattr(launcher, 'sys', SimpleNamespace(
        platform='linux', flags=SimpleNamespace(isolated=True, no_site=True),
        dont_write_bytecode=True, modules={}, path=[], stdout=state.stdout))
    monkeypatch.setattr(launcher, 'os', SimpleNamespace(
        geteuid=lambda: 0, readlink=lambda path: path,
        umask=lambda value: state.events.append(('umask', value)),
        mkdir=lambda path, mode: state.events.append(('mkdir', path)),
        symlink=lambda target, path: state.events.append(('symlink', path)),
        chroot=lambda path: state.events.append(('chroot', path)),
        chdir=lambda path: state.events.append(('chdir', path)),
        path=SimpleNamespace(realpath=lambda path: '/dev/sr1'),
        stat=lambda path: SimpleNamespace(st_mode=0o060600)))
    return state


def mount_view(commands):
    """Tiny explicit argv model, deliberately NOT a mount or kernel simulator.

    Assume visible mounts beneath the modeled chroot and synthetic bind backing.
    Native tests must independently check both assumptions and actual flags.
    Unknown command shapes fail the test rather than being silently ignored.
    """
    mounts = {}
    backing = {'/usr': 'squashfs', '/etc': 'squashfs', '/proc': 'proc', '/dev': 'devtmpfs'}
    for argv in commands:
        if argv[0] != '/usr/bin/mount':
            assert argv[0] == '/usr/bin/setpriv'
            continue
        target = argv[-1]
        assert target == ROOT or target.startswith(ROOT + '/')
        path = target[len(ROOT):] or '/'
        if argv[1] == '-t':
            assert len(argv) == 7 and argv[3] == '-o' and path not in mounts
            mounts[path] = (argv[2], set(argv[4].split(',')))
        elif argv[1] == '--bind':
            assert len(argv) == 4 and path not in mounts and argv[2] in backing
            mounts[path] = (backing[argv[2]], {'rw'})
        else:
            assert len(argv) == 4 and argv[1] == '-o' and path in mounts
            options = set(argv[2].split(','))
            assert 'remount' in options
            mounts[path] = (mounts[path][0], options - {'remount', 'bind'})
    raw = ''.join(f'{index} 0 0:{index} / {path} {",".join(sorted(options))} - {fs} synthetic ro\n'
                  for index, (path, (fs, options)) in enumerate(sorted(mounts.items()), 1))
    return raw, mounts


def test_recorded_namespace_plan_meets_real_probe_mount_contract(model):
    launcher.namespace(context(internal=True))
    raw, mounts = mount_view(model.commands)
    probe.check_mounts(raw)
    assert set(mounts) == {'/', '/usr', '/etc', '/proc', '/dev', '/sys',
                           '/run/night-shift-bootstrap', '/var/lib/hyperv'}
    assert mounts['/sys'] == ('sysfs', {'ro', 'nodev', 'nosuid', 'noexec'})
    assert 'ro' in mounts['/'][1] and 'noexec' in mounts['/'][1]
    assert 'noexec' not in mounts['/usr'][1]
    assert 'noexec' not in mounts['/run/night-shift-bootstrap'][1]
    assert 'noexec' in mounts['/var/lib/hyperv'][1]
    assert len(model.commands) == 14
    assert [event for event in model.events if event[0] == 'write'] == [
        ('write', ROOT + launcher.SEED_PATH), ('write', ROOT + '/entry.py')]


@pytest.mark.parametrize('change', [
    'root-writable', 'runtime-noexec', 'pool-executable', 'pool-persistent',
    'proc-writable', 'sys-writable', 'extra-writable', 'nested-runtime',
])
def test_contract_rejects_mount_plan_drift(model, change):
    launcher.namespace(context(internal=True))
    commands = [list(argv) for argv in model.commands]
    if change in ('extra-writable', 'nested-runtime'):
        suffix = '/unexpected' if change == 'extra-writable' else '/run/night-shift-bootstrap/nested'
        commands.insert(-1, ['/usr/bin/mount', '-t', 'tmpfs', '-o',
                             'rw,nodev,nosuid,noexec', 'tmpfs', ROOT + suffix])
    else:
        suffix = {'root-writable': '', 'runtime-noexec': '/run/night-shift-bootstrap',
                  'pool-executable': '/var/lib/hyperv', 'pool-persistent': '/var/lib/hyperv',
                  'proc-writable': '/proc', 'sys-writable': '/sys'}[change]
        argv = next(argv for argv in commands if argv[-1] == ROOT + suffix
                    and argv[1] in ('-t', '-o'))
        if change == 'root-writable':
            argv = next(argv for argv in commands if argv[1] == '-o' and argv[-1] == ROOT)
        if change == 'pool-persistent':
            argv[2], argv[5] = 'ext4', '/dev/SYNTHETIC'
        else:
            index = 4 if argv[1] == '-t' else 2
            if change == 'runtime-noexec':
                argv[index] += ',noexec'
            elif change == 'pool-executable':
                argv[index] = argv[index].replace(',noexec', '')
            else:
                argv[index] = argv[index].replace('ro', 'rw')
    with pytest.raises(probe.GuestProbeRefused):
        probe.check_mounts(mount_view(commands)[0])


def test_only_fixed_runtime_binds_and_fresh_sysfs_are_requested(model):
    launcher.namespace(context(internal=True))
    binds = [argv[2] for argv in model.commands if argv[1] == '--bind']
    assert binds == ['/usr', '/etc', '/proc', '/dev']
    assert ['/usr/bin/mount', '-t', 'sysfs', '-o', 'ro,nodev,nosuid,noexec',
            'sysfs', ROOT + '/sys'] in model.commands
    assert all('--rbind' not in argv and '--make-rshared' not in argv for argv in model.commands)


@pytest.mark.parametrize('failure_at', range(1, 15))
def test_each_namespace_command_failure_stops_without_retry_or_later_phase(model, monkeypatch, failure_at):
    original = launcher._command

    def command(argv, value, **options):
        original(argv, value, **options)
        if len(model.commands) == failure_at:
            raise launcher.RecoveryLaunchUnknown('synthetic_native_unknown')

    monkeypatch.setattr(launcher, '_command', command)
    with pytest.raises(launcher.RecoveryLaunchUnknown, match='^synthetic_native_unknown$'):
        launcher.namespace(context(internal=True))
    assert len(model.commands) == failure_at
    assert len({tuple(argv) for argv in model.commands}) == failure_at
    assert any(event[0] == 'chroot' for event in model.events) is (failure_at == 14)
    writes = [event for event in model.events if event[0] == 'write']
    assert len(writes) == (2 if failure_at >= 13 else 0)
    assert model.stdout.getvalue() == ''


@pytest.mark.parametrize('failure_at', range(1, 5))
def test_boot_native_failure_never_adds_or_launches_a_later_phase(model, monkeypatch, failure_at):
    original = launcher._command

    def command(argv, value, **options):
        original(argv, value, **options)
        if len(model.commands) == failure_at:
            raise launcher.RecoveryLaunchUnknown('synthetic_native_unknown')

    monkeypatch.setattr(launcher, '_command', command)
    with pytest.raises(launcher.RecoveryLaunchUnknown, match='^synthetic_native_unknown$'):
        launcher.boot(context(), trusted_source=SOURCE)
    assert len(model.commands) == failure_at
    assert model.events[0] == ('early', None)
    assert [argv[0] for argv in model.commands] == [
        '/usr/bin/mount', '/usr/sbin/apparmor_parser',
        '/usr/sbin/apparmor_parser', '/usr/bin/unshare'][:failure_at]
    if failure_at >= 2:
        assert model.commands[1][1:3] == ['-Q', '-K']
    if failure_at >= 3:
        assert model.commands[2][1:3] == ['-a', '-K']
    assert all('-r' not in argv and '--replace' not in argv for argv in model.commands)
    assert not any(event[0] == 'chroot' for event in model.events)
    assert model.stdout.getvalue() == ''


@pytest.mark.parametrize('field', ['NoNewPrivs', 'CapInh', 'CapPrm', 'CapEff', 'CapBnd', 'CapAmb'])
def test_each_missing_confinement_property_stops_before_transition_or_import(model, monkeypatch, field):
    raw = b'\n'.join(line for line in status().splitlines() if not line.startswith(field.encode() + b':'))
    monkeypatch.setattr(launcher, '_read', lambda *args: raw)
    with pytest.raises(launcher.RecoveryLaunchRefused, match='^capabilities$'):
        launcher.confined(context(internal=True))
    assert model.events == [] and launcher.sys.path == [] and model.stdout.getvalue() == ''


@pytest.mark.parametrize('failure', ['open', 'write', 'short-write', 'readback'])
def test_transition_uncertainty_never_imports_support_code(model, monkeypatch, failure):
    operations = []

    def open_profile(*args):
        operations.append('open')
        if failure == 'open':
            raise PermissionError('SYNTHETIC')
        return 99

    def write_profile(fd, raw):
        operations.append('write')
        if failure == 'write':
            raise PermissionError('SYNTHETIC')
        return len(raw) - 1 if failure == 'short-write' else len(raw)

    monkeypatch.setattr(launcher.os, 'open', open_profile, raising=False)
    monkeypatch.setattr(launcher.os, 'write', write_profile, raising=False)
    monkeypatch.setattr(launcher.os, 'close', lambda fd: operations.append('close'), raising=False)
    for name, value in (('O_WRONLY', 1), ('O_NOFOLLOW', 2), ('O_CLOEXEC', 4)):
        monkeypatch.setattr(launcher.os, name, value, raising=False)
    if failure == 'readback':
        original = launcher._read
        monkeypatch.setattr(launcher, '_read', lambda path, limit:
                            b'unconfined\n' if path == '/proc/self/attr/current' else original(path, limit))
    expected = {'open': PermissionError, 'write': PermissionError,
                'short-write': launcher.RecoveryLaunchUnknown,
                'readback': launcher.RecoveryLaunchRefused}[failure]
    with pytest.raises(expected):
        launcher.confined(context(internal=True))
    assert operations == (['open'] if failure == 'open' else ['open', 'write', 'close'])
    assert launcher.sys.path == [] and model.stdout.getvalue() == ''


def test_real_inspection_bundle_still_excludes_recovery_and_validation_assets():
    import zipfile

    from night_shifts.inspection_bundle import bundle_bytes

    with zipfile.ZipFile(io.BytesIO(bundle_bytes())) as archive:
        names = archive.namelist()
    assert all(not any(part in name for part in (
        'bootstrap_recovery', 'bootstrap_confinement', 'bootstrap_public_probe',
        'bootstrap_probe_seed', 'bootstrap-public-probe.apparmor', 'hv_kvp_daemon')) for name in names)
