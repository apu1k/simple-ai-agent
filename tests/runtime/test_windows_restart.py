"""Restart-controller tests use only scratch launchers and fake processes/APIs."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
from uuid import uuid4

import pytest

from tests.runtime.test_windows_startup import TOKEN, fake_backend, powershell

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
pytestmark = pytest.mark.skipif(os.name != "nt" or not shutil.which("powershell.exe"), reason="Windows PowerShell required")


def helper_env():
    return {"AI_TEST_RESTART_HELPER": str(SCRIPTS / "agent_restart.ps1")}


@pytest.mark.parametrize("name", ["agent_restart.ps1", "restart_agent.ps1"])
def test_restart_scripts_parse_without_execution(name):
    result = powershell(r"""
$tokens = $null; $problems = $null
[Management.Automation.Language.Parser]::ParseFile($env:AI_TEST_SCRIPT, [ref]$tokens, [ref]$problems) | Out-Null
if ($problems.Count) { throw ($problems.Message -join '; ') }
""", env={"AI_TEST_SCRIPT": str(SCRIPTS / name)})
    assert result.returncode == 0, result.stderr


def test_batch_launcher_is_relative_and_preserves_the_exit_status():
    text = (ROOT / "restart_agent.bat").read_text(encoding="utf-8")
    assert '%~dp0scripts\\restart_agent.ps1' in text
    assert 'set "result=%ERRORLEVEL%"' in text
    assert 'exit /b %result%' in text
    assert "-Verb RunAs" not in text


def test_status_probe_authenticates_without_exporting_chat(tmp_path):
    payload = {"version": 1, "server_id": "a" * 32, "process_id": 321,
               "sequence": 7, "processing": False, "pending_count": 2, "closed": False}
    with fake_backend(200, payload) as (port, requests):
        helper = tmp_path / "probe.ps1"
        helper.write_text((SCRIPTS / "agent_restart.ps1").read_text(encoding="utf-8").replace(
            "http://127.0.0.1:8765", f"http://127.0.0.1:{port}",
        ), encoding="utf-8")
        result = powershell(r"""
. $env:AI_TEST_RESTART_HELPER
$status = Get-AgentRestartStatus
if ($status.Legacy -or $status.Processing -or $status.Sequence -ne 7 -or $status.PendingCount -ne 2) { throw 'Incorrect status' }
Write-Output 'status-verified'
""", env={"AI_TEST_RESTART_HELPER": str(helper), "AI_AGENT_TOKEN": TOKEN})
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "status-verified"
    assert requests == [("/v1/maintenance", f"Bearer {TOKEN}")]
    assert TOKEN not in result.stdout + result.stderr


@pytest.mark.parametrize("status,payload", [(401, {}), (302, {}), (200, {"version": 1}),
                                             (200, {"padding": "x" * 70000})])
def test_bad_status_or_redirect_fails_closed_without_a_second_request(tmp_path, status, payload):
    with fake_backend(status, payload) as (port, requests):
        helper = tmp_path / "probe.ps1"
        helper.write_text((SCRIPTS / "agent_restart.ps1").read_text(encoding="utf-8").replace(
            "http://127.0.0.1:8765", f"http://127.0.0.1:{port}",
        ), encoding="utf-8")
        result = powershell(". $env:AI_TEST_RESTART_HELPER; Get-AgentRestartStatus | Out-Null",
                            env={"AI_TEST_RESTART_HELPER": str(helper), "AI_AGENT_TOKEN": TOKEN})
    assert result.returncode != 0
    assert len(requests) == 1
    assert TOKEN not in result.stdout + result.stderr


@pytest.mark.parametrize("legacy,answer,accepted", [
    (False, "RESTART", True), (False, "cancel", False),
    (True, "RESTART", False), (True, "LEGACY RESTART", True),
])
def test_confirmation_requires_explicit_legacy_acknowledgement(legacy, answer, accepted):
    result = powershell(r"""
. $env:AI_TEST_RESTART_HELPER
function Read-Host { param($Prompt) return $env:AI_TEST_ANSWER }
$status = [pscustomobject]@{ Legacy = ($env:AI_TEST_LEGACY -eq 'yes'); Processing = $false; PendingCount = 3; Closed = $false }
$actual = Confirm-AgentRestart -Status $status
if ($actual -ne ($env:AI_TEST_ACCEPTED -eq 'yes')) { throw 'Wrong confirmation result' }
""", env=dict(helper_env(), AI_TEST_LEGACY="yes" if legacy else "no", AI_TEST_ANSWER=answer,
              AI_TEST_ACCEPTED="yes" if accepted else "no"))
    assert result.returncode == 0, result.stderr
    assert "live model context and pending proposals" in result.stdout


def test_drain_binds_the_reviewed_epoch_sequence_and_inspected_pid():
    result = powershell(r"""
