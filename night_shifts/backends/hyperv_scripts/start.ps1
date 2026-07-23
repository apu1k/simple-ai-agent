param(
    [Parameter(Mandatory = $true)][string]$VmName,
    [Parameter(Mandatory = $true)][string]$OwnerMarker
)
$ErrorActionPreference = 'Stop'
$vm = Get-VM -Name $VmName -ErrorAction Stop
if ($vm.Notes -ne $OwnerMarker) {
    throw "Refusing to start a VM without the expected night-shift owner marker"
}
if ($vm.State -eq 'Paused' -or $vm.State -eq 'Saved') {
    Resume-VM -VM $vm
}
elseif ($vm.State -ne 'Running') {
    Start-VM -VM $vm
}
