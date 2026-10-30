"""Offline models only; never spawn, transition, execute a wrapper or run worker.

All child native adapters and worker evaluation are substituted. Embedded source
is parsed/compiled as data. Passing models is not native capability/LSM evidence.
"""
from __future__ import annotations

import ast
import base64
import errno
import hashlib
import io
import json
import stat
import zipfile
from dataclasses import FrozenInstanceError, dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from night_shifts import bootstrap_native_child_plan as plans
from night_shifts.guest import bootstrap_native_child as child
from night_shifts.guest import bootstrap_native_worker as worker
from night_shifts.maintenance_tls_prototype import AttemptBinding

BINDING = AttemptBinding('1' * 32, '00000000-0000-4000-8000-000000000001')
WORKER = Path(worker.__file__).read_text(encoding='utf-8').encode('utf-8')
_REAL_READ = child._read


def status():
    return ('NoNewPrivs:\t1\n' + ''.join(name + ':\t0000000000000000\n' for name in child._CAPS)).encode()


def context(report=10, gate=11, **changes):
    value = dict(attempt_id=BINDING.attempt_id, vm_id=BINDING.vm_id, seed_sha256='a' * 64,
                 deadline='105.0', case_id='runtime_write', mode='confined', report_fd=report, gate_fd=gate)
    value.update(changes)
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode('ascii')


@dataclass
class Descriptor:
    node: SimpleNamespace
    flags: int
    inheritable: bool = True
    position: int = 0


class Model:
    def __init__(self, report=10, gate=11):
        self.report, self.gate, self.now = report, gate, 100.0
        self.events, self.closed, self.evaluated = [], [], []
        self.status, self.label = status(), 'unconfined'
        self.after_status = self.bad_readback = None
        self.short_write = self.write_error = self.open_error = self.dup_error = False
        self.close_errors, self.threads, self.extra_names = set(), ['123'], []
        null = SimpleNamespace(st_mode=stat.S_IFCHR | 0o666, st_rdev=3, st_uid=0, st_gid=0, st_dev=1, st_ino=3)
        self.fds = {fd: Descriptor(null, int(fd != 0)) for fd in (0, 1, 2)}
        for fd, ino, access in ((report, 100, 1), (gate, 200, 0)):
            node = SimpleNamespace(st_mode=stat.S_IFIFO | 0o600, st_rdev=0,
                                   st_uid=0, st_gid=0, st_dev=1, st_ino=ino)
            self.fds[fd] = Descriptor(node, access | 32)
        node = SimpleNamespace(st_mode=stat.S_IFREG | 0o400, st_rdev=0, st_uid=0, st_gid=0, st_dev=9, st_ino=900)
        self.fds[21] = Descriptor(node, 0)
        self.os = SimpleNamespace(
            O_RDONLY=0, O_WRONLY=1, O_ACCMODE=3, O_NONBLOCK=32, O_CLOEXEC=64, O_NOFOLLOW=128,
            getuid=lambda: 0, geteuid=lambda: 0, getgid=lambda: 0, getegid=lambda: 0,
            getgroups=lambda: [], getpid=lambda: 123, environ={'LANG': 'C', 'LC_ALL': 'C'},
            fstat=lambda fd: self.fds[fd].node, major=lambda dev: 1 if dev == 3 else 0, minor=lambda dev: dev,
            get_inheritable=lambda fd: self.fds[fd].inheritable,
            get_blocking=lambda fd: not bool(self.fds[fd].flags & 32),
            listdir=self.listdir, readlink=self.readlink, open=self.open,
            read=self.read, write=self.write, close=self.close, dup2=self.dup2)
        self.control = SimpleNamespace(F_GETFL=1, F_DUPFD_CLOEXEC=2, fcntl=self.fcntl)

    def unused(self, minimum=5):
        fd = minimum
        while fd in self.fds:
            fd += 1
        return fd

    def listdir(self, path):
        if path == '/proc/self/task':
            return self.threads
        assert path == '/proc/self/fd'
        return [str(fd) for fd in sorted(self.fds)] + self.extra_names

    def readlink(self, path):
        fd = int(path.rsplit('/', 1)[1])
        if fd not in self.fds:
            raise FileNotFoundError
        return 'pipe:[' + str(self.fds[fd].node.st_ino) + ']'

    def read_system(self, path, limit, deadline):
        deadline.check()
        self.events.append(('read', path))
        value = self.status if path == '/proc/self/status' else (self.label + '\n').encode()
        assert path in ('/proc/self/status', '/proc/self/attr/current') and len(value) <= limit
        return value

    def fcntl(self, fd, command, arg=0):
        if command == 1:
            return self.fds[fd].flags
        assert command == 2 and arg == 5
        target, source = self.unused(arg), self.fds[fd]
        self.fds[target] = Descriptor(source.node, source.flags, False)
        self.events.append(('stage', fd, target))
        return target

    def dup2(self, source, target, *, inheritable=True):
        self.events.append(('dup2', source, target, inheritable))
        if self.dup_error:
            raise OSError(errno.EBADF, 'CANARY_NATIVE_ERROR')
        item = self.fds[source]
        self.fds[target] = Descriptor(item.node, item.flags, inheritable)

    def close(self, fd):
        self.closed.append(fd)
        self.events.append(('close', fd))
        self.fds.pop(fd)
        if fd in self.close_errors:
            raise OSError(errno.EINTR, 'CANARY_NATIVE_ERROR')

    def open(self, path, flags):
        self.events.append(('open', path, flags))
        if flags & 1 and self.open_error:
            raise OSError(errno.EACCES, 'CANARY_NATIVE_ERROR')
        fd = self.unused()
        self.fds[fd] = Descriptor(SimpleNamespace(st_mode=stat.S_IFREG | 0o600), flags, False)
        return fd

    def read(self, fd, count):
        item = self.fds[fd]
        part = self.status[item.position:item.position + count]
        item.position += len(part)
        return part

    def write(self, fd, raw):
        self.events.append(('write', fd, raw))
        assert raw == b'changeprofile night-shift-kvp-public-probe'
        if self.write_error:
            raise OSError(errno.EACCES, 'CANARY_NATIVE_ERROR')
        if not self.short_write:
            self.label = self.bad_readback or child.PROFILE + ' (enforce)'
            if self.after_status is not None:
                self.status = self.after_status
        return len(raw) - int(self.short_write)

    def evaluate(self, source, value):
        assert source == WORKER and set(self.fds) == {0, 1, 2, 3, 4}
        assert self.status == status()
        assert self.label == (child.PROFILE + ' (enforce)' if value['mode'] == 'confined' else 'unconfined')
        assert self.fds[3].node.st_ino == 100 and self.fds[4].node.st_ino == 200
        assert not self.fds[3].inheritable and not self.fds[4].inheritable
        assert set(value) == worker._FIELDS and value['deadline'] == '105.0'
        self.events.append(('evaluate',))
        self.evaluated.append(value)
        return 0