. $env:AI_TEST_RESTART_HELPER
function Assert-AgentRestartTargetCurrent { param($Target,$Port) if ($Port -ne 8765) { throw 'Wrong port' } }
function Invoke-AgentRestartHttp {
    param($Path,$Method,$Body)
    if ($Path -ne '/v1/maintenance/drain' -or $Method -ne 'POST' -or $Body.server_id -ne ('a'*32) -or $Body.sequence -ne 7) { throw 'Wrong drain request' }
    return [pscustomobject]@{ Data = [pscustomobject]@{ server_id = ('a'*32); closed = $true } }
}
$status = [pscustomobject]@{ Legacy = $false; Processing = $false; ProcessId = 321; ServerId = ('a'*32); Sequence = 7 }
$target = [pscustomobject]@{ Process = [pscustomobject]@{ Id = 321 } }
Enter-AgentRestartDrain -Status $status -Target $target
$status.ProcessId = 999
try { Enter-AgentRestartDrain -Status $status -Target $target; throw 'Wrong PID accepted' }
catch { if ($_.Exception.Message -notlike '*PID differs*') { throw } }
Write-Output 'drain-verified'
""", env=helper_env())
    assert result.returncode == 0, result.stderr


def test_legacy_status_is_private_and_rechecked_after_confirmation():
    result = powershell(r"""
. $env:AI_TEST_RESTART_HELPER
$script:reads = 0
function Invoke-AgentRestartHttp {
    param($Path,$MaxChars)
    if ($Path -eq '/v1/maintenance') { return [pscustomobject]@{ Status = 404; Data = $null } }
    $script:reads++
    return [pscustomobject]@{ Status = 200; Data = [pscustomobject]@{
        version = 1; server_id = ('a'*32); pending = @()
        snapshot = [pscustomobject]@{ sequence = $script:reads; closed = $false; run = $null; messages = @('PRIVATE_CHAT_SENTINEL') }
    } }
}
function Assert-AgentRestartTargetCurrent { param($Target,$Port) }
$status = Get-AgentRestartStatus
if (-not $status.Legacy -or $status.Sequence -ne 1) { throw 'Legacy status not read' }
try { Enter-AgentRestartDrain -Status $status -Target ([pscustomobject]@{}); throw 'Changed legacy state accepted' }
catch { if ($_.Exception.Message -notlike '*changed after confirmation*') { throw } }
Write-Output 'legacy-rechecked'
""", env=helper_env())
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "legacy-rechecked"
    assert "PRIVATE_CHAT_SENTINEL" not in result.stdout + result.stderr


@pytest.mark.parametrize("kind", ["backend", "textual"])
@pytest.mark.parametrize("mode", ["valid-shim", "foreign-project", "wrong-parent"])
def test_listener_selection_supports_venv_redirectors_but_rejects_other_processes(tmp_path, kind, mode):
    result = powershell(r"""
. $env:AI_TEST_RESTART_HELPER
$python = Join-Path $env:AI_TEST_PROJECT '.venv\Scripts\python.exe'
$textual = Join-Path $env:AI_TEST_PROJECT '.venv\Scripts\textual.exe'
$command = '"' + $python + '" -m runtime.server'
if ($env:AI_TEST_KIND -eq 'textual') { $command = '"' + $python + '" "' + $textual + '" serve -h 127.0.0.1 -p 8000 --dev main_textual.py' }
if ($env:AI_TEST_MODE -eq 'foreign-project') { $command = $command.Replace($env:AI_TEST_PROJECT, 'C:\another-project') }
$script:record = [pscustomobject]@{ ProcessId = 321; ParentProcessId = 320; CommandLine = $command; ExecutablePath = 'C:\Python\python.exe'; CreationDate = (Get-Date) }
$script:parent = [pscustomobject]@{ ProcessId = 320; CommandLine = $command; ExecutablePath = $python; CreationDate = (Get-Date).AddSeconds(-1) }
if ($env:AI_TEST_MODE -eq 'wrong-parent') { $script:parent.ExecutablePath = 'C:\unrelated\python.exe' }
function Get-AgentRestartPortOwner { param($Port) return 321 }
function Get-CimInstance { param($ClassName,$Filter) if ($Filter -eq 'ProcessId = 321') { return $script:record }; return $script:parent }
function Open-AgentRestartProcess { param($Record) return [pscustomobject]@{ Id = $Record.ProcessId } }
$target = Get-AgentRestartTarget -Project $env:AI_TEST_PROJECT -Port 8765 -Kind $env:AI_TEST_KIND
if ($target.Process.Id -ne 321) { throw 'Wrong target' }
""", env=dict(helper_env(), AI_TEST_PROJECT=str(tmp_path / "project with spaces"), AI_TEST_KIND=kind, AI_TEST_MODE=mode))
    if mode == "valid-shim":
        assert result.returncode == 0, result.stderr
    else:
        assert result.returncode != 0
        assert "will not be stopped" in result.stderr or "refusing restart" in result.stderr


@pytest.mark.parametrize("mode", ["success", "busy", "cancel", "drain-failed", "check-only"])
def test_controller_never_touches_live_stack_and_stops_only_after_confirmation_and_drain(tmp_path, mode):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    entry = scripts / "restart_agent.ps1"
    entry.write_text((SCRIPTS / "restart_agent.ps1").read_text(encoding="utf-8"), encoding="utf-8")
    for name in ("start_backend.ps1", "start_textual.ps1"):
        (scripts / name).write_text("throw 'A real launcher must never be called by this test'", encoding="utf-8")
    (scripts / "agent_startup.ps1").write_text(
        "function Initialize-AgentStartupEnvironment { param($Project) }\n"
        f"function Get-AgentStartupMutexName {{ param($Project,$Purpose) return 'Local\\restart-test-{uuid4().hex}' }}\n",
        encoding="utf-8",
    )
    (scripts / "agent_restart.ps1").write_text(r"""
