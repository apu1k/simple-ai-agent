"""Offline protocol/clock/audit models only; no native worker, ELF or log I/O."""
from __future__ import annotations

import errno
import io
import json
import zipfile
from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace

import pytest

from night_shifts import bootstrap_native_supervision as core
from night_shifts.guest import bootstrap_native_worker as worker
from night_shifts.maintenance_tls_prototype import AttemptBinding
from tests.night_shifts.test_bootstrap_native_denials import record

BINDING = AttemptBinding('1' * 32, '00000000-0000-4000-8000-000000000001')


class Clock:
    def __init__(self, now=100.0):
        self.now = now
        self.stopped = False

    def __call__(self):
        return self.now


def session(case='runtime_write', mode='confined', pid=222, start=100.0):
    clock = Clock(start)
    state = core.WorkerReportSession(BINDING, case, mode, pid, deadline=start + 5,
                                     clock=clock, cancelled=lambda: clock.stopped)
    return state, clock


def frame(case='runtime_write', mode='confined', pid=222, phase='ready', **fields):
    return (json.dumps(dict(case_id=case, mode=mode, pid=pid, phase=phase, **fields),
                       sort_keys=True, separators=(',', ':')) + '\n').encode('ascii')


def release(state, case='runtime_write', mode='confined', pid=222):
    state.feed(frame(case, mode, pid))
    assert state.ready_for_release
    state.mark_gate_released()
    assert not state.ready_for_release


def observed(case='runtime_write', mode='confined', pid=222, start=101.0):
    state, clock = session(case, mode, pid, start)
    release(state, case, mode, pid)
    if mode == 'confined':
        state.feed(frame(case, mode, pid, 'result', observation='syscall_error', errno=errno.EACCES))
    elif case != 'outside_exec':
        state.feed(frame(case, mode, pid, 'result', observation='control_written', errno=0))
    state.end_of_reports()
    clock.now += 0.1
    return state.finish_exit(worker_pid=pid, exit_code=37 if mode == 'control' and case == 'outside_exec' else 0)


@pytest.mark.parametrize('case', core.CASES)
@pytest.mark.parametrize('chunk', [1, 7, 256])
def test_incremental_negative_reports_require_release_eof_and_exact_normal_exit(case, chunk):
    state, clock = session(case)
    ready = frame(case)
    for offset in range(0, len(ready), chunk):
        state.feed(ready[offset:offset + chunk])
    assert state.ready_for_release
    state.mark_gate_released()
    result = frame(case, phase='result', observation='syscall_error', errno=13)
    for offset in range(0, len(result), chunk):
        state.feed(result[offset:offset + chunk])
    state.end_of_reports()
    clock.now = 101
    observation = state.finish_exit(worker_pid=222, exit_code=0)
    assert observation == core.LocalWorkerObservation(BINDING, case, 'confined', 222,
                                                     'syscall_error', 13, 0, 100.0, 101.0)
    with pytest.raises(FrozenInstanceError):
        observation.worker_pid = 1
    with pytest.raises(core.NativeSupervisionRefused, match='^terminal$'):
        state.feed(ready)


@pytest.mark.parametrize('case', core.CASES)
def test_positive_control_exec_has_no_result_only_for_the_fixed_exit_37(case):
    result = observed(case, 'control', 111, 100)
    assert result.observation == ('control_exec' if case == 'outside_exec' else 'control_written')
    assert result.exit_code == (37 if case == 'outside_exec' else 0)


@pytest.mark.parametrize('case', core.CASES)
@pytest.mark.parametrize('mode', ['control', 'confined'])
def test_actual_worker_message_encoder_matches_core_without_running_worker(model_unused=None, *, case, mode, monkeypatch):
    # Call only _message with substituted clock/write/getpid; never preflight,
    # run_fixed_case, fixture creation, native operation, exec or policy transition.
    raw = []
    monkeypatch.setattr(worker, 'time', SimpleNamespace(monotonic=lambda: 100.0))
    monkeypatch.setattr(worker, 'os', SimpleNamespace(getpid=lambda: 222,
                        write=lambda fd, data: raw.append(data) or len(data)))
    context = dict(case_id=case, mode=mode, deadline='105')
    worker._message(context, 'ready', {})
    state, _ = session(case, mode)
    state.feed(raw.pop())
    state.mark_gate_released()
    if not (case == 'outside_exec' and mode == 'control'):
        fields = dict(observation='syscall_error', errno=13) if mode == 'confined' else dict(observation='control_written', errno=0)
        worker._message(context, 'result', fields)
        state.feed(raw.pop())
    state.end_of_reports()
    result = state.finish_exit(worker_pid=222, exit_code=37 if case == 'outside_exec' and mode == 'control' else 0)
    assert result.case_id == case and result.mode == mode