def install(monkeypatch, state):
    monkeypatch.setattr(child, 'os', state.os)
    monkeypatch.setattr(child, '_fcntl', lambda: state.control)
    monkeypatch.setattr(child, '_read', state.read_system)
    monkeypatch.setattr(child, '_evaluate', state.evaluate)
    monkeypatch.setattr(child, 'time', SimpleNamespace(monotonic=lambda: state.now))
    monkeypatch.setattr(child, 'platform', SimpleNamespace(machine=lambda: 'x86_64', release=lambda: '6.8.0-139-generic'))
    monkeypatch.setattr(child, 'sys', SimpleNamespace(platform='linux', version_info=(3, 12, 3),
                        flags=SimpleNamespace(isolated=True, no_site=True), dont_write_bytecode=True, modules={}))
    return state


@pytest.fixture
def model(monkeypatch):
    return install(monkeypatch, Model())


@pytest.mark.parametrize('report,gate', [(10, 11), (3, 4), (4, 3), (3, 10), (10, 4), (5, 6)])
@pytest.mark.parametrize('mode', ['control', 'confined'])
def test_alias_safe_mapping_closes_all_privileged_fds_before_worker_evaluation(monkeypatch, report, gate, mode):
    state = install(monkeypatch, Model(report, gate))
    assert child.enter(context(report, gate, mode=mode), WORKER) == 0
    assert len(state.evaluated) == 1 and state.events[-1] == ('evaluate',)
    stages = [i for i, event in enumerate(state.events) if event[0] == 'stage']
    duplicates = [i for i, event in enumerate(state.events) if event[0] == 'dup2']
    assert len(stages) == len(duplicates) == 2 and max(stages) < min(duplicates)
    assert len([event for event in state.events if event[0] == 'write']) == int(mode == 'confined')
    # A later fresh open of attr/current may legitimately reuse a closed number.
    mapping_closed = state.closed[:-1] if mode == 'confined' else state.closed
    assert 21 in mapping_closed and len(mapping_closed) == len(set(mapping_closed))
    assert all(not event[3] for event in state.events if event[0] == 'dup2')


