"""Offline fixed-sequence models; NEVER launch worker/VM or read native logs.

Native single-worker calls and fixture ownership are replaced. Actual paired
and denial correlation consume synthetic records; no fabricated summary is
accepted as native evidence or a host receipt. No generated source is executed.
"""
from __future__ import annotations

import io
import json
import zipfile
from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace

import pytest

from night_shifts import bootstrap_native_sequence as sequence
from night_shifts.bootstrap_native_capture import LocalCapturedWorker, LocalKernelInterval, NativeCaptureUnknown
from night_shifts.bootstrap_native_denials import LocalDenialCorrelation
from night_shifts.bootstrap_native_supervision import CASES, POOL_CASE, LocalWorkerObservation
from night_shifts.maintenance_tls_prototype import AttemptBinding
from tests.night_shifts.test_bootstrap_native_denials import record

BINDING = AttemptBinding('1' * 32, '00000000-0000-4000-8000-000000000001')
OTHER = AttemptBinding('2' * 32, '00000000-0000-4000-8000-000000000002')
ORDER = ((POOL_CASE, 'confined'), *((case, mode) for case in CASES
          for mode in ('control', 'confined', 'control')), (POOL_CASE, 'confined'))


@pytest.fixture
def model(monkeypatch):
    state = SimpleNamespace(now=100.0, stopped=False, calls=[], fail_at=None, cleanup_unknown=False,
                            mutate=None, duration=0.2, change_context=False)

    class Fixtures:
        def __init__(self):
            self.context = (BINDING, 'a' * 64)

        def launch_context(self):
            return self.context

    state.fixtures = Fixtures()

    def observe(fixtures, case, mode, *, deadline, cancelled):
        index = len(state.calls)
        state.calls.append((case, mode, deadline, cancelled))
        assert fixtures is state.fixtures and cancelled() is False
        if index == state.fail_at:
            if state.cleanup_unknown:
                raise NativeCaptureUnknown('cleanup_unknown')
            raise RuntimeError('SYNTHETIC_CANARY')
        began = state.now
        pid, baseline, serial = 100 + index, 1000 + index * 10, 2000 + index
        negative = case in CASES and mode == 'confined'
        kind = ('pools_checked' if case == POOL_CASE else 'syscall_error' if negative
                else 'control_exec' if case == 'outside_exec' else 'control_written')
        worker = LocalWorkerObservation(BINDING, case, mode, pid, kind, 13 if negative else 0,
                    37 if case == 'outside_exec' and mode == 'control' else 0, began + 0.01, began + 0.05)
        raw = record(case, sequence=baseline + 1, timestamp=int((began + 0.03) * 1e6), pid=pid).replace(
            b':71):', (':' + str(serial) + '):').encode('ascii')) if negative else None
        interval = LocalKernelInterval(baseline, int((began + 0.02) * 1e6), int((began + 0.1) * 1e6),
                                       (raw,) if raw is not None else ())
        denial = LocalDenialCorrelation(case, pid, baseline + 1, serial) if negative else None
        result = LocalCapturedWorker(worker, interval, denial)
        state.now += state.duration
        if state.change_context:
            state.fixtures.context = (OTHER, 'b' * 64)
        if state.mutate is not None:
            result = state.mutate(result, index)
        return result

    monkeypatch.setattr(sequence, 'NativeRamFixtures', Fixtures)
    monkeypatch.setattr(sequence, 'observe_fixed_worker', observe)
    monkeypatch.setattr(sequence, 'time', SimpleNamespace(monotonic=lambda: state.now))
    return state


def acquire(model, **changes):
    fields = dict(deadline=160, cancelled=lambda: model.stopped)
    fields.update(changes)
    return sequence.NativeValidationSequence(model.fixtures, **fields)


