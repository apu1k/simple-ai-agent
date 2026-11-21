"""Exercise literal action bindings and native jobs without Hyper-V or elevation."""
from __future__ import annotations

import base64
import ctypes as c
import hashlib
import os
import sys
import time
from pathlib import Path

import pytest

from night_shifts import gate_a_fixed_actions as fixed
from night_shifts.gate_a_action_process_windows import _WindowsGateAProcess
from night_shifts.gate_a_host_lifecycle import _RECONCILE, _START, _action_args
from night_shifts.gate_a_watchdog import CLEANUP_RESERVE_NS, MAX_RECEIPT_BYTES, TeardownTarget, WatchdogRefused

_TARGET = TeardownTarget('smoke', 'a' * 32, '51434da9-9168-428a-8624-72a246ccc18d')
_ROOT = r'D:\NightShift\fresh attempts'
_ASSET = r'D:\NightShift\images\base (reviewed).vhdx'
_SYSTEM = r'C:\Windows\System32'
_ACTION_DIR = Path(__file__).resolve().parents[2] / 'night_shifts/backends/hyperv_scripts'
_NATIVE = pytest.mark.skipif(os.name != 'nt' or c.sizeof(c.c_void_p) != 8, reason='native x64 Windows')


def _snapshot(source):
    return fixed.GateAActionSnapshot(source, hashlib.sha256(source).hexdigest())


def _actions(deadline, *, start=None, reconcile=None):
    return fixed.WindowsPinnedGateAActions(
        _TARGET, held_workspace_root=_ROOT, held_boot_asset=_ASSET, deadline_ns=deadline,
        start=_snapshot((_ACTION_DIR / _START).read_bytes()) if start is None else start,
        reconcile=_snapshot((_ACTION_DIR / _RECONCILE).read_bytes()) if reconcile is None else reconcile,
    )


@pytest.mark.parametrize('bad', [fixed.GateAActionSnapshot(b'changed', '0' * 64), _snapshot(b'\xff'),
                                 _snapshot(b'\0'), _snapshot(b' ' * 8193)])
def test_bad_snapshot_refused_before_any_action(bad):
    with pytest.raises(WatchdogRefused, match='action_(pin|encoding)'):
        _actions(time.monotonic_ns() + 60_000_000_000, start=bad)


def test_path_argument_source_and_deadline_bound_before_spawn(monkeypatch):
    captured = []

    class Fixture:
        def __init__(self, *, require_protected_owner):
            assert require_protected_owner

        def system_identity(self):
            return _SYSTEM, 'FIXEDHOST'

        def capture(self, argv, **opts):
            captured.append((argv, opts))
            return b'fixture'

    monkeypatch.setattr(fixed, '_WindowsGateAProcess', Fixture)
    deadline = time.monotonic_ns() + 60_000_000_000
    work_until = deadline - CLEANUP_RESERVE_NS
    actions = _actions(deadline)
    start, cleanup = _action_args(_TARGET, _ROOT, _ASSET, deadline)
    for label, args, until, limit in [
        (_START.upper(), start, work_until, MAX_RECEIPT_BYTES),
        (_START, start[:-1], work_until, MAX_RECEIPT_BYTES),
        (_START, start, work_until + 1, MAX_RECEIPT_BYTES),
        (_START, start, work_until, 3),
        (_RECONCILE, cleanup[:-1], deadline, MAX_RECEIPT_BYTES),
        (_RECONCILE, cleanup + ('-OtherVM',), deadline, MAX_RECEIPT_BYTES),
    ]:
        with pytest.raises(WatchdogRefused, match='action_refused'):
            actions.run(label, args, deadline_ns=until, stdout_limit=limit)
    assert not captured
    assert actions.run(_START, start, deadline_ns=work_until, stdout_limit=MAX_RECEIPT_BYTES) == b'fixture'
    assert actions.run(_RECONCILE, cleanup, deadline_ns=deadline, stdout_limit=MAX_RECEIPT_BYTES) == b'fixture'
    with pytest.raises(WatchdogRefused, match='action_refused'):
        actions.run(_RECONCILE, cleanup, deadline_ns=deadline, stdout_limit=MAX_RECEIPT_BYTES)
    for (argv, opts), label in zip(captured, (_START, _RECONCILE), strict=True):
        assert argv[:-1] == (_SYSTEM + r'\WindowsPowerShell\v1.0\powershell.exe', '-NoLogo', '-NoProfile',
                             '-NonInteractive', '-OutputFormat', 'Text', '-EncodedCommand')
        script = base64.b64decode(argv[-1]).decode('utf-16-le')
        assert (_ACTION_DIR / label).read_text(encoding='utf-8') in script.replace('\r\n', '\n')
        assert rf"'{_SYSTEM}\WindowsPowerShell\v1.0\Modules\Hyper-V\2.0.0.0\Hyper-V.psd1'" in script
        assert f"-WorkspaceRoot '{_ROOT}'" in script
        assert opts['environment']['COMPUTERNAME'] == 'FIXEDHOST'
        assert opts['environment']['PATH'] == opts['cwd'] == _SYSTEM
        assert len(argv[-1]) < 29000
    assert captured[0][1]['deadline_ns'] == work_until
    assert captured[1][1]['deadline_ns'] == deadline
    assert '-RemoveSmokeDisk\n' in base64.b64decode(captured[1][0][-1]).decode('utf-16-le')


