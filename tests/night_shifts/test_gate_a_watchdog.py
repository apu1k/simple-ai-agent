"""Watchdog policy and exact Windows signals; no elevation or Hyper-V."""
from __future__ import annotations

import ctypes as c
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from night_shifts.gate_a_watchdog import (
    CLEANUP_RESERVE_NS, MAX_RECEIPT_BYTES, MAX_WAIT_MS, MAX_WINDOW_NS, GateAWatchdog,
    HostCleanup, StopReason, TeardownTarget, WatchdogRefused, validate_cleanup_receipt,
)
from night_shifts.gate_a_watchdog_windows import WindowsWatchSignals

FINALIZATION = TeardownTarget('finalization', 'a' * 32, '51434da9-9168-428a-8624-72a246ccc18d')
SMOKE = TeardownTarget('smoke', FINALIZATION.attempt_id, FINALIZATION.vm_id)


def receipt(target: TeardownTarget, **changes: object) -> bytes:
    data = {'version': 1, 'operation': target.operation, 'id': target.attempt_id, 'vm_id': target.vm_id,
            'vm_absent': True, 'disk_unattached_and_unreferenced': True,
            'disk_retained': not target.remove_smoke_disk}
    if target.remove_smoke_disk:
        data['disk_absent'] = True
    return json.dumps({**data, **changes}).encode('ascii') + b'\r\n'


class Fixture:
    def __init__(self, target: TeardownTarget = FINALIZATION) -> None:
        self.target = target
        self.now = 10**12
        self.deadline = self.now + CLEANUP_RESERVE_NS + 410_000_000
        self.events: list[str] = []
        self.waits: list[int] = []
        self.reason: StopReason | None = StopReason.WORKER_EXITED
        self.trigger_at = 2
        self.fault = ''
        self.seal_result: object = True
        self.stdout = receipt(target)

    def clock(self) -> int:
        return self.now

    def wait(self, milliseconds: int) -> StopReason | None:
        assert 0 <= milliseconds <= MAX_WAIT_MS
        self.waits.append(milliseconds)
        self.events.append('wait')
        if self.fault == 'wait':
            raise OSError('do not disclose')
        if self.fault == 'regress':
            self.now -= 1
        elif self.fault != 'no_progress':
            self.now += milliseconds * 1_000_000
        return self.reason if len(self.waits) == self.trigger_at else None

    def arm(self) -> None:
        self.events.append('arm')
        if self.fault == 'arm':
            raise OSError('do not disclose')

    def seal(self, target: TeardownTarget, *, deadline_ns: int) -> bool:
        assert target == self.target and deadline_ns == self.deadline and self.now < deadline_ns
        self.events.append('seal')
        if self.fault == 'seal':
            raise OSError('do not disclose')
        if self.fault == 'seal_late':
            self.now = deadline_ns
        return self.seal_result  # type: ignore[return-value]  # intentionally malformed in one case

    def reconcile_once(self, target: TeardownTarget, *, deadline_ns: int) -> bytes:
        assert self.events[-1] == 'seal'
        assert target == self.target and deadline_ns == self.deadline and self.now < deadline_ns
        self.events.append('reconcile')
        if self.fault == 'reconcile':
            raise OSError('do not disclose')
        if self.fault == 'reconcile_late':
            self.now = deadline_ns
        return self.stdout

    def build(self) -> GateAWatchdog:
        return GateAWatchdog(self.target, self, self, deadline_ns=self.deadline, clock=self.clock)


@pytest.mark.parametrize('target', [FINALIZATION, SMOKE])
@pytest.mark.parametrize('reason', [StopReason.RUNTIME_EXITED, StopReason.WORKER_EXITED, StopReason.CANCELLED])
@pytest.mark.parametrize('prearmed', [False, True])
def test_exact_signal_seals_then_reconciles_once(target, reason, prearmed):
    f = Fixture(target)
    f.reason = reason
    f.trigger_at = 2 if prearmed else 1
    watchdog = f.build()
    outcome = watchdog.run()
    assert outcome.stop_reason is reason and outcome.cleanup_unknown is None
    assert outcome.cleanup == HostCleanup(target, disk_retained=target is FINALIZATION)
    assert f.events == (['wait', 'arm', 'wait'] if prearmed else ['wait']) + ['seal', 'reconcile']
    with pytest.raises(WatchdogRefused, match='one_shot'):
        watchdog.run()
    assert f.events.count('reconcile') == 1


