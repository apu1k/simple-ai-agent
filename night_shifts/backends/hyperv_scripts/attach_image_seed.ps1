param(
    [Parameter(Mandatory = $true)][string]$VmName,
    [Parameter(Mandatory = $true)][string]$OwnerMarker,
    [Parameter(Mandatory = $true)][string]$DiskPath,
    [Parameter(Mandatory = $true)][string]$VmConfigPath,
    [Parameter(Mandatory = $true)][string]$InstallerIso,
    [Parameter(Mandatory = $true)][string]$InstallerIsoSha256,
    [Parameter(Mandatory = $true)][string]$SeedIso,
    [Parameter(Mandatory = $true)][string]$SeedIsoSha256,
    [string]$ExpectedVmId = ''
)
$ErrorActionPreference = 'Stop'
# Attach only; no VM creation, power-on, network attachment or arbitrary paths.
if ($VmName -notmatch '^night-shift-image-prep-[0-9a-f]{32}$' -or
    $OwnerMarker -ne ('night-shift-image-prep-owner:' + $VmName.Substring(23))) {
    throw 'Untrusted image-preparation VM identity'
}
if ($InstallerIsoSha256 -notmatch '^[0-9a-fA-F]{64}$' -or
    $SeedIsoSha256 -notmatch '^[0-9a-fA-F]{64}$') {
    throw 'A media digest is missing or malformed'
}
if ($ExpectedVmId -and
    ($ExpectedVmId -cnotmatch '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' -or
     [guid]$ExpectedVmId -eq [guid]::Empty)) {
    throw 'Malformed pinned preparation VM GUID'
}
$vm = if ($ExpectedVmId) {
    Get-VM -Id ([guid]$ExpectedVmId) -ErrorAction Stop
} else {
    Get-VM -Name $VmName -ErrorAction Stop
}
$workspace = Split-Path -Parent $DiskPath
$expectedConfigPath = Join-Path (Join-Path $workspace 'vm-config') $VmName
if ((Split-Path -Leaf $workspace) -cne $VmName.Substring(23) -or
    (Split-Path -Leaf $DiskPath) -cne 'ubuntu-build.vhdx' -or
    $VmConfigPath -ne $expectedConfigPath -or
    $vm.Name -ne $VmName -or $vm.Notes -ne $OwnerMarker -or
    $vm.Path -ne $VmConfigPath -or $vm.Generation -ne 2 -or $vm.State -ne 'Off') {
    throw 'VM identity, ownership, configuration path, generation, or off-state differs'
}
if ($ExpectedVmId -and $vm.Id -ne [guid]$ExpectedVmId) {
    throw 'Refusing a same-name replacement with a different preparation VM GUID'
}
$disks = @(Get-VMHardDiskDrive -VM $vm)
if ($disks.Count -ne 1 -or $disks[0].Path -ne $DiskPath) {
    throw 'VM does not have exactly its recorded preparation disk'
}
$networkAdapters = @(Get-VMNetworkAdapter -VM $vm)
foreach ($adapter in $networkAdapters) {
    if ($adapter.SwitchName) { throw 'Image-preparation VM has a connected network adapter' }
}
$dvds = @(Get-VMDvdDrive -VM $vm)
if ($dvds.Count -ne 1 -or $dvds[0].Path -ne $InstallerIso) {
    throw 'Installer DVD differs from the recorded preparation input'
}
if (-not (Test-Path -LiteralPath $InstallerIso -PathType Leaf) -or
    (Get-FileHash -LiteralPath $InstallerIso -Algorithm SHA256).Hash -ne $InstallerIsoSha256) {
    throw 'Installer ISO changed before seed attachment'
}
if (-not (Test-Path -LiteralPath $SeedIso -PathType Leaf) -or
    (Get-FileHash -LiteralPath $SeedIso -Algorithm SHA256).Hash -ne $SeedIsoSha256) {
    throw 'Seed ISO changed before attachment'
}
$added = Add-VMDvdDrive -VM $vm -Path $SeedIso -Passthru
if (-not $added -or $added.Path -ne $SeedIso) {
    throw 'Seed DVD attachment not confirmed; inspect the exact owned VM'
}
$VmName
