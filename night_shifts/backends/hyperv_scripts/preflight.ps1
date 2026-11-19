$ErrorActionPreference = 'Stop'
$required = @(
    'Get-VM', 'New-VM', 'Remove-VM', 'Start-VM', 'Stop-VM',
    'Suspend-VM', 'Resume-VM', 'Set-VM', 'Set-VMMemory', 'Get-VMMemory', 'Set-VMProcessor', 'Get-VMNetworkAdapter',
    'Set-VMFirmware', 'Set-VMComPort', 'Get-VMHardDiskDrive', 'New-VHD', 'Get-VHD', 'Resize-VHD'
)
foreach ($command in $required) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "Required Hyper-V command is unavailable: $command"
    }
}
'ready'