def test_original_work_cutoff_leaves_cleanup_reserve_and_expiry_wins_over_signal():
    f = Fixture()
    f.trigger_at = 3
    result = f.build().run()
    assert result.stop_reason is StopReason.DEADLINE and result.cleanup is not None
    assert f.waits == [0, 250, 160]
    assert f.now == f.deadline - CLEANUP_RESERVE_NS


@pytest.mark.parametrize('full_expiry', [False, True])
def test_delayed_start_never_rearms_or_renews_original_deadline(full_expiry):
    f = Fixture()
    watchdog = f.build()
    f.now = f.deadline if full_expiry else f.deadline - CLEANUP_RESERVE_NS
    result = watchdog.run()
    assert result.stop_reason is StopReason.DEADLINE
    assert (result.cleanup is not None) is not full_expiry
    assert f.events == ([] if full_expiry else ['seal', 'reconcile'])


@pytest.mark.parametrize('fault', ['wait', 'arm', 'no_progress', 'invalid_reason'])
def test_signal_unknown_still_performs_safe_cleanup(fault):
    f = Fixture()
    f.fault = fault
    f.reason = StopReason.DEADLINE if fault == 'invalid_reason' else None
    result = f.build().run()
    assert result.stop_reason is StopReason.SIGNAL_UNKNOWN
    assert result.cleanup is not None and f.events[-2:] == ['seal', 'reconcile']


def test_clock_regression_never_opens_a_new_cleanup_window():
    f = Fixture()
    f.fault = 'regress'
    result = f.build().run()
    assert result.stop_reason is StopReason.SIGNAL_UNKNOWN and result.cleanup is None
    assert result.cleanup_unknown == 'window_unknown_or_expired'
    assert f.events == ['wait']


@pytest.mark.parametrize(('fault', 'expected', 'last_action'), [
    ('seal', 'lifecycle_unknown', 'seal'), ('seal_false', 'lifecycle_unknown', 'seal'),
    ('seal_truthy', 'lifecycle_unknown', 'seal'), ('seal_late', 'window_unknown_or_expired', 'seal'),
    ('reconcile', 'reconciliation_unknown', 'reconcile'), ('reconcile_bad', 'reconciliation_unknown', 'reconcile'),
    ('reconcile_late', 'window_unknown_or_expired', 'reconcile'),
])
def test_uncertain_lifecycle_or_receipt_is_terminal(fault, expected, last_action):
    f = Fixture()
    f.fault = fault
    if fault == 'seal_false':
        f.seal_result = False
    elif fault == 'seal_truthy':
        f.seal_result = 1
    elif fault == 'reconcile_bad':
        f.stdout = receipt(SMOKE)
    watchdog = f.build()
    result = watchdog.run()
    assert result.cleanup is None and result.cleanup_unknown == expected
    assert f.events[-1] == last_action
    with pytest.raises(WatchdogRefused, match='one_shot'):
        watchdog.run()
    assert f.events.count(last_action) == 1


def test_maximum_window_clamped_by_refusal_not_renewal():
    f = Fixture()
    f.deadline = f.now + MAX_WINDOW_NS + 1
    with pytest.raises(WatchdogRefused, match='window'):
        f.build()
    assert not f.events


@pytest.mark.parametrize(('operation', 'identity', 'vm_id'), [
    ('inspection', FINALIZATION.attempt_id, FINALIZATION.vm_id),
    ('smoke', 'A' * 32, FINALIZATION.vm_id),
    ('smoke', 'a' * 33, FINALIZATION.vm_id),
    ('smoke', FINALIZATION.attempt_id, FINALIZATION.vm_id.upper()),
    ('smoke', FINALIZATION.attempt_id, '00000000-0000-0000-0000-000000000000'),
])
def test_fixed_target_binding(operation, identity, vm_id):
    with pytest.raises(WatchdogRefused, match='target'):
        TeardownTarget(operation, identity, vm_id)


