param(
    [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{32}$')][string]$RequestId,
    [Parameter(Mandatory=$true)][long]$DeadlineUnix,
    [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{64}$')][string]$RequestSha256,
    [long]$PreparationPipe=0, [long]$PreparationOwner=0,
    [long]$ExecutionQpcLimit=0, [long]$ExecutionQpcFrequency=0,
    [ValidateRange(0,1)][int]$BootstrapSupervised=0, [int]$BootstrapTimeout=0
)
# Internal inherited cancellation handles, NEVER code or approval authority.
$inheritedFrame = $PreparationPipe -ne 0 -or $PreparationOwner -ne 0
$preparationWorker = $inheritedFrame -and $BootstrapSupervised -eq 0
$bootstrapWorker = $inheritedFrame -and $BootstrapSupervised -eq 1
if (($inheritedFrame -and ($PreparationPipe -le 0 -or $PreparationOwner -le 0 -or
    $PreparationPipe -eq $PreparationOwner -or $ExecutionQpcLimit -le 0 -or $ExecutionQpcFrequency -le 0)) -or
    (-not $inheritedFrame -and ($ExecutionQpcLimit -ne 0 -or $ExecutionQpcFrequency -ne 0)) -or
    ($BootstrapSupervised -eq 1 -and -not $bootstrapWorker) -or
    ($bootstrapWorker -and ($BootstrapTimeout -lt 1 -or $BootstrapTimeout -gt 900)) -or
    (-not $bootstrapWorker -and $BootstrapTimeout -ne 0)) {
    throw 'Invalid inherited preparation frame'
}
# GENERAL ADMINISTRATOR EXECUTION. Protected installation only. Not a sandbox.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
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
if ($policy.version -ne 1 -or $policy.max_timeout -ne 900 -or $policy.lifetime_protocol -ne 1 -or $policy.preparation_protocol -ne 1 -or
    $policy.setup_preload_protocol -ne 1 -or $policy.preparation_supervision_protocol -ne 1 -or
    $policy.helper_sha256 -cne $helperHash -or $policy.operator_sid -cne $identity.User.Value) {
    throw 'Installed policy/code/operator mismatch'
}
$bootstrapPolicy = $null -ne $policy.PSObject.Properties['bootstrap_supervision_protocol']
if ($bootstrapPolicy -and ($policy.bootstrap_supervision_protocol -isnot [int] -or $policy.bootstrap_supervision_protocol -ne 1 -or
    $policy.bootstrap_sha256 -isnot [string] -or $policy.bootstrap_sha256 -cnotmatch '^[0-9a-f]{64}$' -or
    (-not $bootstrapWorker -and -not $preparationWorker))) { throw 'Supervised bootstrap deployment required' }
if ($bootstrapWorker -and -not $bootstrapPolicy) { throw 'Bootstrap policy unavailable' }
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
$fields = @('version','request_id','operation','deadline_unix','timeout','script','cwd','reason','operator_sid','helper_sha256','lifetime')
if ($null -ne $request.PSObject.Properties['setup_preload']) { $fields += 'setup_preload' }
if ($bootstrapPolicy) { $fields += 'bootstrap_sha256' }
if ($bootstrapPolicy -and ($request.bootstrap_sha256 -cne $policy.bootstrap_sha256 -or
    ($bootstrapWorker -and $BootstrapTimeout -ne $request.timeout))) { throw 'Approved bootstrap binding differs' }
if (@(Compare-Object $fields @($request.PSObject.Properties.Name)).Count -ne 0 -or
    $request.version -ne 1 -or $request.request_id -cne $RequestId -or
    $request.operation -cne 'elevated_commands' -or $request.deadline_unix -ne $DeadlineUnix -or
    $request.operator_sid -cne $identity.User.Value -or $request.helper_sha256 -cne $helperHash -or
    $request.timeout -isnot [int] -or $request.timeout -lt 1 -or $request.timeout -gt $policy.max_timeout -or
    $request.script -isnot [string] -or [string]::IsNullOrWhiteSpace($request.script) -or
    $request.script.Contains([string][char]0) -or $utf8.GetByteCount($request.script) -gt 32768 -or
    $request.reason -isnot [string] -or [string]::IsNullOrWhiteSpace($request.reason) -or
    $request.reason.Length -gt 2000 -or $request.cwd -isnot [string]) { throw 'Invalid approved request schema' }
$lifetimeFields = @('version','pipe','owner_pid','owner_created')
if ($null -eq $request.lifetime -or @(Compare-Object $lifetimeFields @($request.lifetime.PSObject.Properties.Name)).Count -ne 0 -or
    $request.lifetime.version -ne 1 -or $request.lifetime.pipe -isnot [string] -or
    ($request.lifetime.owner_pid -isnot [int] -and $request.lifetime.owner_pid -isnot [long]) -or
    $request.lifetime.owner_pid -lt 1 -or $request.lifetime.owner_pid -gt [uint32]::MaxValue -or
    $request.lifetime.owner_created -isnot [string]) { throw 'Caller lifetime binding required' }
Check-Local $request.cwd
if (-not [IO.Directory]::Exists($request.cwd)) { throw 'Working directory missing' }
function New-ProtectedFileSecurity([string]$OperatorSid) {
    if ($OperatorSid -cnotmatch '^S-1-5-21-\d+-\d+-\d+-\d+$') { throw 'Invalid operator SID' }
    $acl = New-Object Security.AccessControl.FileSecurity
    # Owner-only FileSecurity creates a protected EMPTY DACL, not inherited access.
    $acl.SetSecurityDescriptorSddlForm(
        ('O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;FRFX;;;' + $OperatorSid + ')'))
    return $acl
}
$fileSecurity = New-ProtectedFileSecurity $identity.User.Value
# Give every claim, snapshot, payload and result its explicit protected file DACL.
function Write-New([string]$Name,[byte[]]$Data,[bool]$GuardPreparation=$true) {
    if ($GuardPreparation) { $preparation.Check() }
    $path = [IO.Path]::Combine($receipts,$Name)
    $out = New-Object IO.FileStream($path,[IO.FileMode]::CreateNew,
        [Security.AccessControl.FileSystemRights]::Write,[IO.FileShare]::Read,4096,[IO.FileOptions]::None,$fileSecurity)
    try {
        if ($GuardPreparation) { $preparation.Check() }
        $out.Write($Data,0,$Data.Length); $out.Flush($true)
        if ($GuardPreparation) { $preparation.Check() }
    } finally { $out.Dispose() }
    $sections = [Security.AccessControl.AccessControlSections]'Owner,Group,Access'
    $actual = Get-Acl -LiteralPath $path -ErrorAction Stop
    if ($actual.GetSecurityDescriptorSddlForm($sections) -cne
        $fileSecurity.GetSecurityDescriptorSddlForm($sections)) {
        throw 'Created file security differs from the protected descriptor; retain for review'
    }
    if ($GuardPreparation) { $preparation.Check() }
}
function Write-Receipt([string]$Name,[object]$Value,[bool]$GuardPreparation=$true) {
    $data = $utf8.GetBytes(($Value | ConvertTo-Json -Depth 8 -Compress))
    if ($data.Length -gt 65536) { throw 'Oversized receipt' }
    Write-New $Name $data $GuardPreparation
}
# Capture the ORIGINAL execution window BEFORE claims, snapshots or compilation.
# This protected monotonic record may only shorten the later native worker wait.
$qpcFrequency = [Diagnostics.Stopwatch]::Frequency
$qpcFirst = [Diagnostics.Stopwatch]::GetTimestamp()
$qpcWall = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
$executionSeconds = [Math]::Min([int]$request.timeout, ($DeadlineUnix - $qpcWall / 1000.0))
if ($qpcFrequency -lt 1 -or $qpcFrequency -gt 1000000000 -or $qpcFirst -lt 1 -or $executionSeconds -le 0) {
    throw 'Original execution window unavailable'
}
$qpcLimit = [long]([decimal]$qpcFirst + [Math]::Floor([decimal]$executionSeconds * $qpcFrequency))
if ($inheritedFrame) {
    if ($ExecutionQpcFrequency -ne $qpcFrequency) { throw 'Inherited execution clock differs' }
    $qpcLimit = [Math]::Min($qpcLimit,$ExecutionQpcLimit)
}
if ($qpcLimit -le $qpcFirst) { throw 'Original execution window expired' }
# No durable preparation or payload before the SAME native lifetime is acquired.
# A reviewed precompiled bootstrap supervises this WHOLE helper when deployed.
# Legacy general entry remains distinct. The bootstrap's own OS/CLR/module load
# is an external trust prerequisite, not authenticated by this helper.
$preparation = $null
$scriptPath = [IO.Path]::Combine($receipts,($RequestId + '.payload.ps1'))
function Command-Arguments([string]$ScriptPath) {
    $quoted = "'" + $ScriptPath.Replace("'","''") + "'"
    $bootstrap = '$ProgressPreference = ''SilentlyContinue''; [Console]::OutputEncoding = New-Object Text.UTF8Encoding($false); ' +
        '$OutputEncoding = [Console]::OutputEncoding; & ' + $quoted +
        '; $ok = $?; if ($null -ne $LASTEXITCODE -and $LASTEXITCODE -ne 0) { exit $LASTEXITCODE }; ' +
        'if (-not $ok) { exit 1 }; exit 0'
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($bootstrap))
    return '-NoProfile -NonInteractive -ExecutionPolicy RemoteSigned -EncodedCommand ' + $encoded
}
$result = @{version=1; request_id=$RequestId; operation='elevated_commands'; request_sha256=$digest;
    helper_sha256=$helperHash; status='outcome_unknown'; executed=$false; effects_verified=$false; process_tree_observed=$false; lifetime_observed=$false; preparation_observed=$false; setup_preload_observed=$false; preparation_supervision_observed=$false;
    bootstrap_frame_observed=$false; bootstrap_sha256=$null;
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
    [StructLayout(LayoutKind.Sequential)] struct StartupEx { public Startup Startup; public IntPtr Attributes; }
    [StructLayout(LayoutKind.Sequential)] struct ProcessInfo { public IntPtr Process,Thread; public uint Id,ThreadId; }
    [StructLayout(LayoutKind.Sequential)] struct Accounting {
        public long User,Kernel,PeriodUser,PeriodKernel; public uint Faults,Total,Active,Terminated;
    }
    [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)] static extern IntPtr CreateJobObject(IntPtr a,string n);
    [DllImport("kernel32.dll",SetLastError=true)] static extern bool SetInformationJobObject(IntPtr j,int k,ref Limits l,uint n);
    [DllImport("kernel32.dll",SetLastError=true)] static extern bool CreatePipe(out IntPtr r,out IntPtr w,ref Security s,uint n);
    [DllImport("kernel32.dll",SetLastError=true)] static extern bool SetHandleInformation(IntPtr h,uint m,uint f);
    [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)] static extern IntPtr CreateFile(string n,uint a,uint s,ref Security sa,uint c,uint f,IntPtr t);
    [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)] static extern bool CreateProcess(string a,StringBuilder c,IntPtr pa,IntPtr ta,bool inherit,uint flags,IntPtr env,string cwd,ref StartupEx s,out ProcessInfo p);
    [DllImport("kernel32.dll",SetLastError=true)] static extern bool InitializeProcThreadAttributeList(IntPtr a,int count,uint flags,ref UIntPtr bytes);
    [DllImport("kernel32.dll",SetLastError=true)] static extern bool UpdateProcThreadAttribute(IntPtr a,uint flags,UIntPtr key,IntPtr value,UIntPtr bytes,IntPtr previous,IntPtr returned);
    [DllImport("kernel32.dll")] static extern void DeleteProcThreadAttributeList(IntPtr a);
    [DllImport("kernel32.dll")] static extern bool IsProcessInJob(IntPtr p,IntPtr j,out bool member);
    [DllImport("kernel32.dll")] static extern bool GetHandleInformation(IntPtr h,out uint flags);
    [DllImport("kernel32.dll",EntryPoint="QueryInformationJobObject")] static extern bool QueryLimits(IntPtr j,int kind,out Limits info,uint bytes,IntPtr returned);
    [DllImport("kernel32.dll",EntryPoint="QueryInformationJobObject")] static extern bool QueryAccounting(IntPtr j,int kind,out Accounting info,uint bytes,IntPtr returned);
    [DllImport("kernel32.dll",SetLastError=true)] static extern uint ResumeThread(IntPtr t);
    [DllImport("kernel32.dll")] static extern uint WaitForSingleObject(IntPtr p,uint ms);
    [DllImport("kernel32.dll")] static extern bool GetExitCodeProcess(IntPtr p,out uint c);
    [DllImport("kernel32.dll")] static extern bool TerminateJobObject(IntPtr j,uint c);
    [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr h);
    public sealed class Dump { public string Text; public bool Truncated; }
    // Process observations only; never external-service/VM/effect verification.
    public sealed class Answer { public int Code; public bool Timeout,Truncated,ProcessTreeObserved,LifetimeObserved,Cancelled,PreparationObserved,SetupPreloadObserved; public string Stdout,Stderr; }
    [DllImport("kernel32.dll",ExactSpelling=true,SetLastError=true)] static extern bool PeekNamedPipe(IntPtr pipe,IntPtr buffer,uint bytes,IntPtr read,out uint available,IntPtr left);
    [DllImport("kernel32.dll",ExactSpelling=true)] static extern bool GetNamedPipeServerProcessId(IntPtr pipe,out uint pid);
    [DllImport("kernel32.dll",ExactSpelling=true)] static extern IntPtr OpenProcess(uint access,bool inherit,uint pid);
    [DllImport("kernel32.dll",ExactSpelling=true)] static extern bool GetProcessTimes(IntPtr process,out ulong created,out ulong exited,out ulong kernel,out ulong user);
    [DllImport("kernel32.dll",ExactSpelling=true)] static extern uint GetFileType(IntPtr file);
    // Caller-controlled channel can ONLY subtract lifetime. It carries NO code,
    // output, approval, deadline extension or acceptance. Authenticate the native
    // server process identity, not the pipe spelling or a PID alone. Anonymous
    // SQOS prevents the unelevated server impersonating this elevated client.
    internal sealed class Lifetime : IDisposable {
        IntPtr pipe,owner;
        internal Lifetime(string name,uint pid,string created,string requestId) {
            try {
                string prefix=@"\\.\pipe\AiAgentCommandLease-v1-"+requestId+"-";
                ulong expected;
                if (pid==0 || requestId==null || !System.Text.RegularExpressions.Regex.IsMatch(requestId,@"\A[0-9a-f]{32}\z") ||
                    name==null || !name.StartsWith(prefix,StringComparison.Ordinal) ||
                    !System.Text.RegularExpressions.Regex.IsMatch(name.Substring(prefix.Length),@"\A[0-9a-f]{32}\z") ||
                    !UInt64.TryParse(created,System.Globalization.NumberStyles.None,System.Globalization.CultureInfo.InvariantCulture,out expected) ||
                    expected==0 || expected.ToString(System.Globalization.CultureInfo.InvariantCulture)!=created) throw new Exception("Caller lifetime binding refused");
                Security sa=new Security(); sa.Size=Marshal.SizeOf(sa);
                pipe=CreateFile(name,0x80000000,0,ref sa,3,0x00100000,IntPtr.Zero); // SECURITY_SQOS_PRESENT | SECURITY_ANONYMOUS
                if (pipe==IntPtr.Zero || pipe==new IntPtr(-1)) { pipe=IntPtr.Zero; throw new Exception("Caller lifetime pipe unavailable"); }
                uint actual,flags;
                if (GetFileType(pipe)!=3 || !GetNamedPipeServerProcessId(pipe,out actual) || actual!=pid ||
                    !GetHandleInformation(pipe,out flags) || flags!=0) throw new Exception("Caller lifetime server differs");
                owner=OpenProcess(0x101000,false,pid); ulong born,exit,kernel,user;
                if (owner==IntPtr.Zero || !GetProcessTimes(owner,out born,out exit,out kernel,out user) || born!=expected ||
                    !GetHandleInformation(owner,out flags) || flags!=0) throw new Exception("Caller lifetime owner differs");
                if (!Alive()) throw new Exception("Caller lifetime unavailable before creation");
            } catch { Dispose(); throw; }
        }
        // Two explicit inherited read/observation capabilities; no reconnect,
        // process lookup, owning-job handle, or reusable approval capability.
        internal Lifetime(long inheritedPipe,long inheritedOwner,uint pid,string created) {
            if (inheritedPipe<=0 || inheritedOwner<=0 || inheritedPipe==inheritedOwner)
                throw new Exception("Inherited caller handles refused");
            pipe=new IntPtr(inheritedPipe); owner=new IntPtr(inheritedOwner);
            try {
                ulong expected,born,exited,kernel,user; uint actual,flags;
                if (pid==0 || !UInt64.TryParse(created,System.Globalization.NumberStyles.None,System.Globalization.CultureInfo.InvariantCulture,out expected) ||
                    expected==0 || expected.ToString(System.Globalization.CultureInfo.InvariantCulture)!=created ||
                    GetFileType(pipe)!=3 || !GetNamedPipeServerProcessId(pipe,out actual) || actual!=pid || GetProcessId(owner)!=pid ||
                    !GetProcessTimes(owner,out born,out exited,out kernel,out user) || born!=expected)
                    throw new Exception("Inherited caller identity differs");
                foreach (IntPtr handle in new IntPtr[]{pipe,owner}) {
                    if (!GetHandleInformation(handle,out flags) || flags!=1 || !SetHandleInformation(handle,1,0) ||
                        !GetHandleInformation(handle,out flags) || flags!=0) throw new Exception("Inherited caller flags refused");
                }
                Require();
            } catch { Dispose(); throw; }
        }
        internal void CopyForWorker(out IntPtr copyPipe,out IntPtr copyOwner) {
            copyPipe=IntPtr.Zero; copyOwner=IntPtr.Zero; Require(); uint flags;
            IntPtr self=GetCurrentProcess();
            if (!DuplicateHandle(self,pipe,self,out copyPipe,0,true,2) ||
                !DuplicateHandle(self,owner,self,out copyOwner,0,true,2) ||
                !GetHandleInformation(copyPipe,out flags) || flags!=1 ||
                !GetHandleInformation(copyOwner,out flags) || flags!=1) throw new Exception("Caller handle delivery unknown");
        }
        internal bool Alive() {
            uint wait=WaitForSingleObject(owner,0);
            if (wait==0) return false;
            if (wait!=258) throw new Exception("Caller lifetime wait unknown");
            uint available;
            if (!PeekNamedPipe(pipe,IntPtr.Zero,0,IntPtr.Zero,out available,IntPtr.Zero)) {
                int error=Marshal.GetLastWin32Error();
                if (error==109 || error==232 || error==233) return false;
                throw new Exception("Caller lifetime pipe observation unknown");
            }
            if (available!=0) throw new Exception("Caller lifetime data refused");
            return true;
        }
        internal void Require() { if (!Alive()) throw new Exception("Caller lifetime unavailable before creation"); }
        public void Dispose() {
            bool closed=Release(ref pipe); closed=Release(ref owner)&closed;
            if (!closed) throw new Exception("Caller lifetime close unknown");
        }
    }
    [DllImport("kernel32.dll",ExactSpelling=true)] static extern IntPtr GetCurrentProcess();
    [DllImport("kernel32.dll",ExactSpelling=true)] static extern uint GetProcessId(IntPtr process);
    [DllImport("kernel32.dll",ExactSpelling=true)] static extern bool DuplicateHandle(IntPtr source,IntPtr handle,IntPtr target,out IntPtr copy,uint access,bool inherit,uint options);
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
        return RunCore(exe,args,cwd,ms,0,0,null); // historical ordinary characterization API
    }
    static uint Remaining(uint maximum,long limit,long frequency) {
        if (limit<1 || frequency<1 || frequency>1000000000L || frequency!=System.Diagnostics.Stopwatch.Frequency)
            throw new ArgumentOutOfRangeException("originalWindow");
        long now=System.Diagnostics.Stopwatch.GetTimestamp();
        if (now<1 || limit<=now) return 0;
        decimal ms=Decimal.Floor(((decimal)limit-now)*1000/frequency);
        if (ms>900000) throw new ArgumentOutOfRangeException("originalWindow");
        return (uint)Math.Min(maximum,ms);
    }
    public static Answer RunWithin(string exe,string args,string cwd,uint ms,long limit,long frequency) {
        if (limit<1 || frequency<1) throw new ArgumentOutOfRangeException("originalWindow");
        return RunCore(exe,args,cwd,ms,limit,frequency,null);
    }
    public static Answer RunOwned(string exe,string args,string cwd,uint ms,long limit,long frequency,string pipe,uint ownerPid,string created,string requestId) {
        if (limit<1 || frequency<1) throw new ArgumentOutOfRangeException("originalWindow");
        // Bind BEFORE native child preparation; no inherited lifetime handles.
        using (var lifetime=new Lifetime(pipe,ownerPid,created,requestId)) {
            return RunCore(exe,args,cwd,ms,limit,frequency,lifetime);
        }
    }
    // A single-use native owner bridges durable preparation and launch. There
    // is no reconnect, deadline renewal or second executable attempt on failure.
    // Held native pre-load inputs for the FIXED setup operation only. The
    // already-loaded helper/OS/CLR/compiler closure remains an external trust
    // prerequisite. No create, launch, ACL repair, inventory repair or fallback.
    sealed class SetupLease : IDisposable {
        [StructLayout(LayoutKind.Sequential)] struct UnicodeName { internal ushort Length,Maximum; internal IntPtr Buffer; }
        [StructLayout(LayoutKind.Sequential)] struct Attributes { internal uint Length; internal IntPtr Root,Name; internal uint Flags; internal IntPtr Security,Qos; }
        [StructLayout(LayoutKind.Sequential)] struct Status { internal IntPtr Code; internal UIntPtr Information; }
        [StructLayout(LayoutKind.Sequential)] struct Time { internal uint Low,High; }
        [StructLayout(LayoutKind.Sequential)] struct Info {
            internal uint Flags; internal Time Created,Accessed,Written;
            internal uint Volume,SizeHigh,SizeLow,Links,IndexHigh,IndexLow;
        }
        [DllImport("ntdll.dll",ExactSpelling=true)] static extern int NtCreateFile(out IntPtr handle,uint access,ref Attributes attributes,out Status status,IntPtr size,uint flags,uint share,uint disposition,uint options,IntPtr ea,uint eaBytes);
        [DllImport("kernel32.dll",ExactSpelling=true,CharSet=CharSet.Unicode)] static extern uint GetDriveTypeW(string root);
        [DllImport("kernel32.dll",ExactSpelling=true,CharSet=CharSet.Unicode)] static extern bool GetVolumeInformationByHandleW(IntPtr handle,StringBuilder label,uint count,IntPtr serial,IntPtr maximum,IntPtr flags,StringBuilder fs,uint fsCount);
        [DllImport("kernel32.dll",ExactSpelling=true)] static extern bool GetFileInformationByHandle(IntPtr handle,out Info info);
        [DllImport("kernel32.dll",ExactSpelling=true)] static extern bool GetFileInformationByHandleEx(IntPtr handle,int kind,out uint value,uint count);
        [DllImport("kernel32.dll",ExactSpelling=true,CharSet=CharSet.Unicode)] static extern uint GetFinalPathNameByHandleW(IntPtr handle,StringBuilder name,uint count,uint flags);
        [DllImport("kernel32.dll",ExactSpelling=true)] static extern bool SetFilePointerEx(IntPtr handle,long offset,out long position,uint method);
        [DllImport("kernel32.dll",ExactSpelling=true)] static extern bool ReadFile(IntPtr handle,byte[] bytes,uint count,out uint read,IntPtr overlapped);
        [DllImport("advapi32.dll",ExactSpelling=true)] static extern uint GetSecurityInfo(IntPtr handle,int kind,uint sections,out IntPtr owner,out IntPtr group,out IntPtr dacl,IntPtr sacl,out IntPtr descriptor);
        [DllImport("advapi32.dll",ExactSpelling=true)] static extern uint GetSecurityDescriptorLength(IntPtr descriptor);
        [DllImport("kernel32.dll",ExactSpelling=true)] static extern IntPtr LocalFree(IntPtr pointer);
        sealed class Entry {
            internal IntPtr Handle; internal bool Directory,Ancestor;
            internal Info Before; internal string Path,Descriptor,Hash; internal long Bytes;
        }
        const string Admins="S-1-5-32-544",SystemSid="S-1-5-18",Installer="S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464";
        readonly Action check;
        readonly System.Collections.Generic.List<Entry> entries=new System.Collections.Generic.List<Entry>();
        readonly System.Collections.Generic.HashSet<string> identities=new System.Collections.Generic.HashSet<string>(StringComparer.Ordinal);
        bool disposed;
        static Exception Refused() { return new Exception("Native setup pre-load refused"); }
        static ulong Index(Info info) { return ((ulong)info.IndexHigh<<32)|info.IndexLow; }
        static long Extent(Info info) {
            ulong bytes=((ulong)info.SizeHigh<<32)|info.SizeLow;
            if (bytes>Int64.MaxValue) throw Refused(); return (long)bytes;
        }
        static string Final(IntPtr handle) {
            var name=new StringBuilder(512); uint n=GetFinalPathNameByHandleW(handle,name,512,1);
            if (n<1 || n>=512) throw Refused(); return name.ToString();
        }
        static string Descriptor(IntPtr handle,bool directory,bool ancestor) {
            IntPtr owner,group,dacl,descriptor;
            uint error=GetSecurityInfo(handle,1,7,out owner,out group,out dacl,IntPtr.Zero,out descriptor);
            try {
                if (error!=0 || descriptor==IntPtr.Zero || owner==IntPtr.Zero || group==IntPtr.Zero || dacl==IntPtr.Zero) throw Refused();
                uint length=GetSecurityDescriptorLength(descriptor);
                if (length<20 || length>65536) throw Refused();
                byte[] raw=new byte[(int)length]; Marshal.Copy(descriptor,raw,0,raw.Length);
                var sd=new System.Security.AccessControl.RawSecurityDescriptor(raw,0);
                var acl=sd.DiscretionaryAcl;
                if (sd.Owner==null || (sd.Owner.Value!=Admins && sd.Owner.Value!=SystemSid && (!ancestor || sd.Owner.Value!=Installer)) ||
                    (sd.ControlFlags&System.Security.AccessControl.ControlFlags.DiscretionaryAclPresent)==0 || acl==null || acl.Count<1 || acl.Count>128) throw Refused();
                var remaining=new System.Collections.Generic.HashSet<string>(new string[]{Admins,SystemSid},StringComparer.Ordinal);
                if (!ancestor && ((sd.ControlFlags&System.Security.AccessControl.ControlFlags.DiscretionaryAclProtected)==0 ||
                    sd.Group==null || sd.Group.Value!=Admins || acl.Count!=2)) throw Refused();
                foreach (System.Security.AccessControl.GenericAce value in acl) {
                    var ace=value as System.Security.AccessControl.CommonAce;
                    if (ace==null || ace.IsCallback || (ace.AceType!=System.Security.AccessControl.AceType.AccessAllowed &&
                        ace.AceType!=System.Security.AccessControl.AceType.AccessDenied) || ((int)ace.AceFlags&~31)!=0) throw Refused();
                    string sid=ace.SecurityIdentifier.Value;
                    if (!ancestor) {
                        if (ace.AceType!=System.Security.AccessControl.AceType.AccessAllowed || (int)ace.AceFlags!=(directory?3:0) ||
                            ace.AccessMask!=0x1f01ff || !remaining.Remove(sid)) throw Refused();
                    } else if (((int)ace.AceFlags&8)==0 && ace.AceType==System.Security.AccessControl.AceType.AccessAllowed &&
                        sid!=Admins && sid!=SystemSid && sid!=Installer &&
                        (unchecked((uint)ace.AccessMask)&~(0x1200a9u|2u|4u|0x80000000u|0x20000000u))!=0) throw Refused();
                }
                return sd.GetSddlForm(System.Security.AccessControl.AccessControlSections.Owner|
                    System.Security.AccessControl.AccessControlSections.Group|System.Security.AccessControl.AccessControlSections.Access);
            } finally {
                if (descriptor!=IntPtr.Zero && LocalFree(descriptor)!=IntPtr.Zero) throw new Exception("Native setup security release unknown");
            }
        }
        Info Observe(Entry e) {
            check(); Info info; uint flags;
            if (e.Handle==IntPtr.Zero || GetFileType(e.Handle)!=1 || !GetFileInformationByHandle(e.Handle,out info) ||
                Index(info)==0 || info.Links!=1 || (info.Flags&0x5e00)!=0 || ((info.Flags&16)!=0)!=e.Directory ||
                !GetHandleInformation(e.Handle,out flags) || flags!=0) throw Refused();
            if (e.Directory && (!GetFileInformationByHandleEx(e.Handle,23,out flags,4) || flags!=0)) throw Refused();
            Extent(info); return info;
        }
        Entry Own(IntPtr handle,bool directory,bool ancestor,string path,uint? volume) {
            if (handle==IntPtr.Zero || handle==new IntPtr(-1)) throw Refused();
            var e=new Entry {Handle=handle,Directory=directory,Ancestor=ancestor}; entries.Add(e);
            e.Before=Observe(e); e.Path=Final(handle); e.Descriptor=Descriptor(handle,directory,ancestor);
            if ((path!=null && e.Path!=path) || (volume.HasValue && e.Before.Volume!=volume.Value) ||
                !identities.Add(e.Before.Volume.ToString(System.Globalization.CultureInfo.InvariantCulture)+":"+Index(e.Before).ToString(System.Globalization.CultureInfo.InvariantCulture))) throw Refused();
            return e;
        }
        void Match(Entry e) {
            Info info=Observe(e);
            if (info.Volume!=e.Before.Volume || Index(info)!=Index(e.Before) || info.Flags!=e.Before.Flags || info.Links!=e.Before.Links ||
                (!e.Directory && Extent(info)!=Extent(e.Before)) || Final(e.Handle)!=e.Path || Descriptor(e.Handle,e.Directory,e.Ancestor)!=e.Descriptor) throw Refused();
            check();
        }
        Entry Open(Entry parent,string name,bool directory,bool ancestor) {
            if (name==null || name.Length<1 || name.Length>120 || name=="." || name==".." || name.EndsWith(".",StringComparison.Ordinal) ||
                name.EndsWith(" ",StringComparison.Ordinal) || name.IndexOfAny(new char[]{'\\','/',':','\0','\r','\n','"','*','?','<','>','|'})>=0) throw Refused();
            Match(parent); IntPtr buffer=IntPtr.Zero,text=IntPtr.Zero,handle=IntPtr.Zero;
            try {
                buffer=Marshal.StringToHGlobalUni(name);
                var unicode=new UnicodeName {Length=(ushort)(name.Length*2),Maximum=(ushort)((name.Length+1)*2),Buffer=buffer};
                text=Marshal.AllocHGlobal(Marshal.SizeOf(typeof(UnicodeName))); Marshal.StructureToPtr(unicode,text,false);
                var attributes=new Attributes {Length=(uint)Marshal.SizeOf(typeof(Attributes)),Root=parent.Handle,Name=text,Flags=0x1040};
                Status status;
                int result=NtCreateFile(out handle,directory?0x1200a1u:0x80120080u,ref attributes,out status,IntPtr.Zero,0,
                    directory?3u:1u,1,directory?0x200021u:0x200060u,IntPtr.Zero,0);
                if (result!=0 || status.Information.ToUInt64()!=1) throw Refused();
                IntPtr owned=handle; handle=IntPtr.Zero;
                Entry e=Own(owned,directory,ancestor,parent.Path.TrimEnd('\\')+"\\"+name,parent.Before.Volume); Match(parent); return e;
            } finally { bool closed=Release(ref handle); Free(ref text); Free(ref buffer); if (!closed) throw new Exception("Native setup handle close unknown"); }
        }
        void Pin(Entry e) {
            Match(e); if (Extent(e.Before)!=e.Bytes) throw Refused();
            long position;
            if (!SetFilePointerEx(e.Handle,0,out position,0) || position!=0) throw Refused();
            using (var sha=System.Security.Cryptography.SHA256.Create()) {
                byte[] buffer=new byte[65536]; long total=0; uint read;
                for (;;) {
                    check();
                    if (!ReadFile(e.Handle,buffer,(uint)buffer.Length,out read,IntPtr.Zero) || read>buffer.Length) throw Refused();
                    if (read==0) break;
                    total+=read; if (total>e.Bytes) throw Refused();
                    sha.TransformBlock(buffer,0,(int)read,buffer,0);
                }
                sha.TransformFinalBlock(new byte[0],0,0);
                if (total!=e.Bytes || BitConverter.ToString(sha.Hash).Replace("-","").ToLowerInvariant()!=e.Hash) throw Refused();
            }
            Match(e);
        }
        internal SetupLease(Action guard,string root,uint volume,ulong[] indices,string[] names,long[] lengths,string[] hashes) {
            check=guard;
            try {
                if (root==null || root.Length>240 || !System.Text.RegularExpressions.Regex.IsMatch(root,@"\A[A-Z]:\\") ||
                    System.IO.Path.GetFullPath(root)!=root || root.EndsWith("\\",StringComparison.Ordinal) ||
                    indices==null || indices.Length!=4 || new System.Collections.Generic.HashSet<ulong>(indices).Count!=4 || Array.IndexOf(indices,0ul)>=0 ||
                    names==null || (names.Length!=5 && names.Length!=6) || lengths==null || lengths.Length!=names.Length || hashes==null || hashes.Length!=names.Length) throw Refused();
                string[] fixedNames=new string[]{"policy.json","validator-setup-host.exe","validator-setup-host.exe.config","validator-setup-watchdog.exe","validator-setup-watchdog.exe.config","setup.packet"};
                for (int i=0;i<names.Length;i++) {
                    long maximum=i==0?1024:((i==2 || i==4)?4096:(i==5?33554432:16777216));
                    if (names[i]!=fixedNames[i] || lengths[i]<1 || lengths[i]>maximum || hashes[i]==null ||
                        !System.Text.RegularExpressions.Regex.IsMatch(hashes[i],@"\A[0-9a-f]{64}\z")) throw Refused();
                }
                check(); string drive=root.Substring(0,3);
                if (GetDriveTypeW(drive)!=3) throw Refused();
                Security sa=new Security(); sa.Size=Marshal.SizeOf(sa);
                Entry parent=Own(CreateFile(drive,0x1200a1,3,ref sa,3,0x02200000,IntPtr.Zero),true,true,null,volume);
                var fs=new StringBuilder(32);
                if (!GetVolumeInformationByHandleW(parent.Handle,null,0,IntPtr.Zero,IntPtr.Zero,IntPtr.Zero,fs,32) || fs.ToString()!="NTFS" ||
                    !System.Text.RegularExpressions.Regex.IsMatch(parent.Path,@"\A\\\\\?\\Volume\{[0-9a-fA-F-]{36}\}\\\z")) throw Refused();
                string[] parts=root.Substring(3).Split('\\');
                for (int i=0;i<parts.Length;i++) parent=Open(parent,parts[i],true,i+1!=parts.Length);
                if (Index(parent.Before)!=indices[0]) throw Refused();
                string[] directories=new string[]{"claims","receipts","scratch"};
                for (int i=0;i<directories.Length;i++) if (Index(Open(parent,directories[i],true,false).Before)!=indices[i+1]) throw Refused();
                for (int i=0;i<names.Length;i++) {
                    Entry e=Open(parent,names[i],false,false); e.Bytes=lengths[i]; e.Hash=hashes[i]; Pin(e);
                }
                Verify();
            } catch { Dispose(); throw; }
        }
        internal void Verify() {
            if (disposed) throw Refused();
            foreach (Entry e in entries) { if (e.Hash==null) Match(e); else Pin(e); } check();
        }
        public void Dispose() {
            if (disposed) return; disposed=true; bool closed=true;
            for (int i=entries.Count-1;i>=0;i--) closed=Release(ref entries[i].Handle)&closed;
            if (!closed) throw new Exception("Native setup handle close unknown");
        }
    }
    public sealed class Preparation : IDisposable {
        Lifetime lifetime;
        SetupLease setup;
        bool setupAttempted;
        readonly uint ms;
        readonly long limit,frequency,deadline;
        long lastQpc,lastWall;
        bool spent,disposed,failed;
        internal Preparation(uint maximum,long cap,long rate,long deadlineUnix,string pipe,uint pid,string created,string id,Lifetime inherited=null) {
            if (maximum==0 || maximum>900000 || deadlineUnix<1 || deadlineUnix>253402300799L)
                throw new ArgumentOutOfRangeException("preparationWindow");
            ms=maximum; frequency=rate; deadline=deadlineUnix;
            lastQpc=System.Diagnostics.Stopwatch.GetTimestamp();
            lastWall=DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            // Validate the incoming clock domain, then only SHORTEN its cap.
            Remaining(ms,cap,frequency);
            limit=Math.Min(cap,checked(lastQpc+(long)Decimal.Floor((decimal)ms*frequency/1000)));
            if (Remaining(ms,limit,frequency)==0 || (decimal)lastWall>=(decimal)deadline*1000)
                throw new Exception("Preparation window unavailable");
            lifetime=inherited ?? new Lifetime(pipe,pid,created,id);
            try { Observe(); } catch { Dispose(); throw; }
        }
        void Observe() {
            if (disposed || failed) throw new Exception("Preparation owner unavailable");
            try {
                long now=System.Diagnostics.Stopwatch.GetTimestamp(),wall=DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
                if (now<lastQpc || wall<lastWall || Remaining(ms,limit,frequency)==0 || (decimal)wall>=(decimal)deadline*1000)
                    throw new Exception("Preparation window unavailable");
                lastQpc=now; lastWall=wall; lifetime.Require();
            } catch { failed=true; throw; }
        }
        public void Check() {
            if (spent) throw new Exception("Preparation already consumed");
            Observe();
        }
        public void HoldSetup(string root,uint volume,ulong[] indices,string[] names,long[] lengths,string[] hashes) {
            Check(); if (setupAttempted) throw new Exception("Native setup pre-load already consumed");
            setupAttempted=true;
            try { setup=new SetupLease(Observe,root,volume,indices,names,lengths,hashes); }
            catch { failed=true; throw; }
        }
        internal Answer Run(string exe,string args,string cwd,bool deliver=false) {
            if (spent) throw new Exception("Preparation already consumed");
            spent=true; // uncertainty BEFORE observation or native entry
            Observe();
            if (setup!=null) setup.Verify();
            Answer answer=RunCore(exe,args,cwd,ms,limit,frequency,lifetime,deliver);
            // RunCore already observes cancellation/deadline termination. A
            // later loss cannot promote normal completion into acceptance.
            if (!answer.Cancelled && !answer.Timeout) { Observe(); if (setup!=null) setup.Verify(); }
            answer.SetupPreloadObserved=setup!=null;
            answer.PreparationObserved=true; return answer;
        }
        public void Dispose() {
            if (disposed) return;
            disposed=true;
            SetupLease files=setup; setup=null;
            Lifetime old=lifetime; lifetime=null;
            // Attempt both release families. Neither uncertain close is retried.
            bool closed=true;
            try { if (files!=null) files.Dispose(); } catch { closed=false; }
            try { if (old!=null) old.Dispose(); } catch { closed=false; }
            if (!closed) throw new Exception("Preparation close unknown");
        }
    }
    public static Preparation Prepare(uint ms,long limit,long frequency,long deadlineUnix,string pipe,uint pid,string created,string requestId) {
        return new Preparation(ms,limit,frequency,deadlineUnix,pipe,pid,created,requestId);
    }
    public static Preparation PrepareInherited(uint ms,long limit,long frequency,long deadlineUnix,long pipe,long owner,uint pid,string created,string requestId) {
        var inherited=new Lifetime(pipe,owner,pid,created);
        try { return new Preparation(ms,limit,frequency,deadlineUnix,null,pid,created,requestId,inherited); }
        catch { inherited.Dispose(); throw; }
    }
    public static Answer RunPreparation(Preparation preparation,string exe,string args,string cwd) {
        if (preparation==null) throw new ArgumentNullException("preparation");
        return preparation.Run(exe,args,cwd,true);
    }
    public static Answer RunPrepared(Preparation preparation,string exe,string args,string cwd) {
        if (preparation==null) throw new ArgumentNullException("preparation");
        return preparation.Run(exe,args,cwd);
    }
    static uint WaitRoot(ProcessInfo p,uint ms,long limit,long frequency,Lifetime lifetime,out bool cancelled) {
        cancelled=false;
        if (lifetime==null) return WaitForSingleObject(p.Process,Remaining(ms,limit,frequency));
        for (;;) {
            if (!lifetime.Alive()) { cancelled=true; return 258; }
            uint remaining=Remaining(ms,limit,frequency);
            if (remaining==0) return 258;
            uint wait=WaitForSingleObject(p.Process,Math.Min(100u,remaining));
            if (wait==0) { cancelled=!lifetime.Alive(); return wait; }
            if (wait!=258) return wait;
        }
    }
    static void Close(ref IntPtr h) {
        IntPtr old=h; h=IntPtr.Zero;
        if (old!=IntPtr.Zero && !CloseHandle(old)) throw new Exception("Handle close unknown");
    }
    static bool Release(ref IntPtr h) { try { Close(ref h); return true; } catch { return false; } }
    static void Free(ref IntPtr h) { IntPtr old=h; h=IntPtr.Zero; if (old!=IntPtr.Zero) Marshal.FreeHGlobal(old); }
    static void Empty(IntPtr job,IntPtr process,uint code) {
        // A bounded OBSERVATION allowance, never more executable lifetime.
        var grace=System.Diagnostics.Stopwatch.StartNew();
        if (!TerminateJobObject(job,code) || WaitForSingleObject(process,5000)!=0) throw new Exception("Termination unknown");
        for (;;) {
            Accounting info;
            if (!QueryAccounting(job,1,out info,(uint)Marshal.SizeOf(typeof(Accounting)),IntPtr.Zero) || info.Active>info.Total)
                throw new Exception("Job accounting unknown");
            if (info.Active==0) return;
            if (grace.ElapsedMilliseconds>=5000) throw new Exception("Job emptiness unknown");
            System.Threading.Thread.Sleep(10);
        }
    }
    static Answer RunCore(string exe,string args,string cwd,uint ms,long limit,long frequency,Lifetime lifetime,bool deliver=false) {
        // ONE monotonic execution window includes native preparation even for Run.
        if (ms == 0 || ms > 900000) throw new ArgumentOutOfRangeException("ms");
        long now=System.Diagnostics.Stopwatch.GetTimestamp(),rate=System.Diagnostics.Stopwatch.Frequency;
        long own=checked(now+(long)Decimal.Floor((decimal)ms*rate/1000));
        if (limit==0 && frequency==0) { limit=own; frequency=rate; }
        else { Remaining(ms,limit,frequency); limit=Math.Min(limit,own); }
        IntPtr job=IntPtr.Zero,or=IntPtr.Zero,ow=IntPtr.Zero,er=IntPtr.Zero,ew=IntPtr.Zero,input=IntPtr.Zero;
        IntPtr attrs=IntPtr.Zero,jobs=IntPtr.Zero,handles=IntPtr.Zero,leasePipe=IntPtr.Zero,leaseOwner=IntPtr.Zero; bool ready=false;
        ProcessInfo p=new ProcessInfo(); Task<Dump> stdout=null,stderr=null;
        try {
            job=CreateJobObject(IntPtr.Zero,null);
            if (job==IntPtr.Zero) throw new Exception("Cannot create watchdog");
            Limits l=new Limits(); l.Basic.Flags=0x2000;
            if (!SetInformationJobObject(job,9,ref l,(uint)Marshal.SizeOf(l))) throw new Exception("Cannot contain process");
            Limits actual; uint flags;
            if (!QueryLimits(job,9,out actual,(uint)Marshal.SizeOf(typeof(Limits)),IntPtr.Zero) || actual.Basic.Flags!=0x2000 ||
                actual.Basic.Active!=0 || !GetHandleInformation(job,out flags) || flags!=0) throw new Exception("Job readback unknown");
            Security sa=new Security(); sa.Size=Marshal.SizeOf(sa); sa.Inherit=1;
            if (!CreatePipe(out or,out ow,ref sa,0) || !CreatePipe(out er,out ew,ref sa,0) ||
                !SetHandleInformation(or,1,0) || !SetHandleInformation(er,1,0)) throw new Exception("Cannot create output pipes");
            input=CreateFile("NUL",0x80000000,3,ref sa,3,0,IntPtr.Zero);
            if (input==IntPtr.Zero || input==new IntPtr(-1)) { input=IntPtr.Zero; throw new Exception("Cannot disable input"); }
            UIntPtr size=UIntPtr.Zero;
            if (InitializeProcThreadAttributeList(IntPtr.Zero,2,0,ref size) || Marshal.GetLastWin32Error()!=122 || size.ToUInt64()<1 || size.ToUInt64()>4096)
                throw new Exception("Cannot size atomic attributes");
            attrs=Marshal.AllocHGlobal((int)size.ToUInt64());
            if (!InitializeProcThreadAttributeList(attrs,2,0,ref size)) throw new Exception("Cannot initialize atomic attributes"); ready=true;
            jobs=Marshal.AllocHGlobal(IntPtr.Size); Marshal.WriteIntPtr(jobs,job);
            int handleCount=deliver?5:3;
            if (deliver) {
                if (lifetime==null) throw new Exception("Preparation lifetime required");
                lifetime.CopyForWorker(out leasePipe,out leaseOwner);
                args+=" -PreparationPipe "+leasePipe.ToInt64().ToString(System.Globalization.CultureInfo.InvariantCulture)+
                    " -PreparationOwner "+leaseOwner.ToInt64().ToString(System.Globalization.CultureInfo.InvariantCulture)+
                    " -ExecutionQpcLimit "+limit.ToString(System.Globalization.CultureInfo.InvariantCulture)+
                    " -ExecutionQpcFrequency "+frequency.ToString(System.Globalization.CultureInfo.InvariantCulture);
            }
            handles=Marshal.AllocHGlobal(handleCount*IntPtr.Size);
            Marshal.WriteIntPtr(handles,0,input); Marshal.WriteIntPtr(handles,IntPtr.Size,ow); Marshal.WriteIntPtr(handles,2*IntPtr.Size,ew);
            if (deliver) { Marshal.WriteIntPtr(handles,3*IntPtr.Size,leasePipe); Marshal.WriteIntPtr(handles,4*IntPtr.Size,leaseOwner); }
            // JOB_LIST closes the owner-death gap BEFORE CreateProcess returns.
            // HANDLE_LIST excludes every unrelated inheritable parent handle.
            if (!UpdateProcThreadAttribute(attrs,0,new UIntPtr(0x2000d),jobs,new UIntPtr((uint)IntPtr.Size),IntPtr.Zero,IntPtr.Zero))
                throw new Exception("Atomic job attribute refused");
            if (!UpdateProcThreadAttribute(attrs,0,new UIntPtr(0x20002),handles,new UIntPtr((uint)(handleCount*IntPtr.Size)),IntPtr.Zero,IntPtr.Zero))
                throw new Exception("Explicit handle attribute refused");
            StartupEx s=new StartupEx(); s.Startup.Size=(uint)Marshal.SizeOf(s); s.Startup.Flags=0x100;
            s.Startup.In=input; s.Startup.Out=ow; s.Startup.Error=ew; s.Attributes=attrs;
            if (lifetime!=null) lifetime.Require();
            if (Remaining(ms,limit,frequency)==0) throw new Exception("Original window expired before creation");
            if (!CreateProcess(exe,new StringBuilder("\""+exe+"\" "+args),IntPtr.Zero,IntPtr.Zero,true,0x08080004,IntPtr.Zero,cwd,ref s,out p))
                throw new Exception("Cannot create atomically contained command");
            bool member;
            if (p.Process==IntPtr.Zero || p.Thread==IntPtr.Zero || p.Id==0 || p.ThreadId==0 ||
                !IsProcessInJob(p.Process,job,out member) || !member ||
                !GetHandleInformation(p.Process,out flags) || flags!=0 || !GetHandleInformation(p.Thread,out flags) || flags!=0)
                throw new Exception("Atomic child membership unknown");
            Close(ref ow); Close(ref ew); Close(ref input); Close(ref leasePipe); Close(ref leaseOwner);
            stdout=Drain(or); or=IntPtr.Zero; stderr=Drain(er); er=IntPtr.Zero;
            ready=false; DeleteProcThreadAttributeList(attrs); Free(ref attrs); Free(ref jobs); Free(ref handles);
            if (lifetime!=null) lifetime.Require();
            if (Remaining(ms,limit,frequency)==0) throw new Exception("Original window expired before resume");
            if (ResumeThread(p.Thread)!=1) throw new Exception("Cannot resume command exactly once");
            Close(ref p.Thread);
            bool cancelled; uint wait=WaitRoot(p,ms,limit,frequency,lifetime,out cancelled);
            bool timeout=!cancelled && (wait==258 || (wait==0 && Remaining(ms,limit,frequency)==0)); uint code=0;
            if (cancelled) code=125;
            else if (timeout) code=124;
            else if (wait!=0 || !GetExitCodeProcess(p.Process,out code)) throw new Exception("Completion unknown");
            // Also stop descendants after normal root exit; root exit alone is
            // NOT tree completion. Observe zero active entries BEFORE job close.
            Empty(job,p.Process,cancelled?125u:(timeout?124u:2u));
            if (!Task.WaitAll(new Task[]{stdout,stderr},5000)) throw new Exception("Output completion unknown");
            if (lifetime!=null && !lifetime.Alive()) { cancelled=true; timeout=false; code=125; }
            var answer=new Answer { Code=unchecked((int)code),Timeout=timeout,Cancelled=cancelled,LifetimeObserved=lifetime!=null,
                Stdout=stdout.Result.Text,Stderr=stderr.Result.Text,
                Truncated=stdout.Result.Truncated || stderr.Result.Truncated,ProcessTreeObserved=true };
            Close(ref p.Process); Close(ref job); return answer;
        } finally {
            // Attempt EVERY owned release even if one close fails. No successful
            // Answer may escape an uncertain close. Atomic job close also covers
            // creation/pre-resume exceptions; failure remains UNKNOWN.
            bool released=true;
            released=Release(ref job)&released; released=Release(ref p.Thread)&released; released=Release(ref p.Process)&released;
            released=Release(ref or)&released; released=Release(ref ow)&released; released=Release(ref er)&released;
            released=Release(ref ew)&released; released=Release(ref input)&released;
            released=Release(ref leasePipe)&released; released=Release(ref leaseOwner)&released;
            if (ready) { ready=false; DeleteProcThreadAttributeList(attrs); }
            Free(ref attrs); Free(ref jobs); Free(ref handles);
            if (!released) throw new Exception("Handle close unknown");
        }
    }
}
'@
    if (-not $preparationWorker) {
        # Own the worker BEFORE its code loading, compilation, pre-load I/O or
        # durable preparation. The worker NEVER inherits this owning job handle.
        if ($bootstrapWorker) {
            $preparation = [CommandWatchdog]::PrepareInherited([uint32]($request.timeout*1000),$qpcLimit,$qpcFrequency,$DeadlineUnix,
                $PreparationPipe,$PreparationOwner,
                [uint32]$request.lifetime.owner_pid,$request.lifetime.owner_created,$RequestId)
        } else {
            $preparation = [CommandWatchdog]::Prepare([uint32]($request.timeout*1000),$qpcLimit,$qpcFrequency,$DeadlineUnix,
                $request.lifetime.pipe,[uint32]$request.lifetime.owner_pid,$request.lifetime.owner_created,$RequestId)
        }
        $workerArgs = '-NoProfile -NonInteractive -ExecutionPolicy RemoteSigned -File "' + $PSCommandPath +
            '" -RequestId ' + $RequestId + ' -DeadlineUnix ' + $DeadlineUnix + ' -RequestSha256 ' + $RequestSha256
        Write-Receipt ($RequestId + '.supervision-start.json') @{
            version=1; request_id=$RequestId; operation='elevated_commands'; request_sha256=$digest;
            helper_sha256=$helperHash; execution_qpc_limit=$qpcLimit; execution_qpc_frequency=$qpcFrequency;
            timeout=$request.timeout; deadline_unix=$DeadlineUnix; status='preparation_worker_claimed_not_acceptance'
        }
        $result.executed = $null
        $whole = [CommandWatchdog]::RunPreparation($preparation,$exe,$workerArgs,$root)
        $preparation.Dispose(); $preparation = $null
        if ($whole.Code -ne 0 -or $whole.Timeout -or $whole.Cancelled -or $whole.Truncated -or
            -not $whole.ProcessTreeObserved -or -not $whole.LifetimeObserved -or
            $whole.Stdout -cne '' -or $whole.Stderr -cne '') { throw 'Preparation worker outcome unknown' }
        $workerResult = [IO.Path]::Combine($receipts,($RequestId + '.worker-result.json'))
        Check-Protected $workerResult
        $held = [IO.File]::Open($workerResult,'Open','Read','Read')
        try {
            if ($held.Length -lt 1 -or $held.Length -gt 65536) { throw 'Preparation result bound' }
            $reader = New-Object IO.StreamReader($held,$utf8,$false,4096,$true)
            try { $inner = $reader.ReadToEnd() | ConvertFrom-Json } finally { $reader.Dispose() }
        } finally { $held.Dispose() }
        if ($inner.version -ne 1 -or $inner.request_id -cne $RequestId -or
            $inner.operation -cne 'elevated_commands' -or $inner.request_sha256 -cne $digest -or
            $inner.helper_sha256 -cne $helperHash -or $inner.status -cne 'completed' -or
            $inner.exit_code -ne 0 -or $inner.effects_verified -isnot [bool] -or $inner.effects_verified -or
            $inner.retry_authorized -isnot [bool] -or $inner.retry_authorized) { throw 'Preparation result binding' }
        foreach ($name in @('executed','process_tree_observed','lifetime_observed','preparation_observed')) {
            if ($inner.$name -isnot [bool] -or -not $inner.$name) { throw 'Preparation observation missing' }
        }
        # Transport only bounded child observations AFTER exact tree completion
        # and checked parent releases. Incomplete/failed evidence stays UNKNOWN.
        foreach ($name in @('status','executed','exit_code','stdout','stderr','output_truncated',
            'process_tree_observed','lifetime_observed','preparation_observed','setup_preload_observed')) { $result[$name] = $inner.$name }
        $result.preparation_supervision_observed = $true
        # This child observes only delivery, NEVER its parent's future completion.
        $result.bootstrap_frame_observed = $bootstrapWorker
        if ($bootstrapWorker) { $result.bootstrap_sha256 = $policy.bootstrap_sha256 }
    } else {
    $preparation = [CommandWatchdog]::PrepareInherited([uint32]($request.timeout*1000),$qpcLimit,$qpcFrequency,$DeadlineUnix,
        $PreparationPipe,$PreparationOwner,[uint32]$request.lifetime.owner_pid,$request.lifetime.owner_created,$RequestId)
    $preloadHash = $null
    if ($null -ne $request.PSObject.Properties['setup_preload']) {
        if ($request.setup_preload -isnot [string] -or $request.setup_preload.Length -gt 4096 -or
            $request.setup_preload -cmatch '[^\x20-\x7e]') { throw 'Fixed native setup pre-load data required' }
        $preload = $request.setup_preload | ConvertFrom-Json
        if ($preload.version -isnot [int] -or $preload.version -ne 1 -or
            @(Compare-Object @('version','root','volume','indices','files') @($preload.PSObject.Properties.Name)).Count -ne 0) { throw 'Fixed native setup pre-load schema required' }
        $names = @(); $lengths = @(); $hashes = @()
        foreach ($pin in $preload.files) {
            if (@(Compare-Object @('name','bytes','sha256') @($pin.PSObject.Properties.Name)).Count -ne 0) { throw 'Fixed native setup pin required' }
            $names += $pin.name; $lengths += $pin.bytes; $hashes += $pin.sha256
        }
        $preparation.HoldSetup($preload.root,[uint32]$preload.volume,[uint64[]]$preload.indices,[string[]]$names,[long[]]$lengths,[string[]]$hashes)
        $sha = [Security.Cryptography.SHA256]::Create()
        try { $preloadHash = ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::ASCII.GetBytes($request.setup_preload)))).Replace('-','').ToLowerInvariant() }
        finally { $sha.Dispose() }
    }
    # Permanent collision barrier, exact snapshot and payload, all under ONE
    # held caller capability. A partial write stays; failures never reset it.
    Write-Receipt ($RequestId + '.start.json') @{
        version=1; request_id=$RequestId; operation='elevated_commands'; status='started';
        request_sha256=$digest; helper_sha256=$helperHash; operator_sid=$identity.User.Value;
        started_at_utc=[DateTime]::UtcNow.ToString('o'); timeout=$request.timeout; deadline_unix=$DeadlineUnix;
        execution_qpc_limit=$qpcLimit; execution_qpc_frequency=$qpcFrequency; lifetime=$request.lifetime;
        preparation_protocol=1; setup_preload_protocol=1; preparation_supervision_protocol=1; setup_preload_sha256=$preloadHash
    }
    Write-New ($RequestId + '.approved.json') $bytes
    $bomUtf8 = New-Object Text.UTF8Encoding($true)
    Write-New ($RequestId + '.payload.ps1') ([byte[]]($bomUtf8.GetPreamble() + $bomUtf8.GetBytes($request.script)))
    $preparation.Check()
    $remaining = $DeadlineUnix - [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    if ($remaining -le 0) { throw 'Approval expired before command launch' }
    # Mark launch uncertainty before the native call; only a returned answer proves completion.
    $result.executed = $null
    $answer = [CommandWatchdog]::RunPrepared($preparation,$exe,(Command-Arguments $scriptPath),$request.cwd)
    $preparation.Dispose(); $preparation = $null
    $result.executed = $true
    $result.preparation_observed = $answer.PreparationObserved
    $result.setup_preload_observed = $answer.SetupPreloadObserved
    $result.exit_code = $answer.Code; $result.stdout = $answer.Stdout; $result.stderr = $answer.Stderr
    $result.output_truncated = $answer.Truncated
    $result.process_tree_observed = $answer.ProcessTreeObserved; $result.lifetime_observed = $answer.LifetimeObserved
    $result.status = if ($answer.Cancelled) { 'cancelled_outcome_unknown' } elseif ($answer.Timeout) { 'timeout_outcome_unknown' } elseif ($answer.Code -eq 0) { 'completed' } else { 'failed' }
    }
} catch {
    $result.status = 'outcome_unknown'
} finally {
    if ($null -ne $preparation) {
        try { $preparation.Dispose() } catch {
            $result.status = 'outcome_unknown'
            $result.preparation_observed = $false
        }
    }
    $result.finished_at_utc = [DateTime]::UtcNow.ToString('o')
    # Failure evidence must remain writable AFTER lease/deadline loss. It cannot
    # launch anything, clear the permanent claim or authorize a second attempt.
    $suffix = if ($preparationWorker) { '.worker-result.json' } else { '.result.json' }
    Write-Receipt ($RequestId + $suffix) $result $false
}
if ($result.status -eq 'completed') { exit 0 }
exit 2
