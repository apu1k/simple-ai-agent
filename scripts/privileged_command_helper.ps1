param(
    [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{32}$')][string]$RequestId,
    [Parameter(Mandatory=$true)][long]$DeadlineUnix,
    [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{64}$')][string]$RequestSha256
)
# GENERAL ADMINISTRATOR EXECUTION. Protected installation only. Not a sandbox.
$ErrorActionPreference = 'Stop'
$system = [Environment]::GetFolderPath('System')
$root = [IO.Path]::Combine([Environment]::GetFolderPath('ProgramFiles'), 'AiAgentElevatedCommands')
if ($PSScriptRoot -cne $root -or [IntPtr]::Size -ne 8 -or $PSVersionTable.PSEdition -ne 'Desktop') {
    throw 'Protected native x64 Windows PowerShell installation required'
}
# Do not pass the app's provider keys/Python hooks into approved commands.
$keep = @('SystemRoot','WINDIR','SystemDrive','ProgramFiles','ProgramFiles(x86)','ProgramW6432',
    'CommonProgramFiles','CommonProgramFiles(x86)','CommonProgramW6432','USERNAME','USERDOMAIN',
    'USERPROFILE','HOMEDRIVE','HOMEPATH','LOCALAPPDATA','APPDATA','OS','PROCESSOR_ARCHITECTURE','NUMBER_OF_PROCESSORS')
foreach ($key in @([Environment]::GetEnvironmentVariables('Process').Keys)) {
    if ($keep -inotcontains [string]$key) { [Environment]::SetEnvironmentVariable([string]$key,$null,'Process') }
}
$env:ComSpec = [IO.Path]::Combine($system,'cmd.exe')
$env:PSModulePath = [IO.Path]::Combine($system, 'WindowsPowerShell\v1.0\Modules')
$env:PATH = $system
$receipts = [IO.Path]::Combine($root, 'receipts')
$env:TEMP = $receipts; $env:TMP = $receipts
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Windows administrator consent required'
}
function Check-Local([string]$Path) {
    if ($Path -notmatch '^[A-Za-z]:\\' -or $Path.Length -gt 240 -or
        $Path.Substring(2).Contains(':') -or $Path.IndexOfAny([char[]]"`0`r`n`"") -ge 0 -or
        [IO.Path]::GetFullPath($Path) -cne $Path) { throw 'Canonical local path required' }
    $cursor = $Path
    while ($cursor) {
        $item = Get-Item -LiteralPath $cursor -Force
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse path refused' }
        $parent = [IO.Directory]::GetParent($cursor)
        $cursor = if ($parent) { $parent.FullName } else { $null }
    }
}
function Check-Protected([string]$Path) {
    Check-Local $Path
    $trusted = @('S-1-5-18','S-1-5-32-544',
        'S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464')
    $cursor = $Path; $first = $true
    while ($cursor) {
        $acl = Get-Acl -LiteralPath $cursor
        if ($trusted -notcontains $acl.GetOwner([Security.Principal.SecurityIdentifier]).Value) {
            throw 'Untrusted protected owner'
        }
        $mask = 0x40 -bor 0x40000 -bor 0x80000 -bor 0x10000000
        if ($cursor -ine [IO.Path]::GetPathRoot($cursor)) { $mask = $mask -bor 0x10000 }
        if ($first) { $mask = $mask -bor 0x2 -bor 0x4 -bor 0x10 -bor 0x100 -bor 0x40000000 }
        foreach ($rule in $acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])) {
            if ($rule.PropagationFlags -band [Security.AccessControl.PropagationFlags]::InheritOnly) { continue }
            if ($rule.AccessControlType -eq [Security.AccessControl.AccessControlType]::Allow -and
                $trusted -notcontains $rule.IdentityReference.Value -and ([int]$rule.FileSystemRights -band $mask)) {
                throw 'Protected path permits untrusted mutation'
            }
        }
        $first = $false
        $parent = [IO.Directory]::GetParent($cursor)
        $cursor = if ($parent) { $parent.FullName } else { $null }
    }
}
$exe = [IO.Path]::Combine($system, 'WindowsPowerShell\v1.0\powershell.exe')
foreach ($path in @($root,$receipts,$PSCommandPath,([IO.Path]::Combine($root,'policy.json')),$exe)) {
    Check-Protected $path
}
$policy = [IO.File]::ReadAllText([IO.Path]::Combine($root,'policy.json')) | ConvertFrom-Json
$helperHash = (Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($policy.version -ne 1 -or $policy.max_timeout -ne 60 -or
    $policy.helper_sha256 -cne $helperHash -or $policy.operator_sid -cne $identity.User.Value) {
    throw 'Installed policy/code/operator mismatch'
}
$remaining = $DeadlineUnix - [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
if ($remaining -le 0 -or $remaining -gt 1800) { throw 'Expired or excessive approval deadline' }
$inputPath = [IO.Path]::Combine($root,'requests',($RequestId + '.json'))
Check-Local $inputPath
# Read once with writes/deletion denied. Caller data is NOT executable helper code.
$stream = [IO.File]::Open($inputPath,'Open','Read','Read')
try {
    if ($stream.Length -gt 65536) { throw 'Oversized approved request' }
    $bytes = New-Object byte[] ([int]$stream.Length)
    $offset = 0
    while ($offset -lt $bytes.Length) {
        $count = $stream.Read($bytes,$offset,$bytes.Length-$offset)
        if ($count -eq 0) { throw 'Truncated approved request' }
        $offset += $count
    }
} finally { $stream.Dispose() }
$sha = [Security.Cryptography.SHA256]::Create()
try { $digest = ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-','').ToLowerInvariant() }
finally { $sha.Dispose() }
if ($digest -cne $RequestSha256) { throw 'Approved request changed' }
$utf8 = New-Object Text.UTF8Encoding($false,$true)
$request = $utf8.GetString($bytes) | ConvertFrom-Json
$fields = @('version','request_id','operation','deadline_unix','timeout','script','cwd','reason','operator_sid','helper_sha256')
if (@(Compare-Object $fields @($request.PSObject.Properties.Name)).Count -ne 0 -or
    $request.version -ne 1 -or $request.request_id -cne $RequestId -or
    $request.operation -cne 'elevated_commands' -or $request.deadline_unix -ne $DeadlineUnix -or
    $request.operator_sid -cne $identity.User.Value -or $request.helper_sha256 -cne $helperHash -or
    $request.timeout -isnot [int] -or $request.timeout -lt 1 -or $request.timeout -gt 60 -or
    $request.script -isnot [string] -or [string]::IsNullOrWhiteSpace($request.script) -or
    $request.script.Contains([string][char]0) -or $utf8.GetByteCount($request.script) -gt 32768 -or
    $request.reason -isnot [string] -or [string]::IsNullOrWhiteSpace($request.reason) -or
    $request.reason.Length -gt 2000 -or $request.cwd -isnot [string]) { throw 'Invalid approved request schema' }
Check-Local $request.cwd
if (-not [IO.Directory]::Exists($request.cwd)) { throw 'Working directory missing' }
$admins = New-Object Security.Principal.SecurityIdentifier('S-1-5-32-544')
$fileSecurity = New-Object Security.AccessControl.FileSecurity
$fileSecurity.SetOwner($admins)
# Children inherit the protected receipt directory DACL at creation.
function Write-New([string]$Name,[byte[]]$Data) {
    $path = [IO.Path]::Combine($receipts,$Name)
    $out = New-Object IO.FileStream($path,[IO.FileMode]::CreateNew,
        [Security.AccessControl.FileSystemRights]::Write,[IO.FileShare]::Read,4096,[IO.FileOptions]::None,$fileSecurity)
    try { $out.Write($Data,0,$Data.Length); $out.Flush($true) }
    finally { $out.Dispose() }
}
function Write-Receipt([string]$Name,[object]$Value) {
    $data = $utf8.GetBytes(($Value | ConvertTo-Json -Depth 8 -Compress))
    if ($data.Length -gt 65536) { throw 'Oversized receipt' }
    Write-New $Name $data
}
# Atomic request claim and durable exact approved bytes BEFORE executing anything.
Write-Receipt ($RequestId + '.start.json') @{
    version=1; request_id=$RequestId; operation='elevated_commands'; status='started';
    request_sha256=$digest; helper_sha256=$helperHash; operator_sid=$identity.User.Value;
    started_at_utc=[DateTime]::UtcNow.ToString('o'); timeout=$request.timeout; deadline_unix=$DeadlineUnix
}
Write-New ($RequestId + '.approved.json') $bytes
$scriptPath = [IO.Path]::Combine($receipts,($RequestId + '.payload.ps1'))
$bomUtf8 = New-Object Text.UTF8Encoding($true)
Write-New ($RequestId + '.payload.ps1') ([byte[]]($bomUtf8.GetPreamble() + $bomUtf8.GetBytes($request.script)))
function Command-Arguments([string]$ScriptPath) {
    $quoted = "'" + $ScriptPath.Replace("'","''") + "'"
    $bootstrap = '[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false); ' +
        '$OutputEncoding = [Console]::OutputEncoding; & ' + $quoted +
        '; $ok = $?; if ($null -ne $LASTEXITCODE -and $LASTEXITCODE -ne 0) { exit $LASTEXITCODE }; ' +
        'if (-not $ok) { exit 1 }; exit 0'
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($bootstrap))
    return '-NoProfile -NonInteractive -ExecutionPolicy RemoteSigned -EncodedCommand ' + $encoded
}
$result = @{version=1; request_id=$RequestId; operation='elevated_commands'; request_sha256=$digest;
    helper_sha256=$helperHash; status='outcome_unknown'; executed=$false; effects_verified=$false;
    exit_code=$null; stdout=''; stderr=''; output_truncated=$false; retry_authorized=$false}
try {
    # Kill-on-close process containment. External services/VMs/tasks are NOT contained.
    Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.Text;
using System.Threading.Tasks;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
public static class CommandWatchdog {
    [StructLayout(LayoutKind.Sequential)] struct Basic {
        public long ProcessTime, JobTime; public uint Flags;
        public UIntPtr Min, Max; public uint Active; public UIntPtr Affinity; public uint Priority, Scheduling;
    }
    [StructLayout(LayoutKind.Sequential)] struct IO { public ulong A,B,C,D,E,F; }
    [StructLayout(LayoutKind.Sequential)] struct Limits {
        public Basic Basic; public IO IO; public UIntPtr ProcessMemory,JobMemory,PeakProcess,PeakJob;
    }
    [StructLayout(LayoutKind.Sequential)] struct Security { public int Size; public IntPtr Descriptor; public int Inherit; }
    [StructLayout(LayoutKind.Sequential,CharSet=CharSet.Unicode)] struct Startup {
        public uint Size; public string Reserved,Desktop,Title; public uint X,Y,XS,YS,XC,YC,Fill,Flags;
        public ushort Show,ReservedSize; public IntPtr ReservedPtr,In,Out,Error;
    }
    [StructLayout(LayoutKind.Sequential)] struct ProcessInfo { public IntPtr Process,Thread; public uint Id,ThreadId; }
    [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)] static extern IntPtr CreateJobObject(IntPtr a,string n);
    [DllImport("kernel32.dll",SetLastError=true)] static extern bool SetInformationJobObject(IntPtr j,int k,ref Limits l,uint n);
    [DllImport("kernel32.dll",SetLastError=true)] static extern bool CreatePipe(out IntPtr r,out IntPtr w,ref Security s,uint n);
    [DllImport("kernel32.dll",SetLastError=true)] static extern bool SetHandleInformation(IntPtr h,uint m,uint f);
    [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)] static extern IntPtr CreateFile(string n,uint a,uint s,ref Security sa,uint c,uint f,IntPtr t);
    [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)] static extern bool CreateProcess(string a,StringBuilder c,IntPtr pa,IntPtr ta,bool inherit,uint flags,IntPtr env,string cwd,ref Startup s,out ProcessInfo p);
    [DllImport("kernel32.dll",SetLastError=true)] static extern bool AssignProcessToJobObject(IntPtr j,IntPtr p);
    [DllImport("kernel32.dll",SetLastError=true)] static extern uint ResumeThread(IntPtr t);
    [DllImport("kernel32.dll")] static extern uint WaitForSingleObject(IntPtr p,uint ms);
    [DllImport("kernel32.dll")] static extern bool GetExitCodeProcess(IntPtr p,out uint c);
    [DllImport("kernel32.dll")] static extern bool TerminateProcess(IntPtr p,uint c);
    [DllImport("kernel32.dll")] static extern bool TerminateJobObject(IntPtr j,uint c);
    [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr h);
    public sealed class Dump { public string Text; public bool Truncated; }
    public sealed class Answer { public int Code; public bool Timeout; public bool Truncated; public string Stdout,Stderr; }
    static Task<Dump> Drain(IntPtr h) {
        return Task.Run(() => {
            using (var file = new FileStream(new SafeFileHandle(h,true),FileAccess.Read))
            using (var kept = new MemoryStream()) {
                byte[] buffer = new byte[4096]; int count; bool truncated=false;
                while ((count=file.Read(buffer,0,buffer.Length)) != 0) {
                    int take=Math.Min(count,25000-(int)kept.Length);
                    if (take>0) kept.Write(buffer,0,take);
                    if (take<count) truncated=true;
                }
                string text=Encoding.UTF8.GetString(kept.ToArray());
                if (text.Length>4000) { int end=4000; if (Char.IsHighSurrogate(text[end-1])) end--; text=text.Substring(0,end); truncated=true; }
                return new Dump { Text=text,Truncated=truncated };
            }
        });
    }
    public static Answer Run(string exe,string args,string cwd,uint ms) {
        IntPtr job=IntPtr.Zero,or=IntPtr.Zero,ow=IntPtr.Zero,er=IntPtr.Zero,ew=IntPtr.Zero,input=IntPtr.Zero;
        ProcessInfo p=new ProcessInfo(); Task<Dump> stdout=null,stderr=null;
        try {
            job=CreateJobObject(IntPtr.Zero,null);
            if (job==IntPtr.Zero) throw new Exception("Cannot create watchdog");
            Limits l=new Limits(); l.Basic.Flags=0x2000;
            if (!SetInformationJobObject(job,9,ref l,(uint)Marshal.SizeOf(l))) throw new Exception("Cannot contain process");
            Security sa=new Security(); sa.Size=Marshal.SizeOf(sa); sa.Inherit=1;
            if (!CreatePipe(out or,out ow,ref sa,0) || !CreatePipe(out er,out ew,ref sa,0) ||
                !SetHandleInformation(or,1,0) || !SetHandleInformation(er,1,0)) throw new Exception("Cannot create output pipes");
            input=CreateFile("NUL",0x80000000,3,ref sa,3,0,IntPtr.Zero);
            if (input==new IntPtr(-1)) { input=IntPtr.Zero; throw new Exception("Cannot disable input"); }
            Startup s=new Startup(); s.Size=(uint)Marshal.SizeOf(s); s.Flags=0x100; s.In=input; s.Out=ow; s.Error=ew;
            if (!CreateProcess(exe,new StringBuilder("\""+exe+"\" "+args),IntPtr.Zero,IntPtr.Zero,true,0x08000004,IntPtr.Zero,cwd,ref s,out p))
                throw new Exception("Cannot create suspended command");
            CloseHandle(ow); ow=IntPtr.Zero; CloseHandle(ew); ew=IntPtr.Zero;
            stdout=Drain(or); or=IntPtr.Zero; stderr=Drain(er); er=IntPtr.Zero;
            if (!AssignProcessToJobObject(job,p.Process)) { TerminateProcess(p.Process,2); throw new Exception("Cannot assign watchdog"); }
            if (ResumeThread(p.Thread)==0xffffffff) throw new Exception("Cannot resume command");
            uint wait=WaitForSingleObject(p.Process,ms); bool timeout=wait==258; uint code=0;
            if (timeout) {
                if (!TerminateJobObject(job,124) || WaitForSingleObject(p.Process,5000)!=0) throw new Exception("Termination unknown");
                code=124;
            } else if (wait!=0 || !GetExitCodeProcess(p.Process,out code)) throw new Exception("Completion unknown");
            CloseHandle(job); job=IntPtr.Zero;
            if (!Task.WaitAll(new Task[]{stdout,stderr},5000)) throw new Exception("Output completion unknown");
            return new Answer { Code=unchecked((int)code),Timeout=timeout,
                Stdout=stdout.Result.Text,Stderr=stderr.Result.Text,
                Truncated=stdout.Result.Truncated || stderr.Result.Truncated };
        } finally {
            if (job!=IntPtr.Zero) CloseHandle(job);
            if (p.Thread!=IntPtr.Zero) CloseHandle(p.Thread);
            if (p.Process!=IntPtr.Zero) { TerminateProcess(p.Process,2); CloseHandle(p.Process); }
            foreach (IntPtr h in new IntPtr[]{or,ow,er,ew,input}) if (h!=IntPtr.Zero) CloseHandle(h);
        }
    }
}
'@
    $remaining = $DeadlineUnix - [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    if ($remaining -le 0) { throw 'Approval expired before command launch' }
    $ms = [uint32]([Math]::Min($remaining,[int]$request.timeout) * 1000)
    # Mark launch uncertainty before the native call; only a returned answer proves completion.
    $result.executed = $null
    $answer = [CommandWatchdog]::Run($exe,
        (Command-Arguments $scriptPath),$request.cwd,$ms)
    $result.executed = $true
    $result.exit_code = $answer.Code; $result.stdout = $answer.Stdout; $result.stderr = $answer.Stderr
    $result.output_truncated = $answer.Truncated
    $result.status = if ($answer.Timeout) { 'timeout_outcome_unknown' } elseif ($answer.Code -eq 0) { 'completed' } else { 'failed' }
} catch {
    $result.status = 'outcome_unknown'
} finally {
    $result.finished_at_utc = [DateTime]::UtcNow.ToString('o')
    Write-Receipt ($RequestId + '.result.json') $result
}
if ($result.status -eq 'completed') { exit 0 }
exit 2
