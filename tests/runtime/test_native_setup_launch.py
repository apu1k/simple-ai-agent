"""No UAC: fixed-call integration and ordinary native deadline/file fixtures."""
from __future__ import annotations

import base64
import os
import subprocess
from pathlib import Path

import pytest

from runtime import elevated_commands as client
from runtime import native_setup_launch as integration
from runtime.privileged_host import PrivilegedHostError
from runtime.privileged_turn import ELEVATED_OPERATION, PrivilegedClaim, PrivilegedTurn
from tests.night_shifts.test_bootstrap_native_setup_launch import ID, frame, observation, review
from tests.runtime.test_elevated_commands import quote


@pytest.mark.parametrize('status', ['completed', 'rejected', 'expired', 'uac_cancelled', 'timeout_outcome_unknown', 'helper_failed', 'missing'])
def test_fixed_integration_uses_existing_approval_and_never_retries(monkeypatch, status):
    p, template = review()
    outer, raw, receipt = observation(p)
    data = frame(outer, raw, receipt)
    data.update(status=status, receipt='PROTECTED_RECEIPT_REFERENCE', review_sha256='e' * 64)
    if status in ('rejected', 'expired', 'uac_cancelled'):
        data['executed'] = False
    calls = []
    def run(gate, claim, script, seconds, reason, cwd, *, required_helper_sha256):
        calls.append(claim)
        assert required_helper_sha256 == p['outer_helper_sha256']
        assert seconds == 20 and cwd == r'C:\SetupHost'
        encoded = script.split("FromBase64String('", 1)[1].split("')", 1)[0]
        assert 'NVSO0001' in script and ID in base64.b64decode(encoded).decode('ascii')
        assert 'No provisioning' in reason
        return data
    monkeypatch.setattr(integration, 'run_approved_script', run)
    result = integration.run_reviewed_setup_handoff(PrivilegedTurn(), PrivilegedClaim(ID, 1500, ELEVATED_OPERATION), p, template=template)
    assert len(calls) == 1 and result['accepted'] is result['retry_authorized'] is result['provisioning_authorized'] is False
    expected = 'setup_observed_not_accepted' if status == 'completed' else (status if status in ('rejected', 'expired', 'uac_cancelled') else 'setup_outcome_unknown')
    assert result['status'] == expected and result['gate_a'] == 'unrun'


def test_fixed_integration_has_no_other_operation_or_unpinned_template_fallback(monkeypatch):
    monkeypatch.setattr(integration, 'run_approved_script', lambda *args, **kwargs: pytest.fail('must not request execution'))
    p, template = review()
    with pytest.raises(integration.SetupLaunchRefused, match='operation'):
        integration.run_reviewed_setup_handoff(PrivilegedTurn(), PrivilegedClaim(ID, 1500, 'inspect_image_copy'), p, template=template)
    with pytest.raises(integration.SetupLaunchRefused, match='template_pin'):
        integration.run_reviewed_setup_handoff(PrivilegedTurn(), PrivilegedClaim(ID, 1500, ELEVATED_OPERATION), p, template=template + b'changed')


@pytest.mark.skipif(os.name != 'nt', reason='ordinary Windows path guard fixture')
def test_independent_helper_pin_refuses_before_pending_or_uac(monkeypatch, tmp_path):
    monkeypatch.setattr(client, 'local_path', lambda *args, **kwargs: tmp_path)
    monkeypatch.setattr(client, 'load_launcher', lambda: (tmp_path, tmp_path / 'powershell.exe',
        {'operator_sid': 'fixture', 'helper_sha256': 'a' * 64, 'max_timeout': 900}))
    monkeypatch.setattr(client, 'await_approval', lambda *args, **kwargs: pytest.fail('must refuse before pending'))
    monkeypatch.setattr(client, '_elevate', lambda *args, **kwargs: pytest.fail('must not request UAC'))
    with pytest.raises(PrivilegedHostError, match='Independently reviewed'):
        client.run_approved_script(PrivilegedTurn(), PrivilegedClaim(ID, 1500, ELEVATED_OPERATION),
            'exit 0', 20, 'inert fixture', str(tmp_path), required_helper_sha256='b' * 64)


