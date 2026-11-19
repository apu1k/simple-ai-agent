param(
    [Parameter(Mandatory = $true)][string]$VmName,
    [Parameter(Mandatory = $true)][string]$OwnerMarker,
    [Parameter(Mandatory = $true)][string]$DiskPath
)
$ErrorActionPreference = 'Stop'
# Do not interpret an inventory failure as permission to delete a disk.
$inventory = @(Get-VM -ErrorAction Stop)
$namedVms = @($inventory | Where-Object { $_.Name -ieq $VmName })
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
    $stopped = @(Get-VM -ErrorAction Stop | Where-Object { $_.Id -eq $vmId -or $_.Name -ieq $VmName })
    if ($stopped.Count -ne 1 -or $stopped[0].Id -ne $vmId -or $stopped[0].Name -cne $VmName -or
        $stopped[0].Notes -cne $OwnerMarker -or $stopped[0].State -ne 'Off') {
        throw 'Exact VM stop was not confirmed; retaining the disposable disk'
    }
    Remove-VM -VM $stopped[0] -Force
    # A successful command is not an observation. Check both the exact observed
    # VM ID (including a rename) and the sandbox name (including a replacement).
    $inventory = @(Get-VM -ErrorAction Stop)
    if (@($inventory | Where-Object { $_.Id -eq $vmId -or $_.Name -ieq $VmName }).Count -ne 0) {
        throw 'VM absence was not confirmed; retaining the disposable disk'
    }
}
if (Test-Path -LiteralPath $DiskPath -ErrorAction Stop) {
    $disk = Get-Item -LiteralPath $DiskPath -Force -ErrorAction Stop
    if ($disk.PSIsContainer -or ($disk.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'Refusing to remove an unexpected disposable disk entry'
    }
    foreach ($remaining in $inventory) {
        if (@(Get-VMHardDiskDrive -VM $remaining -ErrorAction Stop | Where-Object { $_.Path -ieq $DiskPath }).Count -ne 0) {
            throw 'Refusing to remove a disk still referenced by a VM'
        }
    }
    $vhd = @(Get-VHD -Path $DiskPath -ErrorAction Stop)
    if ($vhd.Count -ne 1 -or $vhd[0].Path -ine $DiskPath -or $vhd[0].VhdFormat -ne 'VHDX' -or
        $vhd[0].VhdType -ne 'Differencing' -or $vhd[0].Attached -isnot [bool] -or $vhd[0].Attached) {
        throw 'Disposable differencing disk detachment was not confirmed'
    }
    Remove-Item -LiteralPath $DiskPath -Force -ErrorAction Stop
}
if (Test-Path -LiteralPath $DiskPath -ErrorAction Stop) {
    throw 'Disposable disk absence was not confirmed'
}
