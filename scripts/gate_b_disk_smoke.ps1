param(
    [Parameter(Mandatory=$true)][ValidateSet('Open','Close')][string]$Action,
    [Parameter(Mandatory=$true)][ValidatePattern('\A[0-9a-f]{32}\z')][string]$RunId
)
# Attended, synthetic B2.2 disk-only experiment. Not an installed service or worker API.
# Open and Close are separate explicit approvals. No VM, downloads, Python, or raw disk fallback.
Set-StrictMode -Version 3
$ErrorActionPreference = 'Stop'

function Test-SmokeDiskIdentifier($Value, [guid]$Expected) {
    $actual = [guid]::Empty
    return ($Expected -ne [guid]::Empty -and [guid]::TryParse([string]$Value, [ref]$actual) -and
        $actual -eq $Expected)
}

function Confirm-SmokeMapping($Vhd, $Image, $Disk, [string]$Path, [guid]$Id, [bool]$Blank) {
    if ($Vhd.Path -ine $Path -or $Image.ImagePath -ine $Path -or
        -not (Test-SmokeDiskIdentifier $Vhd.DiskIdentifier $Id) -or
        $Vhd.VhdFormat -ne 'VHDX' -or $Vhd.VhdType -ne 'Dynamic' -or $Vhd.ParentPath -or
        $true -ne $Vhd.Attached -or $true -ne $Image.Attached -or
        $null -eq $Vhd.DiskNumber -or $Vhd.DiskNumber -lt 1 -or
        $Image.DevicePath -ine ('\\.\PhysicalDrive' + $Vhd.DiskNumber) -or
        $Disk.Number -ne $Vhd.DiskNumber -or -not $Disk.Path -or
        $Disk.BusType -notin @('File Backed Virtual', 'FileBackedVirtual', '15') -or
        $Vhd.Size -ne 256MB -or $Disk.Size -ne 256MB -or
        $false -ne $Disk.IsBoot -or $false -ne $Disk.IsSystem -or $false -ne $Disk.IsClustered -or
        $false -ne $Disk.IsOffline -or $false -ne $Disk.IsReadOnly) {
        throw 'The storage device was not positively identified as the attached scratch VHDX'
    }
    if ($Blank -and ($Disk.PartitionStyle -ne 'RAW' -or $Disk.NumberOfPartitions -ne 0)) {
        throw 'The attached scratch disk is not blank; refusing initialization'
    }
}

function Get-SmokeMapping([string]$Path, [guid]$Id, [bool]$Blank) {
    $vhd = @(Hyper-V\Get-VHD -Path $Path)
    $image = @(Storage\Get-DiskImage -ImagePath $Path -StorageType VHDX)
    if ($vhd.Count -ne 1 -or $image.Count -ne 1 -or $true -ne $vhd[0].Attached -or
        $null -eq $vhd[0].DiskNumber -or $vhd[0].DiskNumber -lt 1) {
        throw 'No unique scratch VHDX attachment'
    }
    $disk = @(Storage\Get-Disk -Number $vhd[0].DiskNumber)
    if ($disk.Count -ne 1) { throw 'No unique storage disk for the attached scratch VHDX' }
    Confirm-SmokeMapping $vhd[0] $image[0] $disk[0] $Path $Id $Blank
    return $disk[0]
}

function Get-SmokeVhd([string]$Path, [guid]$Id) {
    $vhd = @(Hyper-V\Get-VHD -Path $Path)
    if ($vhd.Count -ne 1 -or $vhd[0].Path -ine $Path -or
        -not (Test-SmokeDiskIdentifier $vhd[0].DiskIdentifier $Id) -or $vhd[0].VhdFormat -ne 'VHDX' -or
        $vhd[0].VhdType -ne 'Dynamic' -or $vhd[0].ParentPath -or $vhd[0].Size -ne 256MB) {
        throw 'Scratch VHDX path or file identity changed'
    }
    return $vhd[0]
}

function Close-SmokeVhd([string]$Path, [guid]$Id) {
    # Never dismount by disk number or drive letter, and never guess if identity is unclear.
    $vhd = Get-SmokeVhd $Path $Id
    if ($vhd.Attached) { Hyper-V\Dismount-VHD -Path $Path }
    $vhd = Get-SmokeVhd $Path $Id
    if ($false -ne $vhd.Attached) { throw 'Scratch VHDX still attached; needs manual review' }
}

