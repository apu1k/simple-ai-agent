"""Offline owner models ONLY: no process, signal, native pipe/wait or worker.

All OS/process/poll/runtime readers are replaced before construction. Real launch
rendering and report evaluation are exercised, but generated source is data only.
These are not native pidfd, setpriv, AppArmor, cleanup or VM observations.
"""
from __future__ import annotations

import ast
import base64
import errno
import io
import json
import stat
import zipfile
from types import SimpleNamespace

import pytest

from night_shifts import bootstrap_native_child_plan as plans
from night_shifts import bootstrap_native_owner as owner
from night_shifts.maintenance_tls_prototype import AttemptBinding

BINDING = AttemptBinding('1' * 32, '00000000-0000-4000-8000-000000000001')
_REAL_SYSTEM, _REAL_PAUSE = owner._system, owner._pause


def frame(case='runtime_write', mode='confined', phase='ready', **extra):
    return (json.dumps(dict(case_id=case, mode=mode, phase=phase, pid=123, **extra),
                       separators=(',', ':')) + '\n').encode('ascii')


class Model:
    def __init__(self):
        self.now, self.cancelled = 100.0, False
        self.events, self.closed, self.reports, self.fds = [], [], [], {}
        self.pipe_calls, self.pipe_error_at, self.fragment = 0, None, 512
        self.close_errors, self.inheritable, self.blocking = set(), set(), set()
        self.bad_pipe, self.bad_pidfd, self.pidfd_error = {}, False, False
        self.spawn_error = self.signal_error = self.wait_error = self.poll_error = False
        self.gate_error, self.gate_count = None, 1
        self.exit, self.reap_result, self.exit_status, self.exit_code = None, None, None, 1
        self.kill_stalls, self.auto_finish, self.eof = False, True, True
        self.result_override, self.exit_waits = {}, 0
        self.sig_handler, self.tasks, self.status = 0, ['111'], b''.join(
            name + b'\t0000000000000000\n' for name in (b'SigIgn:', b'SigCgt:', b'SigBlk:'))
        self.children, self.label = b'', b'unconfined\n'
        self.os = SimpleNamespace(
            O_RDONLY=0, O_CLOEXEC=64, O_NONBLOCK=128, O_NOFOLLOW=256,
            P_PIDFD=3, P_PID=1, WEXITED=4, WNOHANG=8, WNOWAIT=16,
            CLD_EXITED=1, CLD_KILLED=2, CLD_DUMPED=3,
            getuid=lambda: 0, geteuid=lambda: 0, getgid=lambda: 0, getegid=lambda: 0,
            getgroups=lambda: [], environ={'LANG': 'C', 'LC_ALL': 'C'},
            getpid=lambda: 111, listdir=lambda path: self.tasks,
            get_inheritable=lambda fd: fd in self.inheritable,
            get_blocking=lambda fd: fd in self.blocking,
            fstat=lambda fd: self.fds[fd], pipe2=self.pipe2, pidfd_open=self.pidfd_open,
            read=self.read, write=self.write, close=self.close, waitid=self.waitid)
        self.signals = SimpleNamespace(SIGCHLD=17, SIGKILL=9, SIG_DFL=0,
                                       getsignal=lambda sig: self.sig_handler, pidfd_send_signal=self.signal)
        self.process = None

    def system(self, path, limit):
        self.events.append(('system', path))
        if path == '/proc/self/status':
            return self.status
        if path == '/proc/self/attr/current':
            return self.label
        assert path == '/proc/self/task/111/children'
        return self.children

    def pipe2(self, flags):
        self.pipe_calls += 1
        self.events.append(('pipe', flags))
        assert flags == 64 | 128
        if self.pipe_calls == self.pipe_error_at:
            raise OSError(errno.EMFILE, 'CANARY_NATIVE_ERROR')
        ends = (10, 11) if self.pipe_calls == 1 else (12, 13)
        for fd in ends:
            fields = dict(st_dev=1, st_ino=ends[0], st_mode=stat.S_IFIFO | 0o600, st_uid=0, st_gid=0)
            fields.update(self.bad_pipe)
            self.fds[fd] = SimpleNamespace(**fields)
        return ends

    def spawn(self, argv, **options):
        self.events.append(('spawn', argv, options))
        if self.spawn_error:
            raise OSError(errno.ENOENT, 'CANARY_NATIVE_ERROR')
        # Decode the real launch plan as data only. Never exec/compile its code.
        tree = ast.parse(argv[-1])
        blobs = [base64.b64decode(node.args[0].value, validate=True) for node in ast.walk(tree)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                 and node.func.attr == 'b64decode' and isinstance(node.args[0], ast.Constant)]
        self.context = json.loads(next(blob for blob in blobs if blob.startswith(b'{')))
        self.case, self.mode = self.context['case_id'], self.context['mode']
        self.reports.append(frame(self.case, self.mode))
        self.process = SimpleNamespace(pid=123, returncode=None)
        return self.process

    def pidfd_open(self, pid, flags):
        self.events.append(('pidfd', pid, flags))
        assert pid == 123 and flags == 0
        if self.pidfd_error:
            raise OSError(errno.ENOSYS, 'CANARY_NATIVE_ERROR')
        self.fds[14] = SimpleNamespace(st_mode=0)
        if self.bad_pidfd:
            self.inheritable.add(14)
        return 14

    def read(self, fd, count):
        self.events.append(('read', fd, count))
        assert fd == 10 and count == 512
        if not self.reports:
            raise BlockingIOError(errno.EAGAIN, 'CANARY_NATIVE_ERROR')
        data = self.reports.pop(0)
        if isinstance(data, BaseException):
            raise data
        size = min(count, self.fragment)
        if len(data) > size:
            self.reports.insert(0, data[size:])
        return data[:size]

    def write(self, fd, data):
        self.events.append(('gate', fd, data))
        assert fd == 13 and data == b'G'
        if self.gate_error:
            raise self.gate_error
        if self.auto_finish:
            if (self.case, self.mode) != ('outside_exec', 'control'):
                fields = dict(observation='syscall_error' if self.mode == 'confined' else 'control_written',
                              errno=errno.EACCES if self.mode == 'confined' else 0)
                fields.update(self.result_override)
                self.reports.append(frame(self.case, self.mode, 'result', **fields))
            if self.eof:
                self.reports.append(b'')
            self.exit = SimpleNamespace(si_pid=123, si_code=self.exit_code,
                                        si_status=self.exit_status if self.exit_status is not None
                                        else 37 if (self.case, self.mode) == ('outside_exec', 'control') else 0)
        return self.gate_count

    def close(self, fd):
        self.closed.append(fd)
        self.events.append(('close', fd))
        self.fds.pop(fd)
        if fd in self.close_errors:
            raise OSError(errno.EINTR, 'CANARY_NATIVE_ERROR')

    def waitid(self, kind, identity, options):
        self.events.append(('wait', kind, identity, options))
        assert kind in (1, 3) and identity == (123 if kind == 1 else 14)
        assert options in (4 | 8, 4 | 8 | 16)
        if self.wait_error:
            raise ChildProcessError(errno.ECHILD, 'CANARY_NATIVE_ERROR')
        if self.exit_waits:
            self.exit_waits -= 1
            return None
        if not options & 16:
            self.events.append(('reap',))
            return self.reap_result or self.exit
        return self.exit

    def signal(self, fd, sig, info, flags):
        self.events.append(('signal', fd, sig, info, flags))
        assert (fd, sig, info, flags) == (14, 9, None, 0)
        if self.signal_error:
            raise OSError(errno.ESRCH, 'CANARY_NATIVE_ERROR')
        if not self.kill_stalls:
            self.exit = SimpleNamespace(si_pid=123, si_code=2, si_status=9)

    def pause(self, fd, seconds):
        self.events.append(('pause', fd, seconds))
        if self.poll_error:
            raise OSError(errno.EINTR, 'CANARY_NATIVE_ERROR')
        self.now += min(0.02, max(0, seconds))


