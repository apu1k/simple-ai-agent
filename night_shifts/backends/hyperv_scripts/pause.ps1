param(
    [Parameter(Mandatory = $true)][string]$VmName,
    [Parameter(Mandatory = $true)][string]$OwnerMarker
)
$ErrorActionPreference = 'Stop'
$vm = Get-VM -Name $VmName -ErrorAction Stop
if ($vm.Notes -ne $OwnerMarker) {
    throw "Refusing to pause a VM without the expected night-shift owner marker"
}
if ($vm.State -eq 'Running') {
    Suspend-VM -VM $vm
}
elseif ($vm.State -ne 'Paused' -and $vm.State -ne 'Saved') {
    throw "VM cannot be paused from state $($vm.State)"
}
