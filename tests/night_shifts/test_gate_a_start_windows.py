"""Run the fixed start action against mock PowerShell cmdlets only."""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / 'night_shifts/backends/hyperv_scripts/start_gate_a_vm.ps1'
_ID = 'a' * 32
_VM = '51434da9-9168-428a-8624-72a246ccc18d'
_FIXTURE = r'''
param([string]$Action, [string]$Mode, [string]$Scenario, [string]$Root, [string]$Id,
      [guid]$Guid, [string]$Asset, [long]$Cutoff)
$ErrorActionPreference = 'Stop'
$PSModuleAutoLoadingPreference = 'None'
Import-Module Microsoft.PowerShell.Management -ErrorAction Stop
Import-Module Microsoft.PowerShell.Utility -ErrorAction Stop
$testFamily = if ($Mode -eq 'finalization') { 'night-shift-auth-finalize' } else { 'night-shift' }
$testName = $testFamily + '-' + $Id
$testWorkspace = Join-Path $Root $Id
$testConfig = Join-Path (Join-Path $testWorkspace 'vm-config') $testName
$testDisk = if ($Mode -eq 'finalization') { Join-Path $testWorkspace 'working-copy.vhdx' }
    else { Join-Path $testWorkspace 'worker.vhdx' }
$testBoot = if ($Mode -eq 'finalization') { $Asset } else { $testDisk }
$testSeed = Join-Path $testWorkspace 'finalization-seed.iso'
$testPipe = '\\.\pipe\night-shift-' + $Id + '-com1'
$testState = @{ Started = $false; Queries = 0 }
function Get-VM {
    [CmdletBinding()]param()
    $testState.Queries++
    if ($Scenario -eq 'query_failure') { Write-Error 'fixture query fault'; return }
    $actualId = if ($Scenario -eq 'wrong_id') { [guid]'11111111-1111-1111-1111-111111111111' } else { $Guid }
    $actualOwner = if ($Scenario -eq 'wrong_owner' -or ($Scenario -eq 'drift' -and $testState.Queries -eq 2)) { 'wrong' }
        else { $testFamily + '-owner:' + $Id }
    $actualState = if ($Scenario -eq 'already_running' -or ($testState.Started -and $Scenario -ne 'unobserved')) { 'Running' }
        else { 'Off' }
    $actualCheckpoints = if ($Scenario -eq 'checkpoints') { 'Standard' } else { 'Disabled' }
    [pscustomobject]@{ Id=$actualId; Name=$testName; Notes=$actualOwner; State=$actualState;
        Generation=2; Path=$testConfig; CheckpointType=$actualCheckpoints; AutomaticCheckpointsEnabled=$false;
        AutomaticStartAction='Nothing'; AutomaticStopAction='ShutDown' }
}
function Get-VMHardDiskDrive { [CmdletBinding()]param($VM)
    [pscustomobject]@{ Path = if ($Scenario -eq 'wrong_disk') { $testDisk + '.other' } else { $testDisk } }
}
function Get-VMNetworkAdapter { [CmdletBinding()]param($VM)
    if ($Scenario -eq 'network') { [pscustomobject]@{ SwitchName='External'; SwitchId=[guid]::NewGuid() } }
    if ($Scenario -eq 'disconnected') { [pscustomobject]@{ SwitchName=$null; SwitchId=[guid]::Empty } }
}
function Get-VMSnapshot { [CmdletBinding()]param($VM) }
function Get-VMIntegrationService { [CmdletBinding()]param($VM,[string]$Name)
    [pscustomobject]@{ Enabled=($Scenario -eq 'gsi') }
}
function Get-VMComPort { [CmdletBinding()]param($VM,$Number)
    [pscustomobject]@{ Path = if ($Scenario -eq 'com') { $testPipe + '.wrong' } else { $testPipe } }
}
function Get-VMMemory { [CmdletBinding()]param($VM)
    [pscustomobject]@{ Startup=2147483648; DynamicMemoryEnabled=($Scenario -eq 'dynamic') }
}
function Get-VMProcessor { [CmdletBinding()]param($VM) [pscustomobject]@{ Count=2 } }
function Get-VHD { [CmdletBinding()]param($Path)
    $parent = if ($Scenario -eq 'parent') { $Asset + '.wrong' } elseif ($Mode -eq 'smoke') { $Asset } else { $null }
    $format = if ($Mode -eq 'smoke') { 'Differencing' } else { 'Dynamic' }
    [pscustomobject]@{ Path=$testDisk; VhdFormat='VHDX'; VhdType=$format; ParentPath=$parent;
        Size=21474836480; Attached=($Scenario -eq 'attached') }
}
function Get-VMDvdDrive { [CmdletBinding()]param($VM)
    if ($Mode -eq 'finalization' -or $Scenario -eq 'extra_dvd') { [pscustomobject]@{ Path=$Asset } }
    if ($Mode -eq 'finalization' -and $Scenario -ne 'no_seed') { [pscustomobject]@{ Path=$testSeed } }
}
function Get-VMFirmware { [CmdletBinding()]param($VM)
    $order = @([pscustomobject]@{ Device=[pscustomobject]@{ Path=$testBoot } })
    if ($Scenario -eq 'fallthrough') { $order += [pscustomobject]@{ Device=[pscustomobject]@{ Path=$testDisk } } }
    [pscustomobject]@{ SecureBoot='On'; SecureBootTemplate='MicrosoftUEFICertificateAuthority'; BootOrder=$order }
}
function Start-VM { [CmdletBinding()]param($VM)
    if ($VM.Id -ne $Guid -or $VM.State -ne 'Off' -or $testState.Started) { throw 'unexpected start invocation' }
    [Console]::WriteLine('start')
    if ($Scenario -eq 'start_failure') { Write-Error 'fixture provider fault'; return }
    $testState.Started = $true
}
try {
    & $Action -Operation $Mode -Identity $Id -VmId $Guid -WorkspaceRoot $Root -BootAsset $Asset -WorkUntilNanoseconds $Cutoff
    exit 0
} catch { [Console]::Error.WriteLine($_.Exception.Message); exit 1 }
'''


