"""Offline guest phase/syscall models only. NEVER mount/load/chroot/exec/spawn.

All native adapters/import providers are replaced before phase calls. Real
archive validation is data-only on an explicitly synthetic public-seed fixture.
No model establishes boot/confinement/kmsg ABI or a cleanup receipt.
"""
from __future__ import annotations

import base64
import errno
import stat
from types import SimpleNamespace

import pytest

from night_shifts import bootstrap_native_handoff as handoff
from night_shifts.guest import bootstrap_native_boot as boot
from night_shifts.guest import bootstrap_public_probe as probe
from night_shifts.maintenance_tls_prototype import AttemptBinding
from tests.night_shifts import test_bootstrap_recovery_handoff as existing

support = existing.support
_REAL_READ, _REAL_NEW, _REAL_COMMAND = boot._read, boot._new, boot._command
_REAL_VALIDATE = boot.validate_inputs
MOUNTS = b''.join((f'{i} 0 0:{i} / {path} {flags} - {fs} source {flags}\n').encode('ascii')
    for i, (path, fs, flags) in enumerate((('/', 'tmpfs', 'ro,nodev,nosuid,noexec'),
        ('/usr', 'squashfs', 'ro,nosuid'), ('/etc', 'squashfs', 'ro,nosuid,noexec'),
        ('/proc', 'proc', 'ro,nosuid,noexec'), ('/dev', 'devtmpfs', 'ro,nosuid,noexec'),
        ('/sys', 'sysfs', 'ro,nodev,nosuid,noexec'),
        ('/run/night-shift-bootstrap', 'tmpfs', 'rw,nodev,nosuid'),
        ('/var/lib/hyperv', 'tmpfs', 'rw,nodev,nosuid,noexec')), 1))


class ExecReplaced(BaseException):
    """Model same-PID exec without running any executable."""


