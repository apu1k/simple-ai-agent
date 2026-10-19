param([switch]$AuthorizeNewNativeStoreGuardFixtureV1)
# NEW non-secret guard fixture only. Never invoke/reuse the retained V1 fixture.
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
if (-not $AuthorizeNewNativeStoreGuardFixtureV1) { throw 'Explicit new guard-fixture authorization required' }
if ([IntPtr]::Size -ne 8 -or $PSVersionTable.PSEdition -ne 'Desktop') { throw 'Native x64 Windows PowerShell required' }
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
if (-not (New-Object Security.Principal.WindowsPrincipal($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Enabled Administrator required; no guard objects created'
}
function Read-GuardReceipt([string]$Name,[string]$Expected) {
    $path=[IO.Path]::Combine('C:\Program Files\AiAgentElevatedCommands\receipts',$Name)
    $stream=[IO.File]::Open($path,'Open','Read','Read')
    try {
        if ($stream.Length -le 0 -or $stream.Length -gt 65536) { throw 'Receipt size refused' }
        $bytes=New-Object byte[] ([int]$stream.Length);$offset=0
        while ($offset -lt $bytes.Length) {
            $n=$stream.Read($bytes,$offset,$bytes.Length-$offset)
            if ($n -le 0) { throw 'Truncated receipt' }
            $offset+=$n
        }
    } finally { $stream.Dispose() }
    $sha=[Security.Cryptography.SHA256]::Create()
    try { $actual=([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-','').ToLowerInvariant() }
    finally { $sha.Dispose() }
    if ($actual -cne $Expected) { throw 'Pinned old receipt changed; no new attempt authorized' }
    return ([Text.Encoding]::UTF8.GetString($bytes)|ConvertFrom-Json)
}
$failed=Read-GuardReceipt '2fb426b96a7b4cc99b3df8db3e9bf4a3.result.json' '1a03367dfb4f058d863f1fa8d7051d57e8b87d45a3a4e9334c2de4293fc6271a'
$diagnostic=Read-GuardReceipt '75de7de500ff4979b85aed4c60538f4b.result.json' '0ad1a3a739c060c94d463c0af5dd8a37dec59ec768e91331ab4a5e160204db9b'
if ($failed.request_id -cne '2fb426b96a7b4cc99b3df8db3e9bf4a3' -or $failed.status -cne 'failed' -or
    $diagnostic.request_id -cne '75de7de500ff4979b85aed4c60538f4b' -or $diagnostic.status -cne 'completed') { throw 'Unexpected old attempt records' }
$old=$failed.stdout|ConvertFrom-Json
$native=@'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Text;
using Microsoft.Win32.SafeHandles;
public static class NativeStoreGuardFixtureV1 {
 const string ID="97aa76c6db034b4ea87c747a38ce60a0";
 const string Name="native-store-guards-"+ID;
 const string Parent=@"C:\Program Files\AiAgentElevatedCommands\receipts";
 const string BA="S-1-5-32-544", SY="S-1-5-18", TI="S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464";
 const uint Meta=0x120080;
 static readonly byte[] Marker=Encoding.ASCII.GetBytes("NON-SECRET native store guard fixture v1\n");
 static bool attempted;
 static string stage="not_started";
 [StructLayout(LayoutKind.Sequential)]struct Unicode {public ushort Length,Maximum;public IntPtr Buffer;}
 [StructLayout(LayoutKind.Sequential)]struct Attributes {public uint Length;public IntPtr Root,Name;public uint Flags;public IntPtr Security,Qos;}
 [StructLayout(LayoutKind.Sequential)]struct IoStatus {public IntPtr Status;public UIntPtr Information;}
 [StructLayout(LayoutKind.Sequential)]struct Time {public uint Low,High;}
 [StructLayout(LayoutKind.Sequential)]struct FileInfo {public uint Attributes;public Time Created,Accessed,Written;public uint Volume,SizeHigh,SizeLow,Links,IndexHigh,IndexLow;}
 sealed class Fault:Exception {public string Code;public int? Error;public uint? Status;public uint? Access;public Fault(string c,int? e,uint? s,uint? a){Code=c;Error=e;Status=s;Access=a;}}
 sealed class Snap {public FileInfo Info;public RawSecurityDescriptor Sd;public string Text;public ulong Index {get{return ((ulong)Info.IndexHigh<<32)|Info.IndexLow;}}public ulong Size {get{return ((ulong)Info.SizeHigh<<32)|Info.SizeLow;}}}
 [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)]static extern SafeFileHandle CreateFileW(string p,uint a,uint s,IntPtr sa,uint d,uint f,IntPtr t);
 [DllImport("kernel32.dll",SetLastError=true)]static extern bool GetFileInformationByHandle(SafeFileHandle h,out FileInfo i);
 [DllImport("kernel32.dll",SetLastError=true)]static extern uint GetFileType(SafeFileHandle h);
 [DllImport("kernel32.dll",CharSet=CharSet.Unicode)]static extern uint GetDriveTypeW(string p);
 [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)]static extern uint GetFinalPathNameByHandleW(SafeFileHandle h,StringBuilder p,uint n,uint f);
 [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)]static extern bool GetVolumeInformationByHandleW(SafeFileHandle h,IntPtr p,uint n,IntPtr s,IntPtr m,IntPtr f,StringBuilder fs,uint fsn);
 [DllImport("kernel32.dll")]static extern IntPtr LocalFree(IntPtr h);
 [DllImport("kernel32.dll")]static extern IntPtr GetCurrentThread();
 [DllImport("advapi32.dll",SetLastError=true)]static extern bool OpenThreadToken(IntPtr h,uint a,bool self,out SafeFileHandle t);
 [DllImport("advapi32.dll",SetLastError=true)]static extern uint GetSecurityInfo(SafeFileHandle h,int t,uint n,out IntPtr o,out IntPtr g,out IntPtr d,out IntPtr s,out IntPtr sd);
 [DllImport("advapi32.dll")]static extern uint GetSecurityDescriptorLength(IntPtr sd);
 [DllImport("ntdll.dll")]static extern int NtCreateFile(out IntPtr h,uint a,ref Attributes oa,out IoStatus io,IntPtr allocation,uint fa,uint share,uint disposition,uint options,IntPtr ea,uint ean);
 [DllImport("ntdll.dll")]static extern uint RtlNtStatusToDosError(int s);
 [DllImport("kernel32.dll",SetLastError=true)]static extern bool WriteFile(SafeFileHandle h,byte[] b,uint n,out uint z,IntPtr o);
 [DllImport("kernel32.dll",SetLastError=true)]static extern bool ReadFile(SafeFileHandle h,byte[] b,uint n,out uint z,IntPtr o);
 [DllImport("kernel32.dll",SetLastError=true)]static extern bool SetFilePointerEx(SafeFileHandle h,long n,IntPtr next,uint origin);
 [DllImport("kernel32.dll",SetLastError=true)]static extern bool FlushFileBuffers(SafeFileHandle h);
 [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)]static extern bool MoveFileExW(string a,string b,uint f);
 [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)]static extern bool CreateHardLinkW(string a,string b,IntPtr s);
 [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)][return:MarshalAs(UnmanagedType.U1)]static extern bool CreateSymbolicLinkW(string a,string b,uint f);
 [DllImport("kernel32.dll",SetLastError=true)]static extern bool DeviceIoControl(SafeFileHandle h,uint code,IntPtr input,uint inputSize,byte[] output,uint outputSize,out uint returned,IntPtr overlapped);
 static void Need(bool b,string c){if(!b)throw new Fault(c,null,null,null);}
 static void Native(bool b,string c){if(!b)throw new Fault(c,Marshal.GetLastWin32Error(),null,null);}
 static string Hex(uint n){return "0x"+n.ToString("x8");}
 static string Index(Snap s){return s.Index.ToString("x16");}
 static bool Trusted(string s){return s==BA || s==SY || s==TI;}
 static string Sddl(bool dir){string f=dir ? "OICI" : "";return "O:BAG:BAD:P(A;"+f+";FA;;;SY)(A;"+f+";FA;;;BA)";}
 public static string ShapeReason(uint attributes,uint links,bool directory){
  if((attributes&0x400)!=0)return "reparse";
  if(links!=1)return "multiple_links";
  if(((attributes&16)!=0)!=directory || (attributes&(0x200|0x800|0x1000|0x4000))!=0)return "shape";
  return "";
 }
 static void PrivateSd(RawSecurityDescriptor sd,bool directory){
  Need(sd.Owner!=null && sd.Owner.Value==BA && sd.Group!=null && sd.Group.Value==BA,"private_owner_group");
  Need((sd.ControlFlags&ControlFlags.DiscretionaryAclProtected)!=0 && sd.DiscretionaryAcl!=null && sd.DiscretionaryAcl.Count==2,"private_dacl");
  HashSet<string>left=new HashSet<string>(new string[]{SY,BA});
  foreach(GenericAce item in sd.DiscretionaryAcl){CommonAce a=item as CommonAce;Need(a!=null && !a.IsCallback && a.AceQualifier==AceQualifier.AccessAllowed && (uint)a.AccessMask==0x1f01ff && (int)a.AceFlags==(directory ? 3 : 0),"private_ace");Need(left.Remove(a.SecurityIdentifier.Value),"private_principal");}
 }
 public static bool AcceptPrivateDescriptor(string text,bool directory){try{if(text==null || text.Length>8192)return false;PrivateSd(new RawSecurityDescriptor(text),directory);return true;}catch{return false;}}
 static Snap Observe(SafeFileHandle h){
  Need(!h.IsInvalid && GetFileType(h)==1,"disk_handle");FileInfo i;Native(GetFileInformationByHandle(h,out i),"file_info");
  Snap r=new Snap();r.Info=i;Need(r.Index!=0,"file_identity");IntPtr o,g,d,s,sd;uint error=GetSecurityInfo(h,1,7,out o,out g,out d,out s,out sd);if(error!=0)throw new Fault("security_info",(int)error,null,null);
  try{uint n=GetSecurityDescriptorLength(sd);Need(n>0 && n<=65536,"descriptor_bounds");byte[] b=new byte[n];Marshal.Copy(sd,b,0,(int)n);r.Sd=new RawSecurityDescriptor(b,0);Need(r.Sd.DiscretionaryAcl!=null && r.Sd.DiscretionaryAcl.Count<=128,"acl_bounds");r.Text=r.Sd.GetSddlForm(AccessControlSections.Owner|AccessControlSections.Group|AccessControlSections.Access);}finally{LocalFree(sd);}return r;
 }
 static void Private(Snap s,bool directory){string code=ShapeReason(s.Info.Attributes,s.Info.Links,directory);Need(code=="",code);PrivateSd(s.Sd,directory);}
 static void Ancestor(Snap s){
  Need(ShapeReason(s.Info.Attributes,s.Info.Links,true)=="","ancestor_shape");Need(s.Sd.Owner!=null && Trusted(s.Sd.Owner.Value),"ancestor_owner");
  uint dangerous=0x40|0x10000|0x40000|0x80000|0x10000000|0x40000000|0x10|0x100;
  foreach(GenericAce item in s.Sd.DiscretionaryAcl){CommonAce a=item as CommonAce;Need(a!=null && !a.IsCallback && ((int)a.AceFlags&~31)==0 && (a.AceQualifier==AceQualifier.AccessAllowed || a.AceQualifier==AceQualifier.AccessDenied),"ancestor_ace");if((a.AceFlags&AceFlags.InheritOnly)!=0)continue;Need(a.AceQualifier!=AceQualifier.AccessAllowed || Trusted(a.SecurityIdentifier.Value) || ((uint)a.AccessMask&dangerous)==0,"ancestor_mutation");}
 }
 static void Same(Snap a,Snap b,bool linksMayChange){Need(a.Info.Volume==b.Info.Volume && a.Index==b.Index && a.Size==b.Size && a.Info.Attributes==b.Info.Attributes && a.Text==b.Text && (linksMayChange || a.Info.Links==b.Info.Links),"identity_security_drift");}
 static SafeFileHandle Relative(SafeFileHandle parent,string name,bool dir,bool create,bool writable){
  Need(name.Length>0 && name.Length<120 && name!="." && name!=".." && name.IndexOfAny(new char[]{'\\','/',':','\0'})<0,"component");
  IntPtr text=Marshal.StringToHGlobalUni(name),unicode=IntPtr.Zero,security=IntPtr.Zero;
  try{
   Unicode u=new Unicode();u.Length=(ushort)(name.Length*2);u.Maximum=(ushort)((name.Length+1)*2);u.Buffer=text;unicode=Marshal.AllocHGlobal(Marshal.SizeOf(typeof(Unicode)));Marshal.StructureToPtr(u,unicode,false);
   if(create){RawSecurityDescriptor sd=new RawSecurityDescriptor(Sddl(dir));byte[] b=new byte[sd.BinaryLength];sd.GetBinaryForm(b,0);security=Marshal.AllocHGlobal(b.Length);Marshal.Copy(b,0,security,b.Length);}
   Attributes a=new Attributes();a.Length=(uint)Marshal.SizeOf(typeof(Attributes));a.Root=parent.DangerousGetHandle();a.Name=unicode;a.Flags=0x1040;a.Security=security;
   uint access=Meta|(dir ? 0x20U : 0x80000000U);if(writable)access|=dir ? 6U : 0x40000000U;
   IoStatus io;IntPtr raw;int status=NtCreateFile(out raw,access,ref a,out io,IntPtr.Zero,0,dir ? 3U : (create ? 0U : 1U),create ? 2U : 1U,0x200000|0x20|(dir ? 1U : 0x40U),IntPtr.Zero,0);
   if(status!=0){if(raw!=IntPtr.Zero && raw!=new IntPtr(-1))new SafeFileHandle(raw,true).Dispose();throw new Fault(create ? "relative_create" : "relative_open",(int)RtlNtStatusToDosError(status),unchecked((uint)status),access);}
   SafeFileHandle h=new SafeFileHandle(raw,true);if(h.IsInvalid || io.Information.ToUInt64()!=(create ? 2UL : 1UL)){h.Dispose();throw new Fault("create_disposition",null,null,access);}return h;
  }finally{if(security!=IntPtr.Zero)Marshal.FreeHGlobal(security);if(unicode!=IntPtr.Zero)Marshal.FreeHGlobal(unicode);Marshal.FreeHGlobal(text);}
 }
 static void ReadMarker(SafeFileHandle h){Native(SetFilePointerEx(h,0,IntPtr.Zero,0),"marker_seek");byte[] b=new byte[Marker.Length+1];uint n;Native(ReadFile(h,b,(uint)b.Length,out n,IntPtr.Zero),"marker_read");Need(n==Marker.Length,"marker_length");for(int i=0;i<Marker.Length;i++)Need(b[i]==Marker[i],"marker_changed");}
 static Snap NewMarker(SafeFileHandle parent,string name){
  using(SafeFileHandle h=Relative(parent,name,false,true,true)){Snap initial=Observe(h);Private(initial,false);Need(initial.Size==0,"new_file_nonempty");uint n;Native(WriteFile(h,Marker,(uint)Marker.Length,out n,IntPtr.Zero),"marker_write");Need(n==Marker.Length,"short_marker_write");Native(FlushFileBuffers(h),"marker_flush");ReadMarker(h);Snap written=Observe(h);Private(written,false);Need(initial.Info.Volume==written.Info.Volume && initial.Index==written.Index && initial.Text==written.Text && written.Size==(ulong)Marker.Length,"new_marker_drift");return written;}
 }
 static string Decode(byte[] b,int offset,int length){return new UnicodeEncoding(false,false,true).GetString(b,offset,length);}
 static void ReparseData(byte[] b,int count,string target){
  Need(b!=null && count>=20 && count<=b.Length && count<=16384,"reparse_bounds");Need(BitConverter.ToUInt32(b,0)==0xa000000c,"reparse_tag");int length=BitConverter.ToUInt16(b,4);Need(length>=12 && 8+length<=count,"reparse_length");
  int so=BitConverter.ToUInt16(b,8),sl=BitConverter.ToUInt16(b,10),po=BitConverter.ToUInt16(b,12),pl=BitConverter.ToUInt16(b,14);Need(BitConverter.ToUInt32(b,16)==0,"reparse_relative");
  Need((so|sl|po|pl)%2==0 && sl>0 && so+sl<=length-12 && po+pl<=length-12,"reparse_offsets");
  Need(String.Equals(Decode(b,20+so,sl),"\\??\\"+target,StringComparison.OrdinalIgnoreCase),"reparse_target");
  if(pl!=0)Need(String.Equals(Decode(b,20+po,pl),target,StringComparison.OrdinalIgnoreCase),"reparse_print_name");
 }
 public static bool AcceptReparseData(byte[] b,int count,string target){try{ReparseData(b,count,target);return true;}catch{return false;}}
 public static string FixedPath(){return Parent+"\\"+Name;}
 public static Dictionary<string,object> Run(string expectedSid){
  Dictionary<string,object>r=new Dictionary<string,object>();List<object>rows=new List<object>();List<SafeFileHandle>held=new List<SafeFileHandle>();List<Snap>before=new List<Snap>();
  r["v"]=1;r["ok"]=false;r["code"]="not_started";r["op"]="new_native_store_guard_fixture_v1";r["id"]=ID;r["created"]=false;r["original"]="failed";r["v1_reused"]=false;r["ready"]=false;r["system_vm_tested"]=false;r["cols"]=new string[]{"test","nt","win32","detail","ok"};r["rows"]=rows;
  try{
   stage="authorization";using(WindowsIdentity me=WindowsIdentity.GetCurrent()){Need(new WindowsPrincipal(me).IsInRole(WindowsBuiltInRole.Administrator),"enabled_admin_required");Need(me.User.Value==expectedSid,"operator_mismatch");}Need(!attempted,"already_attempted");attempted=true;
   SafeFileHandle thread;bool hasThread=OpenThreadToken(GetCurrentThread(),8,true,out thread);int threadError=Marshal.GetLastWin32Error();if(thread!=null)thread.Dispose();Need(!hasThread && threadError==1008,"thread_context");
   Need(Environment.Is64BitProcess && Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles)==@"C:\Program Files","fixed_host_profile");
   stage="ancestors";Need(GetDriveTypeW(@"C:\")==3,"fixed_volume");SafeFileHandle root=CreateFileW(@"C:\",Meta|0x20,3,IntPtr.Zero,3,0x2200000,IntPtr.Zero);held.Add(root);Native(!root.IsInvalid,"root_open");
   StringBuilder name=new StringBuilder(128);uint count=GetFinalPathNameByHandleW(root,name,128,1);Need(count>0 && count<128 && System.Text.RegularExpressions.Regex.IsMatch(name.ToString(),@"^\\\\\?\\Volume\{[0-9a-fA-F-]{36}\}\\$"),"volume_root");StringBuilder fs=new StringBuilder(32);Native(GetVolumeInformationByHandleW(root,IntPtr.Zero,0,IntPtr.Zero,IntPtr.Zero,IntPtr.Zero,fs,32),"volume_info");Need(fs.ToString()=="NTFS","ntfs_required");
   Snap first=Observe(root);Ancestor(first);before.Add(first);string[] parts=new string[]{"Program Files","AiAgentElevatedCommands","receipts"};
   for(int i=0;i<parts.Length;i++){SafeFileHandle h=Relative(held[held.Count-1],parts[i],true,false,i==parts.Length-1);held.Add(h);Snap s=Observe(h);Ancestor(s);Need(s.Info.Volume==first.Info.Volume,"volume_changed");before.Add(s);}
   for(int i=0;i<before.Count;i++)Same(before[i],Observe(held[i]),false);
   stage="new_root";SafeFileHandle store=Relative(held[held.Count-1],Name,true,true,true);held.Add(store);r["created"]=true;Snap storeBefore=Observe(store);Private(storeBefore,true);r["vol"]=Hex(storeBefore.Info.Volume);r["root_index"]=Index(storeBefore);r["private_sd"]=storeBefore.Text;
   stage="collision";Snap collisionBefore=NewMarker(store,"collision.bin");bool refused=false;Fault collisionError=null;
   try{using(SafeFileHandle unexpected=Relative(store,"collision.bin",false,true,true)){} }catch(Fault f){if(f.Status!=0xc0000035)throw;refused=true;collisionError=f;}
   Need(refused,"collision_not_refused");using(SafeFileHandle h=Relative(store,"collision.bin",false,false,false)){Snap after=Observe(h);Private(after,false);Same(collisionBefore,after,false);ReadMarker(h);rows.Add(new object[]{"collision",Hex(collisionError.Status.Value),collisionError.Error,new object[]{Index(collisionBefore),Index(after),true,true},true});}
   stage="rename";using(SafeFileHandle h=Relative(store,"held-directory",true,true,true)){Snap original=Observe(h);Private(original,true);bool moved=MoveFileExW(FixedPath()+"\\held-directory",FixedPath()+"\\renamed-held-directory",0);int error=Marshal.GetLastWin32Error();if(moved)throw new Fault("rename_succeeded",null,null,null);if(error!=32)throw new Fault("rename_error",error,null,null);Same(original,Observe(h),false);
    using(SafeFileHandle old=Relative(store,"held-directory",true,false,false))Same(original,Observe(old),false);
    bool missing=false;try{using(SafeFileHandle unexpected=Relative(store,"renamed-held-directory",true,false,false)){} }catch(Fault f){if(f.Status!=0xc0000034)throw;missing=true;}
    Need(missing,"rename_destination_exists");rows.Add(new object[]{"rename",null,error,new object[]{Index(original),"0xc0000034",true},true});}
   stage="reparse";using(SafeFileHandle target=Relative(store,"reparse-target",true,true,true)){Snap targetBefore=Observe(target);Private(targetBefore,true);string targetPath=FixedPath()+"\\reparse-target",linkPath=FixedPath()+"\\reparse-link";Native(CreateSymbolicLinkW(linkPath,targetPath,1),"symlink_create");
    using(SafeFileHandle link=CreateFileW(linkPath,Meta,1,IntPtr.Zero,3,0x2200000,IntPtr.Zero)){Native(!link.IsInvalid,"link_metadata_open");Snap linkBefore=Observe(link);Need((linkBefore.Info.Attributes&0x400)!=0 && linkBefore.Info.Links==1 && linkBefore.Index!=targetBefore.Index,"link_identity");byte[] b=new byte[16384];uint n;Native(DeviceIoControl(link,0x000900a8,IntPtr.Zero,0,b,(uint)b.Length,out n,IntPtr.Zero),"get_reparse_data");ReparseData(b,(int)n,targetPath);
     uint? status=null;int? error=null;string mode="shape";bool stopped=false;
     try{using(SafeFileHandle opened=Relative(store,"reparse-link",true,false,false)){Snap observed=Observe(opened);Need(observed.Info.Volume==linkBefore.Info.Volume && observed.Index==linkBefore.Index && observed.Index!=targetBefore.Index,"target_followed");Need(ShapeReason(observed.Info.Attributes,observed.Info.Links,true)=="reparse","reparse_guard_not_triggered");stopped=true;}}
     catch(Fault f){if(f.Status!=0xc000050b)throw;status=f.Status;error=f.Error;mode="native";stopped=true;}
     Need(stopped,"reparse_not_refused");Same(linkBefore,Observe(link),false);Same(targetBefore,Observe(target),false);rows.Add(new object[]{"reparse",status.HasValue ? (object)Hex(status.Value) : null,error,new object[]{"0xa000000c",mode,Index(linkBefore),Index(targetBefore),true},true});}
   }
   stage="multilink";Snap single=NewMarker(store,"links.bin");Native(CreateHardLinkW(FixedPath()+"\\links-alias.bin",FixedPath()+"\\links.bin",IntPtr.Zero),"hardlink_create");
   using(SafeFileHandle a=Relative(store,"links.bin",false,false,false))using(SafeFileHandle b=Relative(store,"links-alias.bin",false,false,false)){Snap one=Observe(a),two=Observe(b);Same(single,one,true);Same(single,two,true);Need(one.Info.Links==2 && two.Info.Links==2,"hardlink_count");Need(ShapeReason(one.Info.Attributes,one.Info.Links,false)=="multiple_links" && ShapeReason(two.Info.Attributes,two.Info.Links,false)=="multiple_links","multilink_guard");PrivateSd(one.Sd,false);PrivateSd(two.Sd,false);ReadMarker(a);ReadMarker(b);rows.Add(new object[]{"multilink",null,null,new object[]{Index(one),Index(two),one.Info.Links,two.Info.Links,true},true});}
   stage="preservation";Same(storeBefore,Observe(store),false);for(int i=0;i<before.Count;i++)Same(before[i],Observe(held[i]),false);Need(rows.Count==4,"missing_case");r["stable"]=true;r["ok"]=true;r["code"]="four_guard_checks_completed";
  }catch(Fault f){r["code"]=f.Code;r["at"]=stage;r["win32"]=f.Error;r["nt"]=f.Status.HasValue ? (object)Hex(f.Status.Value) : null;r["access"]=f.Access.HasValue ? (object)Hex(f.Access.Value) : null;r["kind"]=f.Status.HasValue ? "native_nt" : f.Error.HasValue ? "native_win32" : "guard";}
  catch{r["code"]="managed_failure";r["at"]=stage;}
  finally{for(int i=held.Count-1;i>=0;i--)held[i].Dispose();}
  return r;
 }
}
'@
Add-Type -TypeDefinition $native -ReferencedAssemblies @('System.dll','System.Core.dll','System.Security.dll')
$result=[NativeStoreGuardFixtureV1]::Run([string]$old.operator_sid)
try {
    $null=Read-GuardReceipt '2fb426b96a7b4cc99b3df8db3e9bf4a3.result.json' '1a03367dfb4f058d863f1fa8d7051d57e8b87d45a3a4e9334c2de4293fc6271a'
    $null=Read-GuardReceipt '75de7de500ff4979b85aed4c60538f4b.result.json' '0ad1a3a739c060c94d463c0af5dd8a37dec59ec768e91331ab4a5e160204db9b'
    $result['old_receipts_unchanged']=$true
} catch { $result['ok']=$false;$result['code']='old_receipt_preservation_unverified';$result['old_receipts_unchanged']=$false }
$json=$result|ConvertTo-Json -Depth 6 -Compress
if ($json.Length -gt 3000 -or [Text.Encoding]::UTF8.GetByteCount($json) -gt 3000) {
    '{"v":1,"ok":false,"code":"report_size_refused","ready":false}'
    throw 'Complete guard report exceeds reviewed bound; retain objects; no retry'
}
$json
if ($result['ok'] -ne $true) { throw 'New guard fixture incomplete or failed; retain all objects; no retry authorized' }
