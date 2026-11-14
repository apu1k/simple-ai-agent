"""Held preparation/launch lifetime: models and ordinary native fixtures only.

No helper entry point, elevation, installation or setup body. Production checks
are used unchanged; only child-observation hooks are disposable test adapters.
"""
from __future__ import annotations

import ctypes as c
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from runtime import command_lifetime as lease
from runtime import elevated_commands as client
from runtime.privileged_host import PrivilegedHostError, _windows_paths
from runtime.privileged_turn import ELEVATED_OPERATION, PrivilegedClaim, PrivilegedTurn
from tests.runtime.test_command_lifetime import OWNER
from tests.runtime.test_command_watchdog_ownership_windows import ROOT, WORKER, source
from tests.runtime.test_elevated_commands import quote
from tests.runtime.test_elevated_receipts import receipt


@pytest.mark.parametrize('policy', [
    {}, {'lifetime_protocol': 1}, {'lifetime_protocol': 1, 'preparation_protocol': True},
    {'lifetime_protocol': 1, 'preparation_protocol': 2}, {'preparation_protocol': 1},
])
def test_setup_requires_explicit_preparation_capability_before_pending(monkeypatch, tmp_path, policy):
    policy = dict(operator_sid='fixture', helper_sha256='c' * 64, max_timeout=900, **policy)
    monkeypatch.setattr(client, 'local_path', lambda *args, **kwargs: tmp_path)
    monkeypatch.setattr(client, 'load_launcher', lambda: (tmp_path, tmp_path / 'powershell.exe', policy))
    monkeypatch.setattr(client, 'await_approval', lambda *args: pytest.fail('must refuse before pending'))
    with pytest.raises(PrivilegedHostError, match='preparation-lifetime deployment'):
        client.run_approved_script(PrivilegedTurn(), PrivilegedClaim('a' * 32, time.time() + 30, ELEVATED_OPERATION),
            'exit 0', 20, 'fixture', str(tmp_path), require_preparation=True)


@pytest.mark.parametrize('status,code', [('completed', 0), ('failed', 7), ('timeout_outcome_unknown', 124),
    ('cancelled_outcome_unknown', 125), ('outcome_unknown', None)])
@pytest.mark.parametrize('observed', ['absent', True, False, None, 1, 'true'])
def test_preparation_receipts_never_default_or_promote_missing_observations(status, code, observed):
    data = receipt()
    known = status != 'outcome_unknown'
    data.update(status=status, exit_code=code, executed=True if known else None,
        process_tree_observed=known, lifetime_observed=known)
    if observed != 'absent':
        data['preparation_observed'] = observed
    claim = PrivilegedClaim(data['request_id'], 1000, ELEVATED_OPERATION)
    if observed == 'absent' or observed is known:
        client.validate_receipt(data, claim, 'b' * 64, 'c' * 64)
    else:
        with pytest.raises(PrivilegedHostError):
            client.validate_receipt(data, claim, 'b' * 64, 'c' * 64)


@pytest.mark.parametrize('missing', ['lifetime_observed', 'process_tree_observed'])
def test_preparation_observation_cannot_substitute_for_execution_observations(missing):
    data = receipt()
    data.update(preparation_observed=True, lifetime_observed=True, process_tree_observed=True)
    del data[missing]
    with pytest.raises(PrivilegedHostError):
        client.validate_receipt(data, PrivilegedClaim(data['request_id'], 1000, ELEVATED_OPERATION), 'b' * 64, 'c' * 64)


def test_helper_guards_each_durable_preparation_and_preserves_failure_evidence():
    helper = (ROOT / 'scripts/privileged_command_helper.ps1').read_text(encoding='utf-8')
    first = helper.rindex('$preparation = [CommandWatchdog]::PrepareInherited')
    assert first < helper.index("Write-Receipt ($RequestId + '.start.json')")
    assert first < helper.index("Write-New ($RequestId + '.approved.json')")
    assert first < helper.index("Write-New ($RequestId + '.payload.ps1')")
    write = helper[helper.index('function Write-New('):helper.index('function Write-Receipt(')]
    assert write.count('$preparation.Check()') == 4
    assert write.index('$preparation.Check()') < write.index('New-Object IO.FileStream')
    assert "$suffix = if ($preparationWorker) { '.worker-result.json' } else { '.result.json' }" in helper
    assert 'Write-Receipt ($RequestId + $suffix) $result $false' in helper
    assert helper.count('$answer = [CommandWatchdog]::RunPrepared') == 1
    assert helper.index('$whole = [CommandWatchdog]::RunPreparation') < first
    assert helper.index('$preparation.Dispose(); $preparation = $null') < helper.index('$result.preparation_observed =')
    assert len(helper.encode('utf-8')) < 65536