@pytest.mark.parametrize('field', ['NoNewPrivs', *child._CAPS])
@pytest.mark.parametrize('fault', ['missing', 'nonzero', 'duplicate'])
def test_each_capability_and_nnp_precondition_stops_before_mapping(model, field, fault):
    lines = model.status.splitlines()
    target = next(line for line in lines if line.startswith(field.encode() + b':'))
    if fault == 'missing':
        lines.remove(target)
    elif fault == 'duplicate':
        lines.append(target)
    else:
        lines[lines.index(target)] = field.encode() + (b':\t0' if field == 'NoNewPrivs' else b':\t0000000000000001')
    model.status = b'\n'.join(lines) + b'\n'
    with pytest.raises(child.NativeChildRefused, match='^capabilities$'):
        child.enter(context(), WORKER)
    assert not model.closed and not model.evaluated
    assert not any(event[0] in ('stage', 'dup2', 'write') for event in model.events)


@pytest.mark.parametrize('fault', ['open', 'write', 'short', 'readback', 'post-caps', 'close'])
def test_uncertain_transition_never_evaluates_worker_or_retries(model, fault):
    model.open_error, model.write_error, model.short_write = fault == 'open', fault == 'write', fault == 'short'
    model.bad_readback = child.PROFILE + ' (complain)' if fault == 'readback' else None
    if fault == 'post-caps':
        model.after_status = status().replace(b'CapEff:\t0000000000000000', b'CapEff:\t0000000000000001')
    if fault == 'close':
        original = model.write
        def write_and_fail_close(fd, raw):
            model.close_errors.add(fd)
            return original(fd, raw)
        model.os.write = write_and_fail_close
    with pytest.raises(child.NativeChildRefused) as error:
        child.enter(context(), WORKER)
    assert 'CANARY' not in str(error.value) and not model.evaluated
    assert len([event for event in model.events if event[0] == 'write']) <= 1
    mapping_closed = model.closed if fault == 'open' else model.closed[:-1]
    assert len(mapping_closed) == len(set(mapping_closed))


@pytest.mark.parametrize('fault', ['same-pipe', 'regular', 'owner', 'mode', 'blocking', 'wrong-access', 'stdio'])
def test_pipe_identity_direction_and_stdio_are_checked_before_mapping(model, fault):
    item = model.fds[10]
    if fault == 'same-pipe':
        model.fds[11].node = item.node
    elif fault == 'regular':
        item.node.st_mode = stat.S_IFREG | 0o600
    elif fault == 'owner':
        item.node.st_uid = 1
    elif fault == 'mode':
        item.node.st_mode = stat.S_IFIFO | 0o666
    elif fault == 'blocking':
        item.flags &= ~32
    elif fault == 'wrong-access':
        item.flags = 32
    else:
        model.fds[0].node.st_rdev = 4
    with pytest.raises(child.NativeChildRefused):
        child.enter(context(), WORKER)
    assert not model.evaluated and not any(event[0] in ('stage', 'write') for event in model.events)


def test_uncertain_extra_close_attempts_all_other_fds_once_then_stops(model):
    model.close_errors.add(21)
    with pytest.raises(child.NativeChildUnknown, match='^descriptor_cleanup_unknown$'):
        child.enter(context(), WORKER)
    assert set(model.fds) == {0, 1, 2, 3, 4}
    assert len(model.closed) == len(set(model.closed)) and 21 in model.closed
    assert not model.evaluated


def test_duplication_failure_never_transitions_or_evaluates(model):
    model.dup_error = True
    with pytest.raises(child.NativeChildUnknown, match='^child_entry_unknown$'):
        child.enter(context(), WORKER)
    assert not model.evaluated and not any(event[0] == 'write' for event in model.events)


@pytest.mark.parametrize('names', [['999'], ['bad'], ['01'], ['1048576'], ['0'] * 8193],
                         ids=['transient-listdir', 'nondecimal', 'alias-name', 'fd-bound', 'inventory-bound'])
def test_fd_inventory_is_strict_except_vanished_listdir_descriptor(model, names):
    model.extra_names = names
    if names == ['999']:
        assert child.enter(context(), WORKER) == 0
    else:
        with pytest.raises(child.NativeChildRefused):
            child.enter(context(), WORKER)
        assert not model.evaluated


