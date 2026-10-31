"""OFFLINE ONLY: inert ELF is DATA; every worker native adapter is substituted."""
from __future__ import annotations

import ast
import errno
import hashlib
import io
import json
import stat
import struct
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from night_shifts import bootstrap_native_fixture as fixture
from night_shifts.guest import bootstrap_native_worker as worker
from night_shifts.guest import bootstrap_public_probe as probe

RAW = b'SYNTHETIC_NOT_A_SEED'
VM = '00000000-0000-4000-8000-000000000001'
# Keep only the function reference; its globals/native adapters are still mocked.
_REAL_READ = worker._read


def context(case='runtime_write', mode='confined'):
    return dict(attempt_id='1' * 32, vm_id=VM, seed_sha256=hashlib.sha256(RAW).hexdigest(),
                case_id=case, mode=mode, deadline='104')


def status():
    return ('NoNewPrivs:\t1\n' + ''.join(name + ':\t0000000000000000\n'
            for name in ('CapInh', 'CapPrm', 'CapEff', 'CapBnd', 'CapAmb'))).encode()


def test_inert_fixture_is_exact_pinned_deterministic_data_with_no_elf_loader():
    raw = fixture.inert_fixture_bytes()
    assert raw == fixture.inert_fixture_bytes()
    assert len(raw) == 188 and hashlib.sha256(raw).hexdigest() == fixture.FIXTURE_SHA256
    ident, kind, machine, version, entry, phoff, shoff, flags, ehsize, phsize, phnum, shsize, shnum, shstr = (
        struct.unpack_from('<16sHHIQQQIHHHHHH', raw))
    assert ident == b'\x7fELF\x02\x01\x01' + bytes(9)
    assert (kind, machine, version, flags) == (2, 62, 1, 0)
    assert (ehsize, phoff, phsize, phnum) == (64, 64, 56, 2)
    assert (shoff, shsize, shnum, shstr) == (0, 0, 0, 0)
    load = struct.unpack_from('<IIQQQQQQ', raw, phoff)
    stack = struct.unpack_from('<IIQQQQQQ', raw, phoff + phsize)
    assert load == (1, 5, 0, 0x400000, 0x400000, 188, 188, 4096)
    assert stack == (0x6474e551, 6, 0, 0, 0, 0, 0, 16)
    offset = entry - load[3]
    assert offset == 176
    # Independently decode all three instructions; NEVER execute this fixture.
    code = raw[offset:]
    assert len(code) == 12 and code[0] == 0xb8 and code[5] == 0xbf and code[10:] == b'\x0f\x05'
    assert int.from_bytes(code[1:5], 'little') == 60
    assert int.from_bytes(code[6:10], 'little') == fixture.EXIT_STATUS == 37
    assert worker.FIXTURE_SHA256 == fixture.FIXTURE_SHA256


@pytest.mark.parametrize('offset', [0, 4, 16, 18, 24, 32, 54, 56, 68, 96, 120, 124, 176, 177, 182, 187])
def test_no_modified_header_or_instruction_can_be_accepted(offset):
    raw = bytearray(fixture.inert_fixture_bytes())
    raw[offset] ^= 1
    with pytest.raises(fixture.NativeFixtureRefused, match='^fixture_digest$'):
        fixture.validate_inert_fixture(bytes(raw))


@pytest.mark.parametrize('raw', [b'', b'\x7fELF', bytearray(b'bad'), None, 'not-bytes'])
def test_no_arbitrary_elf_or_nonbytes_fixture(raw):
    with pytest.raises(fixture.NativeFixtureRefused, match='^fixture_digest$'):
        fixture.validate_inert_fixture(raw)


