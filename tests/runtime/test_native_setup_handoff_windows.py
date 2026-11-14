"""Full ORDINARY, INERT snapshot composition; never installation, UAC or setup.

Roles, private-path/descriptor admission and the setup body are explicit test
adapters in disposable COPIES. Actual snapshot hashing/claim/readback, both job
layers, QPC delivery, process handles and result transport execute. Observed pins
and fabricated transport records are TEST data, not production approval/evidence.
Failures retain the exact fixture tree; no retry, claim reset or broad cleanup.
"""
from __future__ import annotations

import ctypes as c
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from night_shifts import bootstrap_native_build as build
from night_shifts import bootstrap_native_setup_build as sb
from night_shifts import bootstrap_native_setup_launch as launch
from runtime.privileged_host import _windows_paths
from runtime.command_lifetime import CommandLifetime
from runtime.privileged_turn import PrivilegedClaim
from tests.night_shifts.test_bootstrap_native_setup_build import profile
from tests.night_shifts.test_native_validator_setup import powershell
from tests.night_shifts.test_native_validator_setup_supervision_windows import FIXTURE, _compile
from tests.runtime.test_elevated_commands import quote
from tests.runtime.test_command_preload import identity as native_identity, ordinary_source

ROOT = Path(__file__).resolve().parents[2]


def _once(text, old, new):
    assert text.count(old) == 1, 'Fixture source seam changed'
    return text.replace(old, new)


