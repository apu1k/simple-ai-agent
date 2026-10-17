"""Timeout policy and real unelevated process-tree fixtures; no UAC or Hyper-V."""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from runtime import elevated_commands as commands
from runtime import privileged_host as evidence
from runtime import privileged_inspection as inspection
from runtime.privileged_turn import ELEVATED_OPERATION, PrivilegedTurn

ROOT = Path(__file__).resolve().parents[2]
SID = 'S-1-5-21-1-2-3-1001'


@pytest.mark.parametrize('limit', [60, 900])
def test_general_launcher_preserves_lower_installed_authority(monkeypatch, tmp_path, limit):
    root = tmp_path / commands.HELPER_DIRECTORY
    root.mkdir()
    helper = b'fixture helper, never executed'
    (root / 'helper.ps1').write_bytes(helper)
    policy = dict(version=1, operator_sid=SID, max_timeout=limit,
                  helper_sha256=hashlib.sha256(helper).hexdigest())
    monkeypatch.setattr(commands, '_windows_paths', lambda: (tmp_path / 'evidence', tmp_path / 'ps.exe'))
    monkeypatch.setattr(commands, '_assert_protected', lambda *a, **kw: None)
    monkeypatch.setattr(commands, '_bounded_json', lambda p: policy)
    monkeypatch.setattr(commands, '_current_user_sid', lambda: SID)
    monkeypatch.setattr(commands, 'local_path', lambda *a, **kw: root)
    assert commands.load_launcher()[2]['max_timeout'] == limit
    commands.validate_script('exit 0', 900, 'fixture')
    if limit == 60:
        monkeypatch.setattr(commands, 'await_approval', lambda *a: pytest.fail('must refuse before approval'))
        monkeypatch.setattr(commands, '_elevate', lambda *a, **kw: pytest.fail('must not elevate'))
        permit = PrivilegedTurn()
        permit.arm(ELEVATED_OPERATION)
        with permit.turn('head'), pytest.raises(evidence.PrivilegedHostError, match='exceeds installed'):
            commands.run_approved_script(permit, permit.claim(ELEVATED_OPERATION), 'exit 0',
                                         61, 'fixture', str(root))


@pytest.mark.parametrize('limit', [None, 60, 901, 1800, True, '900'])
def test_inspection_refuses_missing_or_different_execution_cap(limit):
    policy = {key: None for key in inspection.FIELDS}
    policy.update(version=1, max_execution_seconds=limit)
    if limit is None:
        del policy['max_execution_seconds']
    with pytest.raises(evidence.PrivilegedHostError):
        inspection.validate_policy(policy)


@pytest.mark.parametrize('limit', [None, 60, 901, 1800, True, '900'])
def test_evidence_refuses_legacy_or_different_cap_before_uac(monkeypatch, tmp_path, limit):
    policy = {key: None for key in evidence.FIELDS}
    policy.update(version=1, max_execution_seconds=limit)
    if limit is None:
        del policy['max_execution_seconds']
    monkeypatch.setattr(evidence, '_windows_paths', lambda: (tmp_path, tmp_path / 'ps.exe'))
    monkeypatch.setattr(evidence, '_assert_protected', lambda *a, **kw: None)
    monkeypatch.setattr(evidence, '_bounded_json', lambda p: policy)
    monkeypatch.setattr(evidence, '_elevate', lambda *a: pytest.fail('must not elevate'))
    with pytest.raises(evidence.PrivilegedHostError):
        evidence.load_policy()


def quote(value):
    return "'" + str(value).replace("'", "''") + "'"