@pytest.fixture
def model(monkeypatch):
    state = SimpleNamespace(events=[], closed=[], clock=100.0, gate=b'G', open_errno=13,
                            namespace_same=False, extra_fd=False, inheritable=False,
                            blocking=False, same_pipe=False, wrong_access=False,
                            stdio_bad=False, dir_bad=False, existing_daemon=False,
                            label=worker.PROFILE, blocks=['loop0', 'sr0'], interfaces=['lo'])
    values = {
        worker.SEED: RAW, '/proc/self/status': status(),
        '/proc/self/mountinfo': (
            '1 0 0:1 / / ro,nodev,nosuid,noexec - tmpfs tmpfs ro\n'
            '2 1 0:2 / /run/night-shift-bootstrap rw,nodev,nosuid - tmpfs tmpfs rw\n'
            '3 1 0:3 / /var/lib/hyperv rw,nodev,nosuid,noexec - tmpfs tmpfs rw\n').encode(),
        '/proc/swaps': b'Filename Type Size Used Priority\n',
        '/sys/class/block/sr0/ro': b'1\n', '/sys/class/net/lo/flags': b'0x8\n',
        '/sys/class/dmi/id/product_uuid': VM.encode(),
        worker._PATHS['outside_exec']: fixture.inert_fixture_bytes(),
        worker._PATHS['runtime_write']: b'V', worker._PATHS['pool_sibling_write']: b'V',
    }
    state.values = values

    def read(path, limit):
        state.events.append(('read', path))
        if path == '/proc/self/attr/current':
            return (state.label + '\n').encode()
        if path.endswith('/loop/backing_file') and path not in values:
            raise FileNotFoundError
        if path.startswith('/proc/self/fdinfo/'):
            access = 1 if path.endswith('/3') else 0
            if state.wrong_access:
                access ^= 1
            return ('pos:\t0\nflags:\t' + oct(40 + access)[2:] + '\nmnt_id:\t1\nino:\t1\n').encode()
        if path in ('/proc/1/comm', '/proc/123/comm'):
            return b'hv_kvp_daemon\n' if state.existing_daemon else b'python\n'
        value = values[path]
        assert len(value) <= limit
        return value

    def listdir(path):
        return {'/sys/block': state.blocks, '/sys/class/net': state.interfaces,
                '/proc': ['1', '123'], '/proc/self/fd': ['0', '1', '2', '3', '4', '9']
                + (['8'] if state.extra_fd else [])}[path]

    def readlink(path):
        if path == '/proc/self/fd/9':
            raise FileNotFoundError
        if '/ns/' in path and state.namespace_same:
            return 'same'
        return path

    def fstat(fd):
        return SimpleNamespace(st_mode=(stat.S_IFCHR if fd < 3 else stat.S_IFIFO),
                               st_rdev=0, st_uid=0, st_gid=0, st_dev=1,
                               st_ino=1 if state.same_pipe else fd)

    def lstat(path):
        executable = path == worker._PATHS['outside_exec']
        is_dir = path in ('/run/night-shift-bootstrap', '/var/lib/hyperv')
        return SimpleNamespace(st_mode=(stat.S_IFDIR | (0o777 if state.dir_bad else 0o755)) if is_dir
                               else stat.S_IFREG | (0o700 if executable else 0o600),
                               st_uid=0, st_gid=0, st_nlink=1, st_size=188 if executable else 1)

    def open_file(path, flags):
        state.events.append(('open', path, flags))
        if state.open_errno is not None:
            raise OSError(state.open_errno, 'SYNTHETIC_CANARY')
        return 99

    def write(fd, raw):
        state.events.append(('write', fd, raw))
        return len(raw)

    def execve(path, argv, env):
        state.events.append(('exec', path, argv, env))
        raise PermissionError(errno.EACCES, 'SYNTHETIC_CANARY')

    state.os = SimpleNamespace(
        O_RDONLY=0, O_WRONLY=1, O_ACCMODE=3, O_CLOEXEC=8, O_NOFOLLOW=16, O_NONBLOCK=32,
        getuid=lambda: 0, geteuid=lambda: 0, getgid=lambda: 0, getegid=lambda: 0,
        getgroups=lambda: [], getpid=lambda: 123, environ={'LANG': 'C', 'LC_ALL': 'C'},
        listdir=listdir, readlink=readlink, lstat=lstat, fstat=fstat,
        major=lambda value: 1, minor=lambda value: 5 if state.stdio_bad else 3,
        get_inheritable=lambda fd: state.inheritable, get_blocking=lambda fd: state.blocking,
        open=open_file, write=write, read=lambda fd, count: state.gate,
        execve=execve, close=lambda fd: state.closed.append(fd))
    monkeypatch.setattr(worker, 'os', state.os)
    monkeypatch.setattr(worker, '_read', read)
    monkeypatch.setattr(worker, 'time', SimpleNamespace(monotonic=lambda: state.clock))
    monkeypatch.setattr(worker, 'platform', SimpleNamespace(machine=lambda: 'x86_64',
                                                          release=lambda: '6.8.0-139-generic'))
    monkeypatch.setattr(worker, 'sys', SimpleNamespace(
        platform='linux', version_info=(3, 12, 3), dont_write_bytecode=True,
        flags=SimpleNamespace(isolated=True, no_site=True), modules={}, path=[]))
    monkeypatch.setattr(worker, 'select', SimpleNamespace(select=lambda r, w, e, timeout: ([4], [], [])))

    def import_module(name):
        state.events.append(('import', name))
        assert name == 'night_shifts.guest.bootstrap_public_probe'
        return SimpleNamespace(check_mounts=probe.check_mounts, check_devices=probe.check_devices)

    monkeypatch.setattr(worker, 'importlib', SimpleNamespace(import_module=import_module))
    return state


