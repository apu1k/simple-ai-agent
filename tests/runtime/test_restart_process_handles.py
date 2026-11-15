"""Native handle checks target only newly created, disposable sleeping children."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from tests.runtime.test_windows_startup import powershell

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(os.name != "nt" or not shutil.which("powershell.exe"), reason="Windows PowerShell required")


@pytest.mark.parametrize("mode", ["stop-owned", "wrong-creation-time", "wrong-owner"])
def test_native_handle_stop_never_touches_an_unselected_process(mode):
    # Use the base interpreter, not a Windows venv redirector, so these fixture
    # processes have no shim/child tree and cleanup is limited to our two Popen handles.
    executable = getattr(sys, "_base_executable", sys.executable)
    children = []
    try:
        for _ in range(2):
            children.append(subprocess.Popen(
                [executable, "-c", "import time; time.sleep(60)"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            ))
        selected, bystander = children
        assert selected.pid != bystander.pid and selected.pid != os.getpid()
        result = powershell(r"""
. $env:AI_TEST_RESTART_HELPER
$handle = $null
$record = Get-CimInstance Win32_Process -Filter "ProcessId = $env:AI_TEST_SELECTED_PID" -ErrorAction Stop
if (-not $record) { throw 'Selected fixture exited unexpectedly' }
if ($env:AI_TEST_MODE -eq 'wrong-creation-time') {
    # CIM CreationDate is read-only. Shadow only the fixture's inspected metadata.
    $record | Add-Member -MemberType NoteProperty -Name CreationDate -Value ($record.CreationDate.AddSeconds(-10)) -Force
}
if ($env:AI_TEST_MODE -eq 'wrong-owner') {
    function Invoke-CimMethod { param($InputObject,$MethodName) return [pscustomobject]@{ ReturnValue = 0; Sid = 'S-1-0-0' } }
}
try {
    if ($env:AI_TEST_MODE -eq 'stop-owned') {
        $handle = Open-AgentRestartProcess -Record $record
        if ($handle.Id -ne [int]$env:AI_TEST_SELECTED_PID) { throw 'Wrong fixture handle' }
        Stop-AgentRestartProcesses -Processes @($handle)
    }
    else {
        try {
            $handle = Open-AgentRestartProcess -Record $record
            throw 'Unsafe identity was accepted'
        }
        catch {
            $message = $_.Exception.Message
            if ($env:AI_TEST_MODE -eq 'wrong-creation-time' -and $message -notlike '*identity changed*') { throw }
            if ($env:AI_TEST_MODE -eq 'wrong-owner' -and $message -notlike '*not owned*') { throw }
        }
    }
}
finally { if ($handle) { $handle.Dispose() } }
Write-Output 'fixture-handle-verified'
""", env={
            "AI_TEST_RESTART_HELPER": str(ROOT / "scripts" / "agent_restart.ps1"),
            "AI_TEST_SELECTED_PID": str(selected.pid), "AI_TEST_MODE": mode,
        })
        assert result.returncode == 0, result.stderr + result.stdout
        assert result.stdout.strip() == "fixture-handle-verified"
        if mode == "stop-owned":
            selected.wait(timeout=3)
            assert selected.returncode is not None
        else:
            assert selected.poll() is None
        assert bystander.poll() is None
    finally:
        # No name/port lookup or descendant sweep: only our newly owned children.
        for child in children:
            if child.poll() is None:
                child.terminate()
            child.wait(timeout=5)
