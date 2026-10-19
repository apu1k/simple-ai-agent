param([switch]$AuthorizeRetainedStoreOrdinaryAccessV1)
# Existing NON-SECRET marker only. UNELEVATED process; not fixture acceptance.
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
if (-not $AuthorizeRetainedStoreOrdinaryAccessV1) { throw 'Explicit ordinary-access validation authorization required' }
if ([IntPtr]::Size -ne 8 -or $PSVersionTable.PSEdition -ne 'Desktop') { throw 'Native x64 Windows PowerShell required' }
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
if ((New-Object Security.Principal.WindowsPrincipal($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Ordinary filtered process required; do not elevate this validator'
}
function Read-PinnedReceipt([string]$Name,[string]$Expected) {
    $path=[IO.Path]::Combine('C:\Program Files\AiAgentElevatedCommands\receipts',$Name)
    $file=[IO.File]::Open($path,'Open','Read','Read')
    try {
        if ($file.Length -le 0 -or $file.Length -gt 65536) { throw 'Receipt size refused' }
        $bytes=New-Object byte[] ([int]$file.Length);$offset=0
        while ($offset -lt $bytes.Length) {
            $count=$file.Read($bytes,$offset,$bytes.Length-$offset)
            if ($count -le 0) { throw 'Truncated receipt' }
            $offset+=$count
        }
    } finally { $file.Dispose() }
    $sha=[Security.Cryptography.SHA256]::Create()
    try { $digest=([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-','').ToLowerInvariant() }
    finally { $sha.Dispose() }
    if ($digest -cne $Expected) { throw 'Pinned receipt changed; no probe authorized' }
    return ([Text.Encoding]::UTF8.GetString($bytes)|ConvertFrom-Json)
}
$failed=Read-PinnedReceipt '2fb426b96a7b4cc99b3df8db3e9bf4a3.result.json' '1a03367dfb4f058d863f1fa8d7051d57e8b87d45a3a4e9334c2de4293fc6271a'
$diagnostic=Read-PinnedReceipt '75de7de500ff4979b85aed4c60538f4b.result.json' '0ad1a3a739c060c94d463c0af5dd8a37dec59ec768e91331ab4a5e160204db9b'
if ($failed.request_id -cne '2fb426b96a7b4cc99b3df8db3e9bf4a3' -or $failed.status -cne 'failed' -or
    $diagnostic.request_id -cne '75de7de500ff4979b85aed4c60538f4b' -or $diagnostic.status -cne 'completed' -or
    $diagnostic.output_truncated -ne $true) { throw 'Unexpected retained evidence' }
$original=$failed.stdout|ConvertFrom-Json
if ($original.failure_stage -cne 'filtered_operator_access_after_producer_close' -or
    $original.fixture_root -cne 'C:\Program Files\AiAgentElevatedCommands\receipts\native-store-fixture-22bf6d3069d64b7fbc8bd09771dcae6f') { throw 'Unexpected retained target' }
$native=@'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Security.Principal;
using Microsoft.Win32.SafeHandles;
public static class RetainedOrdinaryAccessV1 {
 const string Target=@"C:\Program Files\AiAgentElevatedCommands\receipts\native-store-fixture-22bf6d3069d64b7fbc8bd09771dcae6f\probe.bin";
 const string Admins="S-1-5-32-544";
 [StructLayout(LayoutKind.Sequential)] struct SA {public IntPtr Sid;public uint Attributes;}
 [StructLayout(LayoutKind.Sequential)] struct GH {public uint Count;public SA First;}
 [DllImport("kernel32.dll")] static extern IntPtr GetCurrentProcess();
 [DllImport("kernel32.dll")] static extern IntPtr GetCurrentThread();
 [DllImport("kernel32.dll",SetLastError=true)] static extern bool CloseHandle(IntPtr handle);
 [DllImport("kernel32.dll",EntryPoint="CreateFileW",CharSet=CharSet.Unicode,SetLastError=true)]
 static extern SafeFileHandle OpenSafe(string p,uint access,uint share,IntPtr security,uint disposition,uint flags,IntPtr template);
 [DllImport("kernel32.dll",EntryPoint="CreateFileW",CharSet=CharSet.Unicode,SetLastError=true)]
 static extern IntPtr OpenRaw(string p,uint access,uint share,IntPtr security,uint disposition,uint flags,IntPtr template);
 [DllImport("advapi32.dll",SetLastError=true)] static extern bool OpenProcessToken(IntPtr process,uint access,out SafeFileHandle token);
 [DllImport("advapi32.dll",SetLastError=true)] static extern bool OpenThreadToken(IntPtr thread,uint access,bool asSelf,out SafeFileHandle token);
 [DllImport("advapi32.dll",SetLastError=true)] static extern bool GetTokenInformation(SafeFileHandle token,int type,IntPtr data,uint size,out uint needed);
 sealed class Fault:Exception {public string Code;public int Error;public Fault(string code,int error){Code=code;Error=error;}}
 static int Number(SafeFileHandle token,int type) {
  IntPtr data=Marshal.AllocHGlobal(4);
  try {uint needed;if(!GetTokenInformation(token,type,data,4,out needed))throw new Fault("token_number_"+type,Marshal.GetLastWin32Error());
   if(needed!=4)throw new Fault("token_number_size",0);return Marshal.ReadInt32(data);
  } finally {Marshal.FreeHGlobal(data);}
 }
 // Pure policy model for tests, NOT caller-provided native attestation.
 public static string ContextCode(int type,int elevationType,int elevated,uint adminAttributes,bool thread,int threadError,string sid,string expected) {
  if(String.IsNullOrEmpty(sid) || String.IsNullOrEmpty(expected) || sid!=expected)return "operator_mismatch";
  if(thread || threadError!=1008 || type!=1 || elevationType!=3 || elevated!=0 ||
     (adminAttributes&16)==0 || (adminAttributes&4)!=0)return "unsupported_context";
  return "";
 }
 public static Dictionary<string,object> DescribeCurrent() {
  Dictionary<string,object> d=new Dictionary<string,object>();
  SafeFileHandle thread;bool present=OpenThreadToken(GetCurrentThread(),8,true,out thread);int threadError=Marshal.GetLastWin32Error();
  if(thread!=null)thread.Dispose();d["th"]=present;d["te"]=present ? 0 : threadError;
  // Identity is taken from the PROCESS token, not an existing impersonation.
  SafeFileHandle token;if(!OpenProcessToken(GetCurrentProcess(),8,out token))throw new Fault("process_token",Marshal.GetLastWin32Error());
  using(token) {
   d["t"]=Number(token,8);d["et"]=Number(token,18);d["el"]=Number(token,20);
   using(WindowsIdentity processIdentity=new WindowsIdentity(token.DangerousGetHandle())) {d["sid"]=processIdentity.User.Value;}
   uint needed;bool first=GetTokenInformation(token,2,IntPtr.Zero,0,out needed);int error=Marshal.GetLastWin32Error();
   if(first || error!=122 || needed==0 || needed>65536)throw new Fault("group_size",error);
   IntPtr data=Marshal.AllocHGlobal((int)needed);
   try {
    uint capacity=needed;if(!GetTokenInformation(token,2,data,capacity,out needed))throw new Fault("group_query",Marshal.GetLastWin32Error());
    int count=Marshal.ReadInt32(data),offset=Marshal.OffsetOf(typeof(GH),"First").ToInt32(),stride=Marshal.SizeOf(typeof(SA));
    if(count<0 || count>512 || offset+count*stride>capacity)throw new Fault("group_bounds",0);
    bool found=false;uint attributes=0;
    for(int i=0;i<count;i++) {SA item=(SA)Marshal.PtrToStructure(IntPtr.Add(data,offset+i*stride),typeof(SA));
     if(new SecurityIdentifier(item.Sid).Value==Admins) {if(found)throw new Fault("duplicate_admin_group",0);found=true;attributes=item.Attributes;}}
    d["ba"]=attributes;
   } finally {Marshal.FreeHGlobal(data);}
  }
  return d;
 }
 static string Context(Dictionary<string,object> d,string expected) {
  return ContextCode((int)d["t"],(int)d["et"],(int)d["el"],(uint)d["ba"],(bool)d["th"],(int)d["te"],(string)d["sid"],expected);
 }
 static object[] Probe(uint access,bool safe) {
  bool granted;int error;bool? closed=null;int? closeError=null;
  if(safe) {
   using(SafeFileHandle h=OpenSafe(Target,access,7,IntPtr.Zero,3,0x200000,IntPtr.Zero)) {
    error=Marshal.GetLastWin32Error();granted=!h.IsInvalid;
    if(granted) {IntPtr raw=h.DangerousGetHandle();h.SetHandleAsInvalid();closed=CloseHandle(raw);int e=Marshal.GetLastWin32Error();if(closed==false)closeError=e;}
   }
  } else {
   IntPtr h=OpenRaw(Target,access,7,IntPtr.Zero,3,0x200000,IntPtr.Zero);error=Marshal.GetLastWin32Error();granted=h!=IntPtr.Zero && h!=new IntPtr(-1);
   if(granted) {closed=CloseHandle(h);int e=Marshal.GetLastWin32Error();if(closed==false)closeError=e;}
  }
  return new object[]{"0x"+access.ToString("x8"),safe ? "S" : "R",granted,granted ? (object)null : error,closed,closeError};
 }
 public static Dictionary<string,object> Run(string expected) {
  Dictionary<string,object> r=new Dictionary<string,object>();List<object> rows=new List<object>();
  r["v"]=1;r["ok"]=false;r["code"]="not_started";r["op"]="ordinary_retained_access_v1";
  r["base"]="2fb426b96a7b4cc99b3df8db3e9bf4a3";r["diag"]="75de7de500ff4979b85aed4c60538f4b";
  r["original"]="failed";r["prior_output"]="truncated";r["ready"]=false;r["recreated"]=false;r["data_io"]=false;
  r["target_identity_attested"]=false;r["cols"]=new string[]{"mask","api","granted","error","closed","close_error"};r["rows"]=rows;
  try {
   Dictionary<string,object> before=DescribeCurrent();r["ctx"]=before;string reason=Context(before,expected);
   if(reason!="") {r["code"]=reason;return r;}
   bool all=true;
   foreach(uint access in new uint[]{0x80000000,0x40000000,0x10000,0x20000,0x40000,0x80000})foreach(bool safe in new bool[]{true,false}) {
    object[] row=Probe(access,safe);rows.Add(row);
    if((bool)row[2] || !object.Equals(row[3],5))all=false;
    if(object.Equals(row[4],false)) {r["code"]="handle_close_failed";return r;}
   }
   Dictionary<string,object> after=DescribeCurrent();r["ctx_stable"]=true;
   foreach(string key in new string[]{"sid","t","et","el","ba","th","te"})if(!before[key].Equals(after[key]))r["ctx_stable"]=false;
   if(Context(after,expected)!="" || !(bool)r["ctx_stable"]) {r["code"]="context_changed";return r;}
   r["ok"]=all;r["code"]=all ? "all_12_denied_error5" : "unexpected_access_result";
  } catch(Fault f) {r["code"]=f.Code;r["native_error"]=f.Error;}
  catch {r["code"]="managed_failure";}
  return r;
 }
}
'@
Add-Type -TypeDefinition $native -ReferencedAssemblies @('System.dll','System.Core.dll','System.Security.dll')
$result=[RetainedOrdinaryAccessV1]::Run([string]$original.operator_sid)
$json=$result|ConvertTo-Json -Depth 6 -Compress
if ($json.Length -gt 3000 -or [Text.Encoding]::UTF8.GetByteCount($json) -gt 3000) {
    '{"v":1,"ok":false,"code":"report_size_refused","ready":false}'
    throw 'Complete report exceeds reviewed bound; no acceptance'
}
$json
if ($result['ok'] -ne $true) { throw 'Ordinary access validation refused; preserve rows; no retry authorized' }
