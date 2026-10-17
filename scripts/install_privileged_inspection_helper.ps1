param(
    [Parameter(Mandatory=$true)][string]$Bundle,
    [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{64}$')][string]$BundleSha256,
    [Parameter(Mandatory=$true)][string]$PythonArchive,
    [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{64}$')][string]$PythonArchiveSha256,
    [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{64}$')][string]$HelperSha256,
    [Parameter(Mandatory=$true)][ValidatePattern('^S-1-5-21-\d+-\d+-\d+-\d+$')][string]$OperatorSid,
    [Parameter(Mandatory=$true)][string]$SourceDisk,
    [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{64}$')][string]$SourceSha256,
    [Parameter(Mandatory=$true)][string]$RecoveryIso,
    [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{64}$')][string]$RecoveryIsoSha256,
    [Parameter(Mandatory=$true)][string]$Workspace,
    [Parameter(Mandatory=$true)][DateTimeOffset]$InspectionApprovedUntilUtc,
    [Parameter(Mandatory=$true)][switch]$PythonProvenanceReviewed,
    [Parameter(Mandatory=$true)][switch]$IsoProvenanceReviewed,
    [Parameter(Mandatory=$true)][switch]$EvidencePreserved,
    [Parameter(Mandatory=$true)][switch]$AuthorizeNewInspectionAttempt
)
# Fresh V2 setup only. V1 installation/claim/receipts remain untouched.
# No VM operation, source mutation, claim reset or permission repair.
$ErrorActionPreference='Stop'
if (-not $AuthorizeNewInspectionAttempt) {
    throw 'A separately reviewed new inspection attempt must be authorized'
}
$system=[Environment]::GetFolderPath('System')
$env:PSModulePath=[IO.Path]::Combine($system,'WindowsPowerShell\v1.0\Modules')
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
$principal=New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) -or
    [IntPtr]::Size -ne 8 -or $PSVersionTable.PSEdition -ne 'Desktop') {
    throw 'Dedicated native x64 Windows PowerShell Administrator setup required'
}
if ($identity.User.Value -cne $OperatorSid) { throw 'Different-account setup is unsupported' }
if (-not $PythonProvenanceReviewed -or -not $IsoProvenanceReviewed -or -not $EvidencePreserved) {
    throw 'Independent provenance review and evidence preservation required'
}
$expiry=$InspectionApprovedUntilUtc.ToUnixTimeSeconds()
$now=[DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
if ($expiry-$now -lt 1800 -or $expiry-$now -gt 86400) { throw 'Approval window must be 30 minutes to 24 hours' }
function Check-Local([string]$Path,[bool]$File) {
    if ($Path.Length -gt 240 -or $Path -notmatch '^[A-Za-z]:\\' -or $Path.Substring(2).Contains(':') -or
        $Path.IndexOfAny([char[]]@([char]0,[char]10,[char]13,[char]34)) -ge 0 -or
        [IO.Path]::GetFullPath($Path) -ine $Path) { throw 'Canonical local path required' }
    if ($File -and -not [IO.File]::Exists($Path)) { throw 'Required input missing' }
    $cursor=$Path
    while ($cursor) {
        $item=Get-Item -LiteralPath $cursor -Force -ErrorAction Stop
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse path refused' }
        $parent=[IO.Directory]::GetParent($cursor); $cursor=if($parent){$parent.FullName}else{$null}
    }
}
foreach ($path in @($Bundle,$PythonArchive,$SourceDisk,$RecoveryIso)) { Check-Local $path $true }
Check-Local $Workspace $false
if (-not [IO.Directory]::Exists($Workspace) -or @(Get-ChildItem -LiteralPath $Workspace -Force).Count -ne 0) {
    throw 'Existing empty reviewed workspace required'
}
$checkout=[IO.Directory]::GetParent($PSScriptRoot).FullName+'\'
foreach ($path in @($SourceDisk,$RecoveryIso,$Workspace)) {
    if ($path.StartsWith($checkout,[StringComparison]::OrdinalIgnoreCase)) { throw 'External inputs/workspace required' }
}
if ([IO.Path]::GetExtension($SourceDisk) -ine '.vhdx' -or [IO.Path]::GetExtension($RecoveryIso) -ine '.iso') {
    throw 'Reviewed VHDX/ISO required'
}
function Hash-Bytes([byte[]]$Bytes) {
    $algorithm=[Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($algorithm.ComputeHash($Bytes))).Replace('-','').ToLowerInvariant() }
    finally { $algorithm.Dispose() }
}
$helper=[IO.File]::ReadAllBytes((Join-Path $PSScriptRoot 'privileged_inspection_helper.ps1'))
if ((Get-Item -LiteralPath $Bundle).Length -gt 4194304 -or
    (Get-Item -LiteralPath $PythonArchive).Length -gt 67108864 -or $helper.Length -gt 65536) {
    throw 'Deployment input exceeds bounds'
}
$bundleBytes=[IO.File]::ReadAllBytes($Bundle); $pythonBytes=[IO.File]::ReadAllBytes($PythonArchive)
if ((Hash-Bytes $helper) -cne $HelperSha256 -or (Hash-Bytes $bundleBytes) -cne $BundleSha256 -or
    (Hash-Bytes $pythonBytes) -cne $PythonArchiveSha256) { throw 'Reviewed byte hash mismatch' }
Add-Type -AssemblyName System.IO.Compression
function Read-Archive([byte[]]$Bytes,[bool]$Runtime) {
    $memory=New-Object IO.MemoryStream(,$Bytes)
    $archive=New-Object IO.Compression.ZipArchive($memory,[IO.Compression.ZipArchiveMode]::Read)
    $result=@{}; $total=0
    try {
        if ($archive.Entries.Count -gt 256) { throw 'Too many archive entries' }
        foreach ($entry in $archive.Entries) {
            $name=$entry.FullName
            $pattern=if($Runtime){'^[A-Za-z0-9_.-]+$'}else{'^(manifest\.json|(?:night_shifts|pycdlib)/[A-Za-z0-9_./-]+)$'}
            $kind=($entry.ExternalAttributes -shr 16) -band 0xF000
            if ($name -cnotmatch $pattern -or $name.Contains('..') -or $name.Contains('//') -or
                $name.EndsWith('/') -or $result.ContainsKey($name) -or $kind -notin @(0,0x8000) -or
                $entry.Length -gt 33554432) { throw 'Unsafe/duplicate archive entry' }
            $total += $entry.Length
            if ($total -gt 100663296) { throw 'Expanded deployment exceeds bound' }
            $input=$entry.Open(); $output=New-Object IO.MemoryStream
            try { $input.CopyTo($output); $result[$name]=$output.ToArray() }
            finally { $input.Dispose(); $output.Dispose() }
        }
    } finally { $archive.Dispose(); $memory.Dispose() }
    return $result
}
$payload=Read-Archive $bundleBytes $false; $runtime=Read-Archive $pythonBytes $true
if (-not $payload.ContainsKey('manifest.json') -or
    -not $payload.ContainsKey('night_shifts/inspection_worker.py') -or -not $runtime.ContainsKey('python.exe')) {
    throw 'Required deployment files missing'
}
$manifest=[Text.Encoding]::UTF8.GetString($payload['manifest.json']) | ConvertFrom-Json
if (@($manifest.PSObject.Properties).Count -ne ($payload.Count-1)) { throw 'Bundle inventory differs' }
foreach ($binding in $manifest.PSObject.Properties) {
    if (-not $payload.ContainsKey($binding.Name) -or (Hash-Bytes $payload[$binding.Name]) -cne $binding.Value) {
        throw 'Bundle content differs from inventory'
    }
}
$pth=@($runtime.Keys | Where-Object { $_ -cmatch '^python\d+\._pth$' })
if ($pth.Count -ne 1) { throw 'Reviewed CPython x64 embeddable ZIP required' }
foreach ($line in ([Text.Encoding]::UTF8.GetString($runtime[$pth[0]]) -split '\r?\n')) {
    $line=$line.Trim()
    if ($line -and -not $line.StartsWith('#') -and $line -cne '.' -and $line -cnotmatch '^python\d+\.zip$') {
        throw 'Python path/site injection refused'
    }
    if ($line -cmatch '^python\d+\.zip$' -and -not $runtime.ContainsKey($line)) { throw 'Missing stdlib' }
}
$programFiles=[Environment]::GetFolderPath('ProgramFiles'); $root=Join-Path $programFiles 'AiAgentHyperVInspectionV2'
if (Test-Path -LiteralPath $root) { throw 'Installation exists; no overwrite, reset, upgrade or repair' }
$trusted=@('S-1-5-18','S-1-5-32-544','S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464')
$cursor=$programFiles
while ($cursor) {
    $item=Get-Item -LiteralPath $cursor -Force
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse ancestor' }
    $acl=Get-Acl -LiteralPath $cursor
    if ($trusted -notcontains $acl.GetOwner([Security.Principal.SecurityIdentifier]).Value) { throw 'Untrusted ancestor owner' }
    $dangerous=0x40 -bor 0x40000 -bor 0x80000 -bor 0x10000000
    if ($cursor -ine [IO.Path]::GetPathRoot($cursor)) { $dangerous=$dangerous -bor 0x10000 }
    foreach ($rule in $acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])) {
        if ($rule.PropagationFlags -band [Security.AccessControl.PropagationFlags]::InheritOnly) { continue }
        if ($rule.AccessControlType -eq 'Allow' -and $trusted -notcontains $rule.IdentityReference.Value -and
            ([int]$rule.FileSystemRights -band $dangerous)) { throw 'Replaceable installation ancestor' }
    }
    $parent=[IO.Directory]::GetParent($cursor); $cursor=if($parent){$parent.FullName}else{$null}
}
$directorySecurity=New-Object Security.AccessControl.DirectorySecurity
$directorySecurity.SetSecurityDescriptorSddlForm(('O:BAG:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FRFX;;;'+$OperatorSid+')'))
$fileSecurity=New-Object Security.AccessControl.FileSecurity
$fileSecurity.SetSecurityDescriptorSddlForm(('O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;FRFX;;;'+$OperatorSid+')'))
$directory=New-Object IO.DirectoryInfo($root); $directory.Create($directorySecurity)
foreach ($name in @('payload','runtime','receipts')) {
    $directory=New-Object IO.DirectoryInfo((Join-Path $root $name)); $directory.Create($directorySecurity)
}
function Write-Protected([string]$Path,[byte[]]$Bytes) {
    $parent=[IO.Directory]::GetParent($Path)
    if (-not $parent.Exists) { $parent.Create($directorySecurity) }
    $stream=New-Object IO.FileStream($Path,[IO.FileMode]::CreateNew,
        [Security.AccessControl.FileSystemRights]::Write,[IO.FileShare]::None,
        4096,[IO.FileOptions]::WriteThrough,$fileSecurity)
    try { $stream.Write($Bytes,0,$Bytes.Length); $stream.Flush($true) } finally { $stream.Dispose() }
}
$files=@{'helper.ps1'=$HelperSha256}; Write-Protected (Join-Path $root 'helper.ps1') $helper
foreach ($name in $payload.Keys) {
    Write-Protected (Join-Path $root ('payload/'+$name)) $payload[$name]; $files['payload/'+$name]=Hash-Bytes $payload[$name]
}
foreach ($name in $runtime.Keys) {
    Write-Protected (Join-Path $root ('runtime/'+$name)) $runtime[$name]; $files['runtime/'+$name]=Hash-Bytes $runtime[$name]
}
# Only the reviewed installed interpreter is executed; no site-packages or VM call.
& (Join-Path $root 'runtime\python.exe') -I -S -B -c 'import sys,ctypes; assert sys.version_info >= (3,11); assert ctypes.sizeof(ctypes.c_void_p)==8'
if ($LASTEXITCODE -ne 0) { throw 'Interpreter check failed; retain partial setup for review' }
$policy=@{ version=1; operation='inspect_image_copy'; operator_sid=$OperatorSid;
    source=$SourceDisk; source_sha256=$SourceSha256; recovery_iso=$RecoveryIso;
    recovery_iso_sha256=$RecoveryIsoSha256; workspace=$Workspace; approved_until_unix=$expiry;
    iso_provenance_reviewed=$true; evidence_preserved=$true; files=$files;
    bundle_sha256=$BundleSha256; python_archive_sha256=$PythonArchiveSha256 }
Write-Protected (Join-Path $root 'policy.json') ([Text.Encoding]::UTF8.GetBytes(($policy | ConvertTo-Json -Depth 6 -Compress)))
@{status='installed';root=$root;operation='inspect_image_copy';launch_performed=$false;
    new_attempt_explicitly_authorized=$true;legacy_installation_modified=$false} | ConvertTo-Json
# Setup does not start inspection. Separate next-turn authorization and UAC remain required.