def test_cleanup_first_permanently_refuses_later_start(monkeypatch):
    def fail(**_):
        raise WatchdogRefused('fixture_failure')

    monkeypatch.setattr(fixed, '_WindowsGateAProcess', fail)
    deadline = time.monotonic_ns() + 60_000_000_000
    actions = _actions(deadline)
    start, cleanup = _action_args(_TARGET, _ROOT, _ASSET, deadline)
    with pytest.raises(WatchdogRefused, match='fixture_failure'):
        actions.run(_RECONCILE, cleanup, deadline_ns=deadline, stdout_limit=MAX_RECEIPT_BYTES)
    with pytest.raises(WatchdogRefused, match='action_refused'):
        actions.run(_START, start, deadline_ns=deadline - CLEANUP_RESERVE_NS, stdout_limit=MAX_RECEIPT_BYTES)


@_NATIVE
def test_real_windows_powershell_receives_literals_and_returns_stdout(monkeypatch, tmp_path):
    # Use Windows PowerShell and the real capture primitive, but no Hyper-V module.
    # The tiny fixture script does not address any VM or change any host state.
    monkeypatch.setattr(fixed, '_MODULES', fixed._MODULES[:2])
    monkeypatch.setattr(fixed, '_WindowsGateAProcess', lambda **_: _WindowsGateAProcess(require_protected_owner=False))
    fixture = _snapshot(b"param($Operation, $Identity, $VmId, $WorkspaceRoot, [switch]$RemoveSmokeDisk)\n"
                        b"if (!$RemoveSmokeDisk -or !$env:COMPUTERNAME) { throw 'fixture' }\n"
                        b"$WorkspaceRoot + '|' + $Identity + '|' + $Operation\n")
    deadline = time.monotonic_ns() + 60_000_000_000
    actions = _actions(deadline, reconcile=fixture)
    actions._scratch = str(tmp_path)  # fixture-only writable TEMP/TMP
    _, cleanup = _action_args(_TARGET, _ROOT, _ASSET, deadline)
    assert actions.run(_RECONCILE, cleanup, deadline_ns=deadline, stdout_limit=MAX_RECEIPT_BYTES) == (
        f'{_ROOT}|{_TARGET.attempt_id}|{_TARGET.operation}'.encode('ascii'))


@_NATIVE
@pytest.mark.parametrize(('source', 'label'), [
    ('import sys; sys.stdout.write("x" * 100000)', 'action_output_bound'),
    ('import sys; sys.stdout.write("not evidence"); sys.exit(7)', 'action_process_failed'),
    ('import time; time.sleep(60)', 'action_deadline'),
])
def test_native_capture_never_returns_failed_large_or_timed_out_output(tmp_path, source, label):
    witness = c.c_void_p()

    class WitnessedProcess(_WindowsGateAProcess):
        def _collect(self, job, process, reader, **opts):
            self._bind(self.k, 'DuplicateHandle', [c.c_void_p, c.c_void_p, c.c_void_p, c.POINTER(c.c_void_p),
                                                  c.c_uint32, c.c_int, c.c_uint32], c.c_int)
            current = self.k.GetCurrentProcess()
            assert self.k.DuplicateHandle(current, process, current, c.byref(witness), 0x100000, False, 0)
            return super()._collect(job, process, reader, **opts)

    native = WitnessedProcess(require_protected_owner=False)
    until = time.monotonic_ns() + (750_000_000 if label == 'action_deadline' else 5_000_000_000)
    try:
        # On Windows a venv launcher itself spawns the base interpreter. Test
        # with the real image so the native one-process cap stays in effect.
        with pytest.raises(WatchdogRefused, match=f'^{label}$'):
            native.capture((sys._base_executable, '-I', '-c', source), cwd=str(tmp_path), environment=dict(os.environ),
                           deadline_ns=until, limit=MAX_RECEIPT_BYTES)
        assert witness.value and native.k.WaitForSingleObject(witness, 2000) == 0
    finally:
        if witness.value:
            assert native.k.CloseHandle(witness)
