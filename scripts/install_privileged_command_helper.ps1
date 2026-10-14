param(
    [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{64}$')][string]$HelperSha256,
    [Parameter(Mandatory=$true)][ValidatePattern('^S-1-5-21-\d+-\d+-\d+-\d+$')][string]$OperatorSid
)
# SEPARATELY REVIEWED OPERATOR SETUP ONLY. No tool installs or upgrades this.
$ErrorActionPreference = 'Stop'
if ([IntPtr]::Size -ne 8 -or $PSVersionTable.PSEdition -ne 'Desktop') {
    throw 'Use native x64 Windows PowerShell'
}
$system = [Environment]::GetFolderPath('System')
$env:PSModulePath = [IO.Path]::Combine($system,'WindowsPowerShell\v1.0\Modules')
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) -or
    $identity.User.Value -cne $OperatorSid) { throw 'Same-account explicit Administrator setup required' }
$admins = New-Object Security.Principal.SecurityIdentifier('S-1-5-32-544')
$systemSid = New-Object Security.Principal.SecurityIdentifier('S-1-5-18')
$operator = New-Object Security.Principal.SecurityIdentifier($OperatorSid)
$programFiles = [Environment]::GetFolderPath('ProgramFiles')
$root = [IO.Path]::Combine($programFiles,'AiAgentElevatedCommands')
if ([IO.Directory]::Exists($root) -or [IO.File]::Exists($root)) {
    throw 'Installation exists; no overwrite, repair, upgrade or automatic retry'
}
$trusted = @('S-1-5-18','S-1-5-32-544',
    'S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464')
$cursor = $programFiles
while ($cursor) {
    $item = Get-Item -LiteralPath $cursor -Force
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse ancestor refused' }
    $acl = Get-Acl -LiteralPath $cursor
    if ($trusted -notcontains $acl.GetOwner([Security.Principal.SecurityIdentifier]).Value) {
        throw 'Untrusted installation ancestor owner'
    }
    $mask = 0x40 -bor 0x40000 -bor 0x80000 -bor 0x10000000
    if ($cursor -ine [IO.Path]::GetPathRoot($cursor)) { $mask = $mask -bor 0x10000 }
    foreach ($rule in $acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])) {
        if ($rule.PropagationFlags -band [Security.AccessControl.PropagationFlags]::InheritOnly) { continue }
        if ($rule.AccessControlType -eq [Security.AccessControl.AccessControlType]::Allow -and
            $trusted -notcontains $rule.IdentityReference.Value -and ([int]$rule.FileSystemRights -band $mask)) {
            throw 'Replaceable installation ancestor'
        }
    }
    $parent = [IO.Directory]::GetParent($cursor)
    $cursor = if ($parent) { $parent.FullName } else { $null }
}
# Read/hash the same bytes we will install, never hash then copy a mutable path.
$bytes = [IO.File]::ReadAllBytes([IO.Path]::Combine($PSScriptRoot,'privileged_command_helper.ps1'))
$sha = [Security.Cryptography.SHA256]::Create()
try { $digest = ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-','').ToLowerInvariant() }
finally { $sha.Dispose() }
if ($bytes.Length -gt 65536 -or $digest -cne $HelperSha256) { throw 'Reviewed helper bytes mismatch' }
$security = New-Object Security.AccessControl.DirectorySecurity
$security.SetAccessRuleProtection($true,$false)
$security.SetOwner($admins)
$inherit = [Security.AccessControl.InheritanceFlags]'ContainerInherit,ObjectInherit'
$propagation = [Security.AccessControl.PropagationFlags]::None
$allow = [Security.AccessControl.AccessControlType]::Allow
foreach ($sid in @($admins,$systemSid)) {
    $security.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule(
        $sid,[Security.AccessControl.FileSystemRights]::FullControl,$inherit,$propagation,$allow)))
}
$security.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule(
    $operator,[Security.AccessControl.FileSystemRights]::ReadAndExecute,$inherit,$propagation,$allow)))
$directory = New-Object IO.DirectoryInfo($root)
$directory.Create($security)
$receipts = New-Object IO.DirectoryInfo([IO.Path]::Combine($root,'receipts'))
$receipts.Create($security)
$fileSecurity = New-Object Security.AccessControl.FileSecurity
$fileSecurity.SetOwner($admins)
function Write-New([string]$Name,[byte[]]$Data) {
    $out = New-Object IO.FileStream(([IO.Path]::Combine($root,$Name)),[IO.FileMode]::CreateNew,
        [Security.AccessControl.FileSystemRights]::Write,[IO.FileShare]::None,4096,[IO.FileOptions]::None,$fileSecurity)
    try { $out.Write($Data,0,$Data.Length); $out.Flush($true) }
    finally { $out.Dispose() }
}
Write-New 'helper.ps1' $bytes
$policy = @{version=1; operator_sid=$OperatorSid; helper_sha256=$digest; max_timeout=60}
Write-New 'policy.json' ([Text.Encoding]::UTF8.GetBytes(($policy | ConvertTo-Json -Compress)))
# Only this data inbox is operator-writable. It is never searched for helper code.
$inboxSecurity = New-Object Security.AccessControl.DirectorySecurity
$inboxSecurity.SetAccessRuleProtection($true,$false)
$inboxSecurity.SetOwner($admins)
foreach ($sid in @($admins,$systemSid)) {
    $inboxSecurity.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule(
        $sid,[Security.AccessControl.FileSystemRights]::FullControl,$inherit,$propagation,$allow)))
}
$inboxSecurity.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule(
    $operator,[Security.AccessControl.FileSystemRights]::Modify,$inherit,$propagation,$allow)))
$inbox = New-Object IO.DirectoryInfo([IO.Path]::Combine($root,'requests'))
$inbox.Create($inboxSecurity)
@{status='installed'; root=$root; operation='elevated_commands'; launch_performed=$false;
    warning='General approved Administrator scripts are not sandboxed.'} | ConvertTo-Json
# No command execution or modification of either existing Hyper-V installation.
# Partial setup stays for review. Do not rerun or repair after failure.
