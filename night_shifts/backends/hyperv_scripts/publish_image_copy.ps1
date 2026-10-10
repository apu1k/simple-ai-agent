param(
    [Parameter(Mandatory = $true)][string]$SourceDisk,
    [Parameter(Mandatory = $true)][string]$ExpectedSha256,
    [Parameter(Mandatory = $true)][string]$Destination
)
$ErrorActionPreference = 'Stop'
if ($ExpectedSha256 -cnotmatch '^[0-9a-f]{64}$' -or $SourceDisk -eq $Destination -or
    [IO.Path]::GetFileName($SourceDisk) -cne 'working-copy.vhdx' -or
    [IO.Path]::GetFileName($Destination) -cnotmatch '^night-shift-protocol-[0-9a-f]{32}\.vhdx$' -or
    (Test-Path -LiteralPath $Destination)) {
    throw 'Publication paths/digest differ or output already exists'
}
foreach ($path in @($SourceDisk, (Split-Path -Parent $Destination))) {
    $item = Get-Item -LiteralPath $path -Force -ErrorAction Stop
    while ($item) {
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Publication path has a reparse point' }
        $item = $item.Parent
        if (-not $item -and $path -eq $SourceDisk) {
            $item = (Get-Item -LiteralPath $SourceDisk).Directory
            $path = ''
        }
    }
}
$vhd = Get-VHD -Path $SourceDisk -ErrorAction Stop
if ($vhd.VhdFormat -ne 'VHDX' -or $vhd.VhdType -ne 'Dynamic' -or
    $vhd.Size -ne 21474836480 -or $vhd.ParentPath -or $vhd.Attached) {
    throw 'Publication source is not an unattached, parentless maintenance copy'
}
foreach ($vm in @(Get-VM -ErrorAction Stop)) {
    if (@(Get-VMHardDiskDrive -VM $vm | Where-Object { $_.Path -eq $SourceDisk }).Count -ne 0) {
        throw 'Publication source is still referenced by a VM'
    }
}
$source = [IO.File]::Open($SourceDisk, 'Open', 'Read', 'Read')
try {
    if ((Get-FileHash -LiteralPath $SourceDisk -Algorithm SHA256).Hash -ne $ExpectedSha256) {
        throw 'Finalized copy changed since accepted audit'
    }
    $output = [IO.File]::Open($Destination, 'CreateNew', 'Write', 'None')
    try { $source.CopyTo($output); $output.Flush($true) }
    finally { $output.Dispose() }
    if ((Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash -ne $ExpectedSha256) {
        throw 'Published bytes differ from accepted copy'
    }
    # Only this fresh export is given a new policy. Never repair evidence ACLs.
    $operator = [Security.Principal.WindowsIdentity]::GetCurrent().User
    $system = New-Object Security.Principal.SecurityIdentifier('S-1-5-18')
    $admins = New-Object Security.Principal.SecurityIdentifier('S-1-5-32-544')
    $acl = New-Object Security.AccessControl.FileSecurity
    $acl.SetOwner($operator)
    $acl.SetAccessRuleProtection($true, $false)
    $acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule($operator, 'ReadAndExecute', 'Allow')))
    foreach ($principal in @($system, $admins)) {
        $acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule($principal, 'FullControl', 'Allow')))
    }
    # Set attributes while the creator still has write-attributes access;
    # then reduce the operator to read/execute without relying on admin groups.
    $item = Get-Item -LiteralPath $Destination -Force
    $item.IsReadOnly = $true
    Set-Acl -LiteralPath $Destination -AclObject $acl -ErrorAction Stop
    $observed = Get-Acl -LiteralPath $Destination
    $rules = @($observed.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier]))
    if (-not $observed.AreAccessRulesProtected -or
        $observed.GetOwner([Security.Principal.SecurityIdentifier]).Value -ne $operator.Value -or
        $rules.Count -ne 3 -or -not (Get-Item -LiteralPath $Destination).IsReadOnly) {
        throw 'Export private/read-only policy not observed'
    }
    foreach ($rule in $rules) {
        $expected = if ($rule.IdentityReference.Value -eq $operator.Value) { [Security.AccessControl.FileSystemRights]::ReadAndExecute -bor [Security.AccessControl.FileSystemRights]::Synchronize } else { [Security.AccessControl.FileSystemRights]::FullControl }
        if ($rule.IdentityReference.Value -notin @($operator.Value, $system.Value, $admins.Value) -or
            $rule.AccessControlType -ne 'Allow' -or $rule.IsInherited -or
            $rule.FileSystemRights -ne [Security.AccessControl.FileSystemRights]$expected) {
            throw 'Export contains an unexpected access rule'
        }
    }
    @{ sha256 = $ExpectedSha256; read_only = $true; private = $true } | ConvertTo-Json -Compress
}
finally { $source.Dispose() }
# On failure keep partial output and permanent claim for explicit investigation.
