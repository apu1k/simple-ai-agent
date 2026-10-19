param([switch]$AuthorizeNonSecretNativeStoreFixtureV1)
# Standalone NON-SECRET profile fixture. Not an installer or credential writer.
# Execute only through a separately reviewed hash-bound general-launcher request.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if (-not $AuthorizeNonSecretNativeStoreFixtureV1) { throw 'Explicit fixture authorization required' }
if ([IntPtr]::Size -ne 8 -or $PSVersionTable.PSEdition -ne 'Desktop') {
    throw 'Native x64 Windows PowerShell required'
}
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Enabled Administrator token required; no objects created'
}
$native = @'
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Text;
using Microsoft.Win32.SafeHandles;

public static class NativeStoreProfileFixtureV1 {
    const string BA = "S-1-5-32-544", SY = "S-1-5-18";
    const string TI = "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464";
    const string ParentPath = @"C:\Program Files\AiAgentElevatedCommands\receipts";
    const string LeafName = "native-store-fixture-22bf6d3069d64b7fbc8bd09771dcae6f";
    const uint Full = 0x1f01ff, Metadata = 0x120080;
    static readonly byte[] Marker = Encoding.ASCII.GetBytes("NON-SECRET host-store native prototype marker v1\n");
    static bool attempted;
    static string stage = "not_started";

