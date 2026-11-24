param(
    [Parameter(Mandatory=$true)][string]$BundlePath,
    [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{64}$')][string]$BundleSha256,
    [Parameter(Mandatory=$true)][string]$BaseImage,
    [Parameter(Mandatory=$true)][ValidatePattern('^S-1-5-21-\d+-\d+-\d+-\d+$')][string]$OperatorSid
)
# Separate, reviewed operator setup. No downloads, start, update, repair or retry.
$ErrorActionPreference = 'Stop'
if ([IntPtr]::Size -ne 8 -or $PSVersionTable.PSEdition -ne 'Desktop') { throw 'Use x64 Windows PowerShell' }
$system = [Environment]::GetFolderPath('System')
$env:PSModulePath = [IO.Path]::Combine($system, 'WindowsPowerShell\v1.0\Modules')
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) -or
    $identity.User.Value -cne $OperatorSid) { throw 'Same-account explicit Administrator setup required' }

$programFiles = [Environment]::GetFolderPath('ProgramFiles')
$root = Join-Path $programFiles 'AiAgentGateA'
$taskName = 'AiAgentGateA'
$imageSha256 = '13bc986452a63d145b6cdd2d5b79e629d9244745269b0996b3bf24daf39894d6'
$trusted = @('S-1-5-18','S-1-5-32-544',
    'S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464')
