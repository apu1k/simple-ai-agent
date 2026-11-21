"""Exercise the exact-VM teardown action with fake Hyper-V cmdlets only."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from night_shifts.gate_a_watchdog import HostCleanup, TeardownTarget, validate_cleanup_receipt

pytestmark = pytest.mark.skipif(sys.platform != 'win32', reason='Windows PowerShell fixture')

_SCRIPT = (Path(__file__).resolve().parents[2] / 'night_shifts/backends/hyperv_scripts'
           / 'reconcile_gate_a_vm.ps1')
_VM_ID = '51434da9-9168-428a-8624-72a246ccc18d'
_ATTEMPT = 'a' * 32
_FIXTURE = r"""
param([string]$Target, [string]$Case, [string]$Mode, [string]$Root, [string]$Attempt, [string]$DiskAction = 'retain')
$ErrorActionPreference = 'Stop'
$PSModuleAutoLoadingPreference = 'None'
Import-Module Microsoft.PowerShell.Management -ErrorAction Stop
Import-Module Microsoft.PowerShell.Utility -ErrorAction Stop
$prefix = if ($Mode -eq 'smoke') { 'night-shift-' }
    elseif ($Mode -eq 'finalization' -and $Case -ne 'legacy_binding') { 'night-shift-auth-finalize-' }
    else { 'night-shift-finalize-' }