@pytest.fixture
def model(monkeypatch):
    state = Model()
    monkeypatch.setattr(owner, 'os', state.os)
    monkeypatch.setattr(owner, 'signal', state.signals)
    monkeypatch.setattr(owner, 'subprocess', SimpleNamespace(Popen=state.spawn, DEVNULL=-3))
    monkeypatch.setattr(owner, 'sys', SimpleNamespace(platform='linux', version_info=(3, 12, 3),
                        flags=SimpleNamespace(isolated=True, no_site=True), dont_write_bytecode=True))
    monkeypatch.setattr(owner, 'platform', SimpleNamespace(machine=lambda: 'x86_64', release=lambda: '6.8.0-139-generic'))
    monkeypatch.setattr(owner, '_system', state.system)
    monkeypatch.setattr(owner, '_pause', state.pause)
    monkeypatch.setattr(owner, '_RETAINED', [])
    clock = SimpleNamespace(monotonic=lambda: state.now)
    monkeypatch.setattr(owner, 'time', clock)
    monkeypatch.setattr(plans, 'time', clock)
    return state


def acquire(model, **changes):
    fields = dict(binding=BINDING, case_id='runtime_write', mode='confined',
                  seed_sha256='a' * 64, deadline=105, cancelled=lambda: model.cancelled)
    fields.update(changes)
    return owner.NativeWorkerOwner(**fields)


