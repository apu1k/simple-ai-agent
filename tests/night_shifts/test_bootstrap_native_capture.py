"""Synthetic kmsg/syscall/child models only; NEVER read native logs or spawn.

The collector and single-worker sequence use replaced OS/clock/poll/owner/fixture
adapters. The actual denial correlator runs on synthetic records. No model value
is native provenance, kernel ABI proof, a validation pass or a cleanup receipt.
"""
from __future__ import annotations

import errno
import io
import stat
import zipfile
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

from night_shifts import bootstrap_native_capture as capture
from night_shifts.bootstrap_native_supervision import LocalWorkerObservation
from night_shifts.maintenance_tls_prototype import AttemptBinding

BINDING = AttemptBinding('1' * 32, '00000000-0000-4000-8000-000000000001')
PATHS = {'runtime_write': ('open', '/run/night-shift-bootstrap/denied-write', 'w'),
         'pool_sibling_write': ('open', '/var/lib/hyperv/.kvp_pool_denied', 'w'),
         'outside_exec': ('exec', '/run/night-shift-bootstrap/denied-exec', 'x')}


def record(sequence=41, stamp=100_000_000, body=b'ordinary SYNTHETIC_CANARY', priority=6, flags='-'):
    return f'{priority},{sequence},{stamp},{flags};'.encode('ascii') + body + b'\n'


def denial(case='runtime_write', **changes):
    operation, path, mask = PATHS[case]
    fields = dict(apparmor='DENIED', operation=operation, profile='night-shift-kvp-public-probe',
                  name=path, pid='123', comm='SYNTHETIC_CANARY', requested_mask=mask,
                  denied_mask=mask, fsuid='0', ouid='0')
    fields.update(changes)
    body = b'audit: type=1400 audit(1760000000.001:71): ' + ' '.join(
        key + '="' + value + '"' for key, value in fields.items()).encode('ascii')
    return record(body=body, priority=4)


class Model:
    def __init__(self):
        self.ns, self.cancelled = 100_000_000_000, False
        self.events, self.closed, self.scheduled = [], [], []
        self.queue = [record(40, 99_000_000), None]
        self.node = SimpleNamespace(st_dev=2, st_ino=99, st_rdev=11, st_mode=stat.S_IFCHR | 0o600,
                                    st_uid=0, st_gid=0, st_nlink=1, st_ctime_ns=3)
        self.path_node = self.node
        self.opened = self.inheritable = self.blocking = False
        self.open_error = self.seek_error = self.close_error = self.poll_error = False
        self.failpoint, self.abort_error, self.no_denial, self.bad_denial = None, False, False, False
        self.tasks, self.label = ['111'], b'unconfined\n'
        self.os = SimpleNamespace(
            O_RDONLY=0, O_CLOEXEC=64, O_NONBLOCK=128, O_NOFOLLOW=256, SEEK_SET=0,
            getuid=lambda: 0, geteuid=lambda: 0, getgid=lambda: 0, getegid=lambda: 0,
            getgroups=lambda: [], getpid=lambda: 111, environ={'LANG': 'C', 'LC_ALL': 'C'},
            listdir=lambda path: self.tasks, major=lambda dev: 1 if dev == 11 else 9,
            minor=lambda dev: dev, get_inheritable=lambda fd: self.inheritable,
            get_blocking=lambda fd: self.blocking, stat=self.stat, fstat=lambda fd: self.node,
            open=self.open, lseek=self.seek, read=self.read, close=self.close)

    def stat(self, path, *, follow_symlinks):
        assert path == '/dev/kmsg' and follow_symlinks is False
        return self.path_node

    def open(self, path, flags):
        assert path == '/dev/kmsg' and flags == 64 | 128 | 256
        self.events.append(('open',))
        if self.open_error or self.failpoint == 'open':
            raise PermissionError(errno.EACCES, 'SYNTHETIC_CANARY')
        self.opened = True
        return 20

    def seek(self, fd, offset, whence):
        assert (fd, offset, whence) == (20, 0, 0)
        self.events.append(('seek',))
        if self.seek_error:
            raise OSError(errno.ESPIPE, 'SYNTHETIC_CANARY')
        return 0

    def read(self, fd, count):
        assert fd == 20 and count == capture.MAX_RECORD_BYTES + 1 and self.opened
        self.events.append(('read',))
        while self.scheduled and self.scheduled[0][0] <= self.ns:
            _, raw = self.scheduled.pop(0)
            self.queue.append(raw)
        raw = self.queue.pop(0) if self.queue else None
        if raw is None:
            self.events.append(('empty',))
            raise BlockingIOError(errno.EAGAIN, 'SYNTHETIC_CANARY')
        if isinstance(raw, BaseException):
            raise raw
        return raw

    def close(self, fd):
        assert fd == 20 and self.opened
        self.events.append(('close',))
        self.closed.append(fd)
        self.opened = False
        if self.close_error or self.failpoint == 'close':
            raise OSError(errno.EINTR, 'SYNTHETIC_CANARY')

    def pause(self, fd, seconds):
        assert fd == 20 and seconds > 0
        self.events.append(('poll',))
        if self.poll_error:
            raise OSError(errno.EINTR, 'SYNTHETIC_CANARY')
        self.ns += min(20_000_000, max(1, round(seconds * 1e9)))

    def system(self, path, limit):
        assert path == '/proc/self/attr/current' and limit == 256
        return self.label


