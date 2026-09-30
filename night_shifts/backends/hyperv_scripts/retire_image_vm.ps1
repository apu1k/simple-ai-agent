param(
    [Parameter(Mandatory = $true)][string]$VmName,
    [Parameter(Mandatory = $true)][string]$OwnerMarker,
    [Parameter(Mandatory = $true)][string]$DiskPath,
    [Parameter(Mandatory = $true)][string]$VmConfigPath,
    [string]$ExpectedVmId = ''
)
$ErrorActionPreference = 'Stop'
# DISCARD ONLY: force-off can corrupt the untrusted build disk. Keep that disk
# and the Python ownership evidence; never use this operation to freeze a base.
if ($VmName -notmatch '^night-shift-image-prep-[0-9a-f]{32}$' -or
    $OwnerMarker -ne ('night-shift-image-prep-owner:' + $VmName.Substring(23))) {
    throw 'Untrusted image-preparation VM identity'
}
if ($ExpectedVmId -and
    ($ExpectedVmId -cnotmatch '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' -or
     [guid]$ExpectedVmId -eq [guid]::Empty)) {
    throw 'Malformed pinned preparation VM GUID'
}
$workspace = Split-Path -Parent $DiskPath
if ((Split-Path -Leaf $workspace) -ne $VmName.Substring(23) -or
    (Split-Path -Leaf $DiskPath) -ne 'ubuntu-build.vhdx' -or
    $VmConfigPath -ne (Join-Path $workspace 'vm-config')) {
    throw 'Preparation disk or configuration is not identity-scoped'
}
function Assert-PreparationOwner($Candidate) {
    if (-not $Candidate -or $Candidate.Name -ne $VmName -or
        $Candidate.Notes -ne $OwnerMarker -or $Candidate.Generation -ne 2 -or
        $Candidate.Path -ne $VmConfigPath) {
        throw 'VM identity, ownership, generation or configuration differs; inspect manually'
    }
    if ($ExpectedVmId -and $Candidate.Id -ne [guid]$ExpectedVmId) {
        throw 'Refusing a same-name replacement with a different preparation VM GUID'
    }
    $disks = @(Get-VMHardDiskDrive -VM $Candidate -ErrorAction Stop)
    if ($disks.Count -ne 1 -or $disks[0].Path -ne $DiskPath) {
        throw 'VM does not have exactly its recorded preparation disk'
    }
}
if (-not (Test-Path -LiteralPath $DiskPath -PathType Leaf)) {
    throw 'Recorded disk is missing; do not infer safe cleanup'
}
# Missing VMs and incomplete creation need manual inspection, not an automatic
# success or name-prefix sweep. Pin the host GUID before any destructive action.
$vm = if ($ExpectedVmId) {
    Get-VM -Id ([guid]$ExpectedVmId) -ErrorAction Stop
} else {
    Get-VM -Name $VmName -ErrorAction Stop
}
Assert-PreparationOwner $vm
$vmId = $vm.Id
if ($vm.State -ne 'Off') {
    Stop-VM -VM $vm -TurnOff -Force -ErrorAction Stop
}
$vm = Get-VM -Id $vmId -ErrorAction Stop
Assert-PreparationOwner $vm
if ($vm.State -ne 'Off') { throw 'Exact VM off-state not observed; do not unregister' }
Remove-VM -VM $vm -Force -ErrorAction Stop
# Inventory errors are failures, NOT evidence that the VM is absent. Query all
# only for observation; no other VM is stopped, unregistered or reconciled.
$remaining = @(Get-VM -ErrorAction Stop | Where-Object {
    $_.Id -eq $vmId -or $_.Name -eq $VmName
})
if ($remaining.Count -ne 0) { throw 'Exact VM absence not observed after retirement' }
if (-not (Test-Path -LiteralPath $DiskPath -PathType Leaf)) {
    throw 'Build disk retention not observed; inspect owned leftovers'
}
@{
    vm_name = $VmName
    vm_id = $vmId.ToString()
    vm_absent = $true
    disk_retained = $true
} | ConvertTo-Json -Compress