@pytest.mark.skipif(os.name != 'nt', reason='ordinary native held caller/preparation/job fixture')
@pytest.mark.parametrize('mode', ['normal', 'cancel_preparation', 'owner_death_preparation', 'deadline_preparation',
    'cancel_running', 'deadline_running', 'consumed_twice', 'disposed', 'sticky_refusal', 'native_failure'])
def test_native_preparation_holds_one_caller_and_one_original_window(mode):
    from night_shifts.ubuntu_preparation_control import _current_user_sid
    sid = _current_user_sid()
    folder = Path(tempfile.mkdtemp(prefix='command-preparation-ordinary-'))
    compiler, worker = folder / 'ordinary.cs', folder / 'inert.py'
    compiler.write_text(source('job_attribute' if mode == 'native_failure' else 'normal'), encoding='utf-8')
    worker.write_text(WORKER, encoding='utf-8')
    request_id, revoked = 'e' * 32, Event()
    lifetime = lease.CommandLifetime(SimpleNamespace(execution_cancelled=lambda claim: revoked.is_set()),
        PrivilegedClaim(request_id, time.time() + 60), sid)
    proc = owner = None
    handles = []
    k = c.WinDLL('kernel32', use_last_error=True)
    k.WaitForSingleObject.argtypes, k.WaitForSingleObject.restype = [c.c_void_p, c.c_uint32], c.c_uint32
    k.CloseHandle.argtypes, k.CloseHandle.restype = [c.c_void_p], c.c_int
    try:
        with lifetime:
            binding = lifetime.binding
            if mode == 'owner_death_preparation':
                owner_script, owner_record = folder / 'owner.py', folder / 'owner.json'
                owner_script.write_text(OWNER, encoding='utf-8')
                owner = subprocess.Popen([sys.executable, '-I', '-B', str(owner_script), str(ROOT), str(owner_record), sid, request_id],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                until = time.monotonic() + 8
                while not owner_record.exists():
                    assert owner.poll() is None and time.monotonic() < until, str(folder)
                    time.sleep(0.01)
                binding = json.loads(owner_record.read_text(encoding='utf-8'))
            worker_mode = 'timeout' if mode in ('cancel_running', 'deadline_running') else 'normal'
            args = f'-I -S -B "{worker}" "{folder}" {worker_mode} {os.getpid()}'
            code = f"""
$ErrorActionPreference='Stop'
$i=[Security.Principal.WindowsIdentity]::GetCurrent()
if ((New-Object Security.Principal.WindowsPrincipal($i)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {{ throw 'UNELEVATED fixture required' }}
$i.Dispose()
Add-Type -Path {quote(compiler)}
[CommandFixture]::Root={quote(folder)}; [CommandFixture]::Mode='normal'
$sentinel=[CommandFixture]::Sentinel(); $p=$null
try {{
    $rate=[Diagnostics.Stopwatch]::Frequency
    $duration=if ({quote(mode)} -like 'deadline_*') {{ 1500 }} else {{ 10000 }}
    $limit=[Diagnostics.Stopwatch]::GetTimestamp()+[long]($duration*$rate/1000)
    $p=[CommandWatchdog]::Prepare(10000,$limit,$rate,([DateTimeOffset]::UtcNow.ToUnixTimeSeconds()+30),{quote(binding['pipe'])},[uint32]{binding['owner_pid']},{quote(binding['owner_created'])},{quote(request_id)})
    $p.Check()
    [IO.File]::WriteAllText({quote(folder / 'prepared.marker')},'test preparation')
    if ({quote(mode)} -in @('cancel_preparation','owner_death_preparation','sticky_refusal')) {{
        $wait=[Diagnostics.Stopwatch]::StartNew()
        while (-not [IO.File]::Exists({quote(folder / 'continue.marker')})) {{
            if ($wait.ElapsedMilliseconds -gt 5000) {{ throw 'FIXTURE_COORDINATION_TIMEOUT' }}
            [Threading.Thread]::Sleep(10)
        }}
    }}
    if ({quote(mode)} -eq 'deadline_preparation') {{ [Threading.Thread]::Sleep(1700) }}
    if ({quote(mode)} -eq 'disposed') {{ $p.Dispose() }}
    try {{
        $p.Check()
        $a=[CommandWatchdog]::RunPrepared($p,{quote(sys.executable)},({quote(args)}+' '+$sentinel.ToInt64()),{quote(folder)})
        $p.Dispose()
        $again=$null
        if ({quote(mode)} -eq 'consumed_twice') {{
            try {{ [void][CommandWatchdog]::RunPrepared($p,{quote(sys.executable)},'',{quote(folder)}) }} catch {{
                $e=$_.Exception; while ($e.InnerException) {{ $e=$e.InnerException }}; $again=$e.Message
            }}
        }}
        @{{status='returned';answer=$a;again=$again}} | ConvertTo-Json -Depth 4 -Compress
    }} catch {{
        $e=$_.Exception; while ($e.InnerException) {{ $e=$e.InnerException }}
        $first=$e.Message; $again=$null
        if ({quote(mode)} -in @('sticky_refusal','native_failure')) {{
            try {{ [void][CommandWatchdog]::RunPrepared($p,{quote(sys.executable)},'',{quote(folder)}) }} catch {{
                $e=$_.Exception; while ($e.InnerException) {{ $e=$e.InnerException }}; $again=$e.Message
            }}
        }}
        @{{status='unknown';cause=$first;again=$again}} | ConvertTo-Json -Compress
    }}
}} finally {{ if ($null -ne $p) {{ $p.Dispose() }}; [CommandFixture]::EndSentinel($sentinel) }}
"""
            path = folder / 'controller.ps1'
            path.write_text(code, encoding='utf-8-sig')
            _, exe = _windows_paths()
            proc = subprocess.Popen([str(exe), '-NoProfile', '-NonInteractive', '-File', str(path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if mode in ('cancel_preparation', 'owner_death_preparation', 'sticky_refusal', 'cancel_running'):
                marker = 'descendant.handle' if mode == 'cancel_running' else 'prepared.marker'
                until = time.monotonic() + 8
                while not (folder / marker).exists():
                    assert proc.poll() is None and time.monotonic() < until, str(folder)
                    time.sleep(0.01)
                if owner is not None:
                    owner.kill()  # exact original lease-owner process handle
                    out, err = owner.communicate(timeout=5)
                    assert not out and not err, (str(folder), out, err)
                else:
                    revoked.set()
                    lifetime._thread.join(2)
                    assert not lifetime._thread.is_alive(), str(folder)
                (folder / 'continue.marker').write_text('test coordination', encoding='ascii')
            out, err = proc.communicate(timeout=14)
            assert proc.returncode == 0 and not err, (str(folder), out, err)
            result = json.loads(out)
            refused = mode in ('cancel_preparation', 'owner_death_preparation', 'deadline_preparation', 'disposed', 'sticky_refusal', 'native_failure')
            if refused:
                cause = 'Preparation window unavailable' if mode == 'deadline_preparation' else (
                    'Preparation owner unavailable' if mode == 'disposed' else (
                    'Atomic job attribute refused' if mode == 'native_failure' else 'Caller lifetime unavailable before creation'))
                assert result['status'] == 'unknown' and result['cause'] == cause, (str(folder), result)
                assert not (folder / 'root.handle').exists() and not (folder / 'resumed.marker').exists(), str(folder)
                if mode in ('sticky_refusal', 'native_failure'):
                    assert result['again'] == ('Preparation already consumed' if mode == 'native_failure' else 'Preparation owner unavailable'), (str(folder), result)
            else:
                assert result['status'] == 'returned', (str(folder), result)
                answer = result['answer']
                assert answer['PreparationObserved'] is answer['LifetimeObserved'] is answer['ProcessTreeObserved'] is True, (str(folder), answer)
                assert answer['Code'] == (125 if mode == 'cancel_running' else (124 if mode == 'deadline_running' else 0)), (str(folder), answer)
                assert answer['Cancelled'] == (mode == 'cancel_running') and answer['Timeout'] == (mode == 'deadline_running')
                assert not answer['Stderr'] and answer['Truncated'] is False, (str(folder), answer)
                if mode == 'consumed_twice':
                    assert result['again'] == 'Preparation already consumed', (str(folder), result)
                for leaf in ('root', 'descendant'):
                    path = folder / (leaf + '.handle')
                    if path.exists():
                        handle = int(path.read_text(encoding='ascii'))
                        handles.append(handle)
                        assert k.WaitForSingleObject(handle, 5000) == 0, 'Termination UNKNOWN: ' + str(folder)
                assert len(handles) == (2 if mode in ('cancel_running', 'deadline_running') else 1), str(folder)
    finally:
        for process in (owner, proc):
            if process is not None and process.poll() is None:
                process.kill()
                process.communicate(timeout=5)
        for leaf in ('root', 'descendant'):
            path = folder / (leaf + '.handle')
            if path.exists():
                handle = int(path.read_text(encoding='ascii'))
                if handle not in handles:
                    handles.append(handle)
        for handle in handles:
            assert k.CloseHandle(handle), 'Capability close UNKNOWN; retain: ' + str(folder)
    shutil.rmtree(folder)  # only verified exact disposable fixtures reach removal