@pytest.mark.skipif(os.name != 'nt', reason='native Windows job-object fixture')
@pytest.mark.parametrize('filename,watchdog,general', [
    ('privileged_command_helper.ps1', 'CommandWatchdog', True),
    ('privileged_host_helper.ps1', 'EvidenceWatchdog', False),
    ('privileged_inspection_helper.ps1', 'InspectionWatchdog', False),
])
def test_native_watchdog_caps_arguments_and_kills_timed_out_parent_and_child(
    tmp_path, filename, watchdog, general,
):
    # Extract only compiler input. Never execute a helper entry point or RunAs.
    helper = (ROOT / 'scripts' / filename).read_text()
    match = re.search("Add-Type -TypeDefinition @'\n(.*?)\n'@", helper, re.S)
    assert match is not None
    pids = tmp_path / 'pids.json'
    late = tmp_path / 'late-marker'
    worker = tmp_path / 'fixture.py'
    child = f"import time;from pathlib import Path;time.sleep(8);Path({str(late)!r}).write_text('late')"
    worker.write_text(
        'import json,os,subprocess,sys,time\nfrom pathlib import Path\n'
        f'p=subprocess.Popen([sys.executable,"-I","-S","-B","-c",{child!r}])\n'
        f'Path({str(pids)!r}).write_text(json.dumps([os.getpid(),p.pid]))\n'
        'time.sleep(30)\n', encoding='utf-8',
    )
    check = ("if(-not $answer.Timeout -or $answer.Code -ne 124){throw 'timeout not reported'}"
             if general else "if($answer -ne 124){throw 'timeout not reported'}")
    script = "Add-Type -TypeDefinition @'\n" + match[1] + "\n'@\n" + f"""
$ErrorActionPreference='Stop'
$exe={quote(sys.executable)}; $cwd={quote(tmp_path)}
foreach($ms in @(0,900001)) {{
    $refused=$false
    try {{ [{watchdog}]::Run($exe,'UNUSED_FIXTURE',$cwd,[uint32]$ms)|Out-Null }}
    catch {{
        $exception=$_.Exception
        while($exception.InnerException) {{ $exception=$exception.InnerException }}
        if($exception -is [ArgumentOutOfRangeException]) {{ $refused=$true }} else {{ throw }}
    }}
    if(-not $refused) {{ throw 'native execution cap not enforced' }}
}}
$clock=[Diagnostics.Stopwatch]::StartNew()
$answer=[{watchdog}]::Run($exe,{quote('-I -S -B "' + str(worker) + '"')},$cwd,1500)
{check}
if($clock.ElapsedMilliseconds -gt 8000) {{ throw 'watchdog exceeded bounded termination allowance' }}
$ids=[IO.File]::ReadAllText({quote(pids)})|ConvertFrom-Json
foreach($id in $ids) {{
    $process=$null
    try {{ $process=[Diagnostics.Process]::GetProcessById([int]$id) }} catch [ArgumentException] {{}}
    if($process) {{
        try {{ if(-not $process.WaitForExit(3000)) {{ throw 'fixture process survived timeout' }} }}
        finally {{ $process.Dispose() }}
    }}
}}
if(Test-Path -LiteralPath {quote(late)}) {{ throw 'timed-out child continued work' }}
Write-Output 'EXECUTION_LIMIT_FIXTURE_PASSED'
"""
    exe = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    result = subprocess.run([str(exe), '-NoProfile', '-NonInteractive', '-Command', script],
                            capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'EXECUTION_LIMIT_FIXTURE_PASSED' in result.stdout


def test_all_launch_sites_clamp_execution_separately_from_turn_deadline():
    command = (ROOT / 'scripts/privileged_command_helper.ps1').read_text()
    evidence_text = (ROOT / 'scripts/privileged_host_helper.ps1').read_text()
    inspection_text = (ROOT / 'scripts/privileged_inspection_helper.ps1').read_text()
    assert '[Math]::Min([int]$request.timeout,900)' in command
    assert '[Math]::Min($remaining, 900)' in evidence_text
    assert '[Math]::Min($remaining,900)' in inspection_text
    assert inspection_text.index('if ($workerExit -eq 124)') < inspection_text.index('$factsPath =')
    for text in (command, evidence_text, inspection_text):
        assert '900000' in text and 'ArgumentOutOfRangeException' in text
    for name in ('command', 'host', 'inspection'):
        text = (ROOT / 'scripts' / f'install_privileged_{name}_helper.ps1').read_text()
        assert ('max_timeout=900' in text or 'max_execution_seconds = 900' in text
                or 'max_execution_seconds=900' in text)