def test_exact_eleven_worker_order_real_pairing_and_bounded_local_summary(model):
    runner = acquire(model)
    result = runner.run()
    assert tuple((case, mode) for case, mode, _, _ in model.calls) == ORDER
    assert len(model.calls) == 11 and result.pool_worker_pids == (100, 110)
    assert tuple(pair.case_id for pair in result.paired) == CASES
    assert [pair.worker_pids for pair in result.paired] == [(101, 102, 103), (104, 105, 106), (107, 108, 109)]
    assert all(deadline <= 160 and deadline <= 105 + index * 0.2 + 1e-9
               for index, (_, _, deadline, _) in enumerate(model.calls))
    raw = result.summary_bytes()
    value = json.loads(raw)
    assert len(raw) <= 512 and raw.endswith(b'\n')
    assert value == dict(kind='local_native_sequence_observation', scope='local_consistency_only',
                        attempt_id=BINDING.attempt_id, vm_id=BINDING.vm_id, workers_observed=11,
                        paired_cases=list(CASES), confined_pool_controls=2, allowed_pool_files=5)
    assert b'SYNTHETIC_CANARY' not in raw and b'kernel_sequence' not in raw and b'seed_sha256' not in raw
    assert set(vars(result)) == {'binding', 'pool_worker_pids', 'paired', 'started_at', 'finished_at'}
    with pytest.raises(FrozenInstanceError):
        result.finished_at = 0
    with pytest.raises(sequence.NativeSequenceRefused, match='^terminal$'):
        runner.run()
    assert len(model.calls) == 11


@pytest.mark.parametrize('index', range(11))
def test_each_worker_failure_stops_without_next_worker_or_retry(model, index):
    model.fail_at = index
    runner = acquire(model)
    with pytest.raises(sequence.NativeSequenceUnknown, match='^sequence_unknown$') as error:
        runner.run()
    assert 'SYNTHETIC_CANARY' not in str(error.value) and len(model.calls) == index + 1
    with pytest.raises(sequence.NativeSequenceRefused, match='^terminal$'):
        runner.run()
    assert len(model.calls) == index + 1


def test_cleanup_unknown_is_not_downgraded_or_retried(model):
    model.fail_at, model.cleanup_unknown = 2, True
    runner = acquire(model)
    with pytest.raises(sequence.NativeSequenceUnknown, match='^cleanup_unknown$'):
        runner.run()
    assert len(model.calls) == 3


@pytest.mark.parametrize('changes', [dict(deadline=True), dict(deadline=float('nan')), dict(deadline=float('inf')),
                                    dict(deadline=161), dict(deadline=100), dict(cancelled=0)])
def test_invalid_outer_budget_never_invokes_child(model, changes):
    with pytest.raises(sequence.NativeSequenceRefused):
        acquire(model, **changes)
    assert not model.calls


@pytest.mark.parametrize('fault', ['cancelled', 'deadline', 'regression', 'callback'])
def test_outer_failure_before_run_is_terminal(model, fault):
    runner = acquire(model)
    if fault == 'cancelled':
        model.stopped = True
    elif fault == 'deadline':
        model.now = 160.0
    elif fault == 'regression':
        model.now = 99.0
    else:
        runner._cancelled = lambda: (_ for _ in ()).throw(KeyboardInterrupt())
    with pytest.raises(sequence.NativeSequenceRefused):
        runner.run()
    assert not model.calls
    with pytest.raises(sequence.NativeSequenceRefused, match='^terminal$'):
        runner.run()


def test_original_outer_deadline_limits_new_worker_deadlines_without_renewal(model):
    runner = acquire(model, deadline=100.9)
    with pytest.raises(sequence.NativeSequenceUnknown):
        runner.run()
    assert len(model.calls) == 5 and all(call[2] <= 100.9 for call in model.calls)


def test_new_worker_cannot_return_after_its_own_five_second_budget(model):
    model.duration = 5.0
    with pytest.raises(sequence.NativeSequenceUnknown, match='^worker_observation_unknown$'):
        acquire(model).run()
    assert len(model.calls) == 1


@pytest.mark.parametrize('field,value', [('binding', OTHER), ('case_id', 'other'), ('mode', 'control'),
                                       ('worker_pid', True), ('worker_pid', 0), ('observation', 'syscall_error'),
                                       ('syscall_errno', True), ('syscall_errno', 13), ('exit_code', True),
                                       ('exit_code', 125), ('started_at', 99.0), ('finished_at', 110.0)])
