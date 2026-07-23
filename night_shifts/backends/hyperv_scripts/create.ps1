param(
    [Parameter(Mandatory = $true)][string]$VmName,
    [Parameter(Mandatory = $true)][string]$OwnerMarker,
    [Parameter(Mandatory = $true)][string]$BaseImage,
    [Parameter(Mandatory = $true)][string]$BaseImageSha256,
    [Parameter(Mandatory = $true)][string]$DiskPath,
    [Parameter(Mandatory = $true)][long]$CpuCount,
    [Parameter(Mandatory = $true)][long]$MemoryBytes,
    [Parameter(Mandatory = $true)][long]$DiskSizeBytes,
    [string]$SwitchName = ''
)
$ErrorActionPreference = 'Stop'
if (Get-VM -Name $VmName -ErrorAction SilentlyContinue) {
    throw "A VM with the requested trusted name already exists"
}
if (-not (Test-Path -LiteralPath $BaseImage -PathType Leaf)) {
    throw "The configured base image does not exist"
}
$actualDigest = (Get-FileHash -LiteralPath $BaseImage -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualDigest -ne $BaseImageSha256.ToLowerInvariant()) {
    throw "The base image digest changed before VM creation"
}
if (Test-Path -LiteralPath $DiskPath) {
    throw "The disposable disk path already exists"
}
$parent = Get-VHD -Path $BaseImage
if ($parent.Size -gt $DiskSizeBytes) {
    throw "The requested disk limit is smaller than the base image virtual size"
}
$createdVm = $false
try {
    New-VHD -Path $DiskPath -ParentPath $BaseImage -Differencing | Out-Null
    if ($parent.Size -lt $DiskSizeBytes) {
        Resize-VHD -Path $DiskPath -SizeBytes $DiskSizeBytes
    }
    $parameters = @{
        Name = $VmName
        Generation = 2
        VHDPath = $DiskPath
        MemoryStartupBytes = $MemoryBytes
    }
    if ($SwitchName) {
        $parameters['SwitchName'] = $SwitchName
    }
    New-VM @parameters | Out-Null
    $createdVm = $true
    Set-VM -Name $VmName -Notes $OwnerMarker -DynamicMemory:$false `
        -AutomaticStartAction Nothing -AutomaticStopAction ShutDown
    Set-VMProcessor -VMName $VmName -Count $CpuCount
    Set-VMFirmware -VMName $VmName -EnableSecureBoot On `
        -SecureBootTemplate MicrosoftUEFICertificateAuthority
    $VmName
}
catch {
    if ($createdVm) {
        Remove-VM -Name $VmName -Force -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath $DiskPath -Force -ErrorAction SilentlyContinue
    throw
}
