param(
    [Parameter(Mandatory = $true)][string]$VmName,
    [Parameter(Mandatory = $true)][string]$OwnerMarker,
    [Parameter(Mandatory = $true)][string]$DiskPath
)
$ErrorActionPreference = 'Stop'
# Do not interpret an inventory failure as permission to delete a disk.
$namedVms = @(Get-VM -ErrorAction Stop | Where-Object { $_.Name -ieq $VmName })
if ($namedVms.Count -gt 1) {
    throw 'Refusing to destroy an ambiguous night-shift VM name'
}
if ($namedVms.Count -eq 1) {
    $vm = $namedVms[0]
    if ($vm.Name -cne $VmName -or $vm.Notes -cne $OwnerMarker) {
        throw 'Refusing to destroy a VM without the expected night-shift owner marker'
    }
    $vmId = $vm.Id
    if ($null -eq $vmId -or $vmId -eq [guid]::Empty) {
        throw 'Refusing to destroy a VM without an observed VM ID'
    }
    if ($vm.State -ne 'Off') {
        Stop-VM -VM $vm -TurnOff -Force
    }
    Remove-VM -VM $vm -Force
    # A successful command is not an observation. Check both the exact observed
    # VM ID (including a rename) and the sandbox name (including a replacement).
    $remaining = @(Get-VM -ErrorAction Stop | Where-Object {
        $_.Id -eq $vmId -or $_.Name -ieq $VmName
    })
    if ($remaining.Count -ne 0) {
        throw 'VM absence was not confirmed; retaining the disposable disk'
    }
}
if (Test-Path -LiteralPath $DiskPath) {
    $disk = Get-Item -LiteralPath $DiskPath -Force
    if ($disk.PSIsContainer -or ($disk.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'Refusing to remove an unexpected disposable disk entry'
    }
    Remove-Item -LiteralPath $DiskPath -Force
}
if (Test-Path -LiteralPath $DiskPath) {
    throw 'Disposable disk absence was not confirmed'
}
