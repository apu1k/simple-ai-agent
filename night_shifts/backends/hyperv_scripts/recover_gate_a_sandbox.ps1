param(
    [Parameter(Mandatory = $true)][string]$Workspace,
    [Parameter(Mandatory = $true)][string]$BaseImage,
    [switch]$Apply
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
# Attended recovery only. The caller validates the report and filesystem
# ancestry, holds the run lease, and must exclude other lifecycle writers.
if ($Workspace -notmatch '^[a-z]:\\' -or [IO.Path]::GetFullPath($Workspace) -cne $Workspace -or
    $BaseImage -notmatch '^[a-z]:\\' -or [IO.Path]::GetFullPath($BaseImage) -cne $BaseImage -or
    $Workspace -cnotmatch '\\gate-a-[0-9a-f]{32}\\sandboxes\\([0-9a-f]{32})\z') {
    throw 'Invalid attended Gate A recovery paths'
}
$sandboxId = $Matches[1]
$name = 'night-shift-' + $sandboxId
$marker = 'night-shift-owner:' + $sandboxId
$prefix = $Workspace + '\'
$disk = Join-Path $Workspace 'worker.vhdx'
$config = Join-Path (Join-Path $Workspace 'vm-config') $name
if ($BaseImage.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase) -or $BaseImage -ieq $Workspace) {
    throw 'Base image overlaps the disposable sandbox'
}

function Test-InWorkspace([string]$Path) {
    $Path -ieq $Workspace -or $Path.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)
}
function Get-SoleTarget([guid]$KnownId) {
    $inventory = @(Get-VM -ErrorAction Stop)
    $found = @($inventory | Where-Object { $_.Name -ieq $name -or $_.Id -eq $KnownId })
    if ($found.Count -gt 1) { throw 'Ambiguous Gate A VM identity' }
    foreach ($other in $inventory) {
        if ($found.Count -eq 1 -and $other -eq $found[0]) { continue }
        if (Test-InWorkspace $other.Path) { throw 'Another VM has configuration in this sandbox' }
        foreach ($drive in @(Get-VMHardDiskDrive -VM $other -ErrorAction Stop)) {
            if (Test-InWorkspace $drive.Path) { throw 'Another VM references this sandbox' }
        }
    }
    if ($found.Count -eq 0) { return }
    $vm = $found[0]
    if ($vm.Name -cne $name -or $vm.Notes -cne $marker -or $vm.Generation -ne 2 -or
        $vm.Path -ine $config -or $vm.Id -isnot [guid] -or $vm.Id -eq [guid]::Empty -or
        ($KnownId -ne [guid]::Empty -and $vm.Id -ne $KnownId)) {
        throw 'VM ID, ownership marker, or Gate A configuration path did not match'
    }
    $drives = @(Get-VMHardDiskDrive -VM $vm -ErrorAction Stop)
    if ($drives.Count -ne 1 -or $drives[0].Path -ine $disk -or
        @(Get-VMSnapshot -VM $vm -ErrorAction Stop).Count -ne 0) {
        throw 'Exact Gate A disk or no-checkpoint state not confirmed'
    }
    $vm
}
function Get-OwnedDisk([bool]$RequireDetached) {
    if (-not (Test-Path -LiteralPath $disk -ErrorAction Stop)) { return }
    $entry = Get-Item -LiteralPath $disk -Force -ErrorAction Stop
    if ($entry -isnot [IO.FileInfo] -or $entry.Name -cne 'worker.vhdx' -or
        ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) -or $entry.LinkType) {
        throw 'Unexpected disposable disk entry'
    }
    $vhd = @(Get-VHD -Path $disk -ErrorAction Stop)
    if ($vhd.Count -ne 1 -or $vhd[0].Path -ine $disk -or $vhd[0].VhdFormat -ne 'VHDX' -or
        $vhd[0].VhdType -ne 'Differencing' -or $vhd[0].ParentPath -ine $BaseImage -or
        $vhd[0].Attached -isnot [bool] -or ($RequireDetached -and $vhd[0].Attached)) {
        throw 'Disposable disk identity, parent or detachment not confirmed'
    }
    $entry
}
function Assert-TargetAbsent([guid]$KnownId) {
    # Includes exact-ID rename/replacement checks and references by other VMs.
    if ($null -ne (Get-SoleTarget $KnownId)) { throw 'VM absence not confirmed' }
}

$target = Get-SoleTarget ([guid]::Empty)
$diskEntry = Get-OwnedDisk ($null -eq $target)
if ($null -ne $target -and $null -eq $diskEntry) { throw 'Target VM disk is missing' }
if (-not $Apply) {
    if ($null -ne $target) { 'vm_candidate' }
    elseif ($null -ne $diskEntry) { 'disk_candidate' }
    elseif (Test-Path -LiteralPath $Workspace -ErrorAction Stop) { 'folders_only' }
    else { 'absent' }
    return
}
$vmId = [guid]::Empty
if ($null -ne $target) {
    $vmId = $target.Id
    if ($target.State -ne 'Off') { Stop-VM -VM $target -TurnOff -Force -ErrorAction Stop | Out-Null }
    $stopped = Get-SoleTarget $vmId
    if ($null -eq $stopped -or $stopped.State -ne 'Off') { throw 'Exact VM stop not confirmed' }
    Remove-VM -VM $stopped -Force -ErrorAction Stop | Out-Null
}
Assert-TargetAbsent $vmId
if ($null -ne (Get-OwnedDisk $true)) {
    Remove-Item -LiteralPath $disk -Force -ErrorAction Stop
}
if (Test-Path -LiteralPath $disk -ErrorAction Stop) { throw 'Disposable disk absence not confirmed' }
'verified'