function Import-SmokeModules([string]$SystemDirectory) {
    $moduleRoot = Join-Path $SystemDirectory 'WindowsPowerShell\v1.0\Modules'
    $env:PSModulePath = $moduleRoot
    foreach ($name in @('Hyper-V', 'Storage')) {
        # Hyper-V can be installed under a versioned directory (e.g. Hyper-V\2.0.0.0).
        # Discover the manifest but load only from the protected system module directory.
        $prefix = (Join-Path $moduleRoot $name) + [IO.Path]::DirectorySeparatorChar
        $module = Get-Module -ListAvailable -Name $name |
            Where-Object { $_.Path.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase) } |
            Sort-Object Version -Descending | Select-Object -First 1
        if ($null -eq $module) { throw "System PowerShell module $name not found under $prefix" }
        Import-Module -Name $module.Path -Global -ErrorAction Stop
    }
}

if ([IntPtr]::Size -ne 8 -or $PSVersionTable.PSEdition -ne 'Desktop') { throw 'Use x64 Windows PowerShell' }
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Administrator approval required' }
$system = [Environment]::GetFolderPath('System')
$env:SystemRoot = [IO.Directory]::GetParent($system).FullName
$env:WINDIR = $env:SystemRoot
$env:COMPUTERNAME = [Environment]::MachineName
Import-SmokeModules $system

# Require trusted ancestors before creating a protected directory for the backing file.
$programFiles = [Environment]::GetFolderPath('ProgramFiles')
$trusted = @('S-1-5-18', 'S-1-5-32-544',
    'S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464')
$root = Join-Path $programFiles ('AiAgentGateB-DiskSmoke-' + $RunId.ToLowerInvariant())
$dirSecurity = New-Object Security.AccessControl.DirectorySecurity
$dirSecurity.SetSecurityDescriptorSddlForm('O:BAG:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)')
$driveRoot = [IO.Path]::GetPathRoot($programFiles)
if ($driveRoot -notmatch '\A[A-Za-z]:\\\z' -or ([IO.DriveInfo]::new($driveRoot)).DriveType -ne 'Fixed') {
    throw 'Expected a local fixed drive for scratch storage'
}
function Confirm-SmokeDirectory([string]$Path, [bool]$RunDirectory) {
    $item = Get-Item -LiteralPath $Path -Force
    if (-not $item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'Scratch storage has a non-directory or reparse component'
    }
    $acl = Get-Acl -LiteralPath $Path
    if ($trusted -notcontains $acl.GetOwner([Security.Principal.SecurityIdentifier]).Value) {
        throw 'Untrusted scratch storage owner'
    }
    # Delete-child, change ACL/owner, or generic-all can invalidate path ownership.
    $mask = 0x40 -bor 0x40000 -bor 0x80000 -bor 0x10000000
    if ($Path -ine $driveRoot) { $mask = $mask -bor 0x10000 }
    if ($Path -ieq $programFiles -or $RunDirectory) { $mask = $mask -bor 0x6 }
    foreach ($rule in $acl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier])) {
        if ($rule.PropagationFlags -band [Security.AccessControl.PropagationFlags]::InheritOnly) { continue }
        if ($rule.AccessControlType -eq 'Allow' -and $trusted -notcontains $rule.IdentityReference.Value -and
            ([int]$rule.FileSystemRights -band $mask)) { throw 'Scratch storage permissions are not protected' }
    }
}
for ($cursor = [IO.DirectoryInfo]$programFiles; $null -ne $cursor; $cursor = $cursor.Parent) {
    Confirm-SmokeDirectory $cursor.FullName $false
}
$vhdPath = Join-Path $root 'input-smoke.vhdx'
$receipt = Join-Path $root 'created.json'

if ($Action -eq 'Close') {
    Confirm-SmokeDirectory $root $true
    foreach ($path in @($receipt, $vhdPath)) {
        $item = Get-Item -LiteralPath $path -Force
        if ($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw 'Unexpected scratch receipt or VHDX file type'
        }
    }
    $created = Get-Content -LiteralPath $receipt -Raw | ConvertFrom-Json
    if ($created.run_id -cne $RunId.ToLowerInvariant() -or $created.path -ine $vhdPath) {
        throw 'Scratch receipt does not identify this run'
    }
    Close-SmokeVhd $vhdPath ([guid]$created.id)
    $digest = (Get-FileHash -LiteralPath $vhdPath -Algorithm SHA256).Hash.ToLowerInvariant()
    [ordered]@{status='detached'; run_id=$created.run_id; path=$vhdPath; vhdx_sha256=$digest} | ConvertTo-Json
    return
}