@pytest.mark.parametrize('fault', ['platform', 'kernel', 'python', 'isolated', 'site', 'bytecode', 'root',
                                  'groups', 'environment', 'thread', 'label', 'import'])
def test_runtime_refusals_precede_fd_mapping(model, fault):
    if fault == 'platform':
        child.sys.platform = 'win32'
    elif fault == 'kernel':
        child.platform.release = lambda: 'other'
    elif fault == 'python':
        child.sys.version_info = (3, 13)
    elif fault == 'isolated':
        child.sys.flags.isolated = False
    elif fault == 'site':
        child.sys.flags.no_site = False
    elif fault == 'bytecode':
        child.sys.dont_write_bytecode = False
    elif fault == 'root':
        model.os.getuid = lambda: 1
    elif fault == 'groups':
        model.os.getgroups = lambda: [1]
    elif fault == 'environment':
        model.os.environ['PATH'] = '/bin'
    elif fault == 'thread':
        model.threads.append('124')
    elif fault == 'label':
        model.label = child.PROFILE + ' (enforce)'
    else:
        child.sys.modules['night_shifts'] = object()
    with pytest.raises(child.NativeChildRefused):
        child.enter(context(), WORKER)
    assert not model.evaluated and not any(event[0] in ('stage', 'dup2', 'write') for event in model.events)


@pytest.mark.parametrize('raw', [b'', b'x' * 4097, b'[]', b'{"mode":NaN}', b'{"mode":"x","mode":"y"}', b'\xff'])
def test_context_is_bounded_ascii_unique_json_before_native_work(model, raw):
    with pytest.raises(child.NativeChildRefused, match='^context$'):
        child.enter(raw, WORKER)
    assert not model.events


@pytest.mark.parametrize('change', [dict(report_fd=True), dict(gate_fd=2), dict(report_fd=11),
                                    dict(report_fd=1 << 20), dict(case_id='arbitrary'), dict(mode='other'),
                                    dict(attempt_id='X' * 32), dict(seed_sha256='x'), dict(vm_id='not-a-vm'),
                                    dict(extra='forbidden'), dict(deadline='nan'), dict(deadline='106')])
def test_context_cannot_select_commands_or_paths(model, change):
    with pytest.raises(child.NativeChildRefused):
        child.enter(context(**change), WORKER)
    assert not model.events and not model.evaluated


@pytest.mark.parametrize('source', [b'', b'print("arbitrary")', bytearray(WORKER), WORKER + b'\n'],
                         ids=['empty', 'arbitrary', 'bytearray', 'changed-snapshot'])
def test_caller_selected_source_is_never_evaluated(model, source):
    with pytest.raises(child.NativeChildRefused, match='^worker_digest$'):
        child.enter(context(), source)
    assert not model.events and not model.evaluated


@pytest.mark.parametrize('fault', ['expiry', 'regression'])
def test_mapping_does_not_renew_original_deadline(model, fault):
    original = model.dup2
    def duplicate(source, target, *, inheritable=True):
        original(source, target, inheritable=inheritable)
        model.now = 105.0 if fault == 'expiry' else 99.0
    model.os.dup2 = duplicate
    with pytest.raises(child.NativeChildUnknown, match='^deadline_unknown$'):
        child.enter(context(), WORKER)
    assert not model.evaluated and not any(event[0] == 'write' for event in model.events)


@pytest.mark.parametrize('overflow,close_error', [(False, False), (True, False), (False, True)])
def test_bounded_reader_control_flow_closes_exact_fd_without_retry(model, overflow, close_error):
    limit = 2 if overflow else len(model.status)
    if close_error:
        model.close_errors.add(5)
    if overflow or close_error:
        with pytest.raises(child.NativeChildRefused):
            _REAL_READ('/proc/self/status', limit, child._Deadline('105'))
    else:
        assert _REAL_READ('/proc/self/status', limit, child._Deadline('105')) == model.status
    assert model.closed == [5]


def plan(monkeypatch, **changes):
    monkeypatch.setattr(plans, 'time', SimpleNamespace(monotonic=lambda: 100.0))
    values = dict(binding=BINDING, case_id='runtime_write', mode='confined', seed_sha256='a' * 64,
                  deadline=105.0, report_fd=10, gate_fd=11)
    values.update(changes)
    return plans.render_native_child_plan(**values)