def released(model, **changes):
    child = acquire(model, **changes)
    child.await_ready()
    child.release_gate()
    return child


@pytest.mark.parametrize('case', ['runtime_write', 'pool_sibling_write', 'outside_exec'])
@pytest.mark.parametrize('mode', ['control', 'confined'])
def test_complete_flow_holds_exact_child_until_capture(model, case, mode):
    child = released(model, case_id=case, mode=mode)
    observation = child.observe_exit()
    assert observation.worker_pid == 123 and observation.binding == BINDING
    assert (observation.case_id, observation.mode) == (case, mode)
    assert observation.exit_code == (37 if (case, mode) == ('outside_exec', 'control') else 0)
    assert not any(event[0] == 'reap' for event in model.events)
    assert owner._RETAINED == [model.process] and model.process.returncode is None
    assert set(model.fds) == {14}
    # Caller capture/fixture checks happen while exit remains WNOWAIT/unreaped.
    model.events.append(('caller_capture_and_fixture_checks',))
    child.reap_after_capture()
    assert model.events.index(('caller_capture_and_fixture_checks',)) < model.events.index(('reap',))
    assert not owner._RETAINED and not model.fds
    assert model.process.returncode == observation.exit_code
    assert not any(event[0] == 'signal' for event in model.events)
    child.abort()  # Known closed is idempotent; no new native calls.


def test_actual_fixed_renderer_and_spawn_options(model):
    child = acquire(model)
    event = next(event for event in model.events if event[0] == 'spawn')
    argv, options = event[1:]
    assert argv[:-1] == plans._SET_PRIV
    assert options == dict(shell=False, close_fds=True, pass_fds=(11, 12), stdin=-3, stdout=-3,
                           stderr=-3, env={'LANG': 'C', 'LC_ALL': 'C'}, cwd='/', start_new_session=False)
    assert model.context['deadline'] == '105.0'
    assert model.context['report_fd'] == 11 and model.context['gate_fd'] == 12
    assert model.closed == [11, 12] and set(model.fds) == {10, 13, 14}
    child.abort()
    assert not owner._RETAINED and model.process.returncode == -9


@pytest.mark.parametrize('fragment', [1, 2, 7, 255, 512])
def test_fragmented_reports(model, fragment):
    model.fragment = fragment
    child = released(model)
    assert child.observe_exit().syscall_errno == errno.EACCES
    child.reap_after_capture()


@pytest.mark.parametrize('change', [dict(binding={}), dict(case_id='shell'), dict(mode='other'),
                                    dict(seed_sha256='X' * 64), dict(deadline=True), dict(deadline=float('nan')),
                                    dict(deadline=float('inf')), dict(deadline=106), dict(deadline=100),
                                    dict(cancelled=3)])
