"""OFFLINE models only: no native pool file, record lock, worker or child.

Exercise the fixed positive operation and its existing launch/report/capture
layers with replaced adapters. Imported fixtures are prior offline models, not
native helpers. No generated launch source or ELF is executed here.
"""
from __future__ import annotations

import errno
import hashlib
import json
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from night_shifts import bootstrap_native_capture as capture
from night_shifts import bootstrap_native_child_plan as plans
from night_shifts import bootstrap_native_supervision as core
from night_shifts.guest import bootstrap_native_child as entry
from night_shifts.guest import bootstrap_native_worker as worker
from tests.night_shifts import test_bootstrap_native_capture as capture_tests
from tests.night_shifts import test_bootstrap_native_child as child_tests
from tests.night_shifts import test_bootstrap_native_owner as owner_tests
from tests.night_shifts import test_bootstrap_native_worker as worker_tests

pipe_model = owner_tests.model
entry_model = child_tests.model
preflight_model = worker_tests.model
model = capture_tests.model
pipeline = capture_tests.pipeline
_REAL_RECORD_LOCKS = worker._record_locks


class Pools:
    def __init__(self):
        self.now = 100.0
        self.nodes = {path: SimpleNamespace(st_dev=3, st_ino=index + 10, st_mode=stat.S_IFREG | 0o600,
                      st_uid=0, st_gid=0, st_nlink=1, st_size=1, raw=b'V')
                      for index, path in enumerate(worker._POOL_PATHS)}
        self.fds, self.locked, self.events, self.closed = {}, set(), [], []
        self.fail_open = self.fail_lock = self.fail_read = self.fail_write = None
        self.short_write = self.bad_readback = False
        self.inheritable = self.blocking = False
        self.close_errors, self.unlock_errors = set(), set()
        self.os = SimpleNamespace(O_RDWR=2, O_NOFOLLOW=16, O_CLOEXEC=8, O_NONBLOCK=32, SEEK_SET=0,
            lstat=lambda path: self.nodes[path], fstat=lambda fd: self.fds[fd],
            get_inheritable=lambda fd: self.inheritable, get_blocking=lambda fd: self.blocking,
            open=self.open, close=self.close, pread=self.pread, pwrite=self.pwrite)
        self.locks = SimpleNamespace(LOCK_EX=1, LOCK_NB=2, LOCK_UN=4, lockf=self.lockf)

    def open(self, path, flags):
        assert path in worker._POOL_PATHS and flags == 2 | 8 | 16 | 32
        self.events.append(('open', path, flags))
        if path == self.fail_open:
            raise OSError(errno.EACCES, 'SYNTHETIC_CANARY')
        fd = 10 + len(self.fds)
        self.fds[fd] = self.nodes[path]
        return fd

    def lockf(self, fd, command, length, start, whence):
        assert (length, start, whence) == (0, 0, 0)
        self.events.append(('lock', fd, command))
        if command == 3:
            if fd == self.fail_lock:
                raise BlockingIOError(errno.EAGAIN, 'SYNTHETIC_CANARY')
            self.locked.add(fd)
        else:
            assert command == 4
            self.locked.discard(fd)
            if fd in self.unlock_errors:
                raise OSError(errno.EIO, 'SYNTHETIC_CANARY')

    def pread(self, fd, count, offset):
        assert count == 2 and offset == 0 and len(self.locked) == 5
        self.events.append(('read', fd))
        if fd == self.fail_read:
            raise OSError(errno.EIO, 'SYNTHETIC_CANARY')
        return self.fds[fd].raw

    def pwrite(self, fd, data, offset):
        assert data == b'V' and offset == 0 and len(self.locked) == 5
        self.events.append(('write', fd))
        if fd == self.fail_write:
            raise OSError(errno.EIO, 'SYNTHETIC_CANARY')
        self.fds[fd].raw = b'X' if self.bad_readback else data
        return 0 if self.short_write else 1

    def close(self, fd):
        self.events.append(('close', fd))
        self.closed.append(fd)
        self.fds.pop(fd)
        self.locked.discard(fd)  # Modeled POSIX close releases this file's lock.
        if fd in self.close_errors:
            raise OSError(errno.EINTR, 'SYNTHETIC_CANARY')


@pytest.fixture
def pools(monkeypatch):
    state = Pools()
    monkeypatch.setattr(worker, 'os', state.os)
    monkeypatch.setattr(worker, 'sys', SimpleNamespace(platform='linux'))
    monkeypatch.setattr(worker, 'time', SimpleNamespace(monotonic=lambda: state.now))
    monkeypatch.setattr(worker, '_record_locks', lambda: state.locks)
    return state


def pool_context(mode='confined'):
    return worker_tests.context('allowed_pools', mode)