@pytest.fixture
def model(monkeypatch):
    state = Model()
    monkeypatch.setattr(capture, 'os', state.os)
    monkeypatch.setattr(capture, 'sys', SimpleNamespace(platform='linux', version_info=(3, 12, 3),
                        flags=SimpleNamespace(isolated=True, no_site=True), dont_write_bytecode=True))
    monkeypatch.setattr(capture, 'platform', SimpleNamespace(machine=lambda: 'x86_64', release=lambda: '6.8.0-139-generic'))
    monkeypatch.setattr(capture, 'time', SimpleNamespace(monotonic_ns=lambda: state.ns))
    monkeypatch.setattr(capture, '_pause', state.pause)
    monkeypatch.setattr(capture, '_system', state.system)
    return state


def acquire(model, **changes):
    fields = dict(deadline=105, cancelled=lambda: model.cancelled)
    fields.update(changes)
    return capture.NativeKernelCapture(**fields)


def test_fresh_cursor_and_quiet_interval_hide_raw_records(model):
    log = acquire(model)
    assert model.events[:3] == [('open',), ('seek',), ('read',)]
    assert not model.queue and not model.closed
    model.queue.append(denial())
    interval = log.finish()
    assert interval.baseline_sequence == 40 and interval.start_us == 100_000_000
    assert interval.end_us - interval.start_us >= 100_000
    assert interval.records == (denial(),) and 'SYNTHETIC_CANARY' not in repr(interval)
    result = capture.correlate_local_denial('runtime_write', worker_pid=123, syscall_errno=13,
                baseline_sequence=interval.baseline_sequence, start_us=interval.start_us,
                end_us=interval.end_us, records=interval.records)
    assert result.kernel_sequence == 41
    with pytest.raises(FrozenInstanceError):
        interval.start_us = 0
    with pytest.raises(capture.NativeCaptureRefused, match='^terminal$'):
        log.finish()
    log.close()
    log.close()
    assert model.closed == [20]


def test_historical_metadata_and_continuations_are_only_discarded_at_baseline(model):
    model.queue = [record(39, 98_000_000, body=b'\xff\n DEVICE=old', flags='c'),
                   record(40, 99_000_000, body=b'old\n SUBSYSTEM=pci'), None]
    log = acquire(model)
    interval = log.finish()
    assert interval.baseline_sequence == 40 and interval.records == ()
    log.close()


@pytest.mark.parametrize('changes', [dict(deadline=True), dict(deadline=float('nan')),
                                     dict(deadline=float('inf')), dict(deadline=106),
                                     dict(deadline=100), dict(cancelled=7)])