def test_unfixed_context_never_spawns(model, change):
    with pytest.raises(owner.NativeOwnerRefused):
        acquire(model, **change)
    assert not model.fds and not any(event[0] == 'spawn' for event in model.events)


@pytest.mark.parametrize('field', ['SigIgn:', 'SigCgt:', 'SigBlk:'])
@pytest.mark.parametrize('shape', ['mask', 'missing', 'duplicate', 'malformed'])
def test_sigchld_ownership_refusal_precedes_pipe_creation(model, field, shape):
    row = field.encode() + b'\t0000000000000000\n'
    replacement = {'mask': field.encode() + b'\t0000000000010000\n', 'missing': b'',
                   'duplicate': row + row, 'malformed': field.encode() + b'\tinvalid\n'}[shape]
    model.status = model.status.replace(row, replacement)
    with pytest.raises(owner.NativeOwnerRefused, match='^sigchld$'):
        acquire(model)
    assert model.pipe_calls == 0


@pytest.mark.parametrize('condition', ['threads', 'children', 'label', 'handler', 'retained', 'environment',
                                       'uid', 'groups', 'kernel', 'python', 'isolated', 'platform'])
def test_wrong_supervisor_prerequisite_refuses(model, monkeypatch, condition):
    if condition == 'threads':
        model.tasks.append('112')
    elif condition == 'children':
        model.children = b'999'
    elif condition == 'label':
        model.label = b'wrong (enforce)'
    elif condition == 'handler':
        model.sig_handler = 1
    elif condition == 'retained':
        owner._RETAINED.append(SimpleNamespace(returncode=None))
    elif condition == 'environment':
        model.os.environ['PATH'] = '/unexpected'
    elif condition == 'uid':
        model.os.geteuid = lambda: 1
    elif condition == 'groups':
        model.os.getgroups = lambda: [0]
    elif condition == 'kernel':
        monkeypatch.setattr(owner.platform, 'release', lambda: 'other')
    elif condition == 'python':
        monkeypatch.setattr(owner.sys, 'version_info', (3, 13, 0))
    elif condition == 'isolated':
        owner.sys.flags.isolated = False
    else:
        monkeypatch.setattr(owner.sys, 'platform', 'win32')
    with pytest.raises(owner.NativeOwnerRefused):
        acquire(model)
    assert model.pipe_calls == 0


@pytest.mark.parametrize('pipe', [1, 2])
def test_pipe_acquisition_failure_closes_only_acquired_fds(model, pipe):
    model.pipe_error_at = pipe
    with pytest.raises(owner.NativeOwnerUnknown):
        acquire(model)
    assert not model.fds and model.closed == ([] if pipe == 1 else [10, 11])


@pytest.mark.parametrize('change', [dict(st_mode=stat.S_IFREG | 0o600), dict(st_mode=stat.S_IFIFO | 0o666),
                                    dict(st_uid=1), dict(st_gid=1)])
def test_pipe_security_before_spawn(model, change):
    model.bad_pipe = change
    with pytest.raises(owner.NativeOwnerRefused, match='^pipe$'):
        acquire(model)
    assert not model.fds and not any(event[0] == 'spawn' for event in model.events)


@pytest.mark.parametrize('attribute', ['inheritable', 'blocking'])
def test_pipe_flags_before_spawn(model, attribute):
    getattr(model, attribute).add(10)
    with pytest.raises(owner.NativeOwnerRefused, match='^pipe$'):
        acquire(model)
    assert not model.fds


def test_spawn_error_is_redacted_and_no_gate_or_signal(model):
    model.spawn_error = True
    with pytest.raises(owner.NativeOwnerUnknown, match='^acquisition_unknown$') as error:
        acquire(model)
    assert 'CANARY' not in str(error.value) and not model.fds
    assert not any(event[0] in ('gate', 'signal', 'wait') for event in model.events)


