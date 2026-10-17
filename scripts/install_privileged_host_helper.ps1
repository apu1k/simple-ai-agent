param(
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$HelperSha256,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$CollectorSha256,
    [Parameter(Mandatory = $true)][string]$OperatorSid,
    [Parameter(Mandatory = $true)][string]$SourceDisk,
    [Parameter(Mandatory = $true)][string]$RecoveryIso,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$RecoveryIsoSha256,
    [Parameter(Mandatory = $true)][string]$Workspace
)
# OPERATOR SETUP ONLY. Never registered as a model tool; no automatic installation.
$ErrorActionPreference = 'Stop'
$system = [Environment]::GetFolderPath('System')
$env:PSModulePath = [IO.Path]::Combine($system, 'WindowsPowerShell\v1.0\Modules')
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Explicit administrator setup required'
}
if ($OperatorSid -notmatch '^S-1-5-21-\d+-\d+-\d+-\d+$') { throw 'Explicit operator account SID required' }
$operator = New-Object Security.Principal.SecurityIdentifier($OperatorSid)
$admins = New-Object Security.Principal.SecurityIdentifier('S-1-5-32-544')
$systemSid = New-Object Security.Principal.SecurityIdentifier('S-1-5-18')
function Check-LocalPath([string]$Path, [bool]$MustExist) {
    if ($Path.Length -gt 240 -or $Path -notmatch '^[A-Za-z]:\\' -or
        $Path.Substring(2).Contains(':') -or $Path.IndexOfAny([char[]]"`0`r`n`"") -ge 0 -or
        [IO.Path]::GetFullPath($Path) -ine $Path) { throw 'Canonical local path required' }
    $cursor = $Path
    if ($MustExist -and -not [IO.File]::Exists($Path)) { throw 'Required input missing' }
    while ($cursor) {
        if ([IO.File]::Exists($cursor) -or [IO.Directory]::Exists($cursor)) {
            $item = Get-Item -LiteralPath $cursor -Force
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse path refused' }
        }
        $parent = [IO.Directory]::GetParent($cursor)
        $cursor = if ($parent) { $parent.FullName } else { $null }
    }
}
Check-LocalPath $SourceDisk $true
Check-LocalPath $RecoveryIso $true
Check-LocalPath $Workspace $false
if ([IO.Path]::GetExtension($SourceDisk) -ine '.vhdx' -or
    [IO.Path]::GetExtension($RecoveryIso) -ine '.iso') { throw 'VHDX and ISO inputs required' }
$checkout = [IO.Directory]::GetParent($PSScriptRoot).FullName + '\'
foreach ($inputPath in @($SourceDisk, $RecoveryIso, $Workspace)) {
    if ($inputPath.StartsWith($checkout, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Inputs/workspace must be outside the AI checkout'
    }
}
$helperSource = [IO.Path]::Combine($PSScriptRoot, 'privileged_host_helper.ps1')
$collectorSource = [IO.Path]::Combine($checkout, 'night_shifts\backends\hyperv_scripts\collect_host_evidence.ps1')
# Read exact bytes once; hashing a path then copying it would allow a race.
$helperBytes = [IO.File]::ReadAllBytes($helperSource)
$collectorBytes = [IO.File]::ReadAllBytes($collectorSource)
$algorithm = [Security.Cryptography.SHA256]::Create()
try {
    $helperHash = ([BitConverter]::ToString($algorithm.ComputeHash($helperBytes))).Replace('-', '').ToLowerInvariant()
    $collectorHash = ([BitConverter]::ToString($algorithm.ComputeHash($collectorBytes))).Replace('-', '').ToLowerInvariant()
} finally { $algorithm.Dispose() }
if ($helperHash -cne $HelperSha256 -or $collectorHash -cne $CollectorSha256 -or
    $helperBytes.Length -gt 65536 -or $collectorBytes.Length -gt 65536) {
    throw 'Reviewed snapshot hash mismatch'
}
$programFiles = [Environment]::GetFolderPath('ProgramFiles')
$root = [IO.Path]::Combine($programFiles, 'AiAgentHyperVEvidence')
Check-LocalPath $root $false
if ([IO.Directory]::Exists($root) -or [IO.File]::Exists($root)) {
    throw 'Installation already exists; no overwrite, repair or automatic upgrade'
}
# Refuse replaceable installation ancestors. Do not repair their permissions.
$trusted = @('S-1-5-18', 'S-1-5-32-544',
    'S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464')
$cursor = $programFiles
while ($cursor) {
    $acl = Get-Acl -LiteralPath $cursor
    if ($trusted -notcontains $acl.GetOwner([Security.Principal.SecurityIdentifier]).Value) {
        throw 'Untrusted installation ancestor owner'
    }
    $dangerous = 0x40 -bor 0x40000 -bor 0x80000 -bor 0x10000000
    if ($cursor -ine [IO.Path]::GetPathRoot($cursor)) { $dangerous = $dangerous -bor 0x10000 }
    foreach ($rule in $acl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier])) {
        if ($rule.PropagationFlags -band [Security.AccessControl.PropagationFlags]::InheritOnly) { continue }
        if ($rule.AccessControlType -eq [Security.AccessControl.AccessControlType]::Allow -and
            $trusted -notcontains $rule.IdentityReference.Value -and
            ([int]$rule.FileSystemRights -band $dangerous)) { throw 'Replaceable installation ancestor' }
    }
    $parent = [IO.Directory]::GetParent($cursor)
    $cursor = if ($parent) { $parent.FullName } else { $null }
}
$security = New-Object Security.AccessControl.DirectorySecurity
$security.SetAccessRuleProtection($true, $false)
$security.SetOwner($admins)
$inherit = [Security.AccessControl.InheritanceFlags]'ContainerInherit, ObjectInherit'
$propagation = [Security.AccessControl.PropagationFlags]::None
$allow = [Security.AccessControl.AccessControlType]::Allow
foreach ($sid in @($admins, $systemSid)) {
    $security.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule(
        $sid, [Security.AccessControl.FileSystemRights]::FullControl, $inherit, $propagation, $allow)))
}
$security.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule(
    $operator, [Security.AccessControl.FileSystemRights]::ReadAndExecute, $inherit, $propagation, $allow)))