def test_exact_frame_and_total_byte_boundaries():
    state, _ = session()
    def padded(raw):
        return raw[:-1] + b' ' * (256 - len(raw)) + b'\n'
    ready = padded(frame())
    result = padded(frame(phase='result', observation='syscall_error', errno=13))
    assert len(ready) == len(result) == 256
    state.feed(ready)
    state.mark_gate_released()
    state.feed(result)
    state.end_of_reports()
    assert state.finish_exit(worker_pid=222, exit_code=0).syscall_errno == 13


@pytest.mark.parametrize('raw', [b'', b'x' * 513, b'x' * 256, b'x' * 256 + b'\n', bytearray(b'x'), None],
                         ids=['empty', 'chunk-overflow', 'unterminated-frame', 'frame-overflow', 'bytearray', 'none'])
def test_report_bounds_are_terminal_without_raw_error_echo(raw):
    state, _ = session()
    with pytest.raises(core.NativeSupervisionRefused, match='^report_bound$'):
        state.feed(raw)
    with pytest.raises(core.NativeSupervisionRefused, match='^report_bound$'):
        state.feed(frame())


@pytest.mark.parametrize('raw', [b'\xff\n', b'[]\n', b'\n', b'{"phase":NaN}\n',
                                 b'{"phase":"ready","phase":"ready"}\n'])
def test_non_ascii_non_object_duplicates_and_constants_refuse(raw):
    state, _ = session()
    with pytest.raises(core.NativeSupervisionRefused, match='^report_shape$'):
        state.feed(raw)


@pytest.mark.parametrize('fields', [dict(case_id='pool_sibling_write'), dict(mode='control'),
                                    dict(pid=333), dict(pid=True), dict(pid='222')])
def test_report_identity_is_compared_to_expected_owned_child_not_learned_from_frame(fields):
    value = dict(case_id='runtime_write', mode='confined', pid=222, phase='ready')
    value.update(fields)
    state, _ = session()
    with pytest.raises(core.NativeSupervisionRefused, match='^report_identity$'):
        state.feed((json.dumps(value) + '\n').encode())


@pytest.mark.parametrize('action', ['result_first', 'result_before_release', 'duplicate_ready',
                                   'release_first', 'duplicate_release', 'partial_before_release',
                                   'coalesced_early_result'])
def test_ready_and_gate_order_cannot_be_bypassed(action):
    state, _ = session()
    result = frame(phase='result', observation='syscall_error', errno=13)
    with pytest.raises(core.NativeSupervisionRefused):
        if action == 'result_first':
            state.feed(result)
        elif action == 'release_first':
            state.mark_gate_released()
        elif action == 'coalesced_early_result':
            state.feed(frame() + result)
        else:
            state.feed(frame())
            if action == 'result_before_release':
                state.feed(result)
            elif action == 'duplicate_ready':
                state.feed(frame())
            elif action == 'duplicate_release':
                state.mark_gate_released()
                state.mark_gate_released()
            else:
                state.feed(b'{')
                assert not state.ready_for_release
                state.mark_gate_released()


@pytest.mark.parametrize('fields', [dict(observation='other', errno=13), dict(observation='syscall_error', errno=True),
                                    dict(observation='syscall_error', errno=0), dict(observation='syscall_error', errno=4096),
                                    dict(observation='control_written', errno=0), dict(observation='unexpected_open', errno=1)])
def test_invalid_observation_or_errno_semantics(fields):
    state, _ = session()
    release(state)
    with pytest.raises(core.NativeSupervisionRefused, match='^result_semantics$'):
        state.feed(frame(phase='result', **fields))


@pytest.mark.parametrize('action', ['duplicate_result', 'third_frame', 'extra_ready_field', 'wrong_phase', 'aggregate_overflow'])
def test_frame_count_unknown_fields_phases_and_aggregate_bound(action):
    state, _ = session()
    if action == 'extra_ready_field':
        raw = frame(private='SYNTHETIC_CANARY')
    elif action == 'wrong_phase':
        raw = frame(phase='unexpected')
    else:
        release(state)
        raw = frame(phase='result', observation='syscall_error', errno=13)
        state.feed(raw)
        if action == 'third_frame':
            raw = frame()
        elif action == 'aggregate_overflow':
            raw = b'x' * (513 - state._total)
    with pytest.raises(core.NativeSupervisionRefused) as failure:
        state.feed(raw)
    assert 'SYNTHETIC_CANARY' not in str(failure.value)