def test_live_child_without_pidfd_is_retained_unknown_never_numeric_killed(model):
    model.pidfd_error = True
    with pytest.raises(owner.NativeOwnerUnknown, match='^cleanup_unknown$'):
        acquire(model)
    assert owner._RETAINED == [model.process] and model.process.returncode is None
    assert not model.fds and not any(event[0] == 'signal' for event in model.events)
    assert ('wait', 1, 123, 4 | 8 | 16) in model.events


def test_already_exited_child_can_be_exact_reaped_after_pidfd_failure(model):
    model.pidfd_error = True
    model.exit = SimpleNamespace(si_pid=123, si_code=1, si_status=125)
    with pytest.raises(owner.NativeOwnerUnknown, match='^acquisition_unknown$'):
        acquire(model)
    assert not owner._RETAINED and model.process.returncode == 125 and not model.fds
    assert not any(event[0] == 'signal' for event in model.events)


def test_inheritable_pidfd_refuses_and_cleans_exact_child(model):
    model.bad_pidfd = True
    with pytest.raises(owner.NativeOwnerUnknown, match='^pidfd_unknown$'):
        acquire(model)
    assert not model.fds and not owner._RETAINED


@pytest.mark.parametrize('method', ['release_gate', 'observe_exit', 'reap_after_capture'])
def test_order_violation_is_terminal(model, method):
    child = acquire(model)
    with pytest.raises(owner.NativeOwnerRefused, match='^order$'):
        getattr(child, method)()
    with pytest.raises(owner.NativeOwnerRefused, match='^terminal$'):
        child.await_ready()
    child.abort()


@pytest.mark.parametrize('data', [b'', b'{', b'x' * 256, b'{"phase":"ready","phase":"ready"}\n',
                                 frame(mode='control'), frame(phase='result', observation='syscall_error', errno=13)])
def test_bad_ready_report_never_releases_gate(model, data):
    child = acquire(model)
    model.reports[:] = [data, b'']
    with pytest.raises(owner.NativeOwnerRefused):
        child.await_ready()
    assert not any(event[0] == 'gate' for event in model.events)
    child.abort()


@pytest.mark.parametrize('extra', [frame(), b'{', b'', frame(phase='result', observation='syscall_error', errno=13)])
def test_release_rechecks_queued_pre_gate_bytes(model, extra):
    child = acquire(model)
    child.await_ready()
    model.reports.append(extra)
    with pytest.raises(owner.NativeOwnerRefused):
        child.release_gate()
    assert not any(event[0] == 'gate' for event in model.events)
    child.abort()


@pytest.mark.parametrize('failure', ['short', 'eagain', 'epipe', 'close'])
def test_gate_is_written_at_most_once_even_on_uncertainty(model, failure):
    child = acquire(model)
    child.await_ready()
    if failure == 'short':
        model.gate_count = 0
    elif failure == 'close':
        model.close_errors.add(13)
    else:
        model.gate_error = BlockingIOError(errno.EAGAIN, 'CANARY') if failure == 'eagain' else BrokenPipeError('CANARY')
    with pytest.raises(owner.NativeOwnerRefused):
        child.release_gate()
    with pytest.raises(owner.NativeOwnerRefused, match='^terminal$'):
        child.release_gate()
    if failure == 'close':
        with pytest.raises(owner.NativeOwnerUnknown, match='^cleanup_unknown$'):
            child.abort()
    else:
        child.abort()
    assert sum(event[0] == 'gate' for event in model.events) == 1
    assert len(model.closed) == len(set(model.closed))


@pytest.mark.parametrize('stage', ['ready', 'released', 'held'])
@pytest.mark.parametrize('failure', ['cancelled', 'deadline', 'regression', 'callback'])
def test_original_budget_terminal_at_every_stage(model, stage, failure):
    child = acquire(model)
    child.await_ready()
    if stage != 'ready':
        child.release_gate()
    if stage == 'held':
        child.observe_exit()
    if failure == 'cancelled':
        model.cancelled = True
    elif failure == 'deadline':
        model.now = 105.0
    elif failure == 'regression':
        model.now = 99.0
    else:
        child._cancelled = lambda: (_ for _ in ()).throw(KeyboardInterrupt())
    method = {'ready': child.release_gate, 'released': child.observe_exit, 'held': child.reap_after_capture}[stage]
    with pytest.raises(owner.NativeOwnerRefused):
        method()
    child.abort()  # Cancellation/expired operation must not suppress exact cleanup.
    assert not owner._RETAINED and not model.fds


