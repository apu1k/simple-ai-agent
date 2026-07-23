param(
    [Parameter(Mandatory = $true)][string]$VmName,
    [Parameter(Mandatory = $true)][string]$OwnerMarker,
    [Parameter(Mandatory = $true)][string]$DiskPath
)
$ErrorActionPreference = 'Stop'
$vm = Get-VM -Name $VmName -ErrorAction SilentlyContinue
if ($vm) {
    if ($vm.Notes -ne $OwnerMarker) {
        throw "Refusing to destroy a VM without the expected night-shift owner marker"
    }
    if ($vm.State -ne 'Off') {
        Stop-VM -VM $vm -TurnOff -Force
    }
    Remove-VM -VM $vm -Force
}
if (Test-Path -LiteralPath $DiskPath) {
    Remove-Item -LiteralPath $DiskPath -Force
}
