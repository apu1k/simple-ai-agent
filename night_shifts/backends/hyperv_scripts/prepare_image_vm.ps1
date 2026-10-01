param(
    [Parameter(Mandatory = $true)][string]$VmName,
    [Parameter(Mandatory = $true)][string]$OwnerMarker,
    [Parameter(Mandatory = $true)][string]$InstallerIso,
    [Parameter(Mandatory = $true)][string]$InstallerIsoSha256,
    [Parameter(Mandatory = $true)][string]$DiskPath,
    [Parameter(Mandatory = $true)][string]$VmConfigRootPath,
    [Parameter(Mandatory = $true)][string]$VmConfigPath,
    [Parameter(Mandatory = $true)][long]$DiskSizeBytes,
    [Parameter(Mandatory = $true)][long]$MemoryBytes,
    [Parameter(Mandatory = $true)][long]$CpuCount
)
$ErrorActionPreference = 'Stop'
# This is ONLY an image-preparation VM; it cannot start a VM or configure a
# switch. Do not use it as the runtime sandbox or treat it as an ISO installer.
if ($VmName -notmatch '^night-shift-image-prep-[0-9a-f]{32}$' -or
    $OwnerMarker -ne ('night-shift-image-prep-owner:' + $VmName.Substring(23))) {
    throw 'Untrusted image-preparation VM identity'
}
$workspace = Split-Path -Parent $DiskPath
if ((Split-Path -Leaf $workspace) -cne $VmName.Substring(23) -or
    (Split-Path -Leaf $DiskPath) -cne 'ubuntu-build.vhdx' -or
    $VmConfigRootPath -ne (Join-Path $workspace 'vm-config') -or
    $VmConfigPath -ne (Join-Path $VmConfigRootPath $VmName)) {
    throw 'VM configuration root and exact path must match the preparation identity'
}
if ($CpuCount -lt 1 -or $CpuCount -gt 8 -or
    $MemoryBytes -lt 1073741824 -or $MemoryBytes -gt 8589934592 -or
    $DiskSizeBytes -lt 10737418240 -or $DiskSizeBytes -gt 42949672960) {
    throw 'Image-preparation resources exceed their fixed bounds'
}
if ((Get-VM -Name $VmName -ErrorAction SilentlyContinue) -or
    (Test-Path -LiteralPath $DiskPath) -or
    (Test-Path -LiteralPath $VmConfigRootPath) -or
    (Test-Path -LiteralPath $VmConfigPath)) {
    throw 'Refusing to reuse an existing VM, disk, or configuration path'
}
if (-not (Test-Path -LiteralPath $InstallerIso -PathType Leaf)) {
    throw 'The pinned installer ISO is missing'
}
if ($InstallerIsoSha256 -notmatch '^[0-9a-fA-F]{64}$' -or
    (Get-FileHash -LiteralPath $InstallerIso -Algorithm SHA256).Hash -ne $InstallerIsoSha256) {
    throw 'Installer ISO differs from the approved SHA-256 before VM creation'
}
$createdDisk = $false
$createdVm = $null
try {
    New-VHD -Path $DiskPath -Dynamic -SizeBytes $DiskSizeBytes | Out-Null
    $createdDisk = $true
    $createdVm = New-VM -Name $VmName -Generation 2 -VHDPath $DiskPath `
        -Path $VmConfigRootPath -MemoryStartupBytes $MemoryBytes
    if ($createdVm.Path -ne $VmConfigPath) {
        throw 'New VM configuration path differs from the exact reviewed identity-derived path'
    }
    Set-VM -VM $createdVm -Notes $OwnerMarker -DynamicMemory:$false `
        -CheckpointType Disabled -AutomaticStartAction Nothing -AutomaticStopAction ShutDown
    Set-VMProcessor -VM $createdVm -Count $CpuCount
    $dvd = Add-VMDvdDrive -VM $createdVm -Path $InstallerIso -Passthru
    if (-not $dvd) { throw 'Installer DVD attachment was not observed' }
    Set-VMFirmware -VM $createdVm -EnableSecureBoot On `
        -SecureBootTemplate MicrosoftUEFICertificateAuthority -FirstBootDevice $dvd
    $createdVm.Name
}
catch {
    # The Python caller records this attempt as UNKNOWN even when cleanup
    # succeeds. Never claim there is no residual configuration without a
    # separate host observation of the exact ID and workspace.
    if ($createdVm) {
        try { Remove-VM -VM $createdVm -Force -ErrorAction Stop } catch { }
    }
    if ($createdDisk) {
        try { Remove-Item -LiteralPath $DiskPath -Force -ErrorAction Stop } catch { }
    }
    throw
}
