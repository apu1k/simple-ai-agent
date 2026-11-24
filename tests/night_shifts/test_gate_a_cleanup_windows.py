"""Exercise recovery in native Windows PowerShell with simulated Hyper-V cmdlets."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != 'win32', reason='Windows PowerShell fixture')
_SCRIPT = (Path(__file__).resolve().parents[2] / 'night_shifts/backends/hyperv_scripts'
           / 'recover_gate_a_sandbox.ps1')
_FIXTURE = r"""
param([string]$Target, [string]$Workspace, [string]$BaseImage, [string]$Scenario)
$ErrorActionPreference = 'Stop'
$PSModuleAutoLoadingPreference = 'None'
Import-Module Microsoft.PowerShell.Management
Import-Module Microsoft.PowerShell.Utility
$fixtureName = 'night-shift-' + ('b' * 32)
$fixtureId = [guid]'350831d9-37df-40f2-8ca8-9d1e2edd50e6'
$fixtureDisk = Join-Path $Workspace 'worker.vhdx'
$fixtureConfig = Join-Path (Join-Path $Workspace 'vm-config') $fixtureName
$fixtureState = @{ Removed = ($Scenario -in @('disk_only', 'reference')); State = 'Running' }
function Get-VM {
    [CmdletBinding()]param()
    [pscustomobject]@{ Name = 'unrelated'; Id = [guid]'868acbfc-c03d-4fc3-a02e-021e2f1fc283'; Path = $BaseImage }
    if ($fixtureState.Removed -and $Scenario -ne 'renamed') { return }
    $vmName = if ($fixtureState.Removed) { 'renamed-after-removal' } else { $fixtureName }
    $notes = if ($Scenario -eq 'wrong_owner') { '' } else { 'night-shift-owner:' + ('b' * 32) }
    $configPath = if ($Scenario -eq 'wrong_config') { $BaseImage } else { $fixtureConfig }
    [pscustomobject]@{ Name = $vmName; Id = $fixtureId; Path = $configPath;
        Notes = $notes; Generation = 2; State = $fixtureState.State }
}
function Get-VMHardDiskDrive {
    [CmdletBinding()]param($VM)
    if ($VM.Id -eq $fixtureId -or $Scenario -eq 'reference') {
        [pscustomobject]@{ Path = $fixtureDisk }
    }
}
function Get-VMSnapshot {
    [CmdletBinding()]param($VM)
    if ($VM.Id -ne $fixtureId) { throw 'unexpected checkpoint query' }
    if ($Scenario -eq 'snapshot') { [pscustomobject]@{ Id = [guid]::NewGuid() } }
}
function Get-VHD {
    [CmdletBinding()]param([string]$Path)
    if ($Path -cne $fixtureDisk) { throw 'queried a non-disposable disk' }
    $parent = if ($Scenario -eq 'wrong_parent') { $Path } else { $BaseImage }
    [pscustomobject]@{ Path = $Path; ParentPath = $parent; VhdFormat = 'VHDX'; VhdType = 'Differencing';
        Attached = (-not $fixtureState.Removed -or $Scenario -eq 'still_attached') }
}
function Stop-VM {
    [CmdletBinding()]param($VM, [switch]$TurnOff, [switch]$Force)
    if ($VM.Id -ne $fixtureId -or -not $TurnOff -or -not $Force) { throw 'unexpected stop' }
    $fixtureState.State = 'Off'
    [Console]::WriteLine('fixture stop')
}
function Remove-VM {
    [CmdletBinding()]param($VM, [switch]$Force)
    if ($VM.Id -ne $fixtureId -or $VM.State -ne 'Off' -or -not $Force) { throw 'unexpected remove' }
    $fixtureState.Removed = $true
    [Console]::WriteLine('fixture remove')
}
try {
    & $Target -Workspace $Workspace -BaseImage $BaseImage -Apply:($Scenario -ne 'preview')
    exit 0
} catch { [Console]::Error.WriteLine($_.Exception.Message); exit 1 }
"""


@pytest.mark.parametrize(('scenario', 'out', 'error'), [
    ('preview', ['vm_candidate'], ''),
    ('apply', ['fixture stop', 'fixture remove', 'verified'], ''),
    ('disk_only', ['verified'], ''),
    ('reference', [], 'Another VM references'),
    ('wrong_config', [], 'configuration path did not match'),
    ('wrong_owner', [], 'ownership marker'),
    ('wrong_parent', [], 'disk identity, parent or detachment'),
    ('snapshot', [], 'no-checkpoint state'),
    ('renamed', ['fixture stop', 'fixture remove'], 'configuration path did not match'),
    ('still_attached', ['fixture stop', 'fixture remove'], 'disk identity, parent or detachment'),
])
def test_recovery_checks_native_effects(tmp_path: Path, scenario: str, out: list[str], error: str):
    ps = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    fixture = tmp_path / 'fixture.ps1'
    fixture.write_text(_FIXTURE, encoding='ascii')
    base = tmp_path / 'base.vhdx'
    base.write_bytes(b'base')
    workspace = tmp_path / ('gate-a-' + 'a' * 32) / 'sandboxes' / ('b' * 32)
    workspace.mkdir(parents=True)
    disk = workspace / 'worker.vhdx'
    disk.write_bytes(b'disposable')
    observed = subprocess.run(
        [str(ps), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'RemoteSigned', '-File', str(fixture),
         str(_SCRIPT), str(workspace), str(base), scenario], capture_output=True, text=True, check=False, timeout=10,
    )
    assert observed.stdout.splitlines() == out, observed.stderr
    assert observed.returncode == bool(error), observed.stderr
    assert error in observed.stderr if error else not observed.stderr
    assert disk.exists() is (scenario not in {'apply', 'disk_only'})
    assert base.read_bytes() == b'base'