@pytest.mark.skipif(os.name != 'nt', reason='ordinary native QPC fixture; never protected helper execution')
def test_actual_command_watchdog_honors_original_window_after_preparation(tmp_path):
    from runtime.privileged_host import _windows_paths
    _, exe = _windows_paths()
    helper = Path(__file__).resolve().parents[2] / 'scripts/privileged_command_helper.ps1'
    marker = tmp_path / 'must-not-create.txt'
    command = base64.b64encode(f'[IO.File]::WriteAllText({quote(marker)}, "unexpected")'.encode('utf-16-le')).decode('ascii')
    script = f"""
$ErrorActionPreference='Stop'
$text=[IO.File]::ReadAllText({quote(helper)})
$start=$text.IndexOf('using System;'); $end=$text.IndexOf("'@",$start)
Add-Type -TypeDefinition $text.Substring($start,$end-$start)
$exe={quote(exe)}; $cwd={quote(tmp_path)}; $rate=[Diagnostics.Stopwatch]::Frequency
$limit=[Diagnostics.Stopwatch]::GetTimestamp()+[long]($rate*0.5)
$timer=[Diagnostics.Stopwatch]::StartNew()
$a=[CommandWatchdog]::RunWithin($exe,'-NoProfile -NonInteractive -Command "Start-Sleep -Seconds 30"',$cwd,10000,$limit,$rate)
if (-not $a.Timeout -or $a.Code -ne 124 -or $timer.Elapsed.TotalSeconds -gt 4) {{ throw 'Original cap renewed' }}
$limit=[Diagnostics.Stopwatch]::GetTimestamp()+[long]($rate*0.05)
[Threading.Thread]::Sleep(100)
$command='-NoProfile -NonInteractive -EncodedCommand {command}'
$refused=$false
try {{ [void][CommandWatchdog]::RunWithin($exe,$command,$cwd,10000,$limit,$rate) }} catch {{ $refused=$true }}
if (-not $refused -or [IO.File]::Exists({quote(marker)})) {{ throw 'Expired preparation created a child' }}
$refused=$false
try {{ [void][CommandWatchdog]::RunWithin($exe,$command,$cwd,10000,[Diagnostics.Stopwatch]::GetTimestamp()+$rate,$rate+1) }} catch {{ $refused=$true }}
if (-not $refused -or [IO.File]::Exists({quote(marker)})) {{ throw 'Counter mismatch created a child' }}
$limit=[Diagnostics.Stopwatch]::GetTimestamp()+5*$rate
$a=[CommandWatchdog]::RunWithin($exe,'-NoProfile -NonInteractive -Command "exit 0"',$cwd,10000,$limit,$rate)
if ($a.Timeout -or $a.Code -ne 0) {{ throw 'Bounded normal completion failed' }}
Write-Output 'ORIGINAL_WINDOW_FIXTURES_PASSED'
"""
    result = subprocess.run([str(exe), '-NoProfile', '-NonInteractive', '-Command', script],
        capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'ORIGINAL_WINDOW_FIXTURES_PASSED' in result.stdout and not marker.exists()


@pytest.mark.skipif(os.name != 'nt', reason='ordinary native file/PowerShell syntax fixture')
def test_actual_handoff_functions_empty_inventory_sharing_private_refusal_and_clock(tmp_path):
    from runtime.privileged_host import _windows_paths
    _, exe = _windows_paths()
    root = Path(__file__).resolve().parents[2]
    template = root / 'scripts/native_validator_setup_handoff.ps1'
    helper = root / 'scripts/privileged_command_helper.ps1'
    ordinary = tmp_path / 'ordinary.bin'
    ordinary.write_bytes(b'ordinary fixture bytes')
    empty = tmp_path / 'empty'
    empty.mkdir()
    script = f"""
$ErrorActionPreference='Stop'
$i=[Security.Principal.WindowsIdentity]::GetCurrent()
if ((New-Object Security.Principal.WindowsPrincipal($i)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {{ throw 'UNELEVATED fixture required' }}
$i.Dispose()
foreach ($file in @({quote(helper)},{quote(template)})) {{
    $tokens=$null; $errors=$null
    $ast=[Management.Automation.Language.Parser]::ParseFile($file,[ref]$tokens,[ref]$errors)
    if ($errors.Count) {{ throw ($errors | Out-String) }}
}}
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile({quote(template)},[ref]$tokens,[ref]$errors)
foreach ($name in @('Budget','PrivateFile','OpenHeld','Bytes','Digest','Names')) {{
    $function=$ast.Find({{param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -ceq $name}},$true)
    if ($null -eq $function) {{ throw 'Missing fixed function' }}
    Invoke-Expression $function.Extent.Text
}}
# Explicit path-admission double ONLY for ordinary disposable function fixtures.
# Production protected-path checks and the template are never changed on disk.
function ProtectedPath([string]$Path) {{ if (-not $Path.StartsWith({quote(tmp_path)},[StringComparison]::Ordinal)) {{ throw 'Outside fixture' }} }}
$review=@{{expires_unix=[long]([DateTimeOffset]::UtcNow.ToUnixTimeSeconds()+20);deadline_unix=[long]([DateTimeOffset]::UtcNow.ToUnixTimeSeconds()+20)}}
$lastQpc=[Diagnostics.Stopwatch]::GetTimestamp(); $lastWall=[DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
$cap=$lastQpc+20*[Diagnostics.Stopwatch]::Frequency
$held=New-Object 'Collections.Generic.List[IO.FileStream]'
try {{
    Names {quote(empty)} @()
    $f=OpenHeld {quote(ordinary)} 1024 $false
    if ([Text.Encoding]::ASCII.GetString((Bytes $f 1024)) -cne 'ordinary fixture bytes') {{ throw 'Bounded held bytes differ' }}
    $refused=$false
    try {{ $w=[IO.File]::Open({quote(ordinary)},'Open','Write','ReadWrite'); $w.Dispose() }} catch [IO.IOException] {{ $refused=$true }}
    if (-not $refused) {{ throw 'Held write sharing was not blocked' }}
    $refused=$false
    try {{ PrivateFile $f }} catch {{ if ($_.Exception.Message -notmatch 'Private held') {{ throw }}; $refused=$true }}
    if (-not $refused) {{ throw 'Ordinary file passed private admission' }}
    $digest=Digest $f
    if ($digest -cne {quote(__import__('hashlib').sha256(ordinary.read_bytes()).hexdigest())}) {{ throw 'Held digest differs' }}
    [IO.File]::WriteAllText([IO.Path]::Combine({quote(empty)},'occupied'),'fixture')
    $refused=$false
    try {{ Names {quote(empty)} @() }} catch {{ if ($_.Exception.Message -cne 'Fixed setup inventory differs') {{ throw }}; $refused=$true }}
    if (-not $refused) {{ throw 'Occupied inventory passed' }}
    $lastQpc=[Diagnostics.Stopwatch]::GetTimestamp()+[Diagnostics.Stopwatch]::Frequency
    $refused=$false
    try {{ Budget }} catch {{ if ($_.Exception.Message -cne 'Setup handoff window unavailable') {{ throw }}; $refused=$true }}
    if (-not $refused) {{ throw 'Counter rollback passed' }}
}} finally {{ foreach ($file in $held) {{ $file.Dispose() }} }}
Write-Output 'HANDOFF_FUNCTION_FIXTURES_PASSED'
"""
    result = subprocess.run([str(exe), '-NoProfile', '-NonInteractive', '-Command', script],
        capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'HANDOFF_FUNCTION_FIXTURES_PASSED' in result.stdout


def test_protected_original_record_precedes_claim_and_native_invocation_has_no_renewal():
    helper = (Path(__file__).resolve().parents[2] / 'scripts/privileged_command_helper.ps1').read_text(encoding='utf-8')
    assert helper.index('$qpcFirst =') < helper.index("Write-Receipt ($RequestId + '.start.json')")
    assert 'execution_qpc_limit=$qpcLimit; execution_qpc_frequency=$qpcFrequency' in helper
    assert 'WaitForSingleObject(p.Process,Remaining(ms,limit,frequency))' in helper
    assert '(Command-Arguments $scriptPath),$request.cwd,$ms,$qpcLimit,$qpcFrequency)' in helper