class Model:
    def __init__(self, support, pack):
        self.now, self.private, self.groups, self.present = 100.0, False, [0], False
        self.events, self.summary, self.retained = [], [], []
        self.fail_sequence = self.fail_close = self.bad_source_mode = False
        self.blocks, self.interfaces, self.tasks = ['loop0', 'sr0', 'sr1'], ['lo'], ['111']
        self.context = dict(attempt_id=support[0].attempt_id, vm_id=support[0].vm_id,
                            seed_sha256=pack.seed_sha256, payload_sha256=pack.payload_sha256)
        self.sources = boot.validate_inputs(self.context, support[1], pack.validator_zip)
        self.source, self.pack = self.sources[boot.BOOT_ENTRY], pack
        self.files = {boot.MEDIA + '/support.zip': support[1], boot.MEDIA + '/validator.zip': pack.validator_zip,
            boot.STAGE + '/entry.py': self.source, boot.SEED_PATH: support[1], '/validator.zip': pack.validator_zip,
            '/entry.py': self.source, '/proc/self/attr/current': b'unconfined\n',
            '/sys/class/dmi/id/product_uuid': support[0].vm_id.encode(),
            '/proc/swaps': b'Filename Type Size Used Priority\n', '/sys/class/block/sr0/ro': b'1\n',
            '/sys/class/block/sr1/ro': b'1\n', '/sys/class/block/sr1/device/type': b'5\n',
            '/sys/class/net/lo/flags': b'0x8\n', '/sys/module/apparmor/parameters/enabled': b'Y\n',
            '/proc/1/comm': b'init\n', '/proc/111/comm': b'python\n',
            '/proc/self/mountinfo': b'1 0 0:1 / /run rw - tmpfs source rw\n',
            **{'/validator/' + name: raw for name, raw in self.sources.items()}}
        self.report = boot._json({'kind': 'local_native_sequence_observation', 'scope': 'local_consistency_only',
            'attempt_id': self.context['attempt_id'], 'vm_id': self.context['vm_id'], 'workers_observed': 11,
            'paired_cases': ['runtime_write', 'pool_sibling_write', 'outside_exec'],
            'confined_pool_controls': 2, 'allowed_pool_files': 5})
        self.os = SimpleNamespace(O_RDONLY=0, O_WRONLY=1, O_CREAT=64, O_EXCL=128, O_NOFOLLOW=256,
            O_CLOEXEC=512, O_NONBLOCK=1024, environ={'LANG': 'C', 'LC_ALL': 'C'},
            getuid=lambda: 0, geteuid=lambda: 0, getgid=lambda: 0, getegid=lambda: 0,
            getgroups=lambda: self.groups, getpid=lambda: 111, listdir=self.listdir, readlink=self.readlink,
            lstat=self.lstat, stat=self.stat, path=SimpleNamespace(realpath=lambda p: '/dev/sr1'),
            umask=lambda value: self.events.append(('umask', value)),
            mkdir=lambda path, mode: self.events.append(('mkdir', path, mode)),
            symlink=lambda target, path: self.events.append(('symlink', target, path)),
            chroot=lambda path: self.events.append(('chroot', path)),
            chdir=lambda path: self.events.append(('chdir', path)), execve=self.execve, write=self.write)

    def internal(self):
        return {**self.context, 'deadline': '190.0'}

    def listdir(self, path):
        return {'/proc/self/task': self.tasks, '/sys/block': self.blocks,
                '/sys/class/net': self.interfaces, '/proc': ['1', '111']}[path]

    def readlink(self, path):
        name = path.rsplit('/', 1)[1]
        return name + (':private' if self.private and '/self/' in path and name in ('mnt', 'net') else ':guest')

    def stat(self, path):
        return SimpleNamespace(st_mode=(stat.S_IFBLK | 0o600) if path == '/dev/sr1' else stat.S_IFREG | 0o755,
                               st_uid=0, st_gid=0)

    def lstat(self, path):
        directory = path in ('/run', '/validator', '/validator/night_shifts', '/validator/night_shifts/guest')
        return SimpleNamespace(st_mode=(stat.S_IFDIR | 0o700) if directory else
                               stat.S_IFREG | (0o666 if self.bad_source_mode else 0o400),
                               st_uid=0, st_gid=0, st_nlink=1, st_size=0 if directory else len(self.files[path]))

    def read(self, path, limit, budget):
        budget.check()
        self.events.append(('read', path))
        if path == '/sys/kernel/security/apparmor/profiles':
            return (boot.PROFILE + ' (enforce)\n').encode() if self.present else b'other (enforce)\n'
        if path not in self.files:
            raise FileNotFoundError(errno.ENOENT, 'SYNTHETIC_CANARY')
        raw = self.files[path]
        if len(raw) > limit:
            raise boot.NativeBootRefused('input_bound')
        return raw

    def new(self, path, raw, budget):
        budget.check()
        self.events.append(('new', path))
        assert path.startswith(boot.STAGE + '/')
        self.files[path] = raw

    def command(self, argv, budget, *, phase=False):
        budget.check()
        self.events.append(('command', tuple(argv), phase))
        if argv[:3] == ['/usr/sbin/apparmor_parser', '-a', '-K']:
            self.present = True

    def execve(self, path, argv, env):
        self.events.append(('exec', path, argv, env))
        raise ExecReplaced

    def write(self, fd, raw):
        assert fd == 1
        self.summary.append(raw)
        self.events.append(('summary',))
        return len(raw)

    def import_module(self, name):
        self.events.append(('import', name))
        state = self

        class Fixtures:
            def __init__(self, binding, *, seed_sha256, deadline):
                assert binding == AttemptBinding(state.context['attempt_id'], state.context['vm_id'])
                assert seed_sha256 == state.context['seed_sha256'] and deadline <= state.now + 5
                state.events.append(('fixtures',))

            def close(self):
                state.events.append(('fixture_close',))
                if state.fail_close:
                    raise OSError('SYNTHETIC_CANARY')

        class Sequence:
            def __init__(self, fixtures, *, deadline):
                assert deadline <= min(190, state.now + 60)
                state.events.append(('sequence',))

            def run(self):
                if state.fail_sequence:
                    raise RuntimeError('SYNTHETIC_CANARY')
                return SimpleNamespace(summary_bytes=lambda: state.report)

        def validate(raw, binding, *, expected_sha256):
            state.events.append(('seed_semantics',))
            assert raw == state.pack.support_zip and expected_sha256 == state.context['seed_sha256']

        return {
            'night_shifts.maintenance_tls_prototype': SimpleNamespace(AttemptBinding=AttemptBinding),
            'night_shifts.bootstrap_probe_seed': SimpleNamespace(validate_public_probe_seed=validate),
            'night_shifts.guest.bootstrap_public_probe': SimpleNamespace(check_mounts=probe.check_mounts),
            'night_shifts.bootstrap_native_ram': SimpleNamespace(NativeRamFixtures=Fixtures),
            'night_shifts.bootstrap_native_sequence': SimpleNamespace(NativeValidationSequence=Sequence),
            'night_shifts.bootstrap_native_owner': SimpleNamespace(_RETAINED=state.retained),
        }[name]


