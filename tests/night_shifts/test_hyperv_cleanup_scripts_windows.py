"""Run the PowerShell cleanup scripts against fake VM cmdlets, never Hyper-V."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell fixture")

_SCRIPTS = Path(__file__).resolve().parents[2] / "night_shifts/backends/hyperv_scripts"
_FIXTURE = r"""
param([string]$Target, [string]$Scenario, [string]$DiskPath)
$ErrorActionPreference = 'Stop'
$PSModuleAutoLoadingPreference = 'None'
# Import only the stock cmdlets needed by the fixture; Hyper-V is never loaded.
Import-Module Microsoft.PowerShell.Management -ErrorAction Stop
Import-Module Microsoft.PowerShell.Utility -ErrorAction Stop
# Invoked scripts have their own $script: scope. Keep fake VM state in one
# distinct object inherited by the stubs, including across both inventories.
$gateAFixture = @{
    VmName = 'night-shift-' + ('a' * 32)
    Marker = 'night-shift-owner:' + ('a' * 32)
    Removed = $false
    State = if ($Scenario -in @('running', 'stop_unconfirmed')) { 'Running' } else { 'Off' }
    Id = [guid]'01a23bfd-e464-4829-8b83-de9e69c9db14'
    OtherId = [guid]'5d3e5890-17e0-45cc-abe7-7fa10e9c78fa'
}
function Get-VM {
    [CmdletBinding()]
    param([string]$Name)
    if ($PSBoundParameters.ContainsKey('Name')) { throw 'fixture requires full inventory' }
    if ($Scenario -eq 'query_error' -or ($Scenario -eq 'post_error' -and $gateAFixture.Removed)) {
        $PSCmdlet.WriteError([System.Management.Automation.ErrorRecord]::new(
            [System.InvalidOperationException]::new('fixture inventory failed'),
            'FixtureInventoryFailed', [System.Management.Automation.ErrorCategory]::ReadError, $null
        ))
        return
    }
    [pscustomobject]@{ Name = 'unrelated'; Notes = ''; Id = $gateAFixture.OtherId; State = 'Off' }
    if ($Scenario -in @('missing', 'missing_vm_disk_referenced')) { return }
    if ($gateAFixture.Removed) {
        if ($Scenario -eq 'renamed') {
            [pscustomobject]@{ Name = 'renamed'; Notes = $gateAFixture.Marker; Id = $gateAFixture.Id; State = 'Off' }
        }
        if ($Scenario -eq 'replacement') {
            [pscustomobject]@{ Name = $gateAFixture.VmName; Notes = ''; Id = [guid]::NewGuid(); State = 'Off' }
        }
        return
    }
    $notes = if ($Scenario -eq 'wrong_owner') { $gateAFixture.Marker.ToUpperInvariant() } else { $gateAFixture.Marker }
    [pscustomobject]@{ Name = $gateAFixture.VmName; Notes = $notes; Id = $gateAFixture.Id; State = $gateAFixture.State }
    if ($Scenario -eq 'duplicate') {
        [pscustomobject]@{ Name = $gateAFixture.VmName; Notes = $gateAFixture.Marker; Id = [guid]::NewGuid(); State = 'Off' }
    }
}
function Stop-VM {
    [CmdletBinding()]
    param($VM, [switch]$TurnOff, [switch]$Force)
    if ($VM.Id -ne $gateAFixture.Id -or -not $TurnOff -or -not $Force) { throw 'unexpected stop' }
    if ($Scenario -ne 'stop_unconfirmed') { $gateAFixture.State = 'Off' }
    [Console]::WriteLine('fixture stop')
}
function Remove-VM {
    [CmdletBinding()]
    param($VM, [switch]$Force)
    if ($VM.Id -ne $gateAFixture.Id -or $gateAFixture.State -ne 'Off' -or -not $Force) { throw 'unexpected remove' }
    $gateAFixture.Removed = $true
    [Console]::WriteLine('fixture remove')
}
function Get-VMHardDiskDrive {
    [CmdletBinding()]
    param($VM)
    if ($VM.Id -ne $gateAFixture.OtherId) { throw 'unexpected VM disk inventory' }
    if ($Scenario -eq 'disk_query_error') { Write-Error 'fixture disk inventory failed'; return }
    if ($Scenario -in @('disk_referenced', 'missing_vm_disk_referenced')) {
        [pscustomobject]@{ Path = $DiskPath.ToUpperInvariant() }
    }
}
function Get-VHD {
    [CmdletBinding()]
    param([string]$Path)
    if ($Path -cne $DiskPath) { throw 'unexpected VHD query' }
    if ($Scenario -eq 'vhd_query_error') { Write-Error 'fixture VHD inventory failed'; return }
    if ($Scenario -eq 'vhd_missing') { return }
    $kind = if ($Scenario -eq 'non_disposable') { 'Dynamic' } else { 'Differencing' }
    [pscustomobject]@{ Path = $DiskPath; VhdFormat = 'VHDX'; VhdType = $kind;
        Attached = ($Scenario -eq 'disk_attached') }
}
$parameters = @{ VmName = $gateAFixture.VmName; OwnerMarker = $gateAFixture.Marker }
if ([IO.Path]::GetFileName($Target) -eq 'destroy.ps1') { $parameters.DiskPath = $DiskPath }
try { & $Target @parameters; exit 0 }
catch { [Console]::Error.WriteLine($_.Exception.Message); exit 1 }
"""


@pytest.mark.parametrize(
    ("script", "scenario", "stdout", "error", "disk_retained"),
    [
        ("status", "missing", "Missing", None, True),
        ("status", "running", "Running", None, True),
        ("status", "query_error", "", "fixture inventory failed", True),
        ("status", "duplicate", "", "ambiguous", True),
        ("status", "wrong_owner", "", "owner marker", True),
        ("destroy", "missing", "", None, False),
        ("destroy", "running", "fixture stop\nfixture remove", None, False),
        ("destroy", "query_error", "", "fixture inventory failed", True),
        ("destroy", "duplicate", "", "ambiguous", True),
        ("destroy", "wrong_owner", "", "owner marker", True),
        ("destroy", "post_error", "fixture remove", "fixture inventory failed", True),
        ("destroy", "renamed", "fixture remove", "VM absence was not confirmed", True),
        ("destroy", "replacement", "fixture remove", "VM absence was not confirmed", True),
        ("destroy", "disk_directory", "fixture remove", "unexpected disposable disk", True),
        ("destroy", "stop_unconfirmed", "fixture stop", "Exact VM stop was not confirmed", True),
        ("destroy", "disk_referenced", "fixture remove", "still referenced by a VM", True),
        ("destroy", "missing_vm_disk_referenced", "", "still referenced by a VM", True),
        ("destroy", "disk_query_error", "fixture remove", "fixture disk inventory failed", True),
        ("destroy", "vhd_query_error", "fixture remove", "fixture VHD inventory failed", True),
        ("destroy", "vhd_missing", "fixture remove", "detachment was not confirmed", True),
        ("destroy", "disk_attached", "fixture remove", "detachment was not confirmed", True),
        ("destroy", "non_disposable", "fixture remove", "detachment was not confirmed", True),
    ],
)
def test_cleanup_requires_observed_absence(
    tmp_path: Path, script: str, scenario: str, stdout: str, error: str | None, disk_retained: bool,
) -> None:
    powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    fixture = tmp_path / "fixture.ps1"
    fixture.write_text(_FIXTURE, encoding="ascii")
    disk = tmp_path / "worker.vhdx"
    if scenario == "disk_directory":
        disk.mkdir()
    else:
        disk.write_bytes(b"inert fixture, not a disk image")

    observed = subprocess.run(
        [str(powershell), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "RemoteSigned",
         "-File", str(fixture), str(_SCRIPTS / f"{script}.ps1"), scenario, str(disk)],
        capture_output=True, text=True, timeout=12, check=False,
    )

    assert observed.stdout.strip() == stdout, observed.stderr
    assert disk.exists() is disk_retained
    if error is None:
        assert observed.returncode == 0, observed.stderr
        assert not observed.stderr
    else:
        assert observed.returncode == 1, observed.stderr
        assert error in observed.stderr