def test_invalid_context_before_device_open(model, changes):
    with pytest.raises(capture.NativeCaptureRefused):
        acquire(model, **changes)
    assert not model.events


@pytest.mark.parametrize('condition', ['platform', 'kernel', 'python', 'isolated', 'identity',
                                       'groups', 'environment', 'threads', 'label'])
def test_runtime_mismatch_no_device_or_fallback(model, condition):
    if condition == 'platform':
        capture.sys.platform = 'win32'
    elif condition == 'kernel':
        capture.platform.release = lambda: 'other'
    elif condition == 'python':
        capture.sys.version_info = (3, 13, 0)
    elif condition == 'isolated':
        capture.sys.flags.isolated = False
    elif condition == 'identity':
        model.os.geteuid = lambda: 1
    elif condition == 'groups':
        model.os.getgroups = lambda: [0]
    elif condition == 'environment':
        model.os.environ['PATH'] = 'other'
    elif condition == 'threads':
        model.tasks.append('112')
    else:
        model.label = b'wrong (enforce)'
    with pytest.raises(capture.NativeCaptureRefused):
        acquire(model)
    assert not model.events


@pytest.mark.parametrize('changes', [dict(st_mode=stat.S_IFREG | 0o600), dict(st_mode=stat.S_IFLNK | 0o600),
                                     dict(st_mode=stat.S_IFCHR | 0o644), dict(st_uid=1), dict(st_gid=1),
                                     dict(st_nlink=2), dict(st_rdev=12)])
def test_only_fixed_root_character_device_is_accepted(model, changes):
    vars(model.node).update(changes)
    with pytest.raises(capture.NativeCaptureRefused, match='^log_device$'):
        acquire(model)
    assert not model.events


@pytest.mark.parametrize('fault', ['inheritable', 'blocking', 'open', 'seek', 'replacement'])
def test_descriptor_acquisition_fault_closes_once(model, fault):
    if fault in ('inheritable', 'blocking'):
        setattr(model, fault, True)
    elif fault == 'replacement':
        model.path_node = SimpleNamespace(**(vars(model.node) | {'st_ino': 100}))
    else:
        setattr(model, fault + '_error', True)
    with pytest.raises(capture.NativeCaptureRefused):
        acquire(model)
    assert not model.opened and model.closed == ([] if fault == 'open' else [20])


@pytest.mark.parametrize('raws', [[], [record(40, 99_000_000), record(42, 99_000_001)],
                                 [record(40, 99_000_000), record(41, 98_000_000)],
                                 [record(40, 100_000_001)],
                                 [record(capture.MAX_COUNTER, 99_000_000)]],
                         ids=['empty', 'gap', 'clock-regression', 'future', 'counter-exhausted'])
def test_invalid_baseline_never_invents_cursor(model, raws):
    model.queue = [*raws, None]
    with pytest.raises(capture.NativeCaptureUnknown):
        acquire(model)
    assert model.closed == [20]


@pytest.mark.parametrize('bound', ['count', 'bytes'])
def test_baseline_drain_is_bounded(model, monkeypatch, bound):
    if bound == 'count':
        monkeypatch.setattr(capture, 'MAX_BASELINE_RECORDS', 2)
        model.queue = [record(n, 99_000_000) for n in (38, 39, 40)]
    else:
        monkeypatch.setattr(capture, 'MAX_BASELINE_BYTES', 30)
    with pytest.raises(capture.NativeCaptureUnknown, match='^baseline_bound_unknown$'):
        acquire(model)
    assert model.closed == [20]


@pytest.mark.parametrize('phase', ['baseline', 'capture'])
@pytest.mark.parametrize('fault', [errno.EPIPE, errno.EINVAL, errno.EIO, errno.EINTR])
def test_log_errors_have_no_seek_repair_or_larger_read_retry(model, phase, fault):
    if phase == 'baseline':
        model.queue = [OSError(fault, 'SYNTHETIC_CANARY')]
        with pytest.raises(capture.NativeCaptureUnknown):
            acquire(model)
    else:
        log = acquire(model)
        model.queue.append(OSError(fault, 'SYNTHETIC_CANARY'))
        with pytest.raises(capture.NativeCaptureUnknown):
            log.finish()
        with pytest.raises(capture.NativeCaptureRefused, match='^terminal$'):
            log.finish()
        log.close()
    assert model.events.count(('seek',)) == 1 and model.closed == [20]