    [StructLayout(LayoutKind.Sequential)] struct Unicode {
        public ushort Length, Maximum; public IntPtr Buffer;
    }
    [StructLayout(LayoutKind.Sequential)] struct Attributes {
        public uint Length; public IntPtr Root, Name; public uint Flags; public IntPtr Security, Qos;
    }
    [StructLayout(LayoutKind.Sequential)] struct IoStatus { public IntPtr Status; public UIntPtr Information; }
    [StructLayout(LayoutKind.Sequential)] struct FileTime { public uint Low, High; }
    [StructLayout(LayoutKind.Sequential)] struct FileInfo {
        public uint Attributes; public FileTime Created, Accessed, Written;
        public uint Volume, SizeHigh, SizeLow, Links, IndexHigh, IndexLow;
    }
    sealed class Fault : Exception {
        public readonly string Code; public readonly int Error; public readonly uint Status;
        public Fault(string code, int error, uint status) { Code=code; Error=error; Status=status; }
    }
    sealed class Snapshot {
        public FileInfo Info; public RawSecurityDescriptor Security; public string Sddl;
        public ulong Index { get { return ((ulong)Info.IndexHigh << 32) | Info.IndexLow; } }
        public ulong Size { get { return ((ulong)Info.SizeHigh << 32) | Info.SizeLow; } }
    }

    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    static extern SafeFileHandle CreateFileW(string path, uint access, uint share, IntPtr sa, uint disposition, uint flags, IntPtr template);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool GetFileInformationByHandle(SafeFileHandle file, out FileInfo info);
    [DllImport("kernel32.dll", SetLastError=true)] static extern uint GetFileType(SafeFileHandle file);
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode)] static extern uint GetDriveTypeW(string root);
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    static extern uint GetFinalPathNameByHandleW(SafeFileHandle file, StringBuilder name, uint size, uint flags);
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    static extern bool GetVolumeInformationByHandleW(SafeFileHandle file, IntPtr name, uint size, IntPtr serial, IntPtr maximum, IntPtr flags, StringBuilder fs, uint fsSize);
    [DllImport("kernel32.dll")] static extern IntPtr LocalFree(IntPtr value);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool WriteFile(SafeFileHandle file, byte[] data, uint size, out uint written, IntPtr overlapped);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool ReadFile(SafeFileHandle file, byte[] data, uint size, out uint read, IntPtr overlapped);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool SetFilePointerEx(SafeFileHandle file, long offset, IntPtr next, uint origin);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool FlushFileBuffers(SafeFileHandle file);
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern bool MoveFileExW(string source, string destination, uint flags);
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern bool CreateHardLinkW(string link, string target, IntPtr security);
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    [return: MarshalAs(UnmanagedType.U1)] static extern bool CreateSymbolicLinkW(string link, string target, uint flags);
    [DllImport("advapi32.dll", SetLastError=true)] static extern uint GetSecurityInfo(SafeFileHandle file, int type, uint information, out IntPtr owner, out IntPtr group, out IntPtr dacl, out IntPtr sacl, out IntPtr descriptor);
    [DllImport("advapi32.dll")] static extern uint GetSecurityDescriptorLength(IntPtr descriptor);
    [DllImport("advapi32.dll", SetLastError=true)] static extern bool OpenProcessToken(IntPtr process, uint access, out SafeFileHandle token);
    [DllImport("kernel32.dll")] static extern IntPtr GetCurrentProcess();
    [DllImport("advapi32.dll", SetLastError=true)] static extern bool GetTokenInformation(SafeFileHandle token, int type, IntPtr buffer, uint size, out uint needed);
    [DllImport("advapi32.dll", SetLastError=true)] static extern bool ImpersonateLoggedOnUser(SafeFileHandle token);
    [DllImport("advapi32.dll", SetLastError=true)] static extern bool RevertToSelf();
    [DllImport("ntdll.dll")] static extern int NtCreateFile(out IntPtr file, uint access, ref Attributes attributes, out IoStatus io, IntPtr allocation, uint fileAttributes, uint share, uint disposition, uint options, IntPtr ea, uint eaSize);
    [DllImport("ntdll.dll")] static extern uint RtlNtStatusToDosError(int status);

    static void Need(bool condition, string code) { if (!condition) throw new Fault(code, 0, 0); }
    static void Native(bool condition, string code) { if (!condition) throw new Fault(code, Marshal.GetLastWin32Error(), 0); }
    static bool Trusted(string sid) { return sid==BA || sid==SY || sid==TI; }
    static string Sddl(bool directory) {
        string flags = directory ? "OICI" : "";
        return "O:BAG:BAD:P(A;"+flags+";FA;;;SY)(A;"+flags+";FA;;;BA)";
    }
    static byte[] Binary(string text) {
        RawSecurityDescriptor sd = new RawSecurityDescriptor(text);
        byte[] data = new byte[sd.BinaryLength]; sd.GetBinaryForm(data, 0); return data;
    }
    static void PrivateSecurity(RawSecurityDescriptor sd, bool directory) {
        Need(sd.Owner!=null && sd.Owner.Value==BA && sd.Group!=null && sd.Group.Value==BA, "private_owner_group");
        Need((sd.ControlFlags & ControlFlags.DiscretionaryAclProtected)!=0 && sd.DiscretionaryAcl!=null && sd.DiscretionaryAcl.Count==2, "private_dacl");
        HashSet<string> remaining = new HashSet<string>(new string[]{SY, BA});
        foreach (GenericAce item in sd.DiscretionaryAcl) {
            CommonAce ace=item as CommonAce;
            Need(ace!=null && !ace.IsCallback && ace.AceQualifier==AceQualifier.AccessAllowed &&
                 (uint)ace.AccessMask==Full && (int)ace.AceFlags==(directory ? 3 : 0), "private_ace");
            Need(remaining.Remove(ace.SecurityIdentifier.Value), "private_principal");
        }
    }
    public static bool AcceptPrivateDescriptor(string text, bool directory) {
        try { if (text==null || text.Length>8192) return false; PrivateSecurity(new RawSecurityDescriptor(text),directory); return true; }
        catch { return false; }
    }
    static Snapshot Observe(SafeFileHandle file) {
        Need(!file.IsInvalid && GetFileType(file)==1, "not_disk_file");
        Snapshot result=new Snapshot(); FileInfo info;
        Native(GetFileInformationByHandle(file,out info),"file_information"); result.Info=info;
        IntPtr owner,group,dacl,sacl,descriptor;
        uint error=GetSecurityInfo(file,1,7,out owner,out group,out dacl,out sacl,out descriptor);
        if (error!=0) throw new Fault("security_information",(int)error,0);
        try {
            uint size=GetSecurityDescriptorLength(descriptor);
            Need(size>0 && size<=65536,"security_bounds");
            byte[] data=new byte[size]; Marshal.Copy(descriptor,data,0,(int)size);
            result.Security=new RawSecurityDescriptor(data,0);
            result.Sddl=result.Security.GetSddlForm(AccessControlSections.Owner|AccessControlSections.Group|AccessControlSections.Access);
            Need(result.Security.DiscretionaryAcl!=null && result.Security.DiscretionaryAcl.Count<=128,"acl_bounds");
        } finally { LocalFree(descriptor); }
        return result;
    }
    static void Shape(Snapshot value, bool directory) {
        Need(value.Index!=0 && value.Info.Links==1 && ((value.Info.Attributes & 0x10)!=0)==directory &&
             (value.Info.Attributes & (0x400|0x200|0x800|0x1000|0x4000))==0,"object_shape");
    }
    static void Private(Snapshot value, bool directory) { Shape(value,directory); PrivateSecurity(value.Security,directory); }
    static bool PythonAncestorWouldAccept(Snapshot value) {
        if (value.Security.Owner==null || (value.Security.Owner.Value!=SY && value.Security.Owner.Value!=BA)) return false;
        uint harmless=0x1200a9|2|4|0x80000000|0x20000000;
        foreach (GenericAce item in value.Security.DiscretionaryAcl) {
            CommonAce ace=item as CommonAce;
            if (ace==null || ace.IsCallback || ((int)ace.AceFlags & ~31)!=0) return false;
            if ((ace.AceFlags & AceFlags.InheritOnly)!=0) continue;
            if (ace.AceQualifier==AceQualifier.AccessAllowed && ace.SecurityIdentifier.Value!=SY && ace.SecurityIdentifier.Value!=BA &&
                ((uint)ace.AccessMask & ~harmless)!=0) return false;
        }
        return true;
    }
    static void Ancestor(Snapshot value) {
        Shape(value,true);
        Need(value.Security.Owner!=null && Trusted(value.Security.Owner.Value),"ancestor_owner");
        // Fixture-only ancestor boundary includes Windows TrustedInstaller, like
        // the existing launcher. NEVER substitute this for the Python policy.
        uint dangerous=0x40|0x10000|0x40000|0x80000|0x10000000|0x40000000|0x10|0x100;
        foreach (GenericAce item in value.Security.DiscretionaryAcl) {
            CommonAce ace=item as CommonAce;
            Need(ace!=null && !ace.IsCallback && ((int)ace.AceFlags & ~31)==0 &&
                 (ace.AceQualifier==AceQualifier.AccessAllowed || ace.AceQualifier==AceQualifier.AccessDenied),"ancestor_ace");
            if ((ace.AceFlags & AceFlags.InheritOnly)!=0) continue;
            Need(ace.AceQualifier!=AceQualifier.AccessAllowed || Trusted(ace.SecurityIdentifier.Value) ||
                 ((uint)ace.AccessMask & dangerous)==0,"ancestor_mutation");
        }
    }
    static void Same(Snapshot a, Snapshot b, bool markerWritten) {
        Need(a.Info.Volume==b.Info.Volume && a.Index==b.Index && a.Info.Links==b.Info.Links && a.Sddl==b.Sddl &&
             (a.Info.Attributes & ~0x20U)==(b.Info.Attributes & ~0x20U) && b.Size==(markerWritten ? (ulong)Marker.Length : a.Size),"identity_security_drift");
    }
    static SafeFileHandle Relative(SafeFileHandle parent, string name, bool directory, bool create, bool writable) {
        Need(name.Length>0 && name.Length<120 && name.IndexOfAny(new char[]{'\\','/',':','\0'})<0 && name!="." && name!="..","component");
        IntPtr buffer=Marshal.StringToHGlobalUni(name), unicodePtr=IntPtr.Zero, security=IntPtr.Zero;
        try {
            Unicode text=new Unicode(); text.Length=(ushort)(name.Length*2); text.Maximum=(ushort)((name.Length+1)*2); text.Buffer=buffer;
            unicodePtr=Marshal.AllocHGlobal(Marshal.SizeOf(typeof(Unicode))); Marshal.StructureToPtr(text,unicodePtr,false);
            if (create) { byte[] data=Binary(Sddl(directory)); security=Marshal.AllocHGlobal(data.Length); Marshal.Copy(data,0,security,data.Length); }
            Attributes attributes=new Attributes(); attributes.Length=(uint)Marshal.SizeOf(typeof(Attributes));
            attributes.Root=parent.DangerousGetHandle(); attributes.Name=unicodePtr; attributes.Flags=0x1040; attributes.Security=security;
            uint access=Metadata | (directory ? 0x20U : 0U); if (writable) access |= directory ? 6U : 0xc0000000U;
            IoStatus io; IntPtr raw;
            int status=NtCreateFile(out raw,access,ref attributes,out io,IntPtr.Zero,0,directory ? 3U : 0U,
                                   create ? 2U : 1U,0x200000|0x20|(directory ? 1U : 0x40U),IntPtr.Zero,0);
            if (status!=0) {
                if (raw!=IntPtr.Zero && raw!=new IntPtr(-1)) new SafeFileHandle(raw,true).Dispose();
                throw new Fault(create ? "relative_create" : "relative_open",(int)RtlNtStatusToDosError(status),unchecked((uint)status));
            }
            SafeFileHandle file=new SafeFileHandle(raw,true);
            if (file.IsInvalid || io.Information.ToUInt64()!=(create ? 2UL : 1UL)) { file.Dispose(); throw new Fault("create_disposition",0,0); }
            return file;
        } finally {
            if (security!=IntPtr.Zero) Marshal.FreeHGlobal(security);
            if (unicodePtr!=IntPtr.Zero) Marshal.FreeHGlobal(unicodePtr);
            Marshal.FreeHGlobal(buffer);
        }
    }
    static void ReadMarker(SafeFileHandle file) {
        Native(SetFilePointerEx(file,0,IntPtr.Zero,0),"marker_seek");
        byte[] data=new byte[Marker.Length+1]; uint count;
        Native(ReadFile(file,data,(uint)data.Length,out count,IntPtr.Zero),"marker_read");
        Need(count==Marker.Length,"marker_length");
        for (int i=0;i<Marker.Length;i++) Need(data[i]==Marker[i],"marker_mismatch");
    }
    static void DeniedOpen(string path, uint access, int expected) {
        using (SafeFileHandle file=CreateFileW(path,access,7,IntPtr.Zero,3,0x200000,IntPtr.Zero)) {
            int error=Marshal.GetLastWin32Error(); Need(file.IsInvalid,"unexpected_access_granted");
            Need(error==expected,"unexpected_access_error");
        }
    }
    static bool FilteredTokenChecks(string markerPath, string operatorSid, Dictionary<string,object> report) {
        SafeFileHandle processToken;
        Native(OpenProcessToken(GetCurrentProcess(),8,out processToken),"process_token");
        using (processToken) {
            IntPtr buffer=Marshal.AllocHGlobal(IntPtr.Size);
            try {
                uint needed;
                if (!GetTokenInformation(processToken,19,buffer,(uint)IntPtr.Size,out needed)) {
                    report["filtered_token_error"]=Marshal.GetLastWin32Error(); return false;
                }
                using (SafeFileHandle linked=new SafeFileHandle(Marshal.ReadIntPtr(buffer),true)) {
                    if (!ImpersonateLoggedOnUser(linked)) { report["filtered_token_error"]=Marshal.GetLastWin32Error(); return false; }
                    try {
                        using (WindowsIdentity current=WindowsIdentity.GetCurrent()) {
                            Need(current.User.Value==operatorSid && !new WindowsPrincipal(current).IsInRole(WindowsBuiltInRole.Administrator),"filtered_token_identity");
                        }
                        foreach (uint access in new uint[]{0x80000000,0x40000000,0x10000,0x20000,0x40000,0x80000}) DeniedOpen(markerPath,access,5);
                        return true;
                    } finally { if (!RevertToSelf()) Environment.Exit(70); }
                }
            } finally { Marshal.FreeHGlobal(buffer); }
        }
    }
    public static string FixedFixturePath() { return ParentPath+"\\"+LeafName; }
    public static Dictionary<string,object> Run() {
        Dictionary<string,object> report=new Dictionary<string,object>();
        report["version"]=1; report["fixture_root"]=FixedFixturePath(); report["production_ready"]=false;
        report["production_python_probe_executed"]=false; report["operator_python_executed"]=false;
        report["system_token_test"]="not_performed"; report["real_vm_capability_token_test"]="not_performed";
        report["objects_retained"]=true; report["retry_authorized"]=false;
        List<SafeFileHandle> held=new List<SafeFileHandle>(); List<Snapshot> baselines=new List<Snapshot>();
        try {
            stage="authorization";
            using (WindowsIdentity current=WindowsIdentity.GetCurrent()) {
                Need(new WindowsPrincipal(current).IsInRole(WindowsBuiltInRole.Administrator),"enabled_administrator_required");
                Need(!attempted,"already_attempted"); attempted=true;
                report["operator_sid"]=current.User.Value;
            }
            Need(Environment.Is64BitProcess && Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles)==@"C:\Program Files","fixed_host_profile");
            stage="ancestor_acquisition"; Need(GetDriveTypeW(@"C:\")==3,"fixed_volume");
            SafeFileHandle root=CreateFileW(@"C:\",Metadata|0x20,3,IntPtr.Zero,3,0x2200000,IntPtr.Zero);
            held.Add(root); Need(!root.IsInvalid,"root_open");
            StringBuilder finalName=new StringBuilder(128); uint length=GetFinalPathNameByHandleW(root,finalName,128,1);
            Need(length>0 && length<128 && System.Text.RegularExpressions.Regex.IsMatch(finalName.ToString(),@"^\\\\\?\\Volume\{[0-9a-fA-F-]{36}\}\\$"),"volume_root");
            StringBuilder fs=new StringBuilder(32);
            Native(GetVolumeInformationByHandleW(root,IntPtr.Zero,0,IntPtr.Zero,IntPtr.Zero,IntPtr.Zero,fs,32),"volume_information"); Need(fs.ToString()=="NTFS","ntfs_required");
            Snapshot baseline=Observe(root); Ancestor(baseline); baselines.Add(baseline);
            bool pythonPolicy=PythonAncestorWouldAccept(baseline);
            string[] components=new string[]{"Program Files","AiAgentElevatedCommands","receipts"};
            for (int i=0;i<components.Length;i++) {
                SafeFileHandle next=Relative(held[held.Count-1],components[i],true,false,i==components.Length-1); held.Add(next);
                Snapshot observed=Observe(next); Ancestor(observed); Need(observed.Info.Volume==baseline.Info.Volume,"volume_changed");
                baselines.Add(observed); pythonPolicy &= PythonAncestorWouldAccept(observed);
            }
            report["strict_python_ancestor_policy_passes"]=pythonPolicy;
            report["fixture_ancestor_policy"]="SYSTEM_Administrators_TrustedInstaller_no_untrusted_mutation";
            for (int i=0;i<held.Count;i++) Same(baselines[i],Observe(held[i]),false);
            stage="atomic_private_creation";
            SafeFileHandle store=Relative(held[held.Count-1],LeafName,true,true,true); held.Add(store);
            Snapshot storeBefore=Observe(store); Private(storeBefore,true);
            string markerPath=FixedFixturePath()+"\\probe.bin"; Snapshot markerBefore;
            using (SafeFileHandle marker=Relative(store,"probe.bin",false,true,true)) {
                markerBefore=Observe(marker); Private(markerBefore,false); Need(markerBefore.Size==0,"new_marker_not_empty");
                for (int i=0;i<baselines.Count;i++) Same(baselines[i],Observe(held[i]),false);
                Same(storeBefore,Observe(store),false); Same(markerBefore,Observe(marker),false);
                stage="marker_write"; uint written;
                Native(WriteFile(marker,Marker,(uint)Marker.Length,out written,IntPtr.Zero),"marker_write"); Need(written==Marker.Length,"short_write");
                Native(FlushFileBuffers(marker),"marker_flush"); ReadMarker(marker); Same(markerBefore,Observe(marker),true);
                stage="data_sharing";
                foreach (uint access in new uint[]{0x80000000,0x40000000,0xc0000000}) DeniedOpen(markerPath,access,32);
                using (SafeFileHandle metadata=CreateFileW(markerPath,Metadata,7,IntPtr.Zero,3,0x200000,IntPtr.Zero)) {
                    Need(!metadata.IsInvalid,"metadata_open"); Same(Observe(marker),Observe(metadata),false);
                }
            }
            report["administrators_owner_and_exact_private_dacl"]=true;
            report["exclusive_data_sharing_and_metadata_exception"]=true;
            stage="admin_access_after_producer_close";
            using (SafeFileHandle reader=CreateFileW(markerPath,0x80000000,7,IntPtr.Zero,3,0x200000,IntPtr.Zero)) {
                Need(!reader.IsInvalid,"admin_read_open"); ReadMarker(reader); Same(markerBefore,Observe(reader),true);
            }
            report["actual_enabled_administrator_read"]=true;
            stage="filtered_operator_access_after_producer_close";
            bool filtered=FilteredTokenChecks(markerPath,(string)report["operator_sid"],report);
            report["actual_linked_filtered_operator_six_access_denials"]=filtered;
            stage="collision_refusal"; bool collision=false;
            try { using (SafeFileHandle unwanted=Relative(store,"probe.bin",false,true,true)) {} }
            catch (Fault error) { if (error.Status!=0xc0000035) throw; collision=true; }
            Need(collision,"collision_not_refused");
            using (SafeFileHandle reader=CreateFileW(markerPath,0x80000000,7,IntPtr.Zero,3,0x200000,IntPtr.Zero)) { Need(!reader.IsInvalid,"collision_read_open"); ReadMarker(reader); }
            report["create_new_collision_preserved_marker"]=true;
            stage="directory_replacement_refusal";
            using (SafeFileHandle locked=Relative(store,"held-directory",true,true,true)) {
                Private(Observe(locked),true);
                bool moved=MoveFileExW(FixedFixturePath()+"\\held-directory",FixedFixturePath()+"\\renamed-held-directory",0);
                int error=Marshal.GetLastWin32Error(); Need(!moved && error==32,"directory_rename_not_refused");
            }
            report["held_directory_rename_denied_error32"]=true;
            stage="reparse_refusal"; bool reparse=false;
            using (SafeFileHandle target=Relative(store,"reparse-target",true,true,true)) {
                Private(Observe(target),true);
                if (CreateSymbolicLinkW(FixedFixturePath()+"\\reparse-link",FixedFixturePath()+"\\reparse-target",1)) {
                    try {
                        using (SafeFileHandle link=Relative(store,"reparse-link",true,false,false)) {
                            Snapshot observed=Observe(link);
                            Need((observed.Info.Attributes & 0x400)!=0,"reparse_target_was_followed");
                            bool refused=false; try { Private(observed,true); } catch (Fault fault) { if (fault.Code!="object_shape") throw; refused=true; }
                            Need(refused,"reparse_shape_not_refused"); reparse=true;
                        }
                    } catch (Fault error) { if (error.Status!=0xc000050b) throw; reparse=true; }
                } else report["reparse_creation_error"]=Marshal.GetLastWin32Error();
            }
            report["native_reparse_refusal"]=reparse;
            stage="hardlink_refusal";
            Native(CreateHardLinkW(FixedFixturePath()+"\\probe-alias.bin",markerPath,IntPtr.Zero),"hardlink_create");
            using (SafeFileHandle linked=CreateFileW(markerPath,Metadata,7,IntPtr.Zero,3,0x200000,IntPtr.Zero)) {
                Need(!linked.IsInvalid,"hardlink_open"); Snapshot observed=Observe(linked); Need(observed.Info.Links==2,"hardlink_count");
                bool refused=false; try { Private(observed,false); } catch (Fault fault) { if (fault.Code!="object_shape") throw; refused=true; }
                Need(refused,"hardlink_not_refused");
            }
            report["native_multilink_refusal"]=true;
            stage="final_preservation"; Same(storeBefore,Observe(store),false);
            for (int i=0;i<baselines.Count;i++) Same(baselines[i],Observe(held[i]),false);
            report["held_ancestor_and_store_identity_security_stable"]=true;
            report["status"]=(filtered && reparse) ? "completed_non_secret_profile_fixture" : "partial_non_secret_profile_fixture";
        } catch (Fault error) {
            report["status"]="failed"; report["failure_stage"]=stage; report["failure_code"]=error.Code;
            report["win32_error"]=error.Error; report["nt_status"]=error.Status;
        } catch {
            report["status"]="failed"; report["failure_stage"]=stage; report["failure_code"]="managed_failure";
        } finally { for (int i=held.Count-1;i>=0;i--) held[i].Dispose(); }
        return report;
    }
}
'@
Add-Type -TypeDefinition $native -ReferencedAssemblies @('System.dll','System.Core.dll','System.Security.dll')
$result = [NativeStoreProfileFixtureV1]::Run()
$result | ConvertTo-Json -Depth 6 -Compress
if ($result['status'] -cne 'completed_non_secret_profile_fixture') {
    throw 'Non-secret fixture incomplete or failed; retain objects and receipt; no retry authorized'
}