def reports(state):
    raw = [event[2] for event in state.events if event[:2] == ('write', 3)]
    assert all(len(item) <= 256 and b'SYNTHETIC_CANARY' not in item for item in raw)
    return [json.loads(item) for item in raw]


@pytest.mark.parametrize('case', ['runtime_write', 'pool_sibling_write', 'outside_exec'])
def test_worker_emits_ready_then_exact_local_errno_without_native_execution(model, case):
    assert worker.run_fixed_case(context(case)) == 0
    ready, result = reports(model)
    assert ready == dict(case_id=case, mode='confined', phase='ready', pid=123)
    assert result == dict(case_id=case, mode='confined', phase='result', pid=123,
                          observation='syscall_error', errno=13)
    assert model.closed == [4, 3]
    assert not any(event[0] == 'read' and event[1] == worker._PATHS[case] for event in model.events)
    assert model.events.index(('read', worker.SEED)) < model.events.index(
        ('import', 'night_shifts.guest.bootstrap_public_probe'))


@pytest.mark.parametrize('case', ['runtime_write', 'pool_sibling_write'])
@pytest.mark.parametrize('mode', ['control', 'confined'])
def test_only_control_writes_one_fixed_ram_byte_and_negative_success_is_not_pass(model, case, mode):
    model.open_errno = None
    model.label = 'unconfined' if mode == 'control' else worker.PROFILE
    assert worker.run_fixed_case(context(case, mode)) == 0
    opened = next(event for event in model.events if event[0] == 'open')
    assert opened == ('open', worker._PATHS[case], 1 | 8 | 16 | 32)
    assert (('write', 99, b'V') in model.events) == (mode == 'control')
    assert reports(model)[1]['observation'] == ('control_written' if mode == 'control' else 'unexpected_open')
    assert model.closed == [99, 4, 3]


@pytest.mark.parametrize('observed_errno', [1, 2, 13, 30, 40])
def test_worker_reports_errno_without_claiming_apparmor_attribution(model, observed_errno):
    model.open_errno = observed_errno
    worker.run_fixed_case(context())
    result = reports(model)[1]
    assert result['errno'] == observed_errno and result['observation'] == 'syscall_error'
    assert not {'success', 'passed', 'host_receipt', 'stopped'} & result.keys()


def test_exec_replaces_same_worker_with_empty_environment_and_fixed_single_argv(model, monkeypatch):
    class Replaced(BaseException):
        pass

    def execve(path, argv, env):
        assert path == worker._PATHS['outside_exec'] and argv == [path] and env == {}
        raise Replaced  # substitute, NEVER invoke native exec

    monkeypatch.setattr(model.os, 'execve', execve)
    with pytest.raises(Replaced):
        worker._operation(context('outside_exec'))
    assert not model.closed


def test_an_impossible_exec_return_is_unknown_not_success(model, monkeypatch):
    monkeypatch.setattr(model.os, 'execve', lambda *a: None)
    with pytest.raises(worker.NativeWorkerUnknown, match='^exec_returned_unknown$'):
        worker.run_fixed_case(context('outside_exec'))
    assert len(reports(model)) == 1 and model.closed == [4, 3]


@pytest.mark.parametrize('gate', [b'', b'X', b'GG', b'G\n'])
def test_missing_wrong_or_extra_start_bytes_never_release_operation(model, gate):
    model.gate = gate
    with pytest.raises(worker.NativeWorkerRefused, match='^gate$'):
        worker.run_fixed_case(context())
    assert not any(event[0] in ('open', 'exec') for event in model.events)
    assert len(reports(model)) == 1 and model.closed == [4, 3]