@pytest.mark.parametrize('stage', ['ready', 'report', 'exit'])
def test_stalled_pipe_or_exit_consumes_shared_budget(model, stage):
    child = acquire(model)
    if stage == 'ready':
        model.reports.clear()
        method = child.await_ready
    else:
        child.await_ready()
        model.now = 103.0
        if stage == 'report':
            model.auto_finish = False
        child.release_gate()
        if stage == 'exit':
            model.exit = None
        method = child.observe_exit
    with pytest.raises(owner.NativeOwnerUnknown):
        method()
    assert 105 <= model.now <= 105.02
    child.abort()
    assert not owner._RETAINED


@pytest.mark.parametrize('fields', [dict(errno=errno.EPERM), dict(observation='unexpected_open', errno=0)])
def test_negative_wrong_semantics_not_a_success(model, fields):
    model.result_override = fields
    child = released(model)
    with pytest.raises(owner.NativeOwnerRefused):
        child.observe_exit()
    child.abort()


@pytest.mark.parametrize('exit_code,status', [(1, 125), (2, 9), (3, 11)])
def test_eof_alone_or_abnormal_exit_never_success(model, exit_code, status):
    model.exit_code, model.exit_status = exit_code, status
    child = released(model)
    with pytest.raises(owner.NativeOwnerRefused):
        child.observe_exit()
    assert not any(event[0] == 'reap' for event in model.events)
    child.abort()
    assert not owner._RETAINED


def test_eof_without_positive_exec_exit37_is_not_success(model):
    model.exit_status = 0
    child = released(model, case_id='outside_exec', mode='control')
    with pytest.raises(owner.NativeOwnerRefused):
        child.observe_exit()
    child.abort()


@pytest.mark.parametrize('failure', ['wrong_pid', 'echild'])
def test_mismatched_pid_or_competing_reaper_never_signals_or_retries(model, failure):
    child = released(model)
    if failure == 'wrong_pid':
        model.exit.si_pid = 999
    else:
        model.wait_error = True
    with pytest.raises(owner.NativeOwnerUnknown):
        child.observe_exit()
    waits = [event for event in model.events if event[0] == 'wait']
    with pytest.raises(owner.NativeOwnerUnknown):
        child.abort()
    assert waits == [event for event in model.events if event[0] == 'wait']
    assert not any(event[0] == 'signal' for event in model.events)
    assert owner._RETAINED == [model.process] and model.process.returncode is None
    assert not model.fds


@pytest.mark.parametrize('failure', ['signal', 'wait', 'timeout', 'reap_mismatch', 'close'])
def test_cleanup_uncertainty_is_sticky_and_no_second_attempt(model, failure):
    child = acquire(model)
    if failure == 'signal':
        model.signal_error = True
    elif failure == 'wait':
        model.wait_error = True
    elif failure == 'timeout':
        model.kill_stalls = True
    elif failure == 'reap_mismatch':
        model.reap_result = SimpleNamespace(si_pid=999, si_code=2, si_status=9)
    else:
        model.close_errors.update((10, 13, 14))
    with pytest.raises(owner.NativeOwnerUnknown, match='^cleanup_unknown$'):
        child.abort()
    events = list(model.events)
    with pytest.raises(owner.NativeOwnerUnknown, match='^cleanup_unknown$'):
        child.abort()
    assert events == model.events and not model.fds
    assert len(model.closed) == len(set(model.closed))
    if failure != 'close':
        assert owner._RETAINED == [model.process] and model.process.returncode is None
    else:
        assert not owner._RETAINED and model.process.returncode == -9


def test_close_failure_during_construction_still_attempts_all_owned_closes(model):
    model.close_errors.add(11)
    with pytest.raises(owner.NativeOwnerUnknown, match='^cleanup_unknown$'):
        acquire(model)
    assert set(model.closed) == {10, 11, 12, 13, 14}
    assert len(model.closed) == 5 and not owner._RETAINED