for ($cursor = [IO.DirectoryInfo]$programFiles; $null -ne $cursor; $cursor = $cursor.Parent) {
    $item = Get-Item -LiteralPath $cursor.FullName -Force
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse installation ancestor refused' }
    $acl = Get-Acl -LiteralPath $cursor.FullName
    if ($trusted -notcontains $acl.GetOwner([Security.Principal.SecurityIdentifier]).Value) {
        throw 'Untrusted installation ancestor owner'
    }
    $mask = 0x40 -bor 0x40000 -bor 0x80000 -bor 0x10000000
    if ($cursor.Parent) { $mask = $mask -bor 0x10000 }
    if ($cursor.FullName -ieq $programFiles) { $mask = $mask -bor 0x6 }
    foreach ($rule in $acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])) {
        if ($rule.PropagationFlags -band [Security.AccessControl.PropagationFlags]::InheritOnly) { continue }
        if ($rule.AccessControlType -eq 'Allow' -and $trusted -notcontains $rule.IdentityReference.Value -and
            ([int]$rule.FileSystemRights -band $mask)) { throw 'Replaceable installation ancestor' }
    }
}
if (Test-Path -LiteralPath $root) { throw 'Installation path exists; retain it for review' }
foreach ($inputPath in @($BundlePath, $BaseImage)) {
    if ($inputPath -notmatch '^[A-Za-z]:\\[^\\]' -or [IO.Path]::GetFullPath($inputPath) -cne $inputPath) {
        throw 'An absolute local canonical input path is required'
    }
}
$scheduler = New-Object -ComObject 'Schedule.Service'
$scheduler.Connect()
$folder = $scheduler.GetFolder('\')
if (@($folder.GetTasks(1) | Where-Object { $_.Name -ieq $taskName }).Count) {
    throw 'Task exists; do not replace or retry installation'
}

# Read a bounded snapshot and hash the exact bytes to be parsed/extracted.
$inputStream = [IO.File]::Open($BundlePath, 'Open', 'Read', 'Read')
try {
    if ($inputStream.Length -lt 1 -or $inputStream.Length -gt 64MB) { throw 'Bundle size limit' }
    $bytes = New-Object byte[] ([int]$inputStream.Length)
    $offset = 0
    while ($offset -lt $bytes.Length) {
        $n = $inputStream.Read($bytes, $offset, $bytes.Length - $offset)
        if ($n -le 0) { throw 'Bundle truncated' }
        $offset += $n
    }
} finally { $inputStream.Dispose() }
$sha = [Security.Cryptography.SHA256]::Create()
try { $digest = ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-', '').ToLowerInvariant() }
finally { $sha.Dispose() }
if ($digest -cne $BundleSha256) { throw 'Reviewed bundle digest does not match' }

$readAce = '(A;OICI;FRFX;;;' + $OperatorSid + ')'
$dirSecurity = New-Object Security.AccessControl.DirectorySecurity
$dirSecurity.SetSecurityDescriptorSddlForm('O:BAG:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)' + $readAce)
$fileSecurity = New-Object Security.AccessControl.FileSecurity
$fileSecurity.SetSecurityDescriptorSddlForm('O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;FRFX;;;' + $OperatorSid + ')')
function New-ProtectedDirectory([string]$Path) {
    $directory = New-Object IO.DirectoryInfo($Path)
    $directory.Create($dirSecurity)
}
function Copy-NewFile([string]$Path, [IO.Stream]$InputFile, [long]$Length) {
    $target = New-Object IO.FileStream($Path, [IO.FileMode]::CreateNew,
        [Security.AccessControl.FileSystemRights]::Write, [IO.FileShare]::None, 65536,
        [IO.FileOptions]::SequentialScan, $fileSecurity)
    try {
        $buffer = New-Object byte[] 65536
        $remaining = $Length
        while ($remaining -gt 0) {
            $read = $InputFile.Read($buffer, 0, [int][Math]::Min($remaining, [long]$buffer.Length))
            if ($read -le 0) { throw 'Input ended before its declared length' }
            $target.Write($buffer, 0, $read)
            $remaining -= $read
        }
        if ($InputFile.ReadByte() -ne -1) { throw 'Input exceeded its declared length' }
        $target.Flush($true)
    } finally { $target.Dispose() }
}

Add-Type -AssemblyName System.IO.Compression
$bufferStream = New-Object IO.MemoryStream(,$bytes)
$zip = New-Object IO.Compression.ZipArchive($bufferStream, [IO.Compression.ZipArchiveMode]::Read)
try {
    if ($zip.Entries.Count -gt 4096) { throw 'Bundle member limit' }
    $paths = @{}
    $size = [long]0
    foreach ($entry in $zip.Entries) {
        $name = $entry.FullName
        if ($name.Length -gt 175 -or $name -cnotmatch '^(python|app)/[A-Za-z0-9_./-]+\z') { throw 'Invalid bundle member' }
        foreach ($part in $name.Split('/')) {
            if ($part -notmatch '^[A-Za-z0-9_][A-Za-z0-9_.-]*\z' -or $part.EndsWith('.') -or
                $part.Split('.')[0] -match '^(CON|AUX|NUL|PRN|COM[0-9]|LPT[0-9])\z') {
                throw 'Unsafe bundle member path'
            }
        }
        if ($paths.ContainsKey($name)) { throw 'Duplicate bundle path' }
        $paths.Add($name, $entry)
        $size += $entry.Length
        if ($size -gt 64MB) { throw 'Bundle expansion limit' }
    }
    $required = @('python/python.exe','python/python314.zip','python/python314.dll','python/python314._pth',
        'app/night_shifts/gate_a_installed.py','app/tests/night_shifts/test_hyperv_real_host.py')
    foreach ($name in $required) { if (-not $paths.ContainsKey($name)) { throw 'Missing required bundle entry' } }
    function New-Parent([string]$Path) {
        if ($Path -ieq $root -or [IO.Directory]::Exists($Path)) { return }
        New-Parent ([IO.Path]::GetDirectoryName($Path))
        New-ProtectedDirectory $Path
    }
    New-ProtectedDirectory $root
    foreach ($name in ($paths.Keys | Sort-Object)) {
        $target = Join-Path $root ($name.Replace('/', '\'))
        New-Parent ([IO.Path]::GetDirectoryName($target))
        $partStream = $paths[$name].Open()
        try { Copy-NewFile $target $partStream $paths[$name].Length }
        finally { $partStream.Dispose() }
    }
} finally { $zip.Dispose(); $bufferStream.Dispose() }

New-ProtectedDirectory (Join-Path $root 'runs')
New-ProtectedDirectory (Join-Path $root 'scratch')
$protectedBase = Join-Path $root 'base.vhdx'
$baseStream = [IO.File]::Open($BaseImage, 'Open', 'Read', 'Read')
try {
    if ($baseStream.Length -lt 1 -or $baseStream.Length -gt 8GB) { throw 'Base image size outside fixed bound' }
    Copy-NewFile $protectedBase $baseStream $baseStream.Length
} finally { $baseStream.Dispose() }
if ((Get-FileHash -LiteralPath $protectedBase -Algorithm SHA256).Hash -ine $imageSha256) {
    throw 'The protected image does not match the passing Gate A SHA-256; no task registered'
}

$definition = $scheduler.NewTask(0)
$definition.RegistrationInfo.Description = 'Run the fixed reviewed offline Night Shift Gate A suite only.'
$definition.Principal.UserId = 'SYSTEM'
$definition.Principal.LogonType = 5  # TASK_LOGON_SERVICE_ACCOUNT
$definition.Principal.RunLevel = 1
$definition.Settings.AllowDemandStart = $true
$definition.Settings.ExecutionTimeLimit = 'PT15M'
$definition.Settings.MultipleInstances = 2  # TASK_INSTANCES_IGNORE_NEW
$definition.Settings.StartWhenAvailable = $false
$definition.Settings.DisallowStartIfOnBatteries = $false
$definition.Settings.StopIfGoingOnBatteries = $false
$action = $definition.Actions.Create(0)
$action.Path = Join-Path $root 'python\python.exe'
$action.WorkingDirectory = Join-Path $root 'app'
$action.Arguments = '-I -B -m night_shifts.gate_a_installed'
# TASK_CREATE | TASK_DONT_ADD_PRINCIPAL_ACE. Grant the selected user read/run,
# not task change/delete/registration. The action has no substitution tokens.
$taskAcl = 'O:BAG:BAD:P(A;;GA;;;SY)(A;;GA;;;BA)(A;;GRGX;;;' + $OperatorSid + ')'
$registered = $folder.RegisterTaskDefinition($taskName, $definition, 18, 'SYSTEM', $null, 5, $taskAcl)
if ($registered.Path -cne '\AiAgentGateA') { throw 'Task registration outcome unconfirmed; retain for review' }
@{status='installed'; task=$registered.Path; root=$root; bundle_sha256=$digest;
    image_sha256=$imageSha256; launch_performed=$false} | ConvertTo-Json -Compress