if (Test-Path -LiteralPath $root) { throw 'Scratch directory already exists; no overwrite or automatic retry' }
if (([IO.DriveInfo]::new($driveRoot)).AvailableFreeSpace -lt 512MB) { throw 'Need at least 512 MiB free for this test' }
([IO.DirectoryInfo]::new($root)).Create($dirSecurity)
Confirm-SmokeDirectory $root $true
if (@(Get-ChildItem -Force -LiteralPath $root).Count -ne 0) { throw 'Scratch directory is not empty' }

$baseline = @(Storage\Get-Disk | ForEach-Object { $_.Number })
if ($baseline.Count -lt 1 -or $null -in $baseline) { throw 'Could not establish a valid storage baseline' }
$created = @(Hyper-V\New-VHD -Path $vhdPath -Dynamic -SizeBytes 256MB)
if ($created.Count -ne 1 -or $created[0].Path -ine $vhdPath) { throw 'No unique newly created scratch VHDX' }
$id = [guid]$created[0].DiskIdentifier
$before = Get-SmokeVhd $vhdPath $id
if ($false -ne $before.Attached) { throw 'New scratch VHDX unexpectedly attached' }
[ordered]@{run_id=$RunId.ToLowerInvariant(); path=$vhdPath; id=$id.ToString()} |
    ConvertTo-Json -Compress | Set-Content -LiteralPath $receipt -Encoding Ascii

try {
    Hyper-V\Mount-VHD -Path $vhdPath -NoDriveLetter
    $disk = Get-SmokeMapping $vhdPath $id $true
    if ($disk.Number -in $baseline) { throw 'Scratch disk number was present before attachment; not initializing' }
    Storage\Initialize-Disk -InputObject $disk -PartitionStyle GPT
    $disk = Get-SmokeMapping $vhdPath $id $false
    if ($disk.PartitionStyle -ne 'GPT' -or $disk.Number -in $baseline) { throw 'Scratch GPT identity changed' }
    $part = @(Storage\New-Partition -InputObject $disk -UseMaximumSize -AssignDriveLetter)
    if ($part.Count -ne 1 -or $part[0].DiskNumber -ne $disk.Number -or $part[0].DriveLetter -notmatch '\A[A-Z]\z') {
        throw 'No unique scratch partition and drive letter'
    }
    # Re-check the mapping and use the partition object, never a format-by-letter call.
    $mapped = Get-SmokeMapping $vhdPath $id $false
    $owned = @(Storage\Get-Partition -DriveLetter $part[0].DriveLetter)
    if ($mapped.Path -ine $disk.Path -or $owned.Count -ne 1 -or $owned[0].DiskNumber -ne $mapped.Number -or
        $owned[0].PartitionNumber -ne $part[0].PartitionNumber -or $owned[0].Guid -ne $part[0].Guid -or
        [guid]$owned[0].Guid -eq [guid]::Empty) { throw 'Scratch partition mapping changed; not formatting' }
    $null = Storage\Format-Volume -Partition $owned[0] -FileSystem exFAT -NewFileSystemLabel 'NSB2SMOKE' -Confirm:$false
    $volume = @(Storage\Get-Volume -Partition $owned[0])
    if ($volume.Count -ne 1 -or $volume[0].FileSystem -ine 'exFAT' -or
        $volume[0].FileSystemLabel -cne 'NSB2SMOKE' -or $volume[0].DriveLetter -ne $part[0].DriveLetter -or
        $volume[0].Path -notmatch '\A\\\\\?\\Volume\{[0-9a-f-]{36}\}\\\z') {
        throw 'Scratch volume verification failed'
    }
    [ordered]@{status='open'; run_id=$RunId.ToLowerInvariant(); path=$vhdPath; id=$id.ToString();
        drive=([string]$volume[0].DriveLetter + ':\'); volume_path=$volume[0].Path;
        size_bytes=[int64]$volume[0].Size} | ConvertTo-Json
} catch {
    $problem = $_
    try { Close-SmokeVhd $vhdPath $id }
    catch { throw "Open failed ($problem); detach not verified ($_). Leave $root for review; do not retry." }
    throw "Open failed ($problem); scratch VHDX verified detached. Evidence retained in $root."
}