@pytest.mark.parametrize('raw', [
    b'', b' ' * (MAX_RECEIPT_BYTES + 1), b'[]', b'\xff', receipt(SMOKE),
    receipt(FINALIZATION, version=True), receipt(FINALIZATION, vm_absent=1),
    receipt(FINALIZATION, disk_retained=False), receipt(FINALIZATION, disk_absent=True),
    receipt(FINALIZATION, id='b' * 32), receipt(FINALIZATION, vm_id='00000000-0000-0000-0000-000000000000'),
    receipt(FINALIZATION).replace(b'"version": 1', b'"version": 1, "version": 1'),
    receipt(FINALIZATION) + b'{}',
])
def test_reject_unverified_or_ambiguous_receipt(raw):
    with pytest.raises(WatchdogRefused, match='receipt'):
        validate_cleanup_receipt(FINALIZATION, raw)


def test_smoke_receipt_requires_disk_absence_not_just_vm_absence():
    with pytest.raises(WatchdogRefused, match='receipt'):
        validate_cleanup_receipt(SMOKE, receipt(SMOKE).replace(b', "disk_absent": true', b''))


@pytest.mark.skipif(os.name != 'nt' or c.sizeof(c.c_void_p) != 8, reason='native x64 Windows handles')
@pytest.mark.parametrize('reason', [StopReason.RUNTIME_EXITED, StopReason.WORKER_EXITED, StopReason.CANCELLED])
def test_windows_watchdog_sees_exact_child_exit_or_cancellation_from_outside(reason):
    kernel = c.WinDLL('kernel32', use_last_error=True)
    for name, args, value in (
        ('CreateEventW', [c.c_void_p, c.c_int, c.c_int, c.c_wchar_p], c.c_void_p),
        ('OpenProcess', [c.c_uint32, c.c_int, c.c_uint32], c.c_void_p),
        ('WaitForSingleObject', [c.c_void_p, c.c_uint32], c.c_uint32),
        ('SetEvent', [c.c_void_p], c.c_int), ('CloseHandle', [c.c_void_p], c.c_int),
    ):
        fn = getattr(kernel, name)
        fn.argtypes, fn.restype = args, value
    handles = []
    processes = []
    try:
        for _ in range(2):
            event = kernel.CreateEventW(None, True, False, None)
            assert event
            handles.append(event)
            process = subprocess.Popen([sys.executable, '-I', '-c', 'import sys; sys.stdin.buffer.read()'],
                                       stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            processes.append(process)
            handle = kernel.OpenProcess(0x101000, False, process.pid)  # synchronize/query only; fixture
            assert handle
            handles.append(handle)
        cancelled, runtime, armed, worker = handles
        signals = WindowsWatchSignals(cancelled=cancelled, runtime=runtime, worker=worker, armed=armed)
        assert signals.wait(0) is None
        lifecycle = Fixture()
        lifecycle.deadline = time.monotonic_ns() + CLEANUP_RESERVE_NS + 3_000_000_000
        watchdog = GateAWatchdog(FINALIZATION, signals, lifecycle, deadline_ns=lifecycle.deadline)
        with ThreadPoolExecutor(max_workers=1) as pool:
            result = pool.submit(watchdog.run)
            assert kernel.WaitForSingleObject(armed, 2000) == 0
            if reason is StopReason.CANCELLED:
                assert kernel.SetEvent(cancelled)
            else:
                child = processes[0 if reason is StopReason.RUNTIME_EXITED else 1]
                assert child.stdin is not None
                child.stdin.close()  # EOF exits only the exact fixture process; no Hyper-V
            observed = result.result(timeout=4)
        assert observed.stop_reason is reason and observed.cleanup == HostCleanup(FINALIZATION, True)
        assert lifecycle.events == ['seal', 'reconcile']
        with pytest.raises(WatchdogRefused, match='signal_arm'):
            signals.arm()
    finally:
        for process in processes:
            if process.stdin is not None:
                process.stdin.close()
            if process.poll() is None:
                process.kill()
            process.wait(timeout=3)
        for handle in handles:
            kernel.CloseHandle(handle)