def test_uncertain_consuming_reap_is_never_retried(model):
    child = released(model)
    child.observe_exit()
    model.reap_result = SimpleNamespace(si_pid=999, si_code=1, si_status=0)
    with pytest.raises(owner.NativeOwnerUnknown, match='^reap_unknown$'):
        child.reap_after_capture()
    waits = [event for event in model.events if event[0] == 'wait']
    assert owner._RETAINED == [model.process] and model.process.returncode is None
    with pytest.raises(owner.NativeOwnerUnknown):
        child.abort()
    assert waits == [event for event in model.events if event[0] == 'wait']
    assert sum(event[0] == 'reap' for event in model.events) == 1
    assert not model.fds


def test_poll_failure_is_terminal_and_redacted(model):
    child = acquire(model)
    model.reports.clear()
    model.poll_error = True
    with pytest.raises(owner.NativeOwnerUnknown, match='^operation_unknown$') as error:
        child.await_ready()
    assert 'CANARY' not in str(error.value)
    model.poll_error = False
    child.abort()


def test_delayed_exit_observation_is_nonconsuming(model):
    child = released(model)
    model.exit_waits = 3
    child.observe_exit()
    assert sum(event[0] == 'pause' for event in model.events) == 3
    assert not any(event[0] == 'reap' for event in model.events)
    child.reap_after_capture()


@pytest.mark.parametrize('data', [OSError(errno.EIO, 'CANARY'), KeyboardInterrupt()])
def test_read_failure_latches_before_cleanup(model, data):
    child = acquire(model)
    model.reports[:] = [data]
    with pytest.raises(owner.NativeOwnerUnknown, match='^operation_unknown$'):
        child.await_ready()
    with pytest.raises(owner.NativeOwnerRefused, match='^terminal$'):
        child.await_ready()
    child.abort()


@pytest.mark.parametrize('seconds,expected', [(5, 20), (0.0001, 1), (0, 0), (-1, 0)])
def test_poll_slice_has_no_selector_descriptor(model, monkeypatch, seconds, expected):
    events = []
    poller = SimpleNamespace(register=lambda *args: events.append(('register', *args)),
                             poll=lambda value: events.append(('poll', value)))
    monkeypatch.setattr(owner, 'select', SimpleNamespace(POLLIN=1, poll=lambda: poller))
    _REAL_PAUSE(5000, seconds)
    assert events == [('register', 5000, 1), ('poll', expected)]


@pytest.mark.parametrize('data', [b'', b'123', b'1234'])
def test_fixed_runtime_reader_bound_and_close_once(model, data):
    events = []
    model.os.open = lambda path, flags: 20
    model.os.read = lambda fd, count: data
    model.os.close = lambda fd: events.append(fd)
    if len(data) > 3:
        with pytest.raises(owner.NativeOwnerRefused, match='^runtime_bound$'):
            _REAL_SYSTEM('/proc/self/status', 3)
    else:
        assert _REAL_SYSTEM('/proc/self/status', 3) == data
    assert events == [20]


def test_fixed_runtime_reader_uncertain_close_not_retried(model):
    events = []
    model.os.open = lambda path, flags: 20
    model.os.read = lambda fd, count: b''

    def close(fd):
        events.append(fd)
        raise OSError(errno.EINTR, 'CANARY')

    model.os.close = close
    with pytest.raises(owner.NativeOwnerUnknown, match='^descriptor_cleanup_unknown$'):
        _REAL_SYSTEM('/proc/self/status', 3)
    assert events == [20]


def test_owner_stays_out_of_actual_public_and_inspection_payloads():
    from night_shifts.bootstrap_probe_seed import SOURCE_FILES
    from night_shifts.inspection_bundle import bundle_bytes
    assert 'bootstrap_native_owner.py' not in SOURCE_FILES
    with zipfile.ZipFile(io.BytesIO(bundle_bytes())) as archive:
        assert 'night_shifts/bootstrap_native_owner.py' not in archive.namelist()