@pytest.fixture
def model(support, monkeypatch):
    pack = handoff.render_native_validation_handoff(support[0], support[1], expected_seed_sha256=existing.sha(support[1]))
    state = Model(support, pack)
    monkeypatch.setattr(boot, 'os', state.os)
    monkeypatch.setattr(boot, 'time', SimpleNamespace(monotonic=lambda: state.now))
    monkeypatch.setattr(boot, 'platform', SimpleNamespace(machine=lambda: 'x86_64', release=lambda: '6.8.0-139-generic'))
    monkeypatch.setattr(boot, 'sys', SimpleNamespace(platform='linux', version_info=(3, 12, 3),
        flags=SimpleNamespace(isolated=True, no_site=True), dont_write_bytecode=True, modules={}, path=[], argv=[]))
    monkeypatch.setattr(boot, '_read', state.read)
    monkeypatch.setattr(boot, '_new', state.new)
    monkeypatch.setattr(boot, '_command', state.command)
    monkeypatch.setattr(boot, 'importlib', SimpleNamespace(import_module=state.import_module))

    def validate(context, seed, payload):
        state.events.append(('validated',))
        return _REAL_VALIDATE(context, seed, payload)

    monkeypatch.setattr(boot, 'validate_inputs', validate)
    return state


def supervisor(model):
    model.private, model.present, model.groups = True, True, []
    model.files['/proc/self/mountinfo'] = MOUNTS
    return model.internal()


def test_boot_validates_both_inputs_before_policy_parse_add_and_namespace(model):
    boot.boot(model.context, trusted_source=model.source)
    commands = [event[1] for event in model.events if event[0] == 'command']
    assert len(commands) == 4
    assert commands[0][:4] == ('/usr/bin/mount', '-n', '--internal-only', '-t')
    assert commands[1][:3] == ('/usr/sbin/apparmor_parser', '-Q', '-K')
    assert commands[2][:3] == ('/usr/sbin/apparmor_parser', '-a', '-K')
    assert commands[3][:5] == ('/usr/bin/unshare', '--mount', '--net', '--propagation', 'private')
    assert model.events.index(('validated',)) < next(i for i, e in enumerate(model.events) if e[0] == 'new')
    assert not model.summary and not any(e[0] in ('import', 'fixtures') for e in model.events)


@pytest.mark.parametrize('fault', ['seed', 'payload', 'entry', 'collision', 'disk', 'nic'])
def test_bad_input_or_runtime_never_adds_policy_or_writes_fixture(model, fault):
    source = model.source
    if fault in ('seed', 'payload'):
        model.files[boot.MEDIA + ('/support.zip' if fault == 'seed' else '/validator.zip')] += b'x'
    elif fault == 'entry':
        source += b'\n'
    elif fault == 'collision':
        model.present = True
    elif fault == 'disk':
        model.blocks.append('sda')
    else:
        model.interfaces.append('eth0')
    with pytest.raises(boot.NativeBootRefused):
        boot.boot(model.context, trusted_source=source)
    assert not any(e[0] == 'new' for e in model.events)
    assert not any(e[0] == 'command' and e[1][0] == '/usr/sbin/apparmor_parser' for e in model.events)
    assert not model.summary


def test_namespace_uses_fixed_sealed_layout_and_same_pid_exec_not_worker_cap_drop(model):
    model.private, model.present = True, True
    with pytest.raises(ExecReplaced):
        boot.namespace(model.internal())
    commands = [e[1] for e in model.events if e[0] == 'command']
    assert len(commands) == 13 and all(argv[:3] == ('/usr/bin/mount', '-n', '--internal-only') for argv in commands)
    assert commands[-1][-3:] == ('-o', 'remount,ro,nodev,nosuid,noexec', boot.ROOT)
    assert ('chroot', boot.ROOT) in model.events
    event = next(e for e in model.events if e[0] == 'exec')
    assert event[1] == '/usr/bin/setpriv' and event[3] == {'LANG': 'C', 'LC_ALL': 'C'}
    assert event[2][1:5] == ['--reuid=0', '--regid=0', '--clear-groups', '--']
    assert '--bounding-set=-all' not in event[2]
    assert event[2][5:11] == ['/usr/bin/python3.12', '-I', '-B', '-S', '/entry.py', '--supervise']
    assert not any(e[0] == 'import' for e in model.events)


def test_sealed_sources_and_semantic_seed_check_precede_fixture_sequence_and_output(model):
    boot.supervise(supervisor(model))
    names = [e[0] for e in model.events]
    assert names.index('validated') < names.index('import') < names.index('seed_semantics') < names.index('fixtures')
    assert names.index('fixtures') < names.index('sequence') < names.index('fixture_close') < names.index('summary')
    assert model.summary == [model.report] and len(model.report) <= 512 and boot.sys.path == ['/validator']


@pytest.mark.parametrize('fault', ['root-rw', 'source', 'mode', 'collision', 'groups', 'pid-view'])
def test_supervisor_refuses_before_import_when_seal_or_identity_wrong(model, fault):
    ctx = supervisor(model)
    if fault == 'root-rw':
        model.files['/proc/self/mountinfo'] = MOUNTS.replace(b'/ / ro,', b'/ / rw,', 1)
    elif fault == 'source':
        path = '/validator/' + boot.BOOT_ENTRY
        model.files[path] = b'X' + model.files[path][1:]
    elif fault == 'mode':
        model.bad_source_mode = True
    elif fault == 'collision':
        boot.sys.modules['night_shifts'] = object()
    elif fault == 'groups':
        model.groups = [0]
    else:
        model.os.readlink = lambda path: path
    with pytest.raises(boot.NativeBootRefused):
        boot.supervise(ctx)
    assert not any(e[0] in ('import', 'fixtures', 'summary') for e in model.events)


