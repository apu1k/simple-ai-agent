param(
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{32}$')][string]$RequestId,
    [Parameter(Mandatory = $true)][long]$DeadlineUnix
)
# Protected installation only; never launch this checkout file elevated.
$ErrorActionPreference = 'Stop'
$system = [Environment]::GetFolderPath('System')
$env:PSModulePath = [IO.Path]::Combine($system, 'WindowsPowerShell\v1.0\Modules')
$expectedRoot = [IO.Path]::Combine([Environment]::GetFolderPath('ProgramFiles'), 'AiAgentHyperVEvidence')
if ($PSScriptRoot -cne $expectedRoot) { throw 'Protected installation required' }
$receipts = [IO.Path]::Combine($PSScriptRoot, 'receipts')
$env:TEMP = $receipts
$env:TMP = $receipts
$env:PATH = $system
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Windows administrator consent required'
}
$policy = [IO.File]::ReadAllText([IO.Path]::Combine($PSScriptRoot, 'policy.json')) | ConvertFrom-Json
$collector = [IO.Path]::Combine($PSScriptRoot, 'collector.ps1')
$helperDigest = (Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant()
$collectorDigest = (Get-FileHash -LiteralPath $collector -Algorithm SHA256).Hash.ToLowerInvariant()
if ($policy.version -ne 1 -or $helperDigest -cne $policy.helper_sha256 -or
    $collectorDigest -cne $policy.collector_sha256) { throw 'Installed code digest mismatch' }
function Write-Receipt([string]$Name, [object]$Value) {
    $text = $Value | ConvertTo-Json -Depth 10 -Compress
    $bytes = [Text.Encoding]::UTF8.GetBytes($text)
    if ($bytes.Length -gt 65536) { throw 'Receipt too large' }
    $path = [IO.Path]::Combine($receipts, $Name)
    $stream = [IO.File]::Open($path, 'CreateNew', 'Write', 'Read')
    try { $stream.Write($bytes, 0, $bytes.Length); $stream.Flush($true) }
    finally { $stream.Dispose() }
    # Never leave receipts owned by an individual operator SID: that owner
    # could alter their DACL even when the inherited permissions are read-only.
    $acl = Get-Acl -LiteralPath $path
    $acl.SetOwner((New-Object Security.Principal.SecurityIdentifier('S-1-5-32-544')))
    Set-Acl -LiteralPath $path -AclObject $acl
}
$started = [DateTime]::UtcNow.ToString('o')
$audit = @{ version = 1; request_id = $RequestId; operation = 'collect_host_evidence';
    started_at_utc = $started; deadline_unix = $DeadlineUnix;
    helper_sha256 = $helperDigest; collector_sha256 = $collectorDigest;
    source = $policy.source; recovery_iso = $policy.recovery_iso;
    elevated_identity = $identity.User.Value; status = 'started'; launch_authorized = $false;
    helper_arguments = @('-RequestId', $RequestId, '-DeadlineUnix', $DeadlineUnix) }
# Atomic, single-use request claim and durable evidence BEFORE worker launch.
Write-Receipt ($RequestId + '.start.json') $audit
$status = 'failed'
$exitCode = 2
$facts = $null
$workerExit = $null
try {
    $remaining = $DeadlineUnix - [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    if ($remaining -le 0 -or $remaining -gt 1800) { throw 'Expired or excessive deadline' }
    Write-Host 'Read-only Hyper-V host evidence collection' -ForegroundColor Cyan
    Write-Host 'Fresh VHDX and ISO SHA-256 hashing may take several minutes.'
    Write-Host 'Live progress and elapsed time appear in the AI application. No VM will be launched.'
    # Start suspended, assign a kill-on-close job, then resume. Watchdog also
    # enforces timeout. No worker survives helper failure or window closure.
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class EvidenceWatchdog {
    [StructLayout(LayoutKind.Sequential)] struct Basic {
        public long ProcessTime, JobTime; public uint Flags;
        public UIntPtr Min, Max; public uint Active; public UIntPtr Affinity;
        public uint Priority, Scheduling;
    }
    [StructLayout(LayoutKind.Sequential)] struct IO { public ulong A, B, C, D, E, F; }
    [StructLayout(LayoutKind.Sequential)] struct Limits {
        public Basic Basic; public IO IO;
        public UIntPtr ProcessMemory, JobMemory, PeakProcess, PeakJob;
    }
    [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)] struct Startup {
        public uint Size; public string Reserved, Desktop, Title;
        public uint X,Y,XS,YS,XC,YC,Fill,Flags; public ushort Show, ReservedSize;
        public IntPtr ReservedPtr, In, Out, Error;
    }
    [StructLayout(LayoutKind.Sequential)] struct ProcessInfo {
        public IntPtr Process, Thread; public uint Id, ThreadId;
    }
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    static extern IntPtr CreateJobObject(IntPtr attrs, string name);
    [DllImport("kernel32.dll", SetLastError=true)]
    static extern bool SetInformationJobObject(IntPtr job, int kind, ref Limits limits, uint length);
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    static extern bool CreateProcess(string app, System.Text.StringBuilder cmd,
        IntPtr pa, IntPtr ta, bool inherit, uint flags, IntPtr env, string cwd,
        ref Startup startup, out ProcessInfo process);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool AssignProcessToJobObject(IntPtr j, IntPtr p);
    [DllImport("kernel32.dll", SetLastError=true)] static extern uint ResumeThread(IntPtr thread);
    [DllImport("kernel32.dll")] static extern uint WaitForSingleObject(IntPtr p, uint ms);
    [DllImport("kernel32.dll")] static extern bool GetExitCodeProcess(IntPtr p, out uint code);
    [DllImport("kernel32.dll")] static extern bool TerminateProcess(IntPtr p, uint code);
    [DllImport("kernel32.dll")] static extern bool TerminateJobObject(IntPtr j, uint code);
    [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr handle);
    public static int Run(string exe, string args, string cwd, uint ms) {
        IntPtr job = CreateJobObject(IntPtr.Zero, null);
        ProcessInfo p = new ProcessInfo();
        if (job == IntPtr.Zero) throw new Exception("Cannot create watchdog job");
        try {
            Limits limits = new Limits(); limits.Basic.Flags = 0x2000;
            if (!SetInformationJobObject(job, 9, ref limits, (uint)Marshal.SizeOf(limits)))
                throw new Exception("Cannot configure kill-on-close");
            Startup s = new Startup(); s.Size = (uint)Marshal.SizeOf(s);
            if (!CreateProcess(exe, new System.Text.StringBuilder("\""+exe+"\" "+args),
                IntPtr.Zero, IntPtr.Zero, false, 0x08000004, IntPtr.Zero, cwd, ref s, out p))
                throw new Exception("Cannot create suspended evidence worker");
            if (!AssignProcessToJobObject(job, p.Process)) {
                TerminateProcess(p.Process, 2);
                throw new Exception("Cannot contain evidence worker");
            }
            if (ResumeThread(p.Thread) == 0xffffffff) throw new Exception("Cannot resume evidence worker");
            uint wait = WaitForSingleObject(p.Process, ms);
            if (wait == 258) {
                TerminateJobObject(job, 2);
                if (WaitForSingleObject(p.Process, 5000) != 0)
                    throw new Exception("Worker termination unknown");
                return 124;
            }
            uint code;
            if (wait != 0 || !GetExitCodeProcess(p.Process, out code))
                throw new Exception("Worker completion unknown");
            return unchecked((int)code);
        } finally {
            CloseHandle(job);
            if (p.Thread != IntPtr.Zero) CloseHandle(p.Thread);
            if (p.Process != IntPtr.Zero) CloseHandle(p.Process);
        }
    }
}
'@
    $remaining = $DeadlineUnix - [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    if ($remaining -le 0) { throw 'Expired before worker launch' }
    $factsPath = [IO.Path]::Combine($receipts, $RequestId + '.facts.json')
    function Quote-Fixed([string]$Value) { return "'" + $Value.Replace("'", "''") + "'" }
    # Fixed phase names and create-new records only. No caller-selected paths,
    # mutable status file, executable, callback or command text is accepted.
    $phaseCode = @'
function Write-EvidencePhase([string]$Phase) {
    if (@('inventory', 'source_hash', 'iso_hash', 'recheck') -cnotcontains $Phase) {
        throw 'Unknown evidence phase'
    }
    $path = $phasePrefix + '.phase-' + $Phase + '.json'
    $value = @{ version = 1; request_id = $phaseRequestId; phase = $Phase;
        started_at_utc = [DateTime]::UtcNow.ToString('o') }
    $bytes = [Text.Encoding]::UTF8.GetBytes(($value | ConvertTo-Json -Compress))
    $stream = [IO.File]::Open($path, 'CreateNew', 'Write', 'Read')
    try { $stream.Write($bytes, 0, $bytes.Length); $stream.Flush($true) }
    finally { $stream.Dispose() }
    $acl = Get-Acl -LiteralPath $path
    $acl.SetOwner((New-Object Security.Principal.SecurityIdentifier('S-1-5-32-544')))
    Set-Acl -LiteralPath $path -AclObject $acl
}
'@
    $query = '$phasePrefix = ' + (Quote-Fixed ([IO.Path]::Combine($receipts, $RequestId))) +
        '; $phaseRequestId = ' + (Quote-Fixed $RequestId) + '; ' + $phaseCode +
        "`ntry { `$ErrorActionPreference = 'Stop'; `$json = & " + (Quote-Fixed $collector) +
        ' -SourceDisk ' + (Quote-Fixed $policy.source) + ' -RecoveryIso ' + (Quote-Fixed $policy.recovery_iso) +
        ' -PhaseCallback ${function:Write-EvidencePhase}' +
        '; [IO.File]::WriteAllText(' + (Quote-Fixed $factsPath) +
        ", `$json, (New-Object Text.UTF8Encoding(`$false))); exit 0 } catch { exit 2 }"
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($query))
    $exe = [IO.Path]::Combine($system, 'WindowsPowerShell\v1.0\powershell.exe')
    $audit.worker_executable = $exe
    $audit.worker_arguments = @('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'RemoteSigned',
        '-EncodedCommand', $encoded)
    Write-Receipt ($RequestId + '.worker.json') $audit
    $remaining = $DeadlineUnix - [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    if ($remaining -le 0) { throw 'Expired during audit write' }
    $workerExit = [EvidenceWatchdog]::Run($exe,
        '-NoProfile -NonInteractive -ExecutionPolicy RemoteSigned -EncodedCommand ' + $encoded,
        $PSScriptRoot, [uint32]($remaining * 1000))
    if ($workerExit -eq 124) { $status = 'timeout' }
    elseif ($workerExit -eq 0) {
        $info = New-Object IO.FileInfo($factsPath)
        if ($info.Length -gt 32768) { throw 'Oversized host response' }
        $facts = [IO.File]::ReadAllText($factsPath) | ConvertFrom-Json
        if ($facts.version -ne 1) { throw 'Invalid host response' }
        # Keep every retained artifact protected, including the raw response.
        $acl = Get-Acl -LiteralPath $factsPath
        $acl.SetOwner((New-Object Security.Principal.SecurityIdentifier('S-1-5-32-544')))
        Set-Acl -LiteralPath $factsPath -AclObject $acl
        $status = 'completed'
        $exitCode = 0
        Write-Host 'Read-only collection completed. Returning protected evidence.'
    }
} catch {
    $status = 'failed_or_unknown'
} finally {
    $audit.status = $status
    $audit.worker_exit_code = $workerExit
    $audit.finished_at_utc = [DateTime]::UtcNow.ToString('o')
    $audit.host = $facts
    Write-Receipt ($RequestId + '.result.json') $audit
}
exit $exitCode
