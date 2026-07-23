param(
    [Parameter(Mandatory = $true)][string]$VmName,
    [Parameter(Mandatory = $true)][string]$OwnerMarker
)
$ErrorActionPreference = 'Stop'
$vm = Get-VM -Name $VmName -ErrorAction SilentlyContinue
if (-not $vm) {
    'Missing'
    exit 0
}
if ($vm.Notes -ne $OwnerMarker) {
    throw "Refusing to inspect a VM without the expected night-shift owner marker"
}
$vm.State.ToString()