@pytest.mark.parametrize('raw', [b'', b'not kmsg\n', record(flags='c'), record(body=b'bad\nmetadata'),
                                record(body=b'\xff'), record()[:-1], record(priority=192),
                                record(sequence=capture.MAX_COUNTER + 1)],
                         ids=['eof', 'shape', 'continuation', 'multiline', 'encoding',
                              'missing-newline', 'priority', 'counter'])
def test_actual_capture_does_not_salvage_or_concatenate_records(model, raw):
    log = acquire(model)
    model.queue.append(raw)
    with pytest.raises(capture.NativeCaptureUnknown):
        log.finish()
    log.close()


@pytest.mark.parametrize('body', [b'kauditd_printk_skb: 2 callbacks suppressed', b'audit: rate limit exceeded',
                                 b'audit_lost=1', b'audit: backlog limit exceeded', b'__ratelimit: loss'])
@pytest.mark.parametrize('phase', ['baseline', 'capture'])
def test_suppression_markers_always_stop(model, body, phase):
    if phase == 'baseline':
        model.queue = [record(40, 99_000_000, body=body), None]
        with pytest.raises(capture.NativeCaptureUnknown, match='^log_loss_unknown$'):
            acquire(model)
    else:
        log = acquire(model)
        model.queue.append(record(body=body))
        with pytest.raises(capture.NativeCaptureUnknown, match='^log_loss_unknown$'):
            log.finish()
        log.close()


@pytest.mark.parametrize('raw', [record(42), record(40), record(stamp=99_999_999),
                                record(stamp=100_000_001)], ids=['gap', 'stale', 'before-start', 'future'])
def test_capture_sequence_and_clock_boundaries(model, raw):
    log = acquire(model)
    model.queue.append(raw)
    with pytest.raises(capture.NativeCaptureUnknown, match='^capture_gap_unknown$'):
        log.finish()
    log.close()


@pytest.mark.parametrize('count,ok', [(64, True), (65, False)])
def test_capture_record_count_exact_boundary(model, count, ok):
    log = acquire(model)
    model.queue.extend(record(n) for n in range(41, 41 + count))
    if ok:
        assert len(log.finish().records) == count
    else:
        with pytest.raises(capture.NativeCaptureUnknown, match='^capture_bound_unknown$'):
            log.finish()
    log.close()


@pytest.mark.parametrize('count,ok', [(8, True), (9, False)])
def test_capture_total_bytes_exact_boundary(model, count, ok):
    log = acquire(model)
    for n in range(41, 41 + count):
        size = capture.MAX_RECORD_BYTES - len(record(n, body=b''))
        model.queue.append(record(n, body=b'x' * size))
    if ok:
        assert sum(map(len, log.finish().records)) == capture.MAX_CAPTURE_BYTES
    else:
        with pytest.raises(capture.NativeCaptureUnknown, match='^capture_bound_unknown$'):
            log.finish()
    log.close()


def test_oversized_record_is_not_partial_buffer_input(model):
    log = acquire(model)
    model.queue.append(b'x' * (capture.MAX_RECORD_BYTES + 1))
    with pytest.raises(capture.NativeCaptureUnknown, match='^record_bound_unknown$'):
        log.finish()
    log.close()


def test_quiet_tail_restarts_for_delayed_records(model):
    log = acquire(model)
    model.queue.append(record())
    model.scheduled.append((100_060_000_000, record(42, 100_060_000)))
    interval = log.finish()
    assert len(interval.records) == 2 and interval.end_us >= 100_160_000
    log.close()


