// Native adapter for the UNWIRED pre-import acquisition/claim body.
// No executable, deployment, watchdog, Python, process launch or permission repair.
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Text;
using System.Text.RegularExpressions;
namespace AiAgent.NativeValidator {
    internal static class BoundarySecurity {
        internal const string Admins="S-1-5-32-544", System="S-1-5-18";
        internal const string ClaimSddl="O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)";
        internal static void Check(string text,bool directory,bool ancestor) {
            var descriptor=new RawSecurityDescriptor(text); RawAcl acl=descriptor.DiscretionaryAcl;
            if (descriptor.Owner==null || (descriptor.Owner.Value!=Admins && descriptor.Owner.Value!=System) ||
                (descriptor.ControlFlags&ControlFlags.DiscretionaryAclPresent)==0 || acl==null || acl.Count<1 || acl.Count>128)
                throw new BoundaryRefused("security");
            var remaining=new HashSet<string>(new string[] {Admins,System},StringComparer.Ordinal);
            if (!ancestor && ((descriptor.ControlFlags&ControlFlags.DiscretionaryAclProtected)==0 ||
                descriptor.Group==null || descriptor.Group.Value!=Admins || acl.Count!=2)) throw new BoundaryRefused("private_security");
            foreach (GenericAce raw in acl) {
                var ace=raw as CommonAce;
                if (ace==null || ace.IsCallback || (ace.AceType!=AceType.AccessAllowed && ace.AceType!=AceType.AccessDenied) ||
                    ((int)ace.AceFlags&~31)!=0) throw new BoundaryRefused("security_ace");
                string sid=ace.SecurityIdentifier.Value;
                if (!ancestor) {
                    if (ace.AceType!=AceType.AccessAllowed || (int)ace.AceFlags!=(directory?3:0) ||
                        ace.AccessMask!=0x1f01ff || !remaining.Remove(sid)) throw new BoundaryRefused("private_security");
                } else if (((int)ace.AceFlags&8)==0 && ace.AceType==AceType.AccessAllowed && sid!=Admins && sid!=System) {
                    // Same ancestor mutation policy as the native marker primitive.
                    // Unrelated sibling creation is harmless; delete-child, ACL/
                    // owner/EA/attribute mutation and generic write/all are not.
                    uint harmless=0x1200a9u|2u|4u|0x80000000u|0x20000000u;
                    if ((unchecked((uint)ace.AccessMask)&~harmless)!=0) throw new BoundaryRefused("ancestor_security");
                }
            }
        }
    }
    internal sealed class WindowsBoundaryFiles : IBoundaryFiles {
        [StructLayout(LayoutKind.Sequential)] internal struct UnicodeName {
            internal ushort Length, Maximum; internal IntPtr Buffer;
        }
        [StructLayout(LayoutKind.Sequential)] internal struct ObjectAttributes {
            internal uint Length; internal IntPtr Root, Name; internal uint Attributes; internal IntPtr Security, Qos;
        }
        [StructLayout(LayoutKind.Sequential)] internal struct IoStatus {
            internal IntPtr Status; internal UIntPtr Information;
        }
        [StructLayout(LayoutKind.Sequential)] internal struct FileTime { internal uint Low, High; }
        [StructLayout(LayoutKind.Sequential)] internal struct FileInfo {
            internal uint Attributes; internal FileTime Created, Accessed, Written;
            internal uint Volume, SizeHigh, SizeLow, Links, IndexHigh, IndexLow;
        }
        [DllImport("kernel32.dll",ExactSpelling=true,CharSet=CharSet.Unicode,SetLastError=true)]
        static extern IntPtr CreateFileW(string name,uint access,uint share,IntPtr security,uint disposition,uint flags,IntPtr template);
        [DllImport("kernel32.dll",ExactSpelling=true,CharSet=CharSet.Unicode)] static extern uint GetDriveTypeW(string root);
        [DllImport("kernel32.dll",ExactSpelling=true,CharSet=CharSet.Unicode,SetLastError=true)]
        static extern bool GetVolumeInformationByHandleW(IntPtr handle,StringBuilder label,uint count,IntPtr serial,
            IntPtr maxComponent,IntPtr flags,StringBuilder filesystem,uint filesystemCount);
        [DllImport("kernel32.dll",ExactSpelling=true,SetLastError=true)] static extern uint GetFileType(IntPtr handle);
        [DllImport("kernel32.dll",ExactSpelling=true,SetLastError=true)] static extern bool GetFileInformationByHandle(IntPtr handle,out FileInfo info);
        [DllImport("kernel32.dll",ExactSpelling=true,SetLastError=true)] static extern bool GetFileInformationByHandleEx(IntPtr handle,int kind,IntPtr buffer,uint size);
        [DllImport("kernel32.dll",ExactSpelling=true,CharSet=CharSet.Unicode,SetLastError=true)]
        static extern uint GetFinalPathNameByHandleW(IntPtr handle,StringBuilder name,uint count,uint flags);
        [DllImport("advapi32.dll",ExactSpelling=true)]
        static extern uint GetSecurityInfo(IntPtr handle,int kind,uint sections,out IntPtr owner,out IntPtr group,
            out IntPtr dacl,IntPtr sacl,out IntPtr descriptor);
        [DllImport("advapi32.dll",ExactSpelling=true,CharSet=CharSet.Unicode,SetLastError=true)]
        static extern bool ConvertSecurityDescriptorToStringSecurityDescriptorW(IntPtr descriptor,uint revision,uint sections,out IntPtr text,out uint length);
        [DllImport("advapi32.dll",ExactSpelling=true,CharSet=CharSet.Unicode,SetLastError=true)]
        static extern bool ConvertStringSecurityDescriptorToSecurityDescriptorW(string text,uint revision,out IntPtr descriptor,out uint length);
        [DllImport("ntdll.dll",ExactSpelling=true)]
        static extern int NtCreateFile(out IntPtr handle,uint access,ref ObjectAttributes attributes,out IoStatus status,
            IntPtr size,uint fileAttributes,uint sharing,uint disposition,uint options,IntPtr ea,uint eaBytes);
        [DllImport("kernel32.dll",ExactSpelling=true,SetLastError=true)] static extern bool SetFilePointerEx(IntPtr handle,long distance,out long position,uint method);
        [DllImport("kernel32.dll",ExactSpelling=true,SetLastError=true)] static extern bool ReadFile(IntPtr handle,[Out] byte[] bytes,uint count,out uint read,IntPtr overlapped);
        [DllImport("kernel32.dll",ExactSpelling=true,SetLastError=true)] static extern bool WriteFile(IntPtr handle,byte[] bytes,uint count,out uint written,IntPtr overlapped);
        [DllImport("kernel32.dll",ExactSpelling=true,SetLastError=true)] static extern bool FlushFileBuffers(IntPtr handle);
        [DllImport("kernel32.dll",ExactSpelling=true,SetLastError=true)] static extern bool CloseHandle(IntPtr handle);
        [DllImport("kernel32.dll",ExactSpelling=true)] static extern IntPtr LocalFree(IntPtr value);
        static void ReleaseLocal(ref IntPtr value) {
            IntPtr releasing=value; value=IntPtr.Zero;
            if (releasing!=IntPtr.Zero && LocalFree(releasing)!=IntPtr.Zero) throw new BoundaryUnknown("native_release_unknown");
        }
        static void ReleaseBuffer(ref IntPtr value) {
            IntPtr releasing=value; value=IntPtr.Zero;
            if (releasing!=IntPtr.Zero) Marshal.FreeHGlobal(releasing);
        }
        public void RequireOperator(string sid) {
            if (Environment.OSVersion.Platform!=PlatformID.Win32NT || IntPtr.Size!=8) throw new BoundaryRefused("native_windows_x64");
            using (WindowsIdentity identity=WindowsIdentity.GetCurrent()) {
                if (identity.User==null || identity.User.Value!=sid || !new WindowsPrincipal(identity).IsInRole(WindowsBuiltInRole.Administrator))
                    throw new BoundaryRefused("enabled_operator_required");
            }
        }
        public object Root(string drive) {
            if (drive==null || !Regex.IsMatch(drive,@"\A[A-Za-z]:\\\z") || GetDriveTypeW(drive)!=3) throw new BoundaryRefused("fixed_local_volume");
            IntPtr handle=CreateFileW(drive,0x1200a1,3,IntPtr.Zero,3,0x02200000,IntPtr.Zero);
            if (handle==IntPtr.Zero || handle==new IntPtr(-1)) throw new BoundaryRefused("root_open");
            try {
                var fs=new StringBuilder(32);
                if (!GetVolumeInformationByHandleW(handle,null,0,IntPtr.Zero,IntPtr.Zero,IntPtr.Zero,fs,32) || fs.ToString()!="NTFS")
                    throw new BoundaryRefused("ntfs_required");
                if (!Regex.IsMatch(FinalName(handle),@"\A\\\\\?\\Volume\{[0-9a-fA-F-]{36}\}\\\z")) throw new BoundaryRefused("volume_root");
                return handle;
            } catch { Close(handle); throw; }
        }
        public object Open(object parent,string name,bool directory) { return Relative((IntPtr)parent,name,directory,false); }
        public object CreateClaim(object parent) { return Relative((IntPtr)parent,InstallBoundary.ClaimName,false,true); }
        IntPtr Relative(IntPtr parent,string name,bool directory,bool create) {
            InstallBoundary.Component(name);
            IntPtr nameBuffer=IntPtr.Zero, textBuffer=IntPtr.Zero, descriptor=IntPtr.Zero, handle=IntPtr.Zero;
            try {
                nameBuffer=Marshal.StringToHGlobalUni(name);
                var text=new UnicodeName {Length=(ushort)(name.Length*2),Maximum=(ushort)((name.Length+1)*2),Buffer=nameBuffer};
                textBuffer=Marshal.AllocHGlobal(Marshal.SizeOf(typeof(UnicodeName))); Marshal.StructureToPtr(text,textBuffer,false);
                if (create) {
                    uint length;
                    if (!ConvertStringSecurityDescriptorToSecurityDescriptorW(BoundarySecurity.ClaimSddl,1,out descriptor,out length))
                        throw new BoundaryRefused("claim_descriptor");
                }
                var attributes=new ObjectAttributes {Length=(uint)Marshal.SizeOf(typeof(ObjectAttributes)),
                    Root=parent,Name=textBuffer,Attributes=0x1040,Security=descriptor};
                IoStatus status;
                uint access=directory?0x1200a1u:(create?0xc0120080u:0x80120080u);
                uint options=directory ? 0x200021u : 0x200060u;
                int result=NtCreateFile(out handle,access,ref attributes,out status,IntPtr.Zero,0,
                    directory?3u:(create?0u:1u),create?2u:1u,options,IntPtr.Zero,0);
                if (result!=0) throw new BoundaryRefused(create?"claim_collision_or_create_refused":"relative_open");
                if (handle==IntPtr.Zero || handle==new IntPtr(-1) || status.Information.ToUInt64()!=(create?2ul:1ul))
                    throw new BoundaryUnknown("create_disposition_unknown");
                // Release ALL scratch allocations before transferring the handle.
                // A release failure must not strand an unowned returned handle.
                ReleaseLocal(ref descriptor); ReleaseBuffer(ref textBuffer); ReleaseBuffer(ref nameBuffer);
                IntPtr owned=handle; handle=IntPtr.Zero; return owned;
            } finally {
                bool unknown=false;
                if (handle!=IntPtr.Zero && handle!=new IntPtr(-1)) {
                    IntPtr closing=handle; handle=IntPtr.Zero; if (!CloseHandle(closing)) unknown=true;
                }
                try { ReleaseLocal(ref descriptor); } catch { unknown=true; }
                try { ReleaseBuffer(ref textBuffer); } catch { unknown=true; }
                try { ReleaseBuffer(ref nameBuffer); } catch { unknown=true; }
                if (unknown) throw new BoundaryUnknown("native_release_unknown");
            }
        }
        static string FinalName(IntPtr handle) {
            var name=new StringBuilder(512); uint count=GetFinalPathNameByHandleW(handle,name,512,1);
            if (count<1 || count>=512) throw new BoundaryRefused("final_name"); return name.ToString();
        }
        static string Security(IntPtr handle) {
            IntPtr owner,group,dacl,descriptor,text=IntPtr.Zero;
            uint error=GetSecurityInfo(handle,1,7,out owner,out group,out dacl,IntPtr.Zero,out descriptor);
            try {
                uint length;
                if (error!=0 || descriptor==IntPtr.Zero || owner==IntPtr.Zero || group==IntPtr.Zero || dacl==IntPtr.Zero ||
                    !ConvertSecurityDescriptorToStringSecurityDescriptorW(descriptor,1,7,out text,out length) ||
                    text==IntPtr.Zero || length<1 || length>65536) throw new BoundaryRefused("security_query");
                return Marshal.PtrToStringUni(text);
            } finally {
                bool unknown=false;
                try { ReleaseLocal(ref text); } catch { unknown=true; }
                try { ReleaseLocal(ref descriptor); } catch { unknown=true; }
                if (unknown) throw new BoundaryUnknown("native_release_unknown");
            }
        }
        public Stamp Observe(object value,bool directory,bool ancestor) {
            IntPtr handle=(IntPtr)value; FileInfo info;
            if (GetFileType(handle)!=1 || !GetFileInformationByHandle(handle,out info)) throw new BoundaryRefused("file_query");
            ulong index=((ulong)info.IndexHigh<<32)|info.IndexLow, size=((ulong)info.SizeHigh<<32)|info.SizeLow;
            if (index==0 || size>Int64.MaxValue || info.Links!=1 || (info.Attributes&0x5e00)!=0 || ((info.Attributes&16)!=0)!=directory)
                throw new BoundaryRefused("object_shape");
            string security=Security(handle); BoundarySecurity.Check(security,directory,ancestor);
            return new Stamp {Volume=info.Volume,Index=index,Attributes=info.Attributes,Links=info.Links,Bytes=(long)size,
                Security=security,Private=!ancestor,FinalName=FinalName(handle)};
        }
        // FILE_ID_BOTH_DIR_INFO: FileNameLength @60, FileName @104.
        internal static void DecodeNames(byte[] buffer,List<string> names) {
            int offset=0;
            while (true) {
                if (offset<0 || offset>buffer.Length-104) throw new BoundaryRefused("directory_buffer");
                uint next=BitConverter.ToUInt32(buffer,offset), length=BitConverter.ToUInt32(buffer,offset+60);
                if (length<2 || length>240 || (length&1)!=0 || length>buffer.Length-offset-104 ||
                    (next!=0 && ((next&7)!=0 || next<104+length || next>buffer.Length-offset-104))) throw new BoundaryRefused("directory_buffer");
                string name=Encoding.Unicode.GetString(buffer,offset+104,(int)length);
                if (name!="." && name!="..") {
                    InstallBoundary.Component(name);
                    if (names.Count >= 128 || names.Contains(name)) throw new BoundaryRefused("directory_extent"); names.Add(name);
                }
                if (next==0) return; offset+=(int)next;
            }
        }
        public string[] Names(object directory) {
            IntPtr buffer=Marshal.AllocHGlobal(65536);
            try {
                var names=new List<string>(); bool first=true;
                for (int page=0;page<128;page++) {
                    // Clear unused bytes; this API does not return a byte count.
                    Marshal.Copy(new byte[65536],0,buffer,65536);
                    if (!GetFileInformationByHandleEx((IntPtr)directory,first?11:10,buffer,65536)) {
                        if (Marshal.GetLastWin32Error() == 18) return names.ToArray(); throw new BoundaryRefused("directory_query");
                    }
                    first=false; byte[] bytes=new byte[65536]; Marshal.Copy(buffer,bytes,0,bytes.Length); DecodeNames(bytes,names);
                }
                throw new BoundaryRefused("directory_extent");
            } finally { Marshal.FreeHGlobal(buffer); }
        }
        public void Rewind(object handle) {
            long position;
            if (!SetFilePointerEx((IntPtr)handle,0,out position,0) || position!=0) throw new BoundaryUnknown("seek_unknown");
        }
        public int Read(object handle,byte[] bytes,int count) {
            if (count<1 || count>bytes.Length) throw new BoundaryRefused("read_extent"); uint read;
            if (!ReadFile((IntPtr)handle,bytes,(uint)count,out read,IntPtr.Zero)) throw new BoundaryUnknown("read_unknown");
            if (read>count) throw new BoundaryRefused("read_extent"); return (int)read;
        }
        public void WriteClaim(object handle,byte[] bytes) {
            if (bytes==null || bytes.Length<1 || bytes.Length>1024) throw new BoundaryRefused("claim_size"); uint written;
            if (!WriteFile((IntPtr)handle,bytes,(uint)bytes.Length,out written,IntPtr.Zero) || written!=bytes.Length)
                throw new BoundaryUnknown("claim_write_unknown");
            if (!FlushFileBuffers((IntPtr)handle)) throw new BoundaryUnknown("claim_flush_unknown");
        }
        public void Close(object handle) { if (!CloseHandle((IntPtr)handle)) throw new BoundaryUnknown("close_unknown"); }
    }
}
