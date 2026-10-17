param(
    [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{32}$')][string]$RequestId,
    [Parameter(Mandatory=$true)][long]$DeadlineUnix
)
# Installed inspect-only supervisor. Never execute this checkout file elevated.
$ErrorActionPreference = 'Stop'
# Fixed new deployment; never reuse or alter the legacy installation's claim.
$root = [IO.Path]::Combine([Environment]::GetFolderPath('ProgramFiles'), 'AiAgentHyperVInspectionV2')
if ($PSScriptRoot -cne $root -or [IntPtr]::Size -ne 8 -or $PSVersionTable.PSEdition -ne 'Desktop') {
    throw 'Protected native x64 Windows PowerShell installation required'
}
# Hyper-V needs local machine identity even under a sanitized parent environment.
# Set only this process variable from Windows, not from caller-controlled input.
$env:COMPUTERNAME = [Environment]::MachineName
$system = [Environment]::GetFolderPath('System')
$env:PATH = $system
$env:PSModulePath = [IO.Path]::Combine($system, 'WindowsPowerShell\v1.0\Modules')
$receipts = Join-Path $root 'receipts'
$env:TEMP = $receipts; $env:TMP = $receipts
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'UAC required' }
function Assert-Protected([string]$Path) {
    $trusted = @('S-1-5-18', 'S-1-5-32-544',
        'S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464')
    $cursor = $Path
    $first = $true
    while ($cursor) {
        $item = Get-Item -LiteralPath $cursor -Force -ErrorAction Stop
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse installation refused' }
        $acl = Get-Acl -LiteralPath $cursor
        if ($trusted -notcontains $acl.GetOwner([Security.Principal.SecurityIdentifier]).Value) { throw 'Untrusted owner' }
        $dangerous = 0x40 -bor 0x40000 -bor 0x80000 -bor 0x10000000
        if ($cursor -ine [IO.Path]::GetPathRoot($cursor)) { $dangerous = $dangerous -bor 0x10000 }
        if ($first) { $dangerous = $dangerous -bor 0x2 -bor 0x4 -bor 0x10 -bor 0x100 -bor 0x40000000 }
        foreach ($rule in $acl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier])) {
            if ($rule.PropagationFlags -band [Security.AccessControl.PropagationFlags]::InheritOnly) { continue }
            if ($rule.AccessControlType -eq 'Allow' -and $trusted -notcontains $rule.IdentityReference.Value -and
                ([int]$rule.FileSystemRights -band $dangerous)) { throw 'Untrusted installation write/replacement' }
        }
        $parent = [IO.Directory]::GetParent($cursor)
        $cursor = if ($parent) { $parent.FullName } else { $null }
        $first = $false
    }
}
Assert-Protected $root
Assert-Protected $receipts
Assert-Protected (Join-Path $root 'policy.json')
$policyPath = Join-Path $root 'policy.json'
if ((Get-Item -LiteralPath $policyPath).Length -gt 65536) { throw 'Oversized policy' }
$policy = [IO.File]::ReadAllText($policyPath) | ConvertFrom-Json
if ($policy.version -ne 1 -or $policy.operation -cne 'inspect_image_copy' -or
    $identity.User.Value -cne $policy.operator_sid -or
    $policy.iso_provenance_reviewed -ne $true -or $policy.evidence_preserved -ne $true) {
    throw 'Installed approval or same-account UAC identity refused'
}
$remaining = [Math]::Min($DeadlineUnix, [long]$policy.approved_until_unix) - [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
if ($remaining -lt 900 -or $remaining -gt 1800) { throw 'Insufficient or expired inspection budget' }
$expectedFiles = @($policy.files.PSObject.Properties.Name)
if ($expectedFiles.Count -lt 20 -or $expectedFiles.Count -gt 256) { throw 'Unexpected deployment inventory' }
foreach ($binding in $policy.files.PSObject.Properties) {
    if ($binding.Name -cnotmatch '^(helper\.ps1|(?:payload|runtime)/[A-Za-z0-9_./-]+)$' -or
        $binding.Name.Contains('..') -or $binding.Value -cnotmatch '^[0-9a-f]{64}$') { throw 'Invalid deployment path/hash' }
    $path = Join-Path $root $binding.Name
    Assert-Protected $path
    if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -cne $binding.Value) {
        throw 'Deployed code/runtime drift'
    }
}
foreach ($tree in @('payload', 'runtime')) {
    foreach ($item in Get-ChildItem -LiteralPath (Join-Path $root $tree) -Recurse -Force) {
        Assert-Protected $item.FullName
        if (-not $item.PSIsContainer) {
            $name = $item.FullName.Substring($root.Length + 1).Replace('\', '/')
            if ($expectedFiles -cnotcontains $name) { throw 'Unexpected deployed import/runtime file' }
        }
    }
}
function Write-NewJson([string]$Path, [object]$Value) {
    $bytes = [Text.Encoding]::UTF8.GetBytes(($Value | ConvertTo-Json -Depth 14 -Compress))
    if ($bytes.Length -gt 65536) { throw 'Oversized protected receipt' }
    $security = New-Object Security.AccessControl.FileSecurity
    $security.SetSecurityDescriptorSddlForm(('O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;FR;;;'+$policy.operator_sid+')'))
    $stream = New-Object IO.FileStream($Path, [IO.FileMode]::CreateNew,
        [Security.AccessControl.FileSystemRights]::Write, [IO.FileShare]::Read,
        4096, [IO.FileOptions]::WriteThrough, $security)
    try { $stream.Write($bytes, 0, $bytes.Length); $stream.Flush($true) } finally { $stream.Dispose() }
}
$policyDigest = (Get-FileHash -LiteralPath $policyPath -Algorithm SHA256).Hash.ToLowerInvariant()
Write-NewJson (Join-Path $receipts ($RequestId+'.start.json')) @{
    version=1; request_id=$RequestId; operation='inspect_image_copy'; policy_sha256=$policyDigest;
    started_at_utc=[DateTime]::UtcNow.ToString('o'); deadline_unix=$DeadlineUnix; status='started'
}
# Installation-level permanent claim: exactly one inspection attempt, even on failure.
# No tool can reset this claim; later recovery/deployment needs separate review.
Write-NewJson (Join-Path $root 'inspection.claim.json') @{ request_id=$RequestId; operation='inspect_image_copy' }
$status = 'blocked_or_outcome_unknown'; $exitCode = 2; $facts = $null
try {
    $python = Join-Path $root 'runtime\python.exe'
    $entry = Join-Path $root 'payload\night_shifts\inspection_worker.py'
    $arguments = '-I -S -B "'+$entry+'" --request-id '+$RequestId+' --deadline '+$DeadlineUnix
    Write-NewJson (Join-Path $receipts ($RequestId+'.worker.json')) @{ executable=$python; arguments=$arguments }
    Write-Host 'Inspection only: creating and checking a fresh disk copy.' -ForegroundColor Cyan
    Write-Host 'No finalization, publication or Gate A. Files and hashes may take several minutes.'
    Write-Host 'Closing this window does NOT prove the recovery VM stopped; inspect retained receipts.'
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class InspectionWatchdog {
    [StructLayout(LayoutKind.Sequential)] struct Basic {
        public long ProcessTime, JobTime; public uint Flags; public UIntPtr Min, Max;
        public uint Active; public UIntPtr Affinity; public uint Priority, Scheduling;
    }
    [StructLayout(LayoutKind.Sequential)] struct IO { public ulong A,B,C,D,E,F; }
    [StructLayout(LayoutKind.Sequential)] struct Limits {
        public Basic Basic; public IO IO; public UIntPtr ProcessMemory,JobMemory,PeakProcess,PeakJob;
    }
    [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)] struct Startup {
        public uint Size; public string Reserved,Desktop,Title; public uint X,Y,XS,YS,XC,YC,Fill,Flags;
        public ushort Show,ReservedSize; public IntPtr ReservedPtr,In,Out,Error;
    }
    [StructLayout(LayoutKind.Sequential)] struct ProcessInfo { public IntPtr Process,Thread; public uint Id,ThreadId; }
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode)] static extern IntPtr CreateJobObject(IntPtr a,string n);
    [DllImport("kernel32.dll")] static extern bool SetInformationJobObject(IntPtr j,int k,ref Limits l,uint n);
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode)] static extern bool CreateProcess(string app,
        System.Text.StringBuilder cmd,IntPtr pa,IntPtr ta,bool inherit,uint flags,IntPtr env,string cwd,
        ref Startup s,out ProcessInfo p);
    [DllImport("kernel32.dll")] static extern bool AssignProcessToJobObject(IntPtr j,IntPtr p);
    [DllImport("kernel32.dll")] static extern uint ResumeThread(IntPtr t);
    [DllImport("kernel32.dll")] static extern uint WaitForSingleObject(IntPtr p,uint ms);
    [DllImport("kernel32.dll")] static extern bool GetExitCodeProcess(IntPtr p,out uint c);
    [DllImport("kernel32.dll")] static extern bool TerminateProcess(IntPtr p,uint c);
    [DllImport("kernel32.dll")] static extern bool TerminateJobObject(IntPtr j,uint c);
    [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr h);
    public static int Run(string exe,string args,string cwd,uint ms) {
        IntPtr job=CreateJobObject(IntPtr.Zero,null); ProcessInfo p=new ProcessInfo();
        if(job==IntPtr.Zero) throw new Exception("Cannot create inspection job");
        try {
            Limits l=new Limits(); l.Basic.Flags=0x2000;
            if(!SetInformationJobObject(job,9,ref l,(uint)Marshal.SizeOf(l))) throw new Exception("Cannot bound worker");
            Startup s=new Startup(); s.Size=(uint)Marshal.SizeOf(s);
            if(!CreateProcess(exe,new System.Text.StringBuilder("\""+exe+"\" "+args),IntPtr.Zero,IntPtr.Zero,
                false,0x08000004,IntPtr.Zero,cwd,ref s,out p)) throw new Exception("Cannot start suspended worker");
            if(!AssignProcessToJobObject(job,p.Process)) {
                TerminateProcess(p.Process,2); throw new Exception("Cannot contain worker");
            }
            if(ResumeThread(p.Thread)==0xffffffff) throw new Exception("Cannot resume worker");
            uint wait=WaitForSingleObject(p.Process,ms);
            if(wait!=0) {
                TerminateJobObject(job,2); WaitForSingleObject(p.Process,5000);
                return 124; // This terminates processes, NOT the Hyper-V VM.
            }
            uint code; if(!GetExitCodeProcess(p.Process,out code)) throw new Exception("Unknown worker result");
            return (int)code;
        } finally {
            if(p.Thread!=IntPtr.Zero) CloseHandle(p.Thread);
            if(p.Process!=IntPtr.Zero) CloseHandle(p.Process);
            CloseHandle(job);
        }
    }
}
'@
    $remaining = [Math]::Min($DeadlineUnix, [long]$policy.approved_until_unix) - [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    if ($remaining -lt 900) { throw 'Execution budget expired before launch' }
    $workerExit = [InspectionWatchdog]::Run($python, $arguments, $receipts, [uint32]($remaining*1000))
    $factsPath = Join-Path $receipts ($RequestId+'.facts.json')
    Assert-Protected $factsPath
    if ((Get-Item -LiteralPath $factsPath).Length -gt 65536) { throw 'Oversized worker result' }
    $facts = [IO.File]::ReadAllText($factsPath) | ConvertFrom-Json
    if ($workerExit -eq 0 -and $facts.request_id -ceq $RequestId -and
        $facts.operation -ceq 'inspect_image_copy' -and $facts.status -ceq 'inspected_not_accepted') {
        $status='completed'; $exitCode=0
    }
} catch { $status='blocked_or_outcome_unknown' }
Write-NewJson (Join-Path $receipts ($RequestId+'.result.json')) @{
    version=1; request_id=$RequestId; operation='inspect_image_copy'; policy_sha256=$policyDigest;
    status=$status; result=$facts; accepted=$false; gate_a='unrun';
    finished_at_utc=[DateTime]::UtcNow.ToString('o')
}
exit $exitCode
