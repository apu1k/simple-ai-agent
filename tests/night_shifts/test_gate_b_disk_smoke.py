"""Parse the Windows disk script and exercise its non-mutating mapping guard."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "gate_b_disk_smoke.ps1"
pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell parser required")

_PARSE = r"""
$ErrorActionPreference = 'Stop'
$tokens = $null; $errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($env:GATE_B_TEST_SCRIPT, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw (($errors | ForEach-Object { $_.ToString() }) -join "`n") }
"""


def _powershell(code: str) -> str:
    exe = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    proc = subprocess.run([str(exe), "-NoProfile", "-NonInteractive", "-Command", code],
                          env={**os.environ, "GATE_B_TEST_SCRIPT": str(_SCRIPT)},
                          capture_output=True, text=True, timeout=12)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc.stdout


def test_windows_disk_smoke_script_parses_without_executing_it() -> None:
    assert "parsed" in _powershell(_PARSE + "\nWrite-Output 'parsed'")


def test_windows_disk_smoke_loads_system_modules_with_restricted_module_path() -> None:
    code = _PARSE + r"""
Set-StrictMode -Version 3
$env:PSModulePath = ''
$system = [Environment]::GetFolderPath('System')
$moduleRoot = Join-Path $system 'WindowsPowerShell\v1.0\Modules'
if (@(Get-ChildItem -LiteralPath $moduleRoot -Directory | Where-Object Name -in 'Hyper-V','Storage').Count -ne 2) {
    Write-Output 'system modules unavailable'
    return
}
$nodes = @($ast.FindAll({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
    $n.Name -eq 'Import-SmokeModules'}, $false))
if ($nodes.Count -ne 1) { throw 'Expected one module loader' }
. ([scriptblock]::Create($nodes[0].Extent.Text))
Import-SmokeModules $system
if (-not (Get-Command 'Hyper-V\New-VHD' -ErrorAction Stop) -or
    -not (Get-Command 'Storage\Format-Volume' -ErrorAction Stop)) { throw 'Expected disk cmdlets' }
Write-Output 'system modules loaded'
"""
    output = _powershell(code)
    if "system modules unavailable" in output:
        pytest.skip("Hyper-V and Storage system modules required")
    assert "system modules loaded" in output


def test_windows_disk_smoke_mapping_rejects_non_scratch_targets() -> None:
    # Execute only the guards found by the parser, not the script or storage cmdlets.
    code = _PARSE + r"""
Set-StrictMode -Version 3
$nodes = @($ast.FindAll({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
    $n.Name -in 'Confirm-SmokeMapping','Test-SmokeDiskIdentifier'}, $false))
if ($nodes.Count -ne 2) { throw 'Expected both mapping guards' }
foreach ($node in $nodes) { . ([scriptblock]::Create($node.Extent.Text)) }
$path = 'C:\Program Files\AiAgentGateB-DiskSmoke-test\input-smoke.vhdx'
$id = [guid]::NewGuid()
$vhd = @{Path=$path;DiskIdentifier=$id.ToString('B');VhdFormat='VHDX';VhdType='Dynamic';ParentPath=$null;
    Attached=$true;DiskNumber=3;Size=256MB}
$image = @{ImagePath=$path;Attached=$true;DevicePath='\\.\PhysicalDrive3'}
$disk = @{Number=3;Path='storage-path';BusType='File Backed Virtual';Size=256MB;IsBoot=$false;
    IsSystem=$false;IsClustered=$false;IsOffline=$false;IsReadOnly=$false;PartitionStyle='RAW';NumberOfPartitions=0}
Confirm-SmokeMapping $vhd $image $disk $path $id $true
$cases = @(
    @($vhd, 'DiskIdentifier', [guid]::NewGuid().ToString()), @($vhd, 'DiskIdentifier', 'invalid'),
    @($vhd, 'Attached', $false),
    @($vhd, 'ParentPath', 'unexpected-parent.vhdx'), @($vhd, 'DiskNumber', $null),
    @($image, 'ImagePath', 'C:\unrelated.vhdx'), @($image, 'DevicePath', '\\.\PhysicalDrive0'),
    @($disk, 'Number', 4), @($disk, 'Size', 512MB), @($disk, 'BusType', 'SATA'),
    @($disk, 'IsBoot', $true), @($disk, 'IsSystem', $true), @($disk, 'IsReadOnly', $true),
    @($disk, 'PartitionStyle', 'GPT'), @($disk, 'NumberOfPartitions', 1)
)
foreach ($case in $cases) {
    $record, $key, $value = $case
    $prior = $record[$key]
    $record[$key] = $value
    $refused = $false
    try { Confirm-SmokeMapping $vhd $image $disk $path $id $true }
    catch { $refused = $_.Exception.Message -match 'not positively identified|is not blank' }
    finally { $record[$key] = $prior }
    if (-not $refused) { throw ('Expected refusal for ' + $key) }
}
Write-Output ('refused ' + $cases.Count)
"""
    assert "refused 15" in _powershell(code)
