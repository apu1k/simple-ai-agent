"""Cancellation-only models and ordinary native pipe/job composition. No UAC.

The only process locators are the known caller/controller. Child verification
uses duplicated ACTUAL CreateProcess handles, never child PID/name searches.
"""
from __future__ import annotations

import ctypes as c
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from core.tool_progress import approval_ui_context, tool_progress_listener
from runtime import command_lifetime as lease
from runtime import elevated_commands as client
from runtime.privileged_host import PrivilegedHostError, _windows_paths
from runtime.privileged_turn import ELEVATED_OPERATION, PrivilegedClaim, PrivilegedTurn
from tests.runtime.test_command_watchdog_ownership_windows import ROOT, WORKER, source
from tests.runtime.test_elevated_commands import approve, quote
from tests.runtime.test_elevated_receipts import receipt


@pytest.mark.parametrize('end', ['revoke', 'expiry', 'turn_exit'])
def test_lifetime_monitor_observes_invalidation_without_execution_authority(end):
    now = [0.0]
    gate = PrivilegedTurn(clock=lambda: now[0], wall_clock=lambda: 1000.0)
    gate.arm(ELEVATED_OPERATION)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with gate.turn('head'):
            claim = gate.claim(ELEVATED_OPERATION)
            assert pool.submit(gate.execution_cancelled, claim).result() is False
            forged = PrivilegedClaim('e' * 32, claim.deadline_unix, ELEVATED_OPERATION)
            assert pool.submit(gate.execution_cancelled, forged).result() is True
            with pytest.raises(PermissionError):
                pool.submit(gate.claim, ELEVATED_OPERATION).result()
            if end == 'revoke':
                gate.revoke()
            elif end == 'expiry':
                now[0] += 1800
            if end != 'turn_exit':
                assert pool.submit(gate.execution_cancelled, claim).result() is True
        assert pool.submit(gate.execution_cancelled, claim).result() is True


@pytest.mark.parametrize('end', ['normal', 'revoke', 'poll_fault', 'close_fault'])
def test_endpoint_is_closed_on_every_exit_without_retry_or_refund(monkeypatch, end):
    calls, closed = [], Event()
    class Pipe:
        created = '123'
        def __init__(self, name, sid):
            calls.append(('create', name))
        def poll(self):
            if end == 'poll_fault':
                raise OSError('fixture')
        def close(self):
            calls.append(('close', None))
            closed.set()
            if end == 'close_fault':
                raise OSError('fixture')
    monkeypatch.setattr(lease, '_Pipe', Pipe)
    gate = PrivilegedTurn()
    gate.arm(ELEVATED_OPERATION)
    with gate.turn('head'):
        claim = gate.claim(ELEVATED_OPERATION)
        lifetime = lease.CommandLifetime(gate, claim, 'fixture')
        def run():
            with lifetime:
                if end == 'revoke':
                    gate.revoke()
                if end in ('revoke', 'poll_fault'):
                    assert closed.wait(2)
        if end in ('poll_fault', 'close_fault'):
            with pytest.raises(PrivilegedHostError, match='outcome unknown'):
                run()
        else:
            run()
    assert [kind for kind, _ in calls] == ['create', 'close']
    assert lifetime.binding['owner_created'] == '123' and lifetime.binding['owner_pid'] == os.getpid()


@pytest.mark.parametrize('accept,state', [(False, 'unused'), (True, 'uac_cancelled'), (True, 'completed'), (True, 'revoke')])
def test_new_client_hashes_lifetime_before_approval_and_preserves_it_until_reconciliation(monkeypatch, tmp_path, accept, state):
    (tmp_path / 'requests').mkdir()
    (tmp_path / 'receipts').mkdir()
    policy = dict(operator_sid='fixture', helper_sha256='c' * 64, max_timeout=900, lifetime_protocol=1)
    events = []
    binding = dict(version=1, pipe=lease.PREFIX + 'a' * 32 + '-' + 'b' * 32, owner_pid=123, owner_created='456')
    class Lease:
        def __init__(self, *args):
            self.binding = binding
        def __enter__(self):
            events.append('open')
            return self
        def __exit__(self, *args):
            events.append('close')
    monkeypatch.setattr(client, 'CommandLifetime', Lease)
    monkeypatch.setattr(client, 'local_path', lambda *args, **kwargs: tmp_path)
    monkeypatch.setattr(client, 'load_launcher', lambda: (tmp_path, tmp_path / 'powershell.exe', policy.copy()))
    gate = PrivilegedTurn()
    gate.arm(ELEVATED_OPERATION)
    def elevate(exe, helper, claim, *, request_sha256):
        events.append('elevate')
        raw = (tmp_path / 'requests' / (claim.request_id + '.json')).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == request_sha256 and json.loads(raw)['lifetime'] == binding
        if state == 'uac_cancelled':
            return state
        if state == 'revoke':
            gate.revoke()
        data = receipt()
        data.update(request_id=claim.request_id, request_sha256=request_sha256, process_tree_observed=True, lifetime_observed=True)
        (tmp_path / 'receipts' / (claim.request_id + '.result.json')).write_text(json.dumps(data))
        return 'completed'
    monkeypatch.setattr(client, '_elevate', elevate)
    monkeypatch.setattr(client, '_bounded_json', lambda path: json.loads(path.read_text()))
    with gate.turn('head'), approval_ui_context(), tool_progress_listener(approve(gate, accept)):
        result = client.run_approved_script(gate, gate.claim(ELEVATED_OPERATION), 'exit 0', 20, 'inert fixture', str(tmp_path), require_lifetime=True)
    assert events == (['open', 'elevate', 'close'] if accept else ['open', 'close'])
    expected = 'rejected' if not accept else ('cancelled_outcome_unknown' if state == 'revoke' else state)
    assert result['status'] == expected and result.get('effects_verified', False) is False


