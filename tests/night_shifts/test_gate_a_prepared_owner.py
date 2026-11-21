"""Start/worker/watchdog composition. Uses fixture actions, not real Hyper-V."""
from __future__ import annotations

import ctypes as c
import json
import os
import subprocess
import sys
import time
from threading import Event

import pytest

from night_shifts.gate_a_host_lifecycle import _RECONCILE, _START, GateAHostLifecycle
from night_shifts.gate_a_prepared_owner import _supervise
from night_shifts.gate_a_watchdog import CLEANUP_RESERVE_NS, HostCleanup, StopReason, TeardownTarget, WatchdogRefused
from night_shifts.gate_a_watchdog_windows import WindowsOwnerSignals

_TARGET = TeardownTarget('finalization', 'b' * 32, '51434da9-9168-428a-8624-72a246ccc18d')


class Actions:
    def __init__(self, start_result):
        self.start_result = start_result
        self.events = []
        self.deadline = time.monotonic_ns() + CLEANUP_RESERVE_NS + 5_000_000_000

    def owner(self):
        return GateAHostLifecycle(_TARGET, held_workspace_root=r'D:\NightShift\attempts',
                                  held_boot_asset=r'D:\NightShift\assets\ubuntu.iso',
                                  actions=self, deadline_ns=self.deadline)

    def run(self, fixed_script, args, *, deadline_ns, stdout_limit):
        self.events.append(fixed_script)
        evidence = {'version': 1, 'id': _TARGET.attempt_id, 'operation': _TARGET.operation, 'vm_id': _TARGET.vm_id}
        if fixed_script == _START:
            if self.start_result is None:
                raise RuntimeError('provider settlement missing')
            evidence['state'] = self.start_result
        else:
            assert fixed_script == _RECONCILE
            evidence.update(vm_absent=True, disk_unattached_and_unreferenced=True, disk_retained=True)
        return json.dumps(evidence).encode('ascii')


class Signals:
    def __init__(self, actions):
        self._cancel = Event()
        self.events = actions.events

    def wait(self, milliseconds):
        return StopReason.CANCELLED if self._cancel.wait(milliseconds / 1000) else None

    def arm(self):
        self.events.append('armed')

    def release_worker(self):
        self.events.append('worker released')
        self._cancel.set()  # fixture worker is immediately done

    def request_cancel(self):
        self.events.append('cancel requested')
        self._cancel.set()


@pytest.mark.parametrize(('state', 'events', 'released', 'cleaned'), [
    ('running_observed', ['armed', _START, 'worker released', _RECONCILE], True, True),
    ('not_started', ['armed', _START, 'cancel requested', _RECONCILE], False, True),
    (None, ['armed', _START, 'cancel requested'], False, False),
])
def test_only_settled_running_can_release_worker_and_unsettled_start_never_reconciles(state, events, released, cleaned):
    actions = Actions(state)
    result = _supervise(actions.owner(), Signals(actions), deadline_ns=actions.deadline)
    assert result.worker_signalled is released
    assert result.host_cleanup.stop_reason is StopReason.CANCELLED
    assert result.host_cleanup.cleanup == (HostCleanup(_TARGET, True) if cleaned else None)
    assert result.host_cleanup.cleanup_unknown == (None if cleaned else 'lifecycle_unknown')
    assert actions.events == events


def test_stop_between_arm_and_admission_prevents_start():
    actions = Actions('running_observed')

    class CancelAtArm(Signals):
        def arm(self):
            super().arm()
            self._cancel.set()

    result = _supervise(actions.owner(), CancelAtArm(actions), deadline_ns=actions.deadline)
    assert not result.worker_signalled
    assert result.host_cleanup.cleanup == HostCleanup(_TARGET, True)
    assert actions.events == ['armed', _RECONCILE]


@pytest.mark.skipif(os.name != 'nt' or c.sizeof(c.c_void_p) != 8, reason='native x64 Windows handles')
@pytest.mark.parametrize('stop', ['worker', 'runtime'])
def test_owner_runs_through_exact_native_process_handles_and_fixed_cleanup(stop):
    k = c.WinDLL('kernel32', use_last_error=True)
    for name, args, value in (
        ('CreateEventW', [c.c_void_p, c.c_int, c.c_int, c.c_wchar_p], c.c_void_p),
        ('OpenProcess', [c.c_uint32, c.c_int, c.c_uint32], c.c_void_p),
        ('WaitForSingleObject', [c.c_void_p, c.c_uint32], c.c_uint32),
        ('CloseHandle', [c.c_void_p], c.c_int),
    ):
        function = getattr(k, name)
        function.argtypes, function.restype = args, value
    handles = []
    children = []
    try:
        for _ in range(3):
            handle = k.CreateEventW(None, True, False, None)
            assert handle
            handles.append(handle)
        cancel, armed, gate = handles
        for _ in range(2):
            process = subprocess.Popen([sys.executable, '-I', '-c', 'import sys; sys.stdin.buffer.read()'],
                                       stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            children.append(process)
            handle = k.OpenProcess(0x101000, False, process.pid)  # test-only acquisition
            assert handle
            handles.append(handle)
        runtime, worker = handles[-2:]
        with pytest.raises(WatchdogRefused, match='worker_gate_handle'):
            WindowsOwnerSignals(cancelled=cancel, runtime=runtime, worker=worker, armed=armed, worker_gate=worker)
        actions = Actions('running_observed')

        class NativeFixture(WindowsOwnerSignals):
            def release_worker(self):
                actions.events.append('worker released')
                super().release_worker()
                assert k.WaitForSingleObject(gate, 0) == 0
                child = children[int(stop == 'worker')]
                assert child.stdin is not None
                child.stdin.close()  # exact fixture child exits upon EOF

        signals = NativeFixture(cancelled=cancel, runtime=runtime, worker=worker, armed=armed, worker_gate=gate)
        result = _supervise(actions.owner(), signals, deadline_ns=actions.deadline)
        assert k.WaitForSingleObject(armed, 0) == 0
        assert result.worker_signalled and result.host_cleanup.cleanup == HostCleanup(_TARGET, True)
        expected = StopReason.WORKER_EXITED if stop == 'worker' else StopReason.RUNTIME_EXITED
        assert result.host_cleanup.stop_reason is expected
        assert actions.events == [_START, 'worker released', _RECONCILE]
    finally:
        for child in children:
            if child.stdin is not None:
                child.stdin.close()
            if child.poll() is None:
                child.kill()
            child.wait(timeout=5)
        for handle in handles:
            k.CloseHandle(handle)