@pytest.mark.parametrize('change', ['timeout', 'deadline', 'label', 'caps'])
def test_recheck_after_readiness_refuses_expiry_or_changed_security_state(model, monkeypatch, change):
    def select_gate(*args):
        if change == 'deadline':
            model.clock = 105
        elif change == 'label':
            model.label = 'unconfined'
        elif change == 'caps':
            model.values['/proc/self/status'] = status().replace(b'CapEff:\t0', b'CapEff:\t1')
        return ([] if change == 'timeout' else [4], [], [])

    monkeypatch.setattr(worker.select, 'select', select_gate)
    with pytest.raises(worker.NativeWorkerRefused):
        worker.run_fixed_case(context())
    assert not any(event[0] in ('open', 'exec') for event in model.events)
    assert model.closed == [4, 3]


@pytest.mark.parametrize('which', ['ready', 'result', 'control'])
def test_partial_writes_are_unknown_never_retried(model, monkeypatch, which):
    original = model.os.write
    count = []

    def write(fd, raw):
        count.append((fd, raw))
        target = ((which == 'ready' and fd == 3 and b'"phase":"ready"' in raw)
                  or (which == 'result' and fd == 3 and b'"phase":"result"' in raw)
                  or (which == 'control' and fd == 99))
        return 0 if target else original(fd, raw)

    monkeypatch.setattr(model.os, 'write', write)
    model.open_errno = None if which == 'control' else 13
    model.label = 'unconfined' if which == 'control' else worker.PROFILE
    with pytest.raises(worker.NativeWorkerUnknown):
        worker.run_fixed_case(context(mode='control' if which == 'control' else 'confined'))
    assert len(count) == {'ready': 1, 'result': 2, 'control': 2}[which]
    assert model.closed[-2:] == [4, 3]


@pytest.mark.parametrize('change', [
    'label', 'caps', 'nnp', 'seed', 'collision', 'namespace', 'network', 'disk',
    'writable-block', 'empty-backing', 'swap', 'vm', 'directory', 'daemon',
    'extra-fd', 'inheritable', 'blocking', 'same-pipe', 'access', 'stdio', 'environment',
])
def test_prerequisite_refusals_emit_no_ready_and_perform_no_operation(model, change):
    if change == 'label':
        model.label = 'unconfined'
    elif change == 'caps':
        model.values['/proc/self/status'] = status().replace(b'CapAmb:\t0', b'CapAmb:\t1')
    elif change == 'nnp':
        model.values['/proc/self/status'] = status().replace(b'NoNewPrivs:\t1', b'NoNewPrivs:\t0')
    elif change == 'seed':
        model.values[worker.SEED] = b'WRONG'
    elif change == 'collision':
        worker.sys.modules['night_shifts'] = object()
    elif change == 'namespace':
        model.namespace_same = True
    elif change == 'network':
        model.values['/sys/class/net/lo/flags'] = b'0x9'
    elif change == 'disk':
        model.blocks = ['sda']
    elif change == 'writable-block':
        model.values['/sys/class/block/sr0/ro'] = b'0'
    elif change == 'empty-backing':
        model.values['/sys/class/block/loop0/loop/backing_file'] = b'\n'
    elif change == 'swap':
        model.values['/proc/swaps'] += b'/swap file 1 0 -2\n'
    elif change == 'vm':
        model.values['/sys/class/dmi/id/product_uuid'] = b'00000000-0000-4000-8000-000000000002'
    elif change == 'directory':
        model.dir_bad = True
    elif change == 'daemon':
        model.existing_daemon = True
    elif change == 'extra-fd':
        model.extra_fd = True
    elif change == 'inheritable':
        model.inheritable = True
    elif change == 'blocking':
        model.blocking = True
    elif change == 'same-pipe':
        model.same_pipe = True
    elif change == 'access':
        model.wrong_access = True
    elif change == 'stdio':
        model.stdio_bad = True
    elif change == 'environment':
        model.os.environ['PATH'] = '/unexpected'
    with pytest.raises(worker.NativeWorkerRefused):
        worker.run_fixed_case(context())
    assert not reports(model)
    assert not any(event[0] in ('open', 'exec') for event in model.events)
    assert not model.closed


@pytest.mark.parametrize('changes', [
    {'case_id': '/arbitrary'}, {'case_id': 'allowed_pools_extra'},
    {'case_id': 'allowed_pools', 'mode': 'control'}, {'mode': 'anything'},
    {'mode': True}, {'attempt_id': 'UPPER'}, {'vm_id': 'bad'}, {'seed_sha256': 'bad'},
    {'deadline': 'nan'}, {'deadline': 'inf'}, {'deadline': '100'}, {'deadline': '106'},
    {'extra': 'field'},
])
def test_invalid_context_cannot_trigger_preflight_or_any_adapter(model, changes):
    value = {**context(), **changes}
    with pytest.raises(worker.NativeWorkerRefused, match='^context$'):
        worker.run_fixed_case(value)
    assert not model.events


