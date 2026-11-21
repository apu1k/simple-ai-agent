param(
    [Parameter(Mandatory = $true)][ValidateSet('finalization', 'smoke')][string]$Operation,
    [Parameter(Mandatory = $true)][string]$Identity,
    [Parameter(Mandatory = $true)][guid]$VmId,
    [Parameter(Mandatory = $true)][string]$WorkspaceRoot,
    [Parameter(Mandatory = $true)][string]$BootAsset,
    [Parameter(Mandatory = $true)][long]$WorkUntilNanoseconds
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
# This is a body for the already armed protected supervisor, not a launch CLI.
# The owner holds the VM configuration, leased storage, and preverified media.
# Cmdlets resolve from the runner's pinned local Hyper-V module only.
foreach ($path in @($WorkspaceRoot, $BootAsset)) {
    if ($path -notmatch '^[A-Z]:\\[^\\]' -or [IO.Path]::GetFullPath($path) -cne $path) {
        throw 'Invalid Gate A start path binding'
    }
}
if ($Identity -cnotmatch '^[0-9a-f]{32}\z' -or $VmId -eq [guid]::Empty -or
    $WorkUntilNanoseconds -le 0) { throw 'Invalid Gate A start binding' }
$workspace = Join-Path $WorkspaceRoot $Identity
if ($Operation -eq 'finalization') {
    $family = 'night-shift-auth-finalize'
    $disk = Join-Path $workspace 'working-copy.vhdx'
    $diskType = 'Dynamic'
    $seed = Join-Path $workspace 'finalization-seed.iso'
    if ([IO.Path]::GetExtension($BootAsset) -ine '.iso' -or $BootAsset -ieq $seed) {
        throw 'Invalid Gate A recovery media binding'
    }
    $bootPath = $BootAsset
} else {
    $family = 'night-shift'
    $disk = Join-Path $workspace 'worker.vhdx'
    $diskType = 'Differencing'
    if ([IO.Path]::GetExtension($BootAsset) -ine '.vhdx' -or $BootAsset -ieq $disk) {
        throw 'Invalid Gate A base image binding'
    }
    $bootPath = $disk
}
$name = $family + '-' + $Identity
$owner = $family + '-owner:' + $Identity
$config = Join-Path (Join-Path $workspace 'vm-config') $name
$pipe = '\\.\pipe\night-shift-' + $Identity + '-com1'

function Get-OwnedVm([string]$ExpectedState) {
    $matchesFound = @(Get-VM -ErrorAction Stop | Where-Object { $_.Id -eq $VmId -or $_.Name -ieq $name })
    if ($matchesFound.Count -ne 1 -or $matchesFound[0].Id -ne $VmId -or
        $matchesFound[0].Name -cne $name -or $matchesFound[0].Notes -cne $owner -or
        $matchesFound[0].Generation -ne 2 -or $matchesFound[0].Path -ine $config -or
        $matchesFound[0].State -ne $ExpectedState) { throw 'Gate A start target unconfirmed' }
    $vm = $matchesFound[0]
    $drives = @(Get-VMHardDiskDrive -VM $vm -ErrorAction Stop)
    if ($drives.Count -ne 1 -or $drives[0].Path -ine $disk) { throw 'Gate A start disk unconfirmed' }
    $vm
}
function Assert-WorkWindow {
    # Stopwatch uses the same system QPC source as Windows monotonic_ns().
    if (-not [Diagnostics.Stopwatch]::IsHighResolution -or [Diagnostics.Stopwatch]::Frequency -le 0) {
        throw 'Gate A work clock unavailable'
    }
    $ticks = [Diagnostics.Stopwatch]::GetTimestamp()
    if ($ticks -lt 0 -or ([decimal]$ticks * 1000000000 / [Diagnostics.Stopwatch]::Frequency) -ge $WorkUntilNanoseconds) {
        throw 'Gate A work window closed'
    }
}
function Write-StartObservation([string]$State) {
    [ordered]@{ version = 1; operation = $Operation.ToLowerInvariant(); id = $Identity;
        vm_id = $VmId.ToString(); state = $State } | ConvertTo-Json -Compress
}

try {
    Assert-WorkWindow
    $vm = Get-OwnedVm 'Off'
    if ($vm.CheckpointType -ne 'Disabled' -or $vm.AutomaticCheckpointsEnabled -ne $false -or
        $vm.AutomaticStartAction -ne 'Nothing' -or $vm.AutomaticStopAction -ne 'ShutDown' -or
        @(Get-VMSnapshot -VM $vm -ErrorAction Stop).Count -ne 0) { throw 'Gate A power policy differs' }
    $adapters = @(Get-VMNetworkAdapter -VM $vm -ErrorAction Stop)
    if (($Operation -eq 'finalization' -and $adapters.Count -ne 0) -or
        @($adapters | Where-Object { $_.SwitchName -or $_.SwitchId -notin @($null, [guid]::Empty) }).Count -ne 0) {
        throw 'Gate A VM is not offline'
    }
    $gsi = @(Get-VMIntegrationService -VM $vm -Name 'Guest Service Interface' -ErrorAction Stop)
    $com = @(Get-VMComPort -VM $vm -Number 1 -ErrorAction Stop)
    $memory = @(Get-VMMemory -VM $vm -ErrorAction Stop)
    $processor = @(Get-VMProcessor -VM $vm -ErrorAction Stop)
    if ($gsi.Count -ne 1 -or $gsi[0].Enabled -isnot [bool] -or $gsi[0].Enabled -or
        $com.Count -ne 1 -or $com[0].Path -cne $pipe -or
        $memory.Count -ne 1 -or $memory[0].Startup -ne 2147483648 -or
        $memory[0].DynamicMemoryEnabled -isnot [bool] -or $memory[0].DynamicMemoryEnabled -or
        $processor.Count -ne 1 -or $processor[0].Count -ne 2) { throw 'Gate A device or resource policy differs' }
    $vhd = @(Get-VHD -Path $disk -ErrorAction Stop)
    if ($vhd.Count -ne 1 -or $vhd[0].Path -ine $disk -or $vhd[0].VhdFormat -ne 'VHDX' -or
        $vhd[0].VhdType -ne $diskType -or $vhd[0].Size -ne 21474836480 -or
        $vhd[0].Attached -isnot [bool] -or $vhd[0].Attached -or
        ($Operation -eq 'finalization' -and $vhd[0].ParentPath) -or
        ($Operation -eq 'smoke' -and $vhd[0].ParentPath -ine $BootAsset)) { throw 'Gate A VHD binding differs' }
    $dvds = @(Get-VMDvdDrive -VM $vm -ErrorAction Stop)
    if ($Operation -eq 'finalization') {
        if ($dvds.Count -ne 2 -or @($dvds | Where-Object { $_.Path -ieq $BootAsset }).Count -ne 1 -or
            @($dvds | Where-Object { $_.Path -ieq $seed }).Count -ne 1) { throw 'Gate A recovery DVDs differ' }
    } elseif (@($dvds | Where-Object { $_.Path }).Count -ne 0) { throw 'Gate A smoke VM has optical media' }
    $firmware = @(Get-VMFirmware -VM $vm -ErrorAction Stop)
    if ($firmware.Count -ne 1 -or $firmware[0].SecureBoot -ne 'On' -or
        $firmware[0].SecureBootTemplate -ne 'MicrosoftUEFICertificateAuthority' -or
        @($firmware[0].BootOrder).Count -ne 1 -or $firmware[0].BootOrder[0].Device.Path -ine $bootPath) {
        throw 'Gate A secure boot policy differs'
    }
    $vm = Get-OwnedVm 'Off'
    Assert-WorkWindow
} catch {
    # This success-shaped local receipt proves ONLY that this fixed invocation
    # never crossed Start-VM. It does not prove the VM is safe to remove.
    Write-StartObservation 'not_started'
    return
}
# No -AsJob, no resume, retries or cleanup. A fault after this crossing is
# UNKNOWN even if the PowerShell process exits. Only normal cmdlet completion
# plus exact running readback can settle an admitted start in the supervisor.
Start-VM -VM $vm -ErrorAction Stop | Out-Null
Get-OwnedVm 'Running' | Out-Null
Write-StartObservation 'running_observed'