@pytest.mark.parametrize('fault', ['cancelled', 'deadline', 'regression', 'bool-clock', 'callback', 'poll', 'identity'])
def test_capture_failure_is_terminal_and_close_ignores_cancellation(model, fault):
    log = acquire(model)
    if fault == 'cancelled':
        model.cancelled = True
    elif fault == 'deadline':
        model.ns = 105_000_000_000
    elif fault == 'regression':
        model.ns -= 1
    elif fault == 'bool-clock':
        model.ns = True
    elif fault == 'callback':
        log._cancelled = lambda: (_ for _ in ()).throw(KeyboardInterrupt())
    elif fault == 'poll':
        model.poll_error = True
    else:
        model.node.st_ctime_ns += 1
    with pytest.raises(capture.NativeCaptureRefused) as error:
        log.finish()
    assert 'SYNTHETIC_CANARY' not in str(error.value)
    with pytest.raises(capture.NativeCaptureRefused, match='^terminal$'):
        log.finish()
    log.close()
    assert model.closed == [20]


def test_quiet_tail_cannot_renew_original_budget(model):
    log = acquire(model)
    model.ns = 104_950_000_000
    with pytest.raises(capture.NativeCaptureUnknown, match='^budget_unknown$'):
        log.finish()
    log.close()
    assert model.ns == 105_000_000_000


def test_close_uncertainty_is_sticky_without_retry(model):
    log = acquire(model)
    model.close_error = True
    for _ in range(2):
        with pytest.raises(capture.NativeCaptureUnknown, match='^descriptor_cleanup_unknown$'):
            log.close()
    assert model.closed == [20]


@pytest.fixture
def pipeline(model, monkeypatch):
    class Fixtures:
        def __init__(self):
            self.checks = 0

        def launch_context(self):
            model.events.append(('context',))
            return BINDING, 'a' * 64

        def verify(self, *, deadline, cancelled):
            self.checks += 1
            assert deadline == 105 and cancelled() is False
            model.events.append(('verify' + str(self.checks),))
            if model.failpoint == 'verify' + str(self.checks):
                raise RuntimeError('SYNTHETIC_CANARY')

    class Child:
        def __init__(self, binding, case, mode, **options):
            assert binding == BINDING and options['seed_sha256'] == 'a' * 64 and options['deadline'] == 105
            self.case, self.mode, self.held, self.reaped = case, mode, False, False
            model.child = self
            self.step('spawn')

        def step(self, label):
            model.events.append((label,))
            if model.failpoint == label:
                raise RuntimeError('SYNTHETIC_CANARY')

        def await_ready(self):
            self.step('ready')

        def release_gate(self):
            assert model.opened and ('empty',) in model.events
            self.step('gate')
            if model.failpoint == 'finish':
                model.queue.append(OSError(errno.EPIPE, 'SYNTHETIC_CANARY'))
            elif self.mode == 'confined' and not model.no_denial:
                model.queue.append(denial(self.case, pid='999' if model.bad_denial else '123'))

        def observe_exit(self):
            self.step('exit')
            self.held = True
            return LocalWorkerObservation(BINDING, self.case, self.mode, 123,
                'syscall_error' if self.mode == 'confined' else 'control_exec' if self.case == 'outside_exec' else 'control_written',
                13 if self.mode == 'confined' else 0, 37 if (self.case, self.mode) == ('outside_exec', 'control') else 0,
                100.0, 100.0)

        def reap_after_capture(self):
            assert self.held and not model.opened and ('verify3',) in model.events
            if self.mode == 'confined':
                assert ('correlate',) in model.events
            self.step('reap')
            self.reaped = True
            self.held = False

        def abort(self):
            model.events.append(('abort',))
            if model.abort_error:
                raise RuntimeError('SYNTHETIC_CANARY')
            self.held = False

    real_correlate = capture.correlate_local_denial

    def correlate(*args, **kwargs):
        assert model.child.held and not model.child.reaped
        model.events.append(('correlate',))
        if model.failpoint == 'correlate':
            raise RuntimeError('SYNTHETIC_CANARY')
        return real_correlate(*args, **kwargs)

    monkeypatch.setattr(capture, 'NativeRamFixtures', Fixtures)
    monkeypatch.setattr(capture, 'NativeWorkerOwner', Child)
    monkeypatch.setattr(capture, 'correlate_local_denial', correlate)
    return Fixtures()