@pytest.mark.parametrize('fault', ['sequence', 'close', 'retained', 'report'])
def test_no_summary_on_uncertain_sequence_child_or_fixture_cleanup(model, fault):
    ctx = supervisor(model)
    if fault == 'sequence':
        model.fail_sequence = True
    elif fault == 'close':
        model.fail_close = True
    elif fault == 'retained':
        model.retained.append(object())
    else:
        model.report = b'UNBOUNDED_OR_WRONG_SYNTHETIC_CANARY'
    with pytest.raises(boot.NativeBootRefused) as error:
        boot.supervise(ctx)
    assert 'SYNTHETIC_CANARY' not in str(error.value)
    assert ('fixture_close',) in model.events and not model.summary


@pytest.mark.parametrize('change', [dict(attempt_id='X' * 32), dict(vm_id='bad'), dict(seed_sha256='x'),
                                    dict(payload_sha256=True), dict(extra='forbidden'), dict(vm_id='x' * 129)])
def test_context_never_invokes_native_adapters(model, change):
    with pytest.raises(boot.NativeBootRefused, match='^context$'):
        boot.boot({**model.context, **change}, trusted_source=model.source)
    assert not model.events


@pytest.mark.parametrize('fault', ['expiry', 'regression'])
def test_original_deadline_guard_is_terminal_without_renewal(model, fault):
    budget = boot._Budget('190')
    model.now = 190 if fault == 'expiry' else 99
    with pytest.raises(boot.NativeBootUnknown, match='^deadline_unknown$'):
        budget.check()


@pytest.mark.parametrize('parts,limit,ok', [([b'ab', b'cd', b''], 4, True), ([b'ab', b'c'], 2, False)])
def test_bounded_read_and_close_once(model, parts, limit, ok):
    requests, closed = [], []
    chunks = iter(parts)
    model.os.open = lambda path, flags: 71
    model.os.read = lambda fd, count: requests.append(count) or next(chunks)
    model.os.close = lambda fd: closed.append(fd)
    if ok:
        assert _REAL_READ('/synthetic', limit, boot._Budget('190')) == b'abcd'
    else:
        with pytest.raises(boot.NativeBootRefused, match='^input_bound$'):
            _REAL_READ('/synthetic', limit, boot._Budget('190'))
    assert closed == [71]


def test_create_new_partial_write_close_unknown_is_never_retried(model):
    writes, closed = [], []
    model.os.open = lambda path, flags, mode: 71
    model.os.write = lambda fd, raw: writes.append(raw) or 1

    def close(fd):
        closed.append(fd)
        raise OSError(errno.EINTR, 'SYNTHETIC_CANARY')

    model.os.close = close
    with pytest.raises(boot.NativeBootUnknown, match='^descriptor_cleanup_unknown$'):
        _REAL_NEW('/synthetic', b'ab', boot._Budget('190'))
    assert writes == [b'ab'] and closed == [71]


@pytest.mark.parametrize('phase', [False, True])
def test_tool_adapter_has_no_shell_path_or_raw_streams_and_bounded_timeout(model, monkeypatch, phase):
    calls = []
    monkeypatch.setattr(boot, 'subprocess', SimpleNamespace(DEVNULL=-3,
        run=lambda argv, **kw: calls.append((argv, kw)) or SimpleNamespace(returncode=0)))
    argv = ['/usr/bin/mount', '-n', '--internal-only']
    _REAL_COMMAND(argv, boot._Budget('190'), phase=phase)
    assert calls == [(argv, dict(shell=False, stdin=-3, stdout=None if phase else -3, stderr=-3,
        env={'LANG': 'C', 'LC_ALL': 'C'}, cwd='/', close_fds=True, timeout=90 if phase else 3))]


@pytest.mark.parametrize('token', ['not-base64', base64.b64encode(b'{"attempt_id":"x","attempt_id":"x"}').decode()])
def test_internal_phase_failures_emit_only_fixed_unknown(model, token):
    boot.sys.argv = ['/entry.py', '--namespace', token]
    assert boot.main() == 125 and model.summary == [boot._UNKNOWN]
    assert not any(e[0] in ('command', 'mkdir', 'fixtures') for e in model.events)


def test_mount_model_is_accepted_by_both_boot_and_real_probe_checkers():
    boot._sealed_view(MOUNTS)
    probe.check_mounts(MOUNTS.decode('ascii'))
