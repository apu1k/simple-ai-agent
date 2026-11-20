param(
    [Parameter(Mandatory = $true)][ValidateSet('inspection', 'smoke')][string]$Operation,
    [Parameter(Mandatory = $true)][string]$Identity,
    [Parameter(Mandatory = $true)][guid]$VmId,
    [Parameter(Mandatory = $true)][string]$WorkspaceRoot,
    [switch]$RemoveSmokeDisk
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
# Fixed teardown body, not an authorization/installation/launch entry point.
# The protected caller must already own the exact claim and private workspace,
# exclude concurrent lifecycle writers and hold independently verified inputs.
if ($Identity -cnotmatch '^[0-9a-f]{32}\z' -or $VmId -eq [guid]::Empty -or
    $WorkspaceRoot -notmatch '^[A-Z]:\\[^\\]' -or
    [IO.Path]::GetFullPath($WorkspaceRoot) -cne $WorkspaceRoot) {
    throw 'Invalid Gate A teardown binding'
}
if ($RemoveSmokeDisk -and $Operation -ne 'smoke') {
    throw 'Disk removal is only permitted for the fixed smoke operation'
}
$workspace = Join-Path $WorkspaceRoot $Identity
if ($Operation -eq 'inspection') {
    $expectedName = 'night-shift-finalize-' + $Identity
    $expectedOwner = 'night-shift-finalize-owner:' + $Identity
    $disk = Join-Path $workspace 'working-copy.vhdx'
    $diskType = 'Dynamic'
} else {
    $expectedName = 'night-shift-' + $Identity
    $expectedOwner = 'night-shift-owner:' + $Identity
    $disk = Join-Path $workspace 'worker.vhdx'
    $diskType = 'Differencing'
}
$config = Join-Path (Join-Path $workspace 'vm-config') $expectedName

function Get-TargetMatches {
    # A successful complete local query is required even when the answer is empty.
    Get-VM -ErrorAction Stop | Where-Object { $_.Id -eq $VmId -or $_.Name -ieq $expectedName }
}
function Get-OwnedTarget {
    $matchesFound = @(Get-TargetMatches)
    if ($matchesFound.Count -ne 1 -or $matchesFound[0].Id -ne $VmId -or
        $matchesFound[0].Name -cne $expectedName -or $matchesFound[0].Notes -cne $expectedOwner -or
        $matchesFound[0].Path -ine $config -or $matchesFound[0].Generation -ne 2) {
        throw 'Gate A VM identity is unconfirmed; no mutation permitted'
    }
    $target = $matchesFound[0]
    $drives = @(Get-VMHardDiskDrive -VM $target -ErrorAction Stop)
    if ($drives.Count -ne 1 -or $drives[0].Path -ine $disk) {
        throw 'Gate A VM disk binding is unconfirmed; no mutation permitted'
    }
    $target
}

function Get-SmokeDiskEntry {
    # This is a consistency check, not a workspace lease. The protected owner
    # must hold trusted ancestry/identity and exclude all other writers.
    $dir = [IO.DirectoryInfo]$workspace
    while ($dir) {
        $observed = Get-Item -LiteralPath $dir.FullName -Force -ErrorAction Stop
        if ($observed -isnot [IO.DirectoryInfo] -or
            ($observed.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw 'Smoke disk ancestry was not confirmed'
        }
        $dir = $dir.Parent
    }
    Get-ChildItem -LiteralPath $workspace -Force -ErrorAction Stop |
        Where-Object { $_.Name -ieq 'worker.vhdx' }
}
function Assert-SmokeDiskEntry {
    $entries = @(Get-SmokeDiskEntry)
    if ($entries.Count -ne 1 -or $entries[0] -isnot [IO.FileInfo] -or
        $entries[0].FullName -ine $disk -or $entries[0].Name -cne 'worker.vhdx' -or
        ($entries[0].Attributes -band [IO.FileAttributes]::ReparsePoint) -or $entries[0].LinkType) {
        throw 'Exact regular unlinked smoke disk entry was not confirmed'
    }
}

if ($RemoveSmokeDisk) { Assert-SmokeDiskEntry }
$target = Get-OwnedTarget
if ($target.State -ne 'Off') {
    Stop-VM -VM $target -TurnOff -Force -ErrorAction Stop | Out-Null
}
$target = Get-OwnedTarget
if ($target.State -ne 'Off') { throw 'Gate A VM stop was not observed' }
Remove-VM -VM $target -Force -ErrorAction Stop | Out-Null
# Use one post-removal inventory for both checks. Refuse on rename/replacement,
# attachment or reference uncertainty; never remove a second VM or any file.
foreach ($remaining in @(Get-VM -ErrorAction Stop)) {
    if ($remaining.Id -eq $VmId -or $remaining.Name -ieq $expectedName) {
        throw 'Gate A VM absence was not observed'
    }
    foreach ($drive in @(Get-VMHardDiskDrive -VM $remaining -ErrorAction Stop)) {
        if ($drive.Path -ieq $disk) { throw 'Gate A disk is still referenced' }
    }
}
$vhd = @(Get-VHD -Path $disk -ErrorAction Stop)
if ($vhd.Count -ne 1 -or $vhd[0].Path -ine $disk -or $vhd[0].VhdFormat -ne 'VHDX' -or
    $vhd[0].VhdType -ne $diskType -or $vhd[0].Attached -isnot [bool] -or $vhd[0].Attached) {
    throw 'Gate A disk detachment was not observed'
}
$receipt = [ordered]@{ version = 1; operation = $Operation.ToLowerInvariant(); id = $Identity;
    vm_id = $VmId.ToString(); vm_absent = $true; disk_unattached_and_unreferenced = $true; disk_retained = $true }
if ($RemoveSmokeDisk) {
    Assert-SmokeDiskEntry
    Remove-Item -LiteralPath $disk -Force -ErrorAction Stop | Out-Null
    if (@(Get-SmokeDiskEntry).Count -ne 0) { throw 'Smoke disk absence was not observed' }
    $receipt.disk_retained = $false
    $receipt['disk_absent'] = $true
}
# No recursive deletion, retries or release of claims. This outcome is host
# state only and says nothing about guest unmount, a reply, or Gate A success.
$receipt | ConvertTo-Json -Compress