def test_fixed_route_refuses_old_deployment_before_approval(monkeypatch, tmp_path):
    monkeypatch.setattr(client, 'local_path', lambda *args, **kwargs: tmp_path)
    monkeypatch.setattr(client, 'load_launcher', lambda: (tmp_path, tmp_path / 'powershell.exe',
        dict(operator_sid='fixture', helper_sha256='c' * 64, max_timeout=900)))
    monkeypatch.setattr(client, 'await_approval', lambda *args: pytest.fail('must refuse before pending'))
    with pytest.raises(PrivilegedHostError, match='lifetime deployment'):
        client.run_approved_script(PrivilegedTurn(), PrivilegedClaim('a' * 32, time.time() + 30, ELEVATED_OPERATION),
            'exit 0', 20, 'fixture', str(tmp_path), require_lifetime=True)


@pytest.mark.parametrize('field,value', [('exit_code', 0), ('process_tree_observed', False), ('lifetime_observed', False),
    ('lifetime_observed', 1), ('lifetime_observed', None), ('executed', None)])
def test_cancellation_receipt_cannot_claim_more_than_observed(field, value):
    data = receipt()
    data.update(status='cancelled_outcome_unknown', exit_code=125, process_tree_observed=True, lifetime_observed=True)
    claim = PrivilegedClaim(data['request_id'], 1000, ELEVATED_OPERATION)
    client.validate_receipt(data, claim, 'b' * 64, 'c' * 64)
    data[field] = value
    with pytest.raises(PrivilegedHostError):
        client.validate_receipt(data, claim, 'b' * 64, 'c' * 64)


OWNER = '''
import json,sys,time
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,sys.argv[1])
from runtime.command_lifetime import CommandLifetime
from runtime.privileged_turn import PrivilegedClaim
with CommandLifetime(SimpleNamespace(execution_cancelled=lambda claim: False),PrivilegedClaim(sys.argv[4],time.time()+60),sys.argv[3]) as lifetime:
    path=Path(sys.argv[2]); pending=path.with_suffix('.pending')
    pending.write_text(json.dumps(lifetime.binding),encoding='utf-8'); pending.rename(path)
    time.sleep(60)
'''


