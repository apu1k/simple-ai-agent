"""Exercise the stop/start race with fixture actions; never launch a real VM."""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from night_shifts.gate_a_host_lifecycle import GateAHostLifecycle
from night_shifts.gate_a_watchdog import CLEANUP_RESERVE_NS, MAX_RECEIPT_BYTES, StopReason, TeardownTarget, WatchdogRefused

_ID = 'a' * 32
_VM = '51434da9-9168-428a-8624-72a246ccc18d'
_ROOT = r'D:\NightShift\fresh attempts'
_START, _CLEANUP = 'start_gate_a_vm.ps1', 'reconcile_gate_a_vm.ps1'


class Signals:
    def __init__(self):
        self.armed = Event()
        self.cancel = Event()

    def wait(self, ms):
        return StopReason.CANCELLED if self.cancel.wait(ms / 1000) else None

    def arm(self):
        self.armed.set()


class Actions:
    def __init__(self, op):
        self.target = TeardownTarget(op, _ID, _VM)
        self.boot = r'D:\NightShift\sources\ubuntu.iso' if op == 'finalization' else r'D:\NightShift\images\base.vhdx'
        self.deadline = time.monotonic_ns() + CLEANUP_RESERVE_NS + 10_000_000_000
        self.calls = []
        self.start_inflight, self.finish_start = Event(), Event()
        self.finish_start.set()
        self.start_outcome = 'running_observed'

    def host(self, **opts):
        return GateAHostLifecycle(self.target, held_workspace_root=opts.get('root', _ROOT),
                                  held_boot_asset=opts.get('asset', self.boot), actions=self,
                                  deadline_ns=self.deadline, clock=opts.get('clock', time.monotonic_ns))

    def run(self, fixed_script, args, *, deadline_ns, stdout_limit):
        assert stdout_limit == MAX_RECEIPT_BYTES
        self.calls.append(fixed_script)
        common = ('-Operation', self.target.operation, '-Identity', _ID, '-VmId', _VM, '-WorkspaceRoot', _ROOT)
        result = {'version': 1, 'operation': self.target.operation, 'id': _ID, 'vm_id': _VM}
        if fixed_script == _START:
            assert deadline_ns == self.deadline - CLEANUP_RESERVE_NS
            assert args == (*common, '-BootAsset', self.boot, '-WorkUntilNanoseconds', str(deadline_ns))
            self.start_inflight.set()
            assert self.finish_start.wait(3)
            if self.start_outcome == 'process_failed':
                raise RuntimeError('redact this evidence')
            if self.start_outcome == 'wrong_vm':
                result['vm_id'] = '0' * 36
            result['state'] = self.start_outcome
        else:
            assert fixed_script == _CLEANUP and deadline_ns == self.deadline
            assert args == common + (('-RemoveSmokeDisk',) if self.target.remove_smoke_disk else ())
            result.update(vm_absent=True, disk_unattached_and_unreferenced=True,
                          disk_retained=not self.target.remove_smoke_disk)
            if self.target.remove_smoke_disk:
                result['disk_absent'] = True
        return json.dumps(result).encode('ascii')


@pytest.mark.parametrize('op', ['finalization', 'smoke'])
@pytest.mark.parametrize('outcome', ['running_observed', 'not_started'])
def test_host_admits_only_after_watchdog_and_binds_both_fixed_actions(op, outcome):
    a, sig = Actions(op), Signals()
    a.start_outcome = outcome
    host = a.host()
    with pytest.raises(WatchdogRefused, match='start_closed'):
        host.start_once()
    with pytest.raises(WatchdogRefused, match='reconcile_closed'):
        host.reconcile_once(a.target, deadline_ns=a.deadline)
    assert a.calls == []
    with ThreadPoolExecutor(max_workers=1) as pool:
        watch = pool.submit(host.watch, sig)
        try:
            assert sig.armed.wait(2)
            assert host.start_once() == (outcome == 'running_observed')
            with pytest.raises(WatchdogRefused, match='start_closed'):
                host.start_once()
        finally:
            sig.cancel.set()
        result = watch.result(3)
    assert result.stop_reason is StopReason.CANCELLED
    assert result.cleanup is not None and result.cleanup.disk_retained == (op == 'finalization')
    assert a.calls == [_START, _CLEANUP]
    with pytest.raises(WatchdogRefused, match='one_shot'):
        host.watch(sig)
    with pytest.raises(WatchdogRefused, match='reconcile_closed'):
        host.reconcile_once(a.target, deadline_ns=a.deadline)


@pytest.mark.parametrize('outcome', ['running_observed', 'process_failed', 'wrong_vm'])
def test_cancellation_closes_admission_and_waits_for_settlement_not_just_exit(outcome):
    a, sig = Actions('finalization'), Signals()
    a.start_outcome = outcome
    a.finish_start.clear()
    host = a.host()
    with ThreadPoolExecutor(max_workers=2) as pool:
        watch = pool.submit(host.watch, sig)
        try:
            assert sig.armed.wait(2)
            start = pool.submit(host.start_once)
            assert a.start_inflight.wait(2)
            sig.cancel.set()
            until = time.monotonic() + 2
            while time.monotonic() < until:
                with host._changed:
                    if host._sealed:
                        break
                time.sleep(0.001)
            assert host._sealed
            assert not watch.done() and a.calls == [_START]
        finally:
            a.finish_start.set()
            sig.cancel.set()
        if outcome == 'running_observed':
            assert start.result(3) is False  # successful provider return, but no new work after seal
        else:
            with pytest.raises(WatchdogRefused, match='^start_unknown$'):
                start.result(3)
        result = watch.result(3)
    if outcome == 'running_observed':
        assert result.cleanup is not None and a.calls == [_START, _CLEANUP]
    else:
        assert result.cleanup is None and result.cleanup_unknown == 'lifecycle_unknown'
        assert a.calls == [_START]


def test_presignalled_cancel_reconciles_without_arming_or_starting():
    a, sig = Actions('smoke'), Signals()
    host = a.host()
    sig.cancel.set()
    result = host.watch(sig)
    assert result.cleanup is not None and not sig.armed.is_set()
    with pytest.raises(WatchdogRefused, match='start_closed'):
        host.start_once()
    assert a.calls == [_CLEANUP]


@pytest.mark.parametrize('asset', [r'D:\NightShift\fake.iso:payload', r'D:\NightShift\CON.iso',
                                  r'D:\NightShift\..\other.iso', r'\\server\test\boot.iso',
                                  _ROOT + '\\' + _ID + r'\second.iso', r'D:\NightShift\worker.vhdx'])
def test_refuses_invalid_or_overlapping_held_asset(asset):
    a = Actions('finalization')
    with pytest.raises(WatchdogRefused, match='held_path'):
        a.host(asset=asset)
    assert a.calls == []
