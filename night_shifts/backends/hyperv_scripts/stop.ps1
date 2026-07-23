param(
    [Parameter(Mandatory = $true)][string]$VmName,
    [Parameter(Mandatory = $true)][string]$OwnerMarker
)
$ErrorActionPreference = 'Stop'
$vm = Get-VM -Name $VmName -ErrorAction Stop
if ($vm.Notes -ne $OwnerMarker) {
    throw "Refusing to stop a VM without the expected night-shift owner marker"
}
if ($vm.State -ne 'Off') {
    Stop-VM -VM $vm -TurnOff -Force
}