@pytest.mark.parametrize('field', ['attempt_id', 'vm_id', 'seed_sha256', 'case_id', 'mode', 'deadline'])
def test_missing_context_field_cannot_trigger_native_adapters(model, field):
    value = context()
    del value[field]
    with pytest.raises(worker.NativeWorkerRefused, match='^context$'):
        worker.run_fixed_case(value)
    assert not model.events


def test_control_exec_fixture_pin_is_checked_before_ready(model):
    model.label = 'unconfined'
    model.values[worker._PATHS['outside_exec']] = bytes(188)
    with pytest.raises(worker.NativeWorkerRefused, match='^fixture$'):
        worker.run_fixed_case(context('outside_exec', 'control'))
    assert not reports(model) and not model.closed


def test_nonlinux_guard_fails_without_io_even_with_plausible_request(model):
    worker.sys.platform = 'win32'
    with pytest.raises(worker.NativeWorkerRefused, match='^runtime$'):
        worker.run_fixed_case(context())
    assert not model.events


@pytest.mark.parametrize('entry', ['abi', 'read', 'descriptors', 'operation'])
def test_linux_abi_guards_refuse_direct_nonlinux_calls_before_any_io(model, entry):
    worker.sys.platform = 'win32'
    calls = {
        'abi': worker._linux,
        'read': lambda: _REAL_READ('/synthetic', 4),
        'descriptors': worker._descriptors,
        'operation': lambda: worker._operation(context()),
    }
    with pytest.raises(worker.NativeWorkerRefused, match='^linux_required$'):
        calls[entry]()
    assert not model.events and not model.closed


def test_linux_abi_cast_returns_only_the_same_native_os_object(model):
    assert worker._linux() is model.os


@pytest.mark.parametrize('chunks,expected', [
    ([b'ab', b'cd', b''], b'abcd'), ([b'ab', b'cd', b'e'], None),
], ids=['short-reads-complete', 'aggregate-overflow'])
def test_real_read_control_flow_uses_typed_flags_and_closes_without_native_io(model, monkeypatch, chunks, expected):
    opened = []
    requests = []
    pieces = iter(chunks)

    def read(fd, count):
        assert fd == 99
        requests.append(count)
        return next(pieces)

    monkeypatch.setattr(model.os, 'open', lambda path, flags: opened.append((path, flags)) or 99)
    monkeypatch.setattr(model.os, 'read', read)
    if expected is None:
        with pytest.raises(worker.NativeWorkerRefused, match='^input_bound$'):
            _REAL_READ('/synthetic', 4)
    else:
        assert _REAL_READ('/synthetic', 4) == expected
    assert opened == [('/synthetic', 8 | 16 | 32)]
    assert requests == [5, 3, 1] and model.closed == [99]


def test_real_read_descriptor_is_closed_when_substituted_native_read_raises(model, monkeypatch):
    def fail(fd, count):
        raise BlockingIOError('SYNTHETIC_CANARY')

    monkeypatch.setattr(model.os, 'open', lambda *args: 99)
    monkeypatch.setattr(model.os, 'read', fail)
    with pytest.raises(BlockingIOError):
        _REAL_READ('/synthetic', 4)
    assert model.closed == [99]


def test_source_candidates_remain_unwired_and_absent_from_actual_deployment_bundle():
    from night_shifts.bootstrap_probe_seed import ENTRY_NAMES
    from night_shifts.inspection_bundle import bundle_bytes

    names = {'night_shifts/bootstrap_native_fixture.py', 'night_shifts/guest/bootstrap_native_worker.py'}
    assert not names & set(ENTRY_NAMES)
    with zipfile.ZipFile(io.BytesIO(bundle_bytes())) as archive:
        assert not names & set(archive.namelist())
    for module in (fixture, worker):
        tree = ast.parse(Path(module.__file__).read_text(encoding='utf-8'))
        assert not any(isinstance(node, ast.FunctionDef) and node.name in {'main', 'boot'}
                       for node in ast.walk(tree))
        assert not any(isinstance(node, ast.Import) and any(alias.name in {'subprocess', 'socket'}
                       for alias in node.names) for node in ast.walk(tree))
    assert not any(isinstance(node, ast.Name) and node.id in {'open', 'exec', 'eval', 'compile'}
                   for node in ast.walk(ast.parse(Path(fixture.__file__).read_text(encoding='utf-8'))))