@pytest.mark.skipif(os.name != 'nt', reason='ordinary native nested-job/QPC fixture')
@pytest.mark.parametrize('mode', ['normal', 'bad_watchdog_pin', 'missing_window', 'claim_collision', 'exit_accounting_lag'])
@pytest.mark.parametrize('newlines', [b'\n', b'\r\n'], ids=['LF', 'CRLF'])
def test_complete_ordinary_handoff_snapshot_and_nested_watchdogs(mode, newlines):
    identity = powershell("$i=[Security.Principal.WindowsIdentity]::GetCurrent(); "
        "if((New-Object Security.Principal.WindowsPrincipal($i)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'UNELEVATED fixture required'}; $i.User.Value")
    assert identity.returncode == 0, identity.stdout + identity.stderr
    sid = identity.stdout.strip()
    assert sid.startswith('S-1-5-21-') and all(ch in 'S-0123456789' for ch in sid)
    workspace = Path(tempfile.mkdtemp(prefix='setup-handoff-ordinary-'))
    sources, target = workspace / 'sources', workspace / 'target'
    sources.mkdir()
    target.mkdir()
    for name in ('claims', 'receipts', 'scratch'):
        (target / name).mkdir()
    hp = profile()
    hp['operator_sid'] = sid
    hp['expires_unix'] = int(time.time()) + 600
    hp['host_anchor']['path'] = str(target)
    volume, index = native_identity(target)
    hp['host_anchor']['identity'] = dict(volume=volume, index=index)
    for name in ('claims', 'receipts', 'scratch'):
        hp['host_anchor'][name + '_index'] = native_identity(target / name)[1]
    hp['budget_seconds'] = 20
    paths = []
    for name in sb.WATCHDOG_SOURCES:
        path = ROOT / 'scripts' / name
        if name == 'native_validator_setup_supervisor_windows.cs':
            text = path.read_text(encoding='utf-8')
            old = 'O:BAG:BAD:P(A;;GA;;;SY)(A;;GA;;;BA)'
            path = sources / name
            path.write_text(_once(text, old, f'O:{sid}G:{sid}D:P(A;;GA;;;SY)(A;;GA;;;{sid})'), encoding='utf-8')
        paths.append(path)
    generated = sources / sb.HOST_PROFILE_NAME
    generated.write_bytes(sb.emit_setup_host_profile(hp))
    paths.append(generated)
    generated_watchdog = sources / sb.WATCHDOG_PROFILE_NAME
    generated_watchdog.write_bytes(sb.emit_setup_watchdog_profile({'bytes': 123, 'sha256': 'a' * 64}))
    paths.append(generated_watchdog)
    fixture = FIXTURE.replace('__MODE__', 'exit_accounting_lag' if mode == 'exit_accounting_lag' else 'normal').replace('__CONTROLLER_PID__', str(os.getpid()))
    fixture = _once(fixture, 'string PathOf(string n) { return Path.Combine(p.Host.Location.Root,n); }',
        'string PathOf(string n) { return Path.Combine(p.Host.Location.Root,n=="fixture-attempt.claim"?"claims/install-attempt.claim":'
        '((n=="operation-result.bin" || n=="supervisor-receipt.json")?"receipts/"+n:n)); }')
    old = 'if (watchdog) New(PathOf("fixture-attempt.claim"),p.Claim());'
    fixture = _once(fixture, old,
        'SetupPayload.Exact(File.ReadAllBytes(Path.Combine(p.Host.Location.Root,"claims/outer-attempt.claim")),p.OuterClaim()); ' + old)
    driver = sources / 'inert-fixture.cs'
    driver.write_text(fixture, encoding='utf-8')
    paths.append(driver)
    host = target / build.SETUP_ENTRY_POINTS[0][0]
    watchdog = target / build.SETUP_ENTRY_POINTS[1][0]
    _compile(sources, paths, host, 'AiAgent.ValidatorSetup.FixtureHostProgram')
    host_pin = {'bytes': host.stat().st_size, 'sha256': hashlib.sha256(host.read_bytes()).hexdigest()}
    generated_watchdog.write_bytes(sb.emit_setup_watchdog_profile(host_pin))
    _compile(sources, paths, watchdog, 'AiAgent.ValidatorSetup.FixtureWatchdogProgram')
    # Exercise exact LF/CRLF pins; normalize ONLY the later disposable test copy.
    template = (ROOT / 'scripts/native_validator_setup_handoff.ps1').read_bytes().replace(b'\r\n', b'\n').replace(b'\n', newlines)
    review = {'version': 1, 'scope': launch.SCOPE, 'host_profile': hp, 'host_pin': host_pin,
        'watchdog_pin': {'bytes': watchdog.stat().st_size, 'sha256': hashlib.sha256(watchdog.read_bytes()).hexdigest()},
        'template_pin': {'bytes': len(template), 'sha256': hashlib.sha256(template).hexdigest()}, 'outer_helper_sha256': 'd' * 64}
    if mode == 'bad_watchdog_pin':
        review['watchdog_pin']['sha256'] = '0' * 64
    (target / 'policy.json').write_bytes(launch._policy(review)[0])
    identity_id, until = 'c' * 32, int(time.time()) + 300
    frozen = launch.prepare_setup_handoff(review, template=template, request_id=identity_id, deadline_unix=until)
    snapshot = frozen.script
    snapshot = snapshot.replace('\r\n', '\n')  # TEST copy only, after exact-byte pin validation
    # Explicit ordinary-user TEST copies only. No production admission bypass.
    start, end = snapshot.index('function ProtectedPath('), snapshot.index('function PrivateFile(')
    snapshot = snapshot[:start] + ('function ProtectedPath([string]$Path) { if (-not $Path.StartsWith('
        + quote(str(workspace) + '\\') + ',[StringComparison]::OrdinalIgnoreCase)) { throw "Outside ordinary fixture" }; '
        'if ((Get-Item -LiteralPath $Path -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Fixture reparse" } }\n') + snapshot[end:]
    start, end = snapshot.index('function PrivateFile('), snapshot.index('function OpenHeld(')
    snapshot = snapshot[:start] + ('function PrivateFile([IO.FileStream]$File) { '
        'if ($File.GetAccessControl().GetOwner([Security.Principal.SecurityIdentifier]).Value -cne '
        + quote(sid) + ') { throw "Ordinary fixture owner differs" } }\n') + snapshot[end:]
    old = '-not (New-Object Security.Principal.WindowsPrincipal($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)'
    snapshot = _once(snapshot, old, old.removeprefix('-not '))
    snapshot = _once(snapshot, 'O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)', f'O:{sid}G:{sid}D:P(A;;FA;;;SY)(A;;FA;;;{sid})')
    old = "$outer = [IO.Path]::Combine([Environment]::GetFolderPath('ProgramFiles'),'AiAgentElevatedCommands','receipts',($review.request_id+'.start.json'))"
    start_path = workspace / 'start.json'
    snapshot = _once(snapshot, old, '$outer = ' + quote(start_path))
    # Exact failure cause + call marker prevent unrelated early refusals passing.
    snapshot = _once(snapshot, '} catch {\n    if ($entered -and -not $observed)',
        '} catch {\n    [Console]::Error.WriteLine("FIXTURE_CAUSE|"+$_.Exception.Message)\n    if ($entered -and -not $observed)')
    marker = target / 'load-attempt.marker'
    old = '$entered = $true # uncertainty BEFORE creation; never retry'
    snapshot = _once(snapshot, old, '[IO.File]::WriteAllText(' + quote(marker) + ',"fixture")\n    ' + old)
    snapshot_path = workspace / 'ordinary-snapshot.ps1'
    snapshot_path.write_text(snapshot, encoding='utf-8-sig')
    outer_claim = target / 'claims/outer-attempt.claim'
    collision = b'EXISTING ORDINARY FIXTURE CLAIM\n'
    if mode == 'claim_collision':
        outer_claim.write_bytes(collision)
    k = c.WinDLL('kernel32', use_last_error=True)
    for name in ('QueryPerformanceCounter', 'QueryPerformanceFrequency'):
        getattr(k, name).argtypes = [c.POINTER(c.c_int64)]
        getattr(k, name).restype = c.c_int
    k.WaitForSingleObject.argtypes = [c.c_void_p, c.c_uint32]
    k.WaitForSingleObject.restype = c.c_uint32
    k.CloseHandle.argtypes = [c.c_void_p]
    k.CloseHandle.restype = c.c_int
    count, rate = c.c_int64(), c.c_int64()
    assert k.QueryPerformanceFrequency(c.byref(rate)) and k.QueryPerformanceCounter(c.byref(count))
    cap = count.value + 20 * rate.value
    record = dict(version=1, operation='elevated_commands', status='started', preparation_protocol=1,
        setup_preload_protocol=1, setup_preload_sha256=hashlib.sha256(frozen.preload.encode('ascii')).hexdigest(), request_id=identity_id,
        operator_sid=sid, helper_sha256='d' * 64, timeout=20, deadline_unix=until,
        execution_qpc_limit=cap, execution_qpc_frequency=rate.value)
    if mode == 'missing_window':
        del record['execution_qpc_limit']
    start_path.write_text(json.dumps(record), encoding='utf-8')
    _, exe = _windows_paths()
    args = '-NoProfile -NonInteractive -ExecutionPolicy RemoteSigned -File "' + str(snapshot_path) + '"'
    # Explicit ordinary lease/admission fixture, not a privileged grant. The
    # real pipe, server identity and native cancellation checks remain intact.
    lease = CommandLifetime(SimpleNamespace(execution_cancelled=lambda claim: False), PrivilegedClaim(identity_id, until), sid)
    binding = lease.binding
    native = workspace / 'ordinary-preload.cs'
    native.write_text(ordinary_source(skip_private=True), encoding='utf-8')
    preload = json.loads(frozen.preload)
    # Bad inner pin is still rejected by the snapshot in this exact-cause case;
    # the OUTER native hold uses the true fixture watchdog pin, not approval.
    if mode == 'bad_watchdog_pin':
        preload['files'][3]['sha256'] = hashlib.sha256(watchdog.read_bytes()).hexdigest()
    preload_path = workspace / 'ordinary-preload.json'
    preload_path.write_text(json.dumps(preload), encoding='ascii')
    controller = f"""
$ErrorActionPreference='Stop'
Add-Type -Path {quote(native)}
$p=[CommandWatchdog]::Prepare(20000,{cap}L,{rate.value}L,{until}L,{quote(binding['pipe'])},[uint32]{binding['owner_pid']},{quote(binding['owner_created'])},{quote(identity_id)})
try {{
    $v=[IO.File]::ReadAllText({quote(preload_path)}) | ConvertFrom-Json
    $p.HoldSetup($v.root,[uint32]$v.volume,[uint64[]]$v.indices,[string[]]@($v.files | ForEach-Object {{$_.name}}),[long[]]@($v.files | ForEach-Object {{$_.bytes}}),[string[]]@($v.files | ForEach-Object {{$_.sha256}}))
    $p.Check(); $a=[CommandWatchdog]::RunPrepared($p,{quote(exe)},{quote(args)},{quote(workspace)})
}} finally {{ $p.Dispose() }}
$a | ConvertTo-Json -Compress
"""
    with lease:
        result = subprocess.run([str(exe), '-NoProfile', '-NonInteractive', '-Command', controller],
            capture_output=True, text=True, timeout=23, check=False)
    assert result.returncode == 0, (str(workspace), result.stdout, result.stderr)
    answer = json.loads(result.stdout)
    assert answer['Timeout'] is answer['Truncated'] is False, str(workspace)
    assert answer['ProcessTreeObserved'] is answer['LifetimeObserved'] is answer['PreparationObserved'] is answer['SetupPreloadObserved'] is True and answer['Cancelled'] is False, str(workspace)
    install_claim = target / 'claims/install-attempt.claim'
    if mode in ('normal', 'exit_accounting_lag'):
        if mode == 'exit_accounting_lag':
            assert (target / 'accounting-lag.marker').read_text(encoding='ascii') == '3'
        assert answer['Code'] == 0 and not answer['Stderr'], (str(workspace), json.dumps(answer, sort_keys=True))
        handle = int((target / 'child-handle.txt').read_text(encoding='ascii'))
        try:
            assert k.WaitForSingleObject(handle, 1000) == 0, str(workspace)
        finally:
            assert k.CloseHandle(handle), str(workspace)
        outer = dict(version=1, operation='elevated_commands', request_id=identity_id, helper_sha256='d' * 64, status='completed',
            executed=True, effects_verified=False, retry_authorized=False, output_truncated=False, exit_code=0, stderr='',
            stdout=answer['Stdout'], process_tree_observed=answer['ProcessTreeObserved'], lifetime_observed=answer['LifetimeObserved'],
            preparation_observed=answer['PreparationObserved'], setup_preload_observed=answer['SetupPreloadObserved'])
        observed = launch.reconcile_setup_handoff(review, request_id=identity_id, outer=outer)
        assert observed['status'] == 'setup_observed_not_accepted'
        assert observed['accepted'] is observed['provisioning_authorized'] is observed['retry_authorized'] is False
        assert observed['references']['indices'] == dict(zip(launch.setup.ANCHORS, range(100, 107), strict=True))
        assert outer_claim.exists() and install_claim.exists() and marker.exists()
        assert (target / 'limit.marker').read_text(encoding='ascii') == '1'
    else:
        expected = {'bad_watchdog_pin': 'Independently pinned launch input differs',
            'missing_window': 'Original protected execution window missing or mismatched', 'claim_collision': 'Fixed setup inventory differs'}[mode]
        assert answer['Code'] != 0 and not answer['Stdout'], (str(workspace), answer)
        assert 'FIXTURE_CAUSE|' + expected in answer['Stderr'], (str(workspace), answer)
        assert not marker.exists() and not install_claim.exists() and not (target / 'child-handle.txt').exists()
        assert outer_claim.exists() == (mode != 'missing_window')
        if mode == 'claim_collision':
            assert outer_claim.read_bytes() == collision
    # Only known successful fixture validation reaches exact-owned removal.
    # Failures/unknown process or close observations retain the entire tree.
    shutil.rmtree(workspace)
