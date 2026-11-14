"""No UAC: fixed-call integration and ordinary native deadline/file fixtures."""
from __future__ import annotations

import base64
import json
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
    def run(gate, claim, script, seconds, reason, cwd, *, required_helper_sha256, require_lifetime, require_preparation, require_preparation_supervision, setup_preload):
        calls.append(claim)
        assert required_helper_sha256 == p['outer_helper_sha256'] and require_lifetime is require_preparation is require_preparation_supervision is True
        assert seconds == 20 and cwd == r'C:\SetupHost'
        assert json.loads(setup_preload)['indices'] == [10, 11, 12, 13]
        assert json.loads(setup_preload)['files'][3] == dict(name='validator-setup-watchdog.exe', **p['watchdog_pin'])
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


@pytest.mark.skipif(os.name != 'nt', reason='ordinary native preparation fault fixture')
@pytest.mark.parametrize('fault', ['qpc_rollback', 'utc_rollback', 'close'])
def test_preparation_clock_and_close_faults_remain_sticky_unknown(tmp_path, fault):
    import time
    from types import SimpleNamespace

    from night_shifts.ubuntu_preparation_control import _current_user_sid
    from runtime.command_lifetime import CommandLifetime
    from runtime.privileged_host import _windows_paths

    sid = _current_user_sid()
    lifetime = CommandLifetime(SimpleNamespace(execution_cancelled=lambda claim: False), PrivilegedClaim(ID, time.time() + 30), sid)
    binding = lifetime.binding
    helper = Path(__file__).resolve().parents[2] / 'scripts/privileged_command_helper.ps1'
    code = f"""
$ErrorActionPreference='Stop'
$i=[Security.Principal.WindowsIdentity]::GetCurrent()
if ((New-Object Security.Principal.WindowsPrincipal($i)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {{ throw 'UNELEVATED fixture required' }}
$i.Dispose()
$text=[IO.File]::ReadAllText({quote(helper)}); $start=$text.IndexOf('using System;'); $end=$text.IndexOf("'@",$start)
$source=$text.Substring($start,$end-$start)
if ({quote(fault)} -eq 'close') {{
    $old='if (!closed) throw new Exception("Caller lifetime close unknown");'
    if (($source.Length-$source.Replace($old,'').Length)/$old.Length -ne 1) {{ throw 'Fixture seam changed' }}
    # Both real native closes STILL execute. Inject only uncertain observation.
    $source=$source.Replace($old,'if (!closed || PreparationFixture.Fault) throw new Exception("Caller lifetime close unknown");')
    $source+=' public static class PreparationFixture {{ public static bool Fault=true; }}'
}}
Add-Type -TypeDefinition $source
$rate=[Diagnostics.Stopwatch]::Frequency; $limit=[Diagnostics.Stopwatch]::GetTimestamp()+10*$rate
$p=[CommandWatchdog]::Prepare(10000,$limit,$rate,([DateTimeOffset]::UtcNow.ToUnixTimeSeconds()+20),{quote(binding['pipe'])},[uint32]{binding['owner_pid']},{quote(binding['owner_created'])},{quote(ID)})
try {{
    $expected='Preparation window unavailable'
    if ({quote(fault)} -eq 'close') {{
        $expected='Preparation close unknown'
    }} else {{
        $field=if ({quote(fault)} -eq 'qpc_rollback') {{ 'lastQpc' }} else {{ 'lastWall' }}
        $value=if ($field -eq 'lastQpc') {{ [Diagnostics.Stopwatch]::GetTimestamp()+$rate }} else {{ [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()+10000 }}
        # Test-only corruption of private observation state, not a production seam.
        $p.GetType().GetField($field,[Reflection.BindingFlags]'Instance,NonPublic').SetValue($p,[long]$value)
    }}
    $cause=$null
    try {{ if ({quote(fault)} -eq 'close') {{ $p.Dispose() }} else {{ $p.Check() }} }} catch {{
        $e=$_.Exception; while ($e.InnerException) {{ $e=$e.InnerException }}; $cause=$e.Message
    }}
    if ($cause -cne $expected) {{ throw ('Unexpected first cause: '+$cause) }}
    $cause=$null
    try {{ $p.Check() }} catch {{ $e=$_.Exception; while ($e.InnerException) {{ $e=$e.InnerException }}; $cause=$e.Message }}
    if ($cause -cne 'Preparation owner unavailable') {{ throw 'Fault recovered its owner' }}
}} finally {{ $p.Dispose() }}
Write-Output 'PREPARATION_FAULTS_PASSED'
"""
    _, exe = _windows_paths()
    with lifetime:
        result = subprocess.run([str(exe), '-NoProfile', '-NonInteractive', '-Command', code],
            capture_output=True, text=True, timeout=12, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'PREPARATION_FAULTS_PASSED' in result.stdout


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


@pytest.mark.skipif(os.name != 'nt', reason='ordinary native preparation/file/receipt fixture')
@pytest.mark.parametrize('phase', [0, 1, 2], ids=['claim', 'approved', 'payload'])
def test_preparation_revocation_blocks_next_write_but_retains_failure_record(tmp_path, phase):
    import time
    from threading import Event
    from types import SimpleNamespace

    from night_shifts.ubuntu_preparation_control import _current_user_sid
    from runtime.command_lifetime import CommandLifetime
    from runtime.privileged_host import _windows_paths

    sid = _current_user_sid()
    helper = Path(__file__).resolve().parents[2] / 'scripts/privileged_command_helper.ps1'
    revoked = Event()
    lifetime = CommandLifetime(SimpleNamespace(execution_cancelled=lambda claim: revoked.is_set()),
        PrivilegedClaim(ID, time.time() + 30), sid)
    binding = lifetime.binding
    code = f"""
$ErrorActionPreference='Stop'
$i=[Security.Principal.WindowsIdentity]::GetCurrent()
if ((New-Object Security.Principal.WindowsPrincipal($i)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {{ throw 'UNELEVATED fixture required' }}
$i.Dispose()
$text=[IO.File]::ReadAllText({quote(helper)}); $start=$text.IndexOf('using System;'); $end=$text.IndexOf("'@",$start)
Add-Type -TypeDefinition $text.Substring($start,$end-$start)
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile({quote(helper)},[ref]$tokens,[ref]$errors)
if ($errors.Count) {{ throw ($errors | Out-String) }}
foreach ($name in @('Write-New','Write-Receipt')) {{
    $node=$ast.Find({{param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $name}},$true)
    Invoke-Expression $node.Extent.Text
}}
$receipts={quote(tmp_path)}; $utf8=New-Object Text.UTF8Encoding($false,$true)
# Ordinary TEST descriptor only; the production Write-New body is unchanged.
$fileSecurity=New-Object Security.AccessControl.FileSecurity
$fileSecurity.SetSecurityDescriptorSddlForm({quote('O:' + sid + 'G:' + sid + 'D:P(A;;FA;;;' + sid + ')')})
$rate=[Diagnostics.Stopwatch]::Frequency; $limit=[Diagnostics.Stopwatch]::GetTimestamp()+10*$rate
$preparation=[CommandWatchdog]::Prepare(10000,$limit,$rate,([DateTimeOffset]::UtcNow.ToUnixTimeSeconds()+20),{quote(binding['pipe'])},[uint32]{binding['owner_pid']},{quote(binding['owner_created'])},{quote(ID)})
try {{
    $names=@('start.json','approved.json','payload.ps1')
    for ($j=0;$j -le {phase};$j++) {{ Write-New $names[$j] ($utf8.GetBytes('inert preparation bytes')) }}
    [IO.File]::WriteAllText({quote(tmp_path / 'prepared.marker')},'ready')
    $wait=[Diagnostics.Stopwatch]::StartNew()
    while (-not [IO.File]::Exists({quote(tmp_path / 'continue.marker')})) {{
        if ($wait.ElapsedMilliseconds -gt 5000) {{ throw 'FIXTURE_COORDINATION_TIMEOUT' }}
        [Threading.Thread]::Sleep(10)
    }}
    $refused=$false
    try {{ Write-New 'blocked.ps1' ($utf8.GetBytes('must not be written')) }} catch {{
        $e=$_.Exception; while ($e.InnerException) {{ $e=$e.InnerException }}
        if ($e.Message -cne 'Caller lifetime unavailable before creation') {{ throw }}
        $refused=$true
    }}
    if (-not $refused) {{ throw 'Revoked preparation wrote next file' }}
}} finally {{ $preparation.Dispose() }}
# Loss never prevents conservative failure DATA, and never bypasses executable preparation.
Write-Receipt 'result.json' @{{status='outcome_unknown';executed=$false;preparation_observed=$false;retry_authorized=$false}} $false
Write-Output 'PREPARATION_WRITE_REFUSAL_PASSED'
"""
    path = tmp_path / 'controller.ps1'
    path.write_text(code, encoding='utf-8-sig')
    _, exe = _windows_paths()
    with lifetime:
        proc = subprocess.Popen([str(exe), '-NoProfile', '-NonInteractive', '-File', str(path)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            until = time.monotonic() + 8
            while not (tmp_path / 'prepared.marker').exists():
                assert proc.poll() is None and time.monotonic() < until, str(tmp_path)
                time.sleep(0.01)
            revoked.set()
            lifetime._thread.join(2)
            assert not lifetime._thread.is_alive()
            (tmp_path / 'continue.marker').write_text('test coordination', encoding='ascii')
            out, err = proc.communicate(timeout=8)
            assert proc.returncode == 0 and not err, (out, err)
            assert b'PREPARATION_WRITE_REFUSAL_PASSED' in out
        finally:
            if proc.poll() is None:
                proc.kill()  # only the original exact-owned ordinary controller
            proc.communicate(timeout=5)
    assert not (tmp_path / 'blocked.ps1').exists()
    for i, name in enumerate(('start.json', 'approved.json', 'payload.ps1')):
        assert (tmp_path / name).exists() == (i <= phase)
        if i <= phase:
            assert (tmp_path / name).read_bytes() == b'inert preparation bytes'
    assert json.loads((tmp_path / 'result.json').read_bytes()) == dict(status='outcome_unknown', executed=False,
        preparation_observed=False, retry_authorized=False)


def test_protected_original_record_precedes_claim_and_native_invocation_has_no_renewal():
    helper = (Path(__file__).resolve().parents[2] / 'scripts/privileged_command_helper.ps1').read_text(encoding='utf-8')
    assert helper.index('$qpcFirst =') < helper.index("Write-Receipt ($RequestId + '.start.json')")
    assert 'execution_qpc_limit=$qpcLimit; execution_qpc_frequency=$qpcFrequency' in helper
    assert 'WaitForSingleObject(p.Process,Remaining(ms,limit,frequency))' in helper
    assert '$preparation = [CommandWatchdog]::Prepare' in helper
    assert helper.index('$preparation = [CommandWatchdog]::Prepare') < helper.index("Write-Receipt ($RequestId + '.start.json')")
    assert '$answer = [CommandWatchdog]::RunPrepared($preparation,$exe,(Command-Arguments $scriptPath),$request.cwd)' in helper
    assert helper.index('$preparation.Dispose(); $preparation = $null') < helper.index('$result.executed = $true')