@pytest.mark.skipif(os.name != 'nt', reason='Windows PowerShell action fixture')
@pytest.mark.parametrize(('mode', 'scenario', 'expected'), [
    ('finalization', 'normal', 'running_observed'), ('smoke', 'normal', 'running_observed'),
    ('smoke', 'disconnected', 'running_observed'), ('finalization', 'disconnected', 'not_started'),
    ('finalization', 'wrong_id', 'not_started'), ('finalization', 'wrong_owner', 'not_started'),
    ('finalization', 'query_failure', 'not_started'), ('smoke', 'already_running', 'not_started'),
    ('smoke', 'drift', 'not_started'), ('finalization', 'wrong_disk', 'not_started'),
    ('smoke', 'checkpoints', 'not_started'), ('finalization', 'network', 'not_started'),
    ('smoke', 'network', 'not_started'), ('finalization', 'com', 'not_started'),
    ('smoke', 'gsi', 'not_started'), ('smoke', 'dynamic', 'not_started'),
    ('finalization', 'no_seed', 'not_started'), ('smoke', 'extra_dvd', 'not_started'),
    ('finalization', 'fallthrough', 'not_started'), ('smoke', 'attached', 'not_started'),
    ('smoke', 'parent', 'not_started'), ('finalization', 'parent', 'not_started'),
    ('finalization', 'expired', 'not_started'), ('smoke', 'start_failure', None),
    ('finalization', 'unobserved', None),
])
def test_start_once_after_exact_offline_vm_readback(tmp_path, mode, scenario, expected):
    powershell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    fixture = tmp_path / 'start-fixture.ps1'
    fixture.write_text(_FIXTURE, encoding='ascii')
    boot = tmp_path / ('reviewed.iso' if mode == 'finalization' else 'base.vhdx')
    deadline = 1 if scenario == 'expired' else time.monotonic_ns() + 10_000_000_000
    result = subprocess.run(
        [str(powershell), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'RemoteSigned', '-File',
         str(fixture), str(_SCRIPT), mode, scenario, str(tmp_path), _ID, _VM, str(boot), str(deadline)],
        capture_output=True, text=True, check=False, timeout=12,
    )
    lines = result.stdout.splitlines()
    if expected is None:
        assert lines == ['start'] and result.returncode == 1 and result.stderr
    else:
        assert result.returncode == 0 and not result.stderr, result.stderr
        assert lines[:-1] == (['start'] if expected == 'running_observed' else [])
        assert json.loads(lines[-1]) == {'version': 1, 'operation': mode, 'id': _ID, 'vm_id': _VM,
                                         'state': expected}