$diskFile = if ($Mode -eq 'smoke') { 'worker.vhdx' } else { 'working-copy.vhdx' }
$expectedDiskType = if ($Mode -eq 'smoke') { 'Differencing' } else { 'Dynamic' }
$fakeDisk = Join-Path (Join-Path $Root $Attempt) $diskFile
$exact = [guid]'51434da9-9168-428a-8624-72a246ccc18d'
$other = [guid]'bb9e5119-08d7-48df-9996-54e2273bfb26'
$fake = @{
    State = if ($Case -eq 'off') { 'Off' } else { 'Running' }
    Removed = $false
    Queries = 0
    Notes = $prefix + 'owner:' + $Attempt
    Name = $prefix + $Attempt
    Config = Join-Path (Join-Path (Join-Path $Root $Attempt) 'vm-config') ($prefix + $Attempt)
}
function Get-VM {
    [CmdletBinding()]
    param()
    $fake.Queries++
    if ($Case -eq 'query_error' -or ($Case -eq 'post_error' -and $fake.Removed)) {
        Write-Error 'fixture inventory error'
        return
    }
    $otherName = if ($Case -eq 'replacement' -and $fake.Removed) { $fake.Name.ToUpperInvariant() } else { 'unrelated' }
    [pscustomobject]@{ Id = $other; Name = $otherName; Notes = ''; Path = ''; Generation = 2; State = 'Running' }
    if ($Case -eq 'missing' -or ($fake.Removed -and $Case -ne 'renamed')) { return }
    $name = if ($fake.Removed) { 'renamed' } else { $fake.Name }
    $id = if ($Case -eq 'wrong_id') { $other } else { $exact }
    $notes = if ($Case -eq 'wrong_owner' -or ($Case -eq 'owner_drift' -and $fake.Queries -eq 2)) {
        $fake.Notes.ToUpperInvariant()
    } else { $fake.Notes }
    $path = if ($Case -eq 'wrong_config') { $Root } else { $fake.Config }
    $generation = if ($Case -eq 'wrong_generation') { 1 } else { 2 }
    [pscustomobject]@{ Id = $id; Name = $name; Notes = $notes; Path = $path;
        Generation = $generation; State = $fake.State }
    if ($Case -eq 'duplicate') {
        [pscustomobject]@{ Id = $other; Name = $fake.Name; Notes = ''; Path = ''; Generation = 2; State = 'Off' }
    }
}
function Get-VMHardDiskDrive {
    [CmdletBinding()]
    param($VM)
    if ($VM.Id -eq $exact) {
        if ($Case -eq 'disk_query_error') { Write-Error 'fixture disk query error'; return }
        if ($Case -eq 'wrong_disk') { [pscustomobject]@{ Path = $fakeDisk + '.other' }; return }
        [pscustomobject]@{ Path = $fakeDisk }
        if ($Case -eq 'extra_disk') { [pscustomobject]@{ Path = $fakeDisk + '.other' } }
    } elseif ($fake.Removed -and $Case -eq 'referenced') {
        [pscustomobject]@{ Path = $fakeDisk.ToUpperInvariant() }
    } elseif ($fake.Removed -and $Case -eq 'reference_query_error') {
        Write-Error 'fixture reference query error'
    }
}
function Get-VHD {
    [CmdletBinding()]
    param([string]$Path)
    if ($Path -ine $fakeDisk -or -not $fake.Removed) { throw 'unexpected VHD query' }
    if ($Case -eq 'vhd_error') { Write-Error 'fixture VHD query error'; return }
    if ($Case -eq 'vhd_missing') { return }
    $attached = switch ($Case) {
        'attached' { $true }
        'invalid_attached' { 'false' }
        default { $false }
    }
    $kind = if ($Case -eq 'vhd_type') { 'Fixed' } else { $expectedDiskType }
    [pscustomobject]@{ Path = $fakeDisk; VhdFormat = 'VHDX'; VhdType = $kind; Attached = $attached }
}
function Stop-VM {
    [CmdletBinding()]
    param($VM, [switch]$TurnOff, [switch]$Force)
    if ($VM.Id -ne $exact -or -not $TurnOff -or -not $Force) { throw 'unexpected stop target' }
    [Console]::WriteLine('stop')
    if ($Case -eq 'stop_error') { Write-Error 'fixture stop error'; return }
    if ($Case -ne 'stop_unconfirmed') { $fake.State = 'Off' }
}
function Remove-VM {
    [CmdletBinding()]
    param($VM, [switch]$Force)
    if ($VM.Id -ne $exact -or $fake.State -ne 'Off' -or -not $Force) { throw 'unexpected remove target' }
    [Console]::WriteLine('remove')
    if ($Case -eq 'remove_error') { Write-Error 'fixture remove error'; return }
    $fake.Removed = $true
}
function Remove-Item {
    [CmdletBinding()]
    param([string]$LiteralPath, [switch]$Force)
    if (-not $fake.Removed -or $LiteralPath -cne $fakeDisk -or -not $Force) { throw 'unexpected disk deletion' }
    [Console]::WriteLine('delete')
    if ($Case -eq 'delete_error') { Write-Error 'fixture delete error'; return }
    if ($Case -eq 'delete_no_effect') { return }
    Microsoft.PowerShell.Management\Remove-Item -LiteralPath $LiteralPath -Force -ErrorAction Stop
    $fake.Deleted = $true
}
function Get-ChildItem {
    [CmdletBinding()]
    param([string]$LiteralPath, [switch]$Force)
    if ($LiteralPath -ine (Split-Path -Parent $fakeDisk) -or -not $Force) { throw 'unexpected workspace query' }
    if ($Case -eq 'absence_error' -and $fake.Deleted) { Write-Error 'fixture absence query error'; return }
    Microsoft.PowerShell.Management\Get-ChildItem -LiteralPath $LiteralPath -Force -ErrorAction Stop
}
$selectedId = if ($Case -eq 'empty_id') { [guid]::Empty } else { $exact }
try {
    & $Target -Operation $Mode -Identity $Attempt -VmId $selectedId -WorkspaceRoot $Root `
        -RemoveSmokeDisk:($DiskAction -eq 'remove')
    exit 0
}
catch { [Console]::Error.WriteLine($_.Exception.Message); exit 1 }
"""


@pytest.mark.parametrize(('mode', 'case', 'actions', 'error'), [
    ('inspection', 'off', ['remove'], None),
    ('inspection', 'running', ['stop', 'remove'], None),
    ('finalization', 'running', ['stop', 'remove'], None),
    ('finalization', 'off', ['remove'], None),
    ('finalization', 'legacy_binding', [], 'VM identity is unconfirmed'),
    ('finalization', 'referenced', ['stop', 'remove'], 'disk is still referenced'),
    ('finalization', 'vhd_missing', ['stop', 'remove'], 'disk detachment was not observed'),
    ('smoke', 'running', ['stop', 'remove'], None),
    ('smoke', 'empty_id', [], 'Invalid Gate A teardown binding'),
    ('smoke', 'missing', [], 'VM identity is unconfirmed'),
    ('smoke', 'wrong_id', [], 'VM identity is unconfirmed'),
    ('smoke', 'wrong_owner', [], 'VM identity is unconfirmed'),
    ('smoke', 'wrong_config', [], 'VM identity is unconfirmed'),
    ('smoke', 'wrong_generation', [], 'VM identity is unconfirmed'),
    ('smoke', 'duplicate', [], 'VM identity is unconfirmed'),
    ('smoke', 'query_error', [], 'fixture inventory error'),
    ('smoke', 'disk_query_error', [], 'fixture disk query error'),
    ('smoke', 'wrong_disk', [], 'disk binding is unconfirmed'),
    ('smoke', 'extra_disk', [], 'disk binding is unconfirmed'),
    ('smoke', 'owner_drift', ['stop'], 'VM identity is unconfirmed'),
    ('smoke', 'stop_error', ['stop'], 'fixture stop error'),
    ('smoke', 'stop_unconfirmed', ['stop'], 'VM stop was not observed'),
    ('smoke', 'remove_error', ['stop', 'remove'], 'fixture remove error'),
    ('smoke', 'post_error', ['stop', 'remove'], 'fixture inventory error'),
    ('smoke', 'renamed', ['stop', 'remove'], 'VM absence was not observed'),
    ('smoke', 'replacement', ['stop', 'remove'], 'VM absence was not observed'),
    ('smoke', 'referenced', ['stop', 'remove'], 'disk is still referenced'),
    ('smoke', 'reference_query_error', ['stop', 'remove'], 'fixture reference query error'),
    ('smoke', 'vhd_error', ['stop', 'remove'], 'fixture VHD query error'),
    ('smoke', 'vhd_missing', ['stop', 'remove'], 'disk detachment was not observed'),
    ('smoke', 'attached', ['stop', 'remove'], 'disk detachment was not observed'),
    ('smoke', 'invalid_attached', ['stop', 'remove'], 'disk detachment was not observed'),
    ('smoke', 'vhd_type', ['stop', 'remove'], 'disk detachment was not observed'),
])
def test_gate_a_reconciliation_observes_exact_vm_and_retains_disk(
    tmp_path: Path, mode: str, case: str, actions: list[str], error: str | None,
) -> None:
    powershell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    fixture = tmp_path / 'reconcile-fixture.ps1'
    fixture.write_text(_FIXTURE, encoding='ascii')
    workspace = tmp_path / _ATTEMPT
    workspace.mkdir()
    disk = workspace / ('worker.vhdx' if mode == 'smoke' else 'working-copy.vhdx')
    disk.write_bytes(b'not a VHDX')
    result = subprocess.run(
        [str(powershell), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'RemoteSigned',
         '-File', str(fixture), str(_SCRIPT), case, mode, str(tmp_path), _ATTEMPT],
        capture_output=True, text=True, check=False, timeout=12,
    )
    lines = result.stdout.splitlines()
    assert lines[:len(actions)] == actions, result.stderr
    assert disk.read_bytes() == b'not a VHDX'
    if error is not None:
        assert result.returncode == 1 and error in result.stderr
        assert len(lines) == len(actions)
    else:
        assert result.returncode == 0 and not result.stderr, result.stderr
        assert len(lines) == len(actions) + 1
        assert json.loads(lines[-1]) == {
            'version': 1, 'operation': mode, 'id': _ATTEMPT, 'vm_id': _VM_ID,
            'vm_absent': True, 'disk_unattached_and_unreferenced': True, 'disk_retained': True,
        }
        if mode == 'finalization':
            target = TeardownTarget(mode, _ATTEMPT, _VM_ID)
            assert validate_cleanup_receipt(target, lines[-1].encode('ascii')) == HostCleanup(target, True)


@pytest.mark.parametrize(('mode', 'case', 'actions', 'error'), [
    ('smoke', 'running', ['stop', 'remove', 'delete'], None),
    ('smoke', 'off', ['remove', 'delete'], None),
    ('inspection', 'running', [], 'only permitted for the fixed smoke operation'),
    ('finalization', 'running', [], 'only permitted for the fixed smoke operation'),
    ('smoke', 'disk_missing_on_entry', [], 'regular unlinked smoke disk'),
    ('smoke', 'disk_directory', [], 'regular unlinked smoke disk'),
    ('smoke', 'disk_hard_link', [], 'regular unlinked smoke disk'),
    ('smoke', 'post_error', ['stop', 'remove'], 'fixture inventory error'),
    ('smoke', 'renamed', ['stop', 'remove'], 'VM absence was not observed'),
    ('smoke', 'referenced', ['stop', 'remove'], 'disk is still referenced'),
    ('smoke', 'attached', ['stop', 'remove'], 'disk detachment was not observed'),
    ('smoke', 'delete_error', ['stop', 'remove', 'delete'], 'fixture delete error'),
    ('smoke', 'delete_no_effect', ['stop', 'remove', 'delete'], 'Smoke disk absence was not observed'),
    ('smoke', 'absence_error', ['stop', 'remove', 'delete'], 'fixture absence query error'),
])
def test_gate_a_reconciliation_removes_only_the_smoke_disk_after_verified_vm_teardown(
    tmp_path: Path, mode: str, case: str, actions: list[str], error: str | None,
) -> None:
    powershell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    fixture = tmp_path / 'reconcile-fixture.ps1'
    fixture.write_text(_FIXTURE, encoding='ascii')
    workspace = tmp_path / _ATTEMPT
    workspace.mkdir()
    disk = workspace / ('worker.vhdx' if mode == 'smoke' else 'working-copy.vhdx')
    neighbor = workspace / 'untouched.vhdx'
    neighbor.write_bytes(b'keep')
    if case == 'disk_directory':
        disk.mkdir()
    elif case == 'disk_hard_link':
        os.link(neighbor, disk)
    elif case != 'disk_missing_on_entry':
        disk.write_bytes(b'not a VHDX')
    result = subprocess.run(
        [str(powershell), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'RemoteSigned',
         '-File', str(fixture), str(_SCRIPT), case, mode, str(tmp_path), _ATTEMPT, 'remove'],
        capture_output=True, text=True, check=False, timeout=12,
    )
    lines = result.stdout.splitlines()
    assert neighbor.read_bytes() == b'keep'
    assert lines[:len(actions)] == actions, result.stderr
    if error is None:
        assert result.returncode == 0 and not result.stderr, result.stderr
        assert len(lines) == len(actions) + 1
        assert json.loads(lines[-1]) == {
            'version': 1, 'operation': 'smoke', 'id': _ATTEMPT, 'vm_id': _VM_ID,
            'vm_absent': True, 'disk_unattached_and_unreferenced': True,
            'disk_retained': False, 'disk_absent': True,
        }
        target = TeardownTarget('smoke', _ATTEMPT, _VM_ID)
        assert validate_cleanup_receipt(target, lines[-1].encode('ascii')) == HostCleanup(target, False)
    else:
        assert result.returncode == 1 and error in result.stderr, result.stderr
        assert lines == actions
    if error is None or case in {'absence_error', 'disk_missing_on_entry'}:
        with pytest.raises(FileNotFoundError):
            disk.lstat()
    else:
        assert disk.exists()