function Trace { param($Text) Add-Content -LiteralPath $env:AI_TEST_TRACE -Value $Text }
function FakeProcess {
    param($Number)
    $value = [pscustomobject]@{ Id = $Number }
    $value | Add-Member ScriptMethod Dispose { Trace "dispose:$($this.Id)" }
    return $value
}
$script:mockBackend = [pscustomobject]@{ Process = (FakeProcess 501) }
$script:mockTextual = [pscustomobject]@{ Process = (FakeProcess 502) }
$script:reads = 0
function Get-AgentRestartTarget { param($Project,$Port,$Kind) if ($Kind -eq 'backend') { return $script:mockBackend }; return $script:mockTextual }
function Get-AgentRestartStatus {
    $script:reads++
    $epoch = 'a'*32
    if ($script:reads -gt 1) { $epoch = 'b'*32 }
    return [pscustomobject]@{ Legacy = $false; ServerId = $epoch; ProcessId = 501; Sequence = 7; Processing = ($env:AI_TEST_MODE -eq 'busy'); PendingCount = 2; Closed = $false }
}
function Confirm-AgentRestart { param($Status) Trace 'confirm'; return ($env:AI_TEST_MODE -ne 'cancel') }
function Get-AgentRestartTree { param($Target) return @($Target.Process) }
function Assert-AgentRestartTargetCurrent { param($Target,$Port) Trace "verify:$Port" }
function Enter-AgentRestartDrain { param($Status,$Target) Trace 'drain'; if ($env:AI_TEST_MODE -eq 'drain-failed') { throw 'Simulated drain refusal' } }
function Stop-AgentRestartProcesses { param($Processes) foreach ($process in $Processes) { Trace "stop:$($process.Id)" } }
function Wait-AgentRestartBackendReleased { param($Project) Trace 'released' }
function Start-AgentRestartLauncher { param($Project,$Name,$Script) Trace "start:$Name" }
function Wait-AgentBackendReady { param($TimeoutSeconds) Trace 'ready:backend' }
function Get-AgentRestartPortOwner { param($Port) return $null }
function Wait-AgentRestartTextualReady { Trace 'ready:textual' }
""", encoding="utf-8")
    trace = tmp_path / "trace.txt"
    script = "& $env:AI_TEST_ENTRY" + (" -CheckOnly" if mode == "check-only" else "")
    result = powershell(script, env={"AI_TEST_ENTRY": str(entry), "AI_TEST_TRACE": str(trace), "AI_TEST_MODE": mode})
    events = trace.read_text(encoding="utf-8").splitlines() if trace.exists() else []
    stops = [event for event in events if event.startswith("stop:")]
    starts = [event for event in events if event.startswith("start:")]
    if mode == "success":
        assert result.returncode == 0, result.stderr + result.stdout
        assert stops == ["stop:502", "stop:501"]
        assert starts == ["start:backend", "start:textual"]
        assert events.index("confirm") < events.index("drain") < events.index("stop:502")
        assert events.index("ready:backend") < events.index("start:textual")
        assert "Caddy and Authelia were left untouched" in result.stdout
    else:
        assert not stops and not starts
        if mode in {"busy", "check-only"}:
            assert "confirm" not in events and "drain" not in events
        if mode == "cancel":
            assert "confirm" in events and "drain" not in events
        assert result.returncode == (1 if mode in {"busy", "drain-failed"} else 0)