@pytest.mark.skipif(os.name != 'nt', reason='ordinary native caller-pipe/process/job fixture')
@pytest.mark.parametrize('mode', ['normal', 'cancel', 'owner_death', 'before_connect', 'bad_pid', 'bad_created', 'bad_name', 'deadline'])
def test_native_caller_lifetime_controls_exact_owned_tree(mode):
    from night_shifts.ubuntu_preparation_control import _current_user_sid
    sid = _current_user_sid()
    folder = Path(tempfile.mkdtemp(prefix='caller-lifetime-ordinary-'))
    compiler, worker = folder / 'ordinary.cs', folder / 'inert.py'
    compiler.write_text(source('normal'), encoding='utf-8')
    worker.write_text(WORKER, encoding='utf-8')
    request_id, revoked = 'c' * 32, Event()
    lifetime = lease.CommandLifetime(SimpleNamespace(execution_cancelled=lambda claim: revoked.is_set()),
        PrivilegedClaim(request_id, time.time() + 60), sid)
    owner = None
    handles = []
    proc = None
    k = c.WinDLL('kernel32', use_last_error=True)
    k.WaitForSingleObject.argtypes, k.WaitForSingleObject.restype = [c.c_void_p, c.c_uint32], c.c_uint32
    k.CloseHandle.argtypes, k.CloseHandle.restype = [c.c_void_p], c.c_int
    try:
        with lifetime:
            binding = dict(lifetime.binding)
            if mode == 'owner_death':
                owner_script, owner_record = folder / 'owner.py', folder / 'owner.json'
                owner_script.write_text(OWNER, encoding='utf-8')
                owner = subprocess.Popen([sys.executable, '-I', '-B', str(owner_script), str(ROOT), str(owner_record), sid, request_id],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                until = time.monotonic() + 8
                while not owner_record.exists():
                    assert owner.poll() is None and time.monotonic() < until, 'Owner did not bind: ' + str(folder)
                    time.sleep(0.01)
                binding = json.loads(owner_record.read_text(encoding='utf-8'))
            if mode == 'before_connect':
                revoked.set()
                assert lifetime._stop.wait(0.2) is False
                lifetime._thread.join(2)
                assert not lifetime._thread.is_alive()
            elif mode == 'bad_pid':
                binding['owner_pid'] += 1
            elif mode == 'bad_created':
                binding['owner_created'] = str(int(binding['owner_created']) + 1)
            elif mode == 'bad_name':
                binding['pipe'] += '-unexpected'
            worker_mode = 'normal' if mode == 'normal' else 'timeout'
            args = f'-I -S -B "{worker}" "{folder}" {worker_mode} {os.getpid()}'
            script = f"""
$ErrorActionPreference='Stop'
$i=[Security.Principal.WindowsIdentity]::GetCurrent()
if ((New-Object Security.Principal.WindowsPrincipal($i)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {{ throw 'UNELEVATED fixture required' }}
$i.Dispose()
Add-Type -Path {quote(compiler)}
[CommandFixture]::Root={quote(folder)}; [CommandFixture]::Mode='normal'
$sentinel=[CommandFixture]::Sentinel()
try {{
    $rate=[Diagnostics.Stopwatch]::Frequency; $ms=10000
    $limit=[Diagnostics.Stopwatch]::GetTimestamp()+[long]({1500 if mode == 'deadline' else 10000}*$rate/1000)
    try {{
        $answer=[CommandWatchdog]::RunOwned({quote(sys.executable)},({quote(args)}+' '+$sentinel.ToInt64()),{quote(folder)},$ms,$limit,$rate,{quote(binding['pipe'])},[uint32]{binding['owner_pid']},{quote(binding['owner_created'])},{quote(request_id)})
        @{{status='returned';answer=$answer}} | ConvertTo-Json -Depth 4 -Compress
    }} catch {{
        $cause=$_.Exception; while ($cause.InnerException) {{ $cause=$cause.InnerException }}
        @{{status='unknown';cause=$cause.Message}} | ConvertTo-Json -Compress
    }}
}} finally {{ [CommandFixture]::EndSentinel($sentinel) }}
"""
            path = folder / 'controller.ps1'
            path.write_text(script, encoding='utf-8-sig')
            _, exe = _windows_paths()
            proc = subprocess.Popen([str(exe), '-NoProfile', '-NonInteractive', '-File', str(path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if mode in ('cancel', 'owner_death'):
                until = time.monotonic() + 8
                while not (folder / 'descendant.handle').exists():
                    assert proc.poll() is None and time.monotonic() < until, 'Child not resumed: ' + str(folder)
                    time.sleep(0.01)
                if mode == 'cancel':
                    revoked.set()
                else:
                    owner.kill()  # the exact original lease-owner process handle
                    out, err = owner.communicate(timeout=5)
                    assert not out and not err, (str(folder), out, err)
            out, err = proc.communicate(timeout=14)
            assert proc.returncode == 0 and not err, (str(folder), out, err)
            result = json.loads(out)
            causes = dict(before_connect='Caller lifetime pipe unavailable', bad_pid='Caller lifetime server differs',
                bad_created='Caller lifetime owner differs', bad_name='Caller lifetime binding refused')
            if mode in causes:
                assert result == dict(status='unknown', cause=causes[mode]), (str(folder), result)
                assert not (folder / 'root.handle').exists() and not (folder / 'resumed.marker').exists(), str(folder)
            else:
                assert result['status'] == 'returned', (str(folder), result)
                answer = result['answer']
                assert answer['ProcessTreeObserved'] is answer['LifetimeObserved'] is True, (str(folder), answer)
                assert answer['Cancelled'] == (mode in ('cancel', 'owner_death'))
                assert answer['Timeout'] == (mode == 'deadline')
                assert answer['Code'] == (124 if mode == 'deadline' else (0 if mode == 'normal' else 125)), (str(folder), answer)
                assert not answer['Stderr'] and answer['Truncated'] is False, (str(folder), answer)
                for name in ('root', 'descendant'):
                    path = folder / (name + '.handle')
                    if path.exists():
                        handle = int(path.read_text(encoding='ascii'))
                        handles.append(handle)
                        assert k.WaitForSingleObject(handle, 5000) == 0, 'Exact tree termination UNKNOWN: ' + str(folder)
                assert len(handles) == (1 if mode == 'normal' else 2), str(folder)
    finally:
        if owner is not None and owner.poll() is None:
            owner.kill()
            owner.communicate(timeout=5)
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.communicate(timeout=5)
        for name in ('root', 'descendant'):
            path = folder / (name + '.handle')
            if path.exists():
                handle = int(path.read_text(encoding='ascii'))
                if handle not in handles:
                    handles.append(handle)
        for handle in handles:
            assert k.CloseHandle(handle), 'Capability close UNKNOWN; retain: ' + str(folder)
    shutil.rmtree(folder)  # verified exact disposable fixture only
