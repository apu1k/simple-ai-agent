param(
    [Parameter(Mandatory = $true)][string]$VmName,
    [Parameter(Mandatory = $true)][string]$VmId,
    [Parameter(Mandatory = $true)][string]$OwnerMarker,
    [Parameter(Mandatory = $true)][string]$DiskPath,
    [Parameter(Mandatory = $true)][string]$VmConfigPath,
    [Parameter(Mandatory = $true)][string]$InstallerIso,
    [Parameter(Mandatory = $true)][string]$InstallerIsoSha256,
    [Parameter(Mandatory = $true)][string]$SeedIso,
    [Parameter(Mandatory = $true)][string]$SeedIsoSha256,
    [Parameter(Mandatory = $true)][long]$DiskSizeBytes,
    [Parameter(Mandatory = $true)][long]$MemoryBytes,
    [Parameter(Mandatory = $true)][long]$CpuCount
)
$ErrorActionPreference = 'Stop'
# Start ONCE for attended installation. Never repair settings, retry, poll an
# installer, reboot, remove media, stop a VM or certify a base image here.
if ($VmName -cnotmatch '^night-shift-image-prep-[0-9a-f]{32}$' -or
    $OwnerMarker -cne ('night-shift-image-prep-owner:' + $VmName.Substring(23)) -or
    $VmId -cnotmatch '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' -or
    [guid]$VmId -eq [guid]::Empty) {
    throw 'Untrusted preparation name, ownership marker or pinned VM GUID'
}
$workspace = Split-Path -Parent $DiskPath
$expectedConfigPath = Join-Path (Join-Path $workspace 'vm-config') $VmName
if ((Split-Path -Leaf $workspace) -cne $VmName.Substring(23) -or
    (Split-Path -Leaf $DiskPath) -cne 'ubuntu-build.vhdx' -or
    $VmConfigPath -ne $expectedConfigPath -or
    (Split-Path -Leaf $SeedIso) -cne ($VmName + '.iso') -or $InstallerIso -eq $SeedIso) {
    throw 'Preparation paths differ from the identity-scoped launch plan'
}
if ($CpuCount -lt 1 -or $CpuCount -gt 8 -or
    $MemoryBytes -lt 1073741824 -or $MemoryBytes -gt 8589934592 -or
    $DiskSizeBytes -lt 10737418240 -or $DiskSizeBytes -gt 42949672960 -or
    $InstallerIsoSha256 -cnotmatch '^[0-9a-f]{64}$' -or
    $SeedIsoSha256 -cnotmatch '^[0-9a-f]{64}$') {
    throw 'Launch resources or media digests are outside fixed bounds'
}
function Assert-LaunchIdentity($Candidate, $ExpectedState) {
    if (-not $Candidate -or $Candidate.Id -ne [guid]$VmId -or
        $Candidate.Name -cne $VmName -or $Candidate.Notes -cne $OwnerMarker -or
        $Candidate.Path -ne $VmConfigPath -or $Candidate.Generation -ne 2 -or
        $Candidate.State -ne $ExpectedState) {
        throw 'Exact VM identity, ownership, configuration, generation or state differs'
    }
    $disks = @(Get-VMHardDiskDrive -VM $Candidate -ErrorAction Stop)
    if ($disks.Count -ne 1 -or $disks[0].Path -ne $DiskPath) {
        throw 'VM does not have exactly its recorded writable preparation disk'
    }
    $adapters = @(Get-VMNetworkAdapter -VM $Candidate -ErrorAction Stop)
    foreach ($adapter in $adapters) {
        if ($adapter.SwitchName -or
            ($null -ne $adapter.SwitchId -and $adapter.SwitchId -ne [guid]::Empty)) {
            throw 'Preparation VM has a connected network adapter'
        }
    }
}
$vm = Get-VM -Id ([guid]$VmId) -ErrorAction Stop
Assert-LaunchIdentity $vm 'Off'
if ($vm.CheckpointType -ne 'Disabled' -or $vm.AutomaticStartAction -ne 'Nothing' -or
    $vm.AutomaticStopAction -ne 'ShutDown' -or
    @(Get-VMSnapshot -VM $vm -ErrorAction Stop).Count -ne 0) {
    throw 'Checkpoint or automatic power policy differs from reviewed preparation settings'
}
$processor = Get-VMProcessor -VM $vm -ErrorAction Stop
$memory = Get-VMMemory -VM $vm -ErrorAction Stop
if ($processor.Count -ne $CpuCount -or $memory.Startup -ne $MemoryBytes -or
    $memory.DynamicMemoryEnabled) {
    throw 'CPU or fixed-memory settings differ from the reviewed launch plan'
}
$vhd = Get-VHD -Path $DiskPath -ErrorAction Stop
if ($vhd.VhdFormat -ne 'VHDX' -or $vhd.VhdType -ne 'Dynamic' -or
    $vhd.Size -ne $DiskSizeBytes -or $vhd.ParentPath -or $vhd.Attached) {
    throw 'Preparation disk format, type, virtual size, parent or attachment differs'
}
$dvds = @(Get-VMDvdDrive -VM $vm -ErrorAction Stop)
if ($dvds.Count -ne 2 -or
    @($dvds | Where-Object { $_.Path -eq $InstallerIso }).Count -ne 1 -or
    @($dvds | Where-Object { $_.Path -eq $SeedIso }).Count -ne 1) {
    throw 'VM must have exactly the reviewed installer and combined seed DVDs'
}
$firmware = Get-VMFirmware -VM $vm -ErrorAction Stop
if ($firmware.SecureBoot -ne 'On' -or
    $firmware.SecureBootTemplate -ne 'MicrosoftUEFICertificateAuthority' -or
    $firmware.BootOrder.Count -lt 1 -or
    $firmware.BootOrder[0].Device.Path -ne $InstallerIso) {
    throw 'Linux Secure Boot or installer-first boot order differs; inspect, never repair automatically'
}
if (-not (Test-Path -LiteralPath $InstallerIso -PathType Leaf) -or
    (Get-FileHash -LiteralPath $InstallerIso -Algorithm SHA256).Hash -ne $InstallerIsoSha256 -or
    -not (Test-Path -LiteralPath $SeedIso -PathType Leaf) -or
    (Get-FileHash -LiteralPath $SeedIso -Algorithm SHA256).Hash -ne $SeedIsoSha256) {
    throw 'Reviewed installer or combined seed changed before launch'
}
Start-VM -VM $vm -ErrorAction Stop
$started = Get-VM -Id ([guid]$VmId) -ErrorAction Stop
Assert-LaunchIdentity $started 'Running'
@{
    vm_name = $started.Name
    vm_id = $started.Id.ToString()
    state = 'Running'
    network_enabled = $false
} | ConvertTo-Json -Compress
