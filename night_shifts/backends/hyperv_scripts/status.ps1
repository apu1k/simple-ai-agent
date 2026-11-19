param(
    [Parameter(Mandatory = $true)][string]$VmName,
    [Parameter(Mandatory = $true)][string]$OwnerMarker
)
$ErrorActionPreference = 'Stop'
# Exact-name absence is evidence only after a successful inventory. A missing
# -Name lookup and a provider/permission failure must not be conflated.
$namedVms = @(Get-VM -ErrorAction Stop | Where-Object { $_.Name -ieq $VmName })
if ($namedVms.Count -eq 0) {
    'Missing'
    exit 0
}
if ($namedVms.Count -ne 1) {
    throw 'Refusing to inspect an ambiguous night-shift VM name'
}
$vm = $namedVms[0]
if ($vm.Name -cne $VmName -or $vm.Notes -cne $OwnerMarker) {
    throw "Refusing to inspect a VM without the expected night-shift owner marker"
}
$vm.State.ToString()