def test_all_five_record_locks_held_before_fixed_read_write_readback(pools):
    assert worker._operation(pool_context()) == {'observation': 'pools_checked', 'errno': 0}
    names = [event[0] for event in pools.events]
    assert names[:10] == ['open', 'lock'] * 5
    assert names[10:25] == ['read', 'write', 'read'] * 5
    assert pools.closed == [14, 13, 12, 11, 10] and not pools.fds and not pools.locked
    assert all(node.raw == b'V' for node in pools.nodes.values())
    assert worker._POOL_PATHS == tuple('/var/lib/hyperv/.kvp_pool_' + str(i) for i in range(5))


@pytest.mark.parametrize('index', range(5))
@pytest.mark.parametrize('fault', ['open', 'lock', 'read', 'write'])
def test_positive_fault_never_retries_and_closes_all_acquired(pools, index, fault):
    setattr(pools, 'fail_' + fault, worker._POOL_PATHS[index] if fault == 'open' else index + 10)
    with pytest.raises(worker.NativeWorkerUnknown, match='^allowed_pools_unknown$') as error:
        worker._operation(pool_context())
    assert 'SYNTHETIC_CANARY' not in str(error.value) and not pools.fds and not pools.locked
    assert len(pools.closed) == len(set(pools.closed))
    calls = [event for event in pools.events if event[0] == fault and (fault != 'lock' or event[2] == 3)]
    assert len(calls) <= (2 * index + 1 if fault == 'read' else index + 1)


@pytest.mark.parametrize('changes', [dict(st_mode=stat.S_IFREG | 0o644), dict(st_mode=stat.S_IFLNK | 0o600),
                                    dict(st_uid=1), dict(st_gid=1), dict(st_nlink=2), dict(st_size=2)])
def test_bad_allowed_pool_metadata_stops_before_write(pools, changes):
    vars(pools.nodes[worker._POOL_PATHS[2]]).update(changes)
    with pytest.raises(worker.NativeWorkerUnknown):
        worker._operation(pool_context())
    assert not any(event[0] == 'write' for event in pools.events) and not pools.fds


@pytest.mark.parametrize('fault', ['inheritable', 'blocking', 'short_write', 'bad_readback'])
def test_flag_or_fixed_byte_uncertainty_is_not_positive_success(pools, fault):
    setattr(pools, fault, True)
    with pytest.raises(worker.NativeWorkerUnknown):
        worker._operation(pool_context())
    assert not pools.fds and len(pools.closed) == len(set(pools.closed))


@pytest.mark.parametrize('cleanup', ['unlock', 'close', 'both'])
def test_uncertain_unlock_close_still_attempts_all_exact_descriptors_once(pools, cleanup):
    if cleanup != 'close':
        pools.unlock_errors.update((10, 12, 14))
    if cleanup != 'unlock':
        pools.close_errors.update((10, 11, 13))
    with pytest.raises(worker.NativeWorkerUnknown, match='^allowed_pools_unknown$'):
        worker._operation(pool_context())
    assert set(pools.closed) == set(range(10, 15)) and len(pools.closed) == 5 and not pools.fds


def test_pool_operation_cannot_be_unconfined_or_use_a_denied_case(pools):
    for value in (pool_context('control'), worker_tests.context()):
        with pytest.raises(worker.NativeWorkerRefused, match='^context$'):
            worker._pool_operation(value)
    assert not pools.events


def test_allowed_pool_context_refuses_control_before_preflight(pools):
    with pytest.raises(worker.NativeWorkerRefused, match='^context$'):
        worker._context(pool_context('control'))


def test_deadline_after_possible_write_still_unlocks_and_closes_all(pools):
    original = pools.os.pwrite

    def write(fd, raw, offset):
        count = original(fd, raw, offset)
        pools.now = 104.0
        return count

    pools.os.pwrite = write
    with pytest.raises(worker.NativeWorkerUnknown, match='^allowed_pools_unknown$'):
        worker._operation(pool_context())
    assert len(pools.closed) == 5 and not pools.fds and not pools.locked


def test_record_lock_adapter_has_no_nonlinux_fallback(pools):
    worker.sys.platform = 'win32'
    with pytest.raises(worker.NativeWorkerRefused, match='^linux_required$'):
        _REAL_RECORD_LOCKS()
    assert not pools.events


def test_preflight_gate_label_and_actual_encoder_cover_positive_case(preflight_model, monkeypatch):
    operations = []
    monkeypatch.setattr(worker, '_pool_operation', lambda value: operations.append(value.copy())
                        or {'observation': 'pools_checked', 'errno': 0})
    assert worker.run_fixed_case(pool_context()) == 0
    reports = worker_tests.reports(preflight_model)
    assert [item['phase'] for item in reports] == ['ready', 'result']
    assert all(item['case_id'] == 'allowed_pools' and item['mode'] == 'confined' for item in reports)
    assert reports[-1]['observation'] == 'pools_checked' and len(operations) == 1
    assert len(json.dumps(reports[-1], sort_keys=True, separators=(',', ':')).encode('ascii')) + 1 <= 256


