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
if ($policy.version -ne 1 -or $policy.max_timeout -ne 900 -or $policy.lifetime_protocol -ne 1 -or $policy.preparation_protocol -ne 1 -or
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
$fields = @('version','request_id','operation','deadline_unix','timeout','script','cwd','reason','operator_sid','helper_sha256','lifetime')
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
if ($qpcLimit -le $qpcFirst) { throw 'Original execution window expired' }
# No durable preparation or payload before the SAME native lifetime is acquired.
# Compilation below is charged to this cap, but is NOT independently supervised.
$preparation = $null
$scriptPath = [IO.Path]::Combine($receipts,($RequestId + '.payload.ps1'))
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
    helper_sha256=$helperHash; status='outcome_unknown'; executed=$false; effects_verified=$false; process_tree_observed=$false; lifetime_observed=$false; preparation_observed=$false;
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
    public sealed class Answer { public int Code; public bool Timeout,Truncated,ProcessTreeObserved,LifetimeObserved,Cancelled,PreparationObserved; public string Stdout,Stderr; }
    [DllImport("kernel32.dll",ExactSpelling=true,SetLastError=true)] static extern bool PeekNamedPipe(IntPtr pipe,IntPtr buffer,uint bytes,IntPtr read,out uint available,IntPtr left);
    [DllImport("kernel32.dll",ExactSpelling=true)] static extern bool GetNamedPipeServerProcessId(IntPtr pipe,out uint pid);
    [DllImport("kernel32.dll",ExactSpelling=true)] static extern IntPtr OpenProcess(uint access,bool inherit,uint pid);
    [DllImport("kernel32.dll",ExactSpelling=true)] static extern bool GetProcessTimes(IntPtr process,out ulong created,out ulong exited,out ulong kernel,out ulong user);
    [DllImport("kernel32.dll",ExactSpelling=true)] static extern uint GetFileType(IntPtr file);
    // Caller-controlled channel can ONLY subtract lifetime. It carries NO code,
    // output, approval, deadline extension or acceptance. Authenticate the native
    // server process identity, not the pipe spelling or a PID alone. Anonymous
    // SQOS prevents the unelevated server impersonating this elevated client.
    sealed class Lifetime : IDisposable {
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
    public sealed class Preparation : IDisposable {
        Lifetime lifetime;
        readonly uint ms;
        readonly long limit,frequency,deadline;
        long lastQpc,lastWall;
        bool spent,disposed,failed;
        internal Preparation(uint maximum,long cap,long rate,long deadlineUnix,string pipe,uint pid,string created,string id) {
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
            lifetime=new Lifetime(pipe,pid,created,id);
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
        internal Answer Run(string exe,string args,string cwd) {
            if (spent) throw new Exception("Preparation already consumed");
            spent=true; // uncertainty BEFORE observation or native entry
            Observe();
            Answer answer=RunCore(exe,args,cwd,ms,limit,frequency,lifetime);
            // RunCore already observes cancellation/deadline termination. A
            // later loss cannot promote normal completion into acceptance.
            if (!answer.Cancelled && !answer.Timeout) Observe();
            answer.PreparationObserved=true; return answer;
        }
        public void Dispose() {
            if (disposed) return;
            disposed=true;
            Lifetime old=lifetime; lifetime=null;
            if (old!=null) old.Dispose(); // checked; never retry uncertain closes
        }
    }
    public static Preparation Prepare(uint ms,long limit,long frequency,long deadlineUnix,string pipe,uint pid,string created,string requestId) {
        return new Preparation(ms,limit,frequency,deadlineUnix,pipe,pid,created,requestId);
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
    static Answer RunCore(string exe,string args,string cwd,uint ms,long limit,long frequency,Lifetime lifetime) {
        // ONE monotonic execution window includes native preparation even for Run.
        if (ms == 0 || ms > 900000) throw new ArgumentOutOfRangeException("ms");
        long now=System.Diagnostics.Stopwatch.GetTimestamp(),rate=System.Diagnostics.Stopwatch.Frequency;
        long own=checked(now+(long)Decimal.Floor((decimal)ms*rate/1000));
        if (limit==0 && frequency==0) { limit=own; frequency=rate; }
        else { Remaining(ms,limit,frequency); limit=Math.Min(limit,own); }
        IntPtr job=IntPtr.Zero,or=IntPtr.Zero,ow=IntPtr.Zero,er=IntPtr.Zero,ew=IntPtr.Zero,input=IntPtr.Zero;
        IntPtr attrs=IntPtr.Zero,jobs=IntPtr.Zero,handles=IntPtr.Zero; bool ready=false;
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
            handles=Marshal.AllocHGlobal(3*IntPtr.Size);
            Marshal.WriteIntPtr(handles,0,input); Marshal.WriteIntPtr(handles,IntPtr.Size,ow); Marshal.WriteIntPtr(handles,2*IntPtr.Size,ew);
            // JOB_LIST closes the owner-death gap BEFORE CreateProcess returns.
            // HANDLE_LIST excludes every unrelated inheritable parent handle.
            if (!UpdateProcThreadAttribute(attrs,0,new UIntPtr(0x2000d),jobs,new UIntPtr((uint)IntPtr.Size),IntPtr.Zero,IntPtr.Zero))
                throw new Exception("Atomic job attribute refused");
            if (!UpdateProcThreadAttribute(attrs,0,new UIntPtr(0x20002),handles,new UIntPtr((uint)(3*IntPtr.Size)),IntPtr.Zero,IntPtr.Zero))
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
            Close(ref ow); Close(ref ew); Close(ref input);
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
            if (ready) { ready=false; DeleteProcThreadAttributeList(attrs); }
            Free(ref attrs); Free(ref jobs); Free(ref handles);
            if (!released) throw new Exception("Handle close unknown");
        }
    }
}
'@
    $preparation = [CommandWatchdog]::Prepare([uint32]($request.timeout*1000),$qpcLimit,$qpcFrequency,$DeadlineUnix,
        $request.lifetime.pipe,[uint32]$request.lifetime.owner_pid,$request.lifetime.owner_created,$RequestId)
    # Permanent collision barrier, exact snapshot and payload, all under ONE
    # held caller capability. A partial write stays; failures never reset it.
    Write-Receipt ($RequestId + '.start.json') @{
        version=1; request_id=$RequestId; operation='elevated_commands'; status='started';
        request_sha256=$digest; helper_sha256=$helperHash; operator_sid=$identity.User.Value;
        started_at_utc=[DateTime]::UtcNow.ToString('o'); timeout=$request.timeout; deadline_unix=$DeadlineUnix;
        execution_qpc_limit=$qpcLimit; execution_qpc_frequency=$qpcFrequency; lifetime=$request.lifetime;
        preparation_protocol=1
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
    $result.exit_code = $answer.Code; $result.stdout = $answer.Stdout; $result.stderr = $answer.Stderr
    $result.output_truncated = $answer.Truncated
    $result.process_tree_observed = $answer.ProcessTreeObserved; $result.lifetime_observed = $answer.LifetimeObserved
    $result.status = if ($answer.Cancelled) { 'cancelled_outcome_unknown' } elseif ($answer.Timeout) { 'timeout_outcome_unknown' } elseif ($answer.Code -eq 0) { 'completed' } else { 'failed' }
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
    Write-Receipt ($RequestId + '.result.json') $result $false
}
if ($result.status -eq 'completed') { exit 0 }
exit 2