@pytest.mark.parametrize('action,label', [('eof_first', 'eof_order'), ('truncated', 'report_truncated_unknown'),
                                         ('exit_before_eof', 'exit_incomplete_unknown'), ('missing_result', 'result_missing_unknown')])
def test_missing_or_incomplete_reports_are_unknown_not_execution_proof(action, label):
    state, _ = session()
    with pytest.raises(core.NativeSupervisionUnknown, match='^' + label + '$'):
        if action == 'eof_first':
            state.end_of_reports()
        else:
            release(state)
            if action == 'truncated':
                state.feed(b'{')
            if action != 'exit_before_eof':
                state.end_of_reports()
            state.finish_exit(worker_pid=222, exit_code=0)


@pytest.mark.parametrize('fields', [dict(worker_pid=333, exit_code=0), dict(worker_pid=True, exit_code=0),
                                    dict(worker_pid=222, exit_code=-9), dict(worker_pid=222, exit_code=True)])
def test_normal_exact_exit_is_not_inferred_from_signal_bool_or_different_pid(fields):
    state, _ = session()
    release(state)
    state.feed(frame(phase='result', observation='syscall_error', errno=13))
    state.end_of_reports()
    with pytest.raises(core.NativeSupervisionUnknown, match='^exit_identity_unknown$'):
        state.finish_exit(**fields)


@pytest.mark.parametrize('case', core.CASES)
def test_unexpected_negative_open_or_exec_is_a_failed_denial(case):
    state, _ = session(case)
    release(state, case)
    if case != 'outside_exec':
        state.feed(frame(case, phase='result', observation='unexpected_open', errno=0))
    state.end_of_reports()
    with pytest.raises(core.NativeSupervisionRefused, match='^negative_allowed$'):
        state.finish_exit(worker_pid=222, exit_code=37 if case == 'outside_exec' else 0)


@pytest.mark.parametrize('number', [errno.EPERM, errno.ENOENT, errno.EROFS])
def test_other_errno_is_not_apparmor_attribution(number):
    state, _ = session()
    release(state)
    state.feed(frame(phase='result', observation='syscall_error', errno=number))
    state.end_of_reports()
    with pytest.raises(core.NativeSupervisionUnknown, match='^syscall_not_eacces_unknown$'):
        state.finish_exit(worker_pid=222, exit_code=0)


def test_failed_positive_control_and_inconsistent_exit_do_not_count():
    for mode, exit_code, expected in [('control', 0, 'control_failed'), ('confined', 1, 'exit_status_unknown')]:
        state, _ = session(mode=mode)
        release(state, mode=mode)
        state.feed(frame(mode=mode, phase='result', observation='syscall_error', errno=13))
        state.end_of_reports()
        with pytest.raises(core.NativeSupervisionRefused, match='^' + expected + '$'):
            state.finish_exit(worker_pid=222, exit_code=exit_code)


def test_deadline_is_not_renewed_and_expired_finish_cannot_return_observation():
    state, clock = session()
    release(state)
    clock.now = 104.9
    state.feed(frame(phase='result', observation='syscall_error', errno=13))
    state.end_of_reports()
    clock.now = 105
    with pytest.raises(core.NativeSupervisionUnknown, match='^deadline_unknown$'):
        state.finish_exit(worker_pid=222, exit_code=0)
    clock.now = 100
    with pytest.raises(core.NativeSupervisionUnknown, match='^deadline_unknown$'):
        state.feed(frame())


@pytest.mark.parametrize('change,label', [('cancel', 'cancelled_unknown'), ('backwards', 'budget_check_unknown'),
                                        ('nan', 'budget_check_unknown'), ('nonbool', 'budget_check_unknown')])
def test_cancellation_and_clock_failures_are_terminal(change, label):
    state, clock = session()
    release(state)
    if change == 'cancel':
        clock.stopped = True
    elif change == 'backwards':
        clock.now = 99
    elif change == 'nan':
        clock.now = float('nan')
    else:
        clock.stopped = 1
    with pytest.raises(core.NativeSupervisionUnknown, match='^' + label + '$'):
        state.end_of_reports()
    clock.now, clock.stopped = 100, False
    with pytest.raises(core.NativeSupervisionUnknown, match='^' + label + '$'):
        state.end_of_reports()