def test_entry_maps_fds_and_transitions_before_pool_worker_evaluation(entry_model):
    assert entry.enter(child_tests.context(case_id='allowed_pools'), child_tests.WORKER) == 0
    assert entry_model.evaluated[0]['case_id'] == 'allowed_pools'
    assert entry_model.events.index(('write', 5, b'changeprofile night-shift-kvp-public-probe')) < entry_model.events.index(('evaluate',))


def test_launch_plan_and_bootstrap_context_bind_pool_to_confined(monkeypatch):
    rendered = child_tests.plan(monkeypatch, case_id='allowed_pools', mode='confined')
    assert rendered.argv[:-1] == plans._SET_PRIV and rendered.pass_fds == (10, 11)
    with pytest.raises(plans.NativeChildPlanRefused, match='^context$'):
        child_tests.plan(monkeypatch, case_id='allowed_pools', mode='control')
    with pytest.raises(entry.NativeChildRefused, match='^context$'):
        entry._context(child_tests.context(case_id='allowed_pools', mode='control'))


def test_source_repin_is_exact_canonical_lf_data():
    raw = Path(worker.__file__).read_text(encoding='utf-8').encode('utf-8')
    assert hashlib.sha256(raw).hexdigest() == entry.WORKER_SHA256 == '2b6fc9a513525eb2d39a6a4c50ef050620228fc4ff596925c9a279fd86a9d3d2'


@pytest.mark.parametrize('kind,number,status', [('pools_checked', 0, 0), ('syscall_error', 13, 0),
                                              ('control_written', 0, 0), ('pools_checked', 0, 37),
                                              ('pools_checked', True, 0)])
def test_pool_report_core_requires_exact_positive_semantics(kind, number, status):
    state = core.WorkerReportSession(child_tests.BINDING, 'allowed_pools', 'confined', 123,
                                     deadline=105, clock=lambda: 100.0)
    state.feed(owner_tests.frame('allowed_pools'))
    state.mark_gate_released()
    if (kind, number, status) == ('pools_checked', 0, 0) and type(number) is int:
        state.feed(owner_tests.frame('allowed_pools', phase='result', observation=kind, errno=number))
        state.end_of_reports()
        assert state.finish_exit(worker_pid=123, exit_code=status).observation == 'pools_checked'
    else:
        with pytest.raises(core.NativeSupervisionRefused):
            state.feed(owner_tests.frame('allowed_pools', phase='result', observation=kind, errno=number))
            state.end_of_reports()
            state.finish_exit(worker_pid=123, exit_code=status)


def test_real_owner_pool_flow_uses_unreaped_exit_and_explicit_reap(pipe_model):
    pipe_model.auto_finish = False
    child = owner_tests.acquire(pipe_model, case_id='allowed_pools')
    child.await_ready()
    child.release_gate()
    pipe_model.reports.extend((owner_tests.frame('allowed_pools', phase='result', observation='pools_checked', errno=0), b''))
    pipe_model.exit = SimpleNamespace(si_pid=123, si_code=1, si_status=0)
    assert child.observe_exit().observation == 'pools_checked'
    assert not any(event[0] == 'reap' for event in pipe_model.events)
    child.reap_after_capture()


def test_pool_cannot_use_owner_control_mode(pipe_model):
    with pytest.raises(owner_tests.owner.NativeOwnerRefused, match='^context$'):
        owner_tests.acquire(pipe_model, case_id='allowed_pools', mode='control')
    assert not pipe_model.events


def test_real_collector_pool_sequence_does_not_call_denial_correlator(model, pipeline, monkeypatch):
    base = capture.NativeWorkerOwner

    class PoolChild(base):
        def release_gate(self):
            self.step('gate')

        def observe_exit(self):
            self.step('exit')
            self.held = True
            return core.LocalWorkerObservation(capture_tests.BINDING, 'allowed_pools', 'confined', 123,
                                               'pools_checked', 0, 0, 100.0, 100.0)

        def reap_after_capture(self):
            assert self.held and not model.opened and ('verify3',) in model.events
            self.step('reap')
            self.reaped, self.held = True, False

    monkeypatch.setattr(capture, 'NativeWorkerOwner', PoolChild)
    result = capture.observe_fixed_worker(pipeline, 'allowed_pools', 'confined', deadline=105)
    assert result.worker.observation == 'pools_checked' and result.denial is None
    assert not any(event[0] == 'correlate' for event in model.events)
    assert model.child.reaped and model.closed == [20]
    assert 'SYNTHETIC_CANARY' not in repr(result)