def test_plan_has_fixed_capability_drop_fresh_interpreter_and_exact_passfds(monkeypatch):
    rendered = plan(monkeypatch)
    assert rendered.argv[:-1] == (
        '/usr/bin/setpriv', '--bounding-set=-all', '--inh-caps=-all', '--ambient-caps=-all',
        '--no-new-privs', '--reuid=0', '--regid=0', '--clear-groups', '--',
        '/usr/bin/python3.12', '-I', '-B', '-S', '-c')
    assert rendered.pass_fds == (10, 11) and rendered.cwd == '/'
    assert dict(rendered.environment) == {'LANG': 'C', 'LC_ALL': 'C'}
    assert len(rendered.argv[-1].encode('ascii')) <= plans.MAX_COMMAND_BYTES
    tree = ast.parse(rendered.argv[-1], feature_version=(3, 12))
    compile(rendered.argv[-1], '<plan-data-only>', 'exec', dont_inherit=True)
    blobs = [base64.b64decode(node.args[0].value, validate=True) for node in ast.walk(tree)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
             and node.func.attr == 'b64decode' and isinstance(node.args[0], ast.Constant)]
    assert WORKER in blobs and plans._source('bootstrap_native_child.py') in blobs
    raw = next(blob for blob in blobs if blob.startswith(b'{'))
    decoded, report, gate = child._context(raw)
    assert decoded['deadline'] == '105.0' and (report, gate) == (10, 11)
    exits = [node.args[0].value for node in ast.walk(tree) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute) and node.func.attr == '_exit']
    assert set(exits) == {0, 125}
    assert 'subprocess' not in rendered.argv[-1] and 'print(' not in rendered.argv[-1]
    with pytest.raises(FrozenInstanceError):
        rendered.cwd = '/other'


@pytest.mark.parametrize('change', [dict(binding={}), dict(case_id='shell'), dict(mode='other'),
                                    dict(seed_sha256='X' * 64), dict(deadline=True), dict(deadline=float('inf')),
                                    dict(deadline=106), dict(deadline=100), dict(report_fd=True),
                                    dict(gate_fd=2), dict(report_fd=11), dict(report_fd=1 << 20)])
def test_renderer_rejects_unfixed_inputs(monkeypatch, change):
    with pytest.raises(plans.NativeChildPlanRefused):
        plan(monkeypatch, **change)


def test_renderer_refuses_worker_snapshot_drift(monkeypatch):
    source = plans._source
    monkeypatch.setattr(plans, '_source', lambda name: WORKER + b'\n' if name == 'bootstrap_native_worker.py' else source(name))
    with pytest.raises(plans.NativeChildPlanRefused, match='^worker_digest$'):
        plan(monkeypatch)


def test_renderer_bounds_command(monkeypatch):
    monkeypatch.setattr(plans, 'MAX_COMMAND_BYTES', 1)
    with pytest.raises(plans.NativeChildPlanRefused, match='^command_bound$'):
        plan(monkeypatch)


def test_renderer_checks_original_deadline_again_after_snapshotting(monkeypatch):
    times = iter([100.0, 105.0])
    monkeypatch.setattr(plans, 'time', SimpleNamespace(monotonic=lambda: next(times)))
    with pytest.raises(plans.NativeChildPlanRefused, match='^deadline$'):
        plans.render_native_child_plan(BINDING, 'runtime_write', 'confined', seed_sha256='a' * 64,
                                       deadline=105, report_fd=10, gate_fd=11)


def test_worker_pin_stdlib_only_entry_and_actual_deployment_exclusions():
    from night_shifts.bootstrap_probe_seed import SOURCE_FILES
    from night_shifts.inspection_bundle import bundle_bytes
    assert hashlib.sha256(WORKER).hexdigest() == child.WORKER_SHA256
    source = plans._source('bootstrap_native_child.py').decode('utf-8')
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            assert all(not item.name.startswith('night_shifts') for item in node.names)
        if isinstance(node, ast.ImportFrom):
            assert not (node.module or '').startswith('night_shifts')
    names = ('guest/bootstrap_native_child.py', 'bootstrap_native_child_plan.py')
    assert not set(names) & set(SOURCE_FILES)
    with zipfile.ZipFile(io.BytesIO(bundle_bytes())) as archive:
        assert not {'night_shifts/' + name for name in names} & set(archive.namelist())