def test_mixed_or_invalid_worker_observation_stops_early(model, field, value):
    def mutate(result, index):
        return replace(result, worker=replace(result.worker, **{field: value}))
    model.mutate = mutate
    with pytest.raises(sequence.NativeSequenceUnknown, match='^worker_observation_unknown$'):
        acquire(model).run()
    assert len(model.calls) == 1


def test_duplicate_pid_even_across_pool_and_denial_cases_refuses(model):
    def mutate(result, index):
        return replace(result, worker=replace(result.worker, worker_pid=100)) if index == 1 else result
    model.mutate = mutate
    with pytest.raises(sequence.NativeSequenceUnknown):
        acquire(model).run()
    assert len(model.calls) == 2


@pytest.mark.parametrize('field,value', [('baseline_sequence', True), ('baseline_sequence', -1),
                                       ('start_us', True), ('end_us', 100_000_000),
                                       ('end_us', 200_000_000), ('records', [b'not-tuple']),
                                       ('records', (b'',)), ('records', (b'x',) * 65)])
def test_invalid_capture_shape_cannot_be_joined(model, field, value):
    def mutate(result, index):
        return replace(result, interval=replace(result.interval, **{field: value}))
    model.mutate = mutate
    with pytest.raises(sequence.NativeSequenceUnknown, match='^capture_observation_unknown$'):
        acquire(model).run()
    assert len(model.calls) == 1


@pytest.mark.parametrize('fault', ['missing', 'wrong-pid', 'wrong-serial', 'malformed-record', 'unexpected-control-denial'])
def test_bad_denial_or_pair_correlation_never_reaches_next_case(model, fault):
    def mutate(result, index):
        if fault == 'unexpected-control-denial' and index == 0:
            return replace(result, denial=LocalDenialCorrelation('runtime_write', 100, 1, 1))
        if index != 2:
            return result
        if fault == 'missing':
            return replace(result, denial=None)
        if fault == 'wrong-pid':
            return replace(result, denial=replace(result.denial, worker_pid=999))
        if fault == 'wrong-serial':
            return replace(result, denial=replace(result.denial, audit_serial=999))
        if fault == 'malformed-record':
            return replace(result, interval=replace(result.interval, records=(b'not kmsg',)))
        return result
    model.mutate = mutate
    with pytest.raises(sequence.NativeSequenceUnknown):
        acquire(model).run()
    assert len(model.calls) <= 4


@pytest.mark.parametrize('when', ['before', 'during'])
def test_changed_held_fixture_context_never_continues(model, when):
    runner = acquire(model)
    if when == 'before':
        model.fixtures.context = (OTHER, 'b' * 64)
    else:
        model.change_context = True
    with pytest.raises(sequence.NativeSequenceUnknown, match='^fixture_context_unknown$'):
        runner.run()
    assert len(model.calls) == (0 if when == 'before' else 1)


def test_bounded_summary_failure_is_terminal_after_observation_not_a_replay(model, monkeypatch):
    runner = acquire(model)
    monkeypatch.setattr(sequence, 'MAX_SUMMARY_BYTES', 1)
    with pytest.raises(sequence.NativeSequenceRefused, match='^summary_bound$'):
        runner.run()
    with pytest.raises(sequence.NativeSequenceRefused, match='^terminal$'):
        runner.run()
    assert len(model.calls) == 11


def test_no_arbitrary_fixture_provider_or_catalog(model):
    with pytest.raises(sequence.NativeSequenceRefused, match='^context$'):
        sequence.NativeValidationSequence(SimpleNamespace(launch_context=lambda: (BINDING, 'a' * 64)), deadline=160)
    assert not model.calls


def test_sequence_stays_out_of_real_public_and_inspection_inventories():
    from night_shifts.bootstrap_probe_seed import SOURCE_FILES
    from night_shifts.inspection_bundle import bundle_bytes
    assert 'bootstrap_native_sequence.py' not in SOURCE_FILES
    with zipfile.ZipFile(io.BytesIO(bundle_bytes())) as archive:
        assert 'night_shifts/bootstrap_native_sequence.py' not in archive.namelist()