@pytest.mark.parametrize('case', PATHS)
@pytest.mark.parametrize('mode', ['control', 'confined'])
def test_single_worker_wires_real_capture_and_correlator_before_exact_reap(model, pipeline, case, mode):
    result = capture.observe_fixed_worker(pipeline, case, mode, deadline=105)
    names = [event[0] for event in model.events]
    assert names.index('verify1') < names.index('spawn') < names.index('ready') < names.index('verify2')
    assert names.index('verify2') < names.index('open') < names.index('empty') < names.index('gate')
    assert names.index('gate') < names.index('exit') < names.index('verify3') < names.index('close') < names.index('reap')
    assert model.child.reaped and not model.opened and model.closed == [20]
    assert result.worker.case_id == case and result.worker.mode == mode
    assert (result.denial is not None) == (mode == 'confined')
    assert 'SYNTHETIC_CANARY' not in repr(result)
    assert set(vars(result)) == {'worker', 'interval', 'denial'}


@pytest.mark.parametrize('fault', ['verify1', 'spawn', 'ready', 'verify2', 'open', 'gate', 'exit',
                                  'finish', 'verify3', 'correlate', 'close', 'reap'])
def test_single_worker_failure_discards_result_and_attempts_both_cleanups(model, pipeline, fault):
    model.failpoint = fault
    with pytest.raises(capture.NativeCaptureUnknown) as error:
        capture.observe_fixed_worker(pipeline, 'runtime_write', 'confined', deadline=105)
    assert 'SYNTHETIC_CANARY' not in str(error.value) and not model.opened
    if fault not in ('verify1', 'spawn'):
        assert ('abort',) in model.events
    assert len(model.closed) <= 1


@pytest.mark.parametrize('fault', ['missing', 'wrong-pid'])
def test_missing_or_unattributed_denial_never_reaps_as_success(model, pipeline, fault):
    model.no_denial, model.bad_denial = fault == 'missing', fault == 'wrong-pid'
    with pytest.raises(capture.NativeCaptureUnknown, match='^worker_observation_unknown$'):
        capture.observe_fixed_worker(pipeline, 'runtime_write', 'confined', deadline=105)
    assert ('reap',) not in model.events and ('abort',) in model.events and model.closed == [20]


def test_unknown_child_cleanup_overrides_other_failure_but_still_closes_log(model, pipeline):
    model.failpoint, model.abort_error = 'correlate', True
    with pytest.raises(capture.NativeCaptureUnknown, match='^cleanup_unknown$'):
        capture.observe_fixed_worker(pipeline, 'runtime_write', 'confined', deadline=105)
    assert model.closed == [20] and ('abort',) in model.events


@pytest.mark.parametrize('case,mode', [('shell', 'control'), ('runtime_write', 'other'), (True, 'confined')])
def test_unfixed_pipeline_input_never_acquires(model, pipeline, case, mode):
    with pytest.raises(capture.NativeCaptureRefused, match='^context$'):
        capture.observe_fixed_worker(pipeline, case, mode, deadline=105)
    assert not model.events


def test_arbitrary_fixture_context_provider_is_not_accepted(model):
    with pytest.raises(capture.NativeCaptureRefused, match='^context$'):
        capture.observe_fixed_worker(SimpleNamespace(launch_context=lambda: (BINDING, 'a' * 64)),
                                     'runtime_write', 'confined', deadline=105)
    assert not model.events


def test_new_candidate_stays_out_of_actual_public_and_inspection_payloads():
    from night_shifts.bootstrap_probe_seed import SOURCE_FILES
    from night_shifts.inspection_bundle import bundle_bytes
    assert 'bootstrap_native_capture.py' not in SOURCE_FILES
    with zipfile.ZipFile(io.BytesIO(bundle_bytes())) as archive:
        assert 'night_shifts/bootstrap_native_capture.py' not in archive.namelist()
