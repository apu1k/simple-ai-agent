param(
    [Parameter(Mandatory = $true)][string]$VmName,
    [Parameter(Mandatory = $true)][string]$OwnerMarker,
    [Parameter(Mandatory = $true)][string]$BaseImage,
    [Parameter(Mandatory = $true)][string]$BaseImageSha256,
    [Parameter(Mandatory = $true)][string]$DiskPath,
    [Parameter(Mandatory = $true)][string]$VmConfigPath,
    [Parameter(Mandatory = $true)][string]$ComPortPipe,
    [Parameter(Mandatory = $true)][long]$CpuCount,
    [Parameter(Mandatory = $true)][long]$MemoryBytes,
    [Parameter(Mandatory = $true)][long]$DiskSizeBytes,
    [string]$SwitchName = ''
)
$ErrorActionPreference = 'Stop'
if (@(Get-VM -ErrorAction Stop | Where-Object { $_.Name -ieq $VmName }).Count -ne 0) {
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
# Controller supplies a fresh, ID-scoped sibling of worker.vhdx. Never
# place VM configuration at Hyper-V's global (often C:) default location.
$expectedConfigPath = Join-Path (Split-Path -Parent $DiskPath) 'vm-config'
if ($VmConfigPath -ne $expectedConfigPath -or (Test-Path -LiteralPath $VmConfigPath)) {
    throw "VM configuration path must be a fresh sandbox-scoped vm-config directory"
}
$parent = Get-VHD -Path $BaseImage
if ($parent.Size -gt $DiskSizeBytes) {
    throw "The requested disk limit is smaller than the base image virtual size"
}
# A native create may have side effects before throwing. Preserve the exact
# attempt workspace on failure; no name-based rollback or speculative disk delete.
New-VHD -Path $DiskPath -ParentPath $BaseImage -Differencing | Out-Null
if ($parent.Size -lt $DiskSizeBytes) {
    Resize-VHD -Path $DiskPath -SizeBytes $DiskSizeBytes
}
$parameters = @{
    Name = $VmName
    Generation = 2
    VHDPath = $DiskPath
    Path = $VmConfigPath
    MemoryStartupBytes = $MemoryBytes
}
if ($SwitchName) {
    $parameters['SwitchName'] = $SwitchName
}
$created = @(New-VM @parameters)
if ($created.Count -ne 1 -or $created[0].Id -isnot [guid] -or $created[0].Id -eq [guid]::Empty -or
    $created[0].Name -cne $VmName -or $created[0].Generation -ne 2 -or $created[0].State -ne 'Off') {
    throw 'Created VM identity or initial state was not observed'
}
$vm = $created[0]
Set-VM -VM $vm -Notes $OwnerMarker -CheckpointType Disabled -AutomaticCheckpointsEnabled $false `
    -AutomaticStartAction Nothing -AutomaticStopAction ShutDown
# DynamicMemory is a Set-VM switch, not a Boolean memory policy. Set the
# actual Boolean explicitly and observe it before reporting create success.
Set-VMMemory -VM $vm -DynamicMemoryEnabled $false -StartupBytes $MemoryBytes
$memory = Get-VMMemory -VM $vm -ErrorAction Stop
if ($null -eq $memory -or $memory.Startup -ne $MemoryBytes -or
    $memory.DynamicMemoryEnabled -ne $false) {
    throw 'Created VM does not have the exact requested fixed-memory settings'
}
Set-VMProcessor -VM $vm -Count $CpuCount
Set-VMComPort -VM $vm -Number 1 -Path $ComPortPipe
Set-VMFirmware -VM $vm -EnableSecureBoot On -SecureBootTemplate MicrosoftUEFICertificateAuthority
$effective = @(Get-VM -Id $vm.Id -ErrorAction Stop)
if ($effective.Count -ne 1 -or $effective[0].Id -ne $vm.Id -or $effective[0].Name -cne $VmName -or
    $effective[0].Notes -cne $OwnerMarker -or $effective[0].State -ne 'Off' -or
    $effective[0].CheckpointType -ne 'Disabled' -or $effective[0].AutomaticCheckpointsEnabled -ne $false) {
    throw 'Created VM identity or no-checkpoint policy was not confirmed'
}
if (-not $SwitchName) {
    foreach ($adapter in @(Get-VMNetworkAdapter -VM $effective[0] -ErrorAction Stop)) {
        if ($adapter.SwitchName -or $adapter.SwitchId -notin @($null, [guid]::Empty)) {
            throw 'An adapter is connected on a VM that must stay offline'
        }
    }
}
$VmName