# Create with the restrictive DACL atomically; never expose a writable install.
$directory = New-Object IO.DirectoryInfo($root)
$directory.Create($security)
function Write-New([string]$Path, [byte[]]$Bytes) {
    $stream = [IO.File]::Open($Path, 'CreateNew', 'Write', 'None')
    try { $stream.Write($Bytes, 0, $Bytes.Length); $stream.Flush($true) }
    finally { $stream.Dispose() }
}
Write-New ([IO.Path]::Combine($root, 'helper.ps1')) $helperBytes
Write-New ([IO.Path]::Combine($root, 'collector.ps1')) $collectorBytes
# Explicit Administrators owner on children, not the elevated individual user.
foreach ($name in @('helper.ps1', 'collector.ps1')) {
    $path = [IO.Path]::Combine($root, $name)
    $acl = Get-Acl -LiteralPath $path
    $acl.SetOwner($admins)
    Set-Acl -LiteralPath $path -AclObject $acl
}
$receipts = New-Object IO.DirectoryInfo([IO.Path]::Combine($root, 'receipts'))
$receipts.Create($security)
$policy = @{ version = 1; operator_sid = $OperatorSid; source = $SourceDisk;
    recovery_iso = $RecoveryIso; recovery_iso_sha256 = $RecoveryIsoSha256;
    workspace = $Workspace; helper_sha256 = $HelperSha256; collector_sha256 = $CollectorSha256;
    max_execution_seconds = 900 }
$policyPath = [IO.Path]::Combine($root, 'policy.json')
Write-New $policyPath ([Text.Encoding]::UTF8.GetBytes(($policy | ConvertTo-Json -Compress)))
$acl = Get-Acl -LiteralPath $policyPath
$acl.SetOwner($admins)
Set-Acl -LiteralPath $policyPath -AclObject $acl
@{ status = 'installed'; root = $root; policy = $policy; launch_authorized = $false } |
    ConvertTo-Json -Depth 4
# No VM/disk/workspace changes. Partial setup failures retain evidence; no retry.