@pytest.mark.parametrize('fields', [dict(case_id='network'), dict(case_id=[]), dict(mode='other'),
                                    dict(worker_pid=True), dict(worker_pid=0), dict(worker_pid=1 << 22),
                                    dict(deadline=True), dict(deadline=float('nan')), dict(deadline=float('inf')),
                                    dict(deadline=100), dict(deadline=105.1), dict(deadline=10 ** 1000),
                                    dict(binding=None)], ids=['case', 'unhashable-case', 'mode', 'bool-pid', 'zero-pid',
                                    'pid-limit', 'bool-time', 'nan', 'infinity', 'expired', 'too-long', 'huge-int', 'binding'])
def test_invalid_context_refuses_without_native_activity(fields):
    arguments = dict(binding=BINDING, case_id='runtime_write', mode='confined', worker_pid=222,
                     deadline=105, clock=Clock())
    arguments.update(fields)
    with pytest.raises(core.NativeSupervisionRefused, match='^context$'):
        core.WorkerReportSession(**arguments)


def triple(case='runtime_write'):
    return (observed(case, 'control', 111, 100), observed(case, 'confined', 222, 101),
            observed(case, 'control', 333, 102))


def paired(values, records=None):
    return core.correlate_paired_case(*values, baseline_sequence=40, start_us=101000000,
                                     end_us=101200000, records=records if records is not None else
                                     (record(values[1].case_id, pid=222, timestamp=101050000),))


@pytest.mark.parametrize('case', core.CASES)
def test_ordered_before_negative_after_plus_exact_audit_is_local_consistency_only(case):
    result = paired(triple(case))
    assert result == core.LocalPairedObservation(BINDING, case, (111, 222, 333), 41, 71)
    assert set(vars(result)) == {'binding', 'case_id', 'worker_pids', 'kernel_sequence', 'audit_serial'}
    assert 'SYNTHETIC_CANARY' not in repr(result)
    with pytest.raises(FrozenInstanceError):
        result.case_id = 'other'


@pytest.mark.parametrize('fault', ['binding', 'case', 'mode', 'pid', 'errno', 'kind', 'exit',
                                   'time_type', 'backwards', 'duration', 'overlap', 'object'])
def test_broken_or_mixed_controls_refuse_before_any_audit_correlation(fault, monkeypatch):
    before, negative, after = triple()
    changes = dict(binding=AttemptBinding('2' * 32, BINDING.vm_id)) if fault == 'binding' else {
        'case': dict(case_id='pool_sibling_write'), 'mode': dict(mode='confined'),
        'pid': dict(worker_pid=222), 'errno': dict(syscall_errno=True), 'kind': dict(observation='other'),
        'exit': dict(exit_code=1), 'time_type': dict(started_at=True),
        'backwards': dict(finished_at=99), 'duration': dict(finished_at=106),
        'overlap': dict(finished_at=101.5), 'object': {},
    }[fault]
    before = {} if fault == 'object' else replace(before, **changes)
    def unexpected(*args, **kwargs):
        pytest.fail('audit_must_not_run_for_bad_controls')
    monkeypatch.setattr(core, 'correlate_local_denial', unexpected)
    with pytest.raises(core.NativeSupervisionRefused, match='^paired_observations$'):
        core.correlate_paired_case(before, negative, after, baseline_sequence=40, start_us=101000000,
                                   end_us=101200000, records=())


@pytest.mark.parametrize('fault', ['missing', 'pid', 'gap', 'origin', 'mask'])
def test_missing_or_unattributable_audit_never_becomes_a_paired_observation(fault):
    raw = record(pid=223 if fault == 'pid' else 222, timestamp=101050000,
                 sequence=42 if fault == 'gap' else 41,
                 denied_mask='r' if fault == 'mask' else 'w')
    if fault == 'origin':
        raw = raw.replace(b'4,41,', b'14,41,')
    with pytest.raises(core.NativeSupervisionUnknown, match='^audit_unknown$'):
        paired(triple(), () if fault == 'missing' else (raw,))


def test_new_core_remains_excluded_from_actual_inspection_and_public_payloads():
    from night_shifts.bootstrap_probe_seed import SOURCE_FILES
    from night_shifts.inspection_bundle import bundle_bytes
    assert 'bootstrap_native_supervision.py' not in SOURCE_FILES
    with zipfile.ZipFile(io.BytesIO(bundle_bytes())) as archive:
        assert 'night_shifts/bootstrap_native_supervision.py' not in archive.namelist()
