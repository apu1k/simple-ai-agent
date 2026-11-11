// Uninstalled create-new SETUP adapter. No launch, deletion, ACL repair or retry.
// Trusted loader/approval/watchdog prerequisites are EXTERNAL, not self-attested.
using System;
using System.Runtime.InteropServices;
using System.Text;
using AiAgent.NativeValidator;
namespace AiAgent.ValidatorSetup {
    internal sealed class WindowsSetupFiles : ISetupFiles {
        readonly WindowsBoundaryFiles read=new WindowsBoundaryFiles();
        [DllImport("ntdll.dll",ExactSpelling=true)]
        static extern int NtCreateFile(out IntPtr handle,uint access,ref WindowsBoundaryFiles.ObjectAttributes attributes,
            out WindowsBoundaryFiles.IoStatus status,IntPtr size,uint fileAttributes,uint sharing,uint disposition,uint options,IntPtr ea,uint eaBytes);
        [DllImport("advapi32.dll",ExactSpelling=true,CharSet=CharSet.Unicode,SetLastError=true)]
        static extern bool ConvertStringSecurityDescriptorToSecurityDescriptorW(string text,uint revision,out IntPtr descriptor,out uint length);
        [DllImport("kernel32.dll",ExactSpelling=true,SetLastError=true)]
        static extern bool GetFileInformationByHandleEx(IntPtr handle,int kind,out uint flags,uint size);
        [DllImport("kernel32.dll",ExactSpelling=true,SetLastError=true)]
        static extern bool WriteFile(IntPtr handle,byte[] data,uint bytes,out uint written,IntPtr overlapped);
        [DllImport("kernel32.dll",ExactSpelling=true,SetLastError=true)] static extern bool FlushFileBuffers(IntPtr handle);
        [DllImport("kernel32.dll",ExactSpelling=true)] static extern IntPtr LocalFree(IntPtr pointer);
        static void Free(ref IntPtr pointer,bool local) {
            IntPtr old=pointer; pointer=IntPtr.Zero;
            if (old==IntPtr.Zero) return;
            if (local) { if (LocalFree(old)!=IntPtr.Zero) throw new SetupUnknown("native_release_unknown"); }
            else Marshal.FreeHGlobal(old);
        }
        public void RequireOperator(string sid) { read.RequireOperator(sid); }
        public object Root(string drive) { return read.Root(drive); }
        public object Open(object parent,string name,bool directory) { return read.Open(parent,name,directory); }
        public Stamp Observe(object handle,bool directory,bool ancestor) {
            Stamp stamp=read.Observe(handle,directory,ancestor);
            uint flags;
            if (directory && (!GetFileInformationByHandleEx((IntPtr)handle,23,out flags,4) || flags!=0))
                throw new SetupRefused("case_sensitive_directory");
            return stamp;
        }
        public string[] Names(object handle) { return read.Names(handle); }
        public void Rewind(object handle) { read.Rewind(handle); }
        public int Read(object handle,byte[] data,int count) { return read.Read(handle,data,count); }
        public void Close(object handle) { read.Close(handle); }
        public object Create(object parent,string name,bool directory) {
            InstallBoundary.Component(name);
            IntPtr nameBuffer=IntPtr.Zero,textBuffer=IntPtr.Zero,descriptor=IntPtr.Zero,handle=IntPtr.Zero;
            try {
                nameBuffer=Marshal.StringToHGlobalUni(name);
                var text=new WindowsBoundaryFiles.UnicodeName {Length=(ushort)(name.Length*2),
                    Maximum=(ushort)((name.Length+1)*2),Buffer=nameBuffer};
                textBuffer=Marshal.AllocHGlobal(Marshal.SizeOf(typeof(WindowsBoundaryFiles.UnicodeName)));
                Marshal.StructureToPtr(text,textBuffer,false);
                string sddl=directory?"O:BAG:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)":BoundarySecurity.ClaimSddl;
                uint length;
                if (!ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl,1,out descriptor,out length))
                    throw new SetupRefused("create_descriptor");
                var attributes=new WindowsBoundaryFiles.ObjectAttributes {
                    Length=(uint)Marshal.SizeOf(typeof(WindowsBoundaryFiles.ObjectAttributes)),Root=(IntPtr)parent,
                    Name=textBuffer,Attributes=0x1040,Security=descriptor};
                WindowsBoundaryFiles.IoStatus status;
                // FILE_CREATE only. Never OPEN_IF, overwrite, path fallback, named
                // alternative or permission repair. Non-inheritable relative opens.
                int result=NtCreateFile(out handle,directory?0x1200a7u:0xc0120080u,ref attributes,out status,IntPtr.Zero,
                    0,directory?3u:0u,2,directory?0x200021u:0x200060u,IntPtr.Zero,0);
                if (result!=0) throw new SetupRefused("create_collision_or_refused");
                if (handle==IntPtr.Zero || handle==new IntPtr(-1) || status.Information.ToUInt64()!=2)
                    throw new SetupUnknown("create_disposition_unknown");
                Free(ref descriptor,true); Free(ref textBuffer,false); Free(ref nameBuffer,false);
                object owned=handle; handle=IntPtr.Zero; return owned;
            } finally {
                bool unknown=false;
                if (handle!=IntPtr.Zero && handle!=new IntPtr(-1)) {
                    IntPtr old=handle; handle=IntPtr.Zero; try { read.Close(old); } catch { unknown=true; }
                }
                try { Free(ref descriptor,true); } catch { unknown=true; }
                try { Free(ref textBuffer,false); } catch { unknown=true; }
                try { Free(ref nameBuffer,false); } catch { unknown=true; }
                if (unknown) throw new SetupUnknown("native_release_unknown");
            }
        }
        public void Write(object handle,byte[] data) {
            if (data==null || data.Length>32*1024*1024) throw new SetupRefused("write_extent");
            // Setup has no child. A short/uncertain write is terminal; leave the
            // exact partial object and permanent publication claim for review.
            uint written;
            if (data.Length!=0 && (!WriteFile((IntPtr)handle,data,(uint)data.Length,out written,IntPtr.Zero) || written!=data.Length))
                throw new SetupUnknown("write_unknown");
            if (!FlushFileBuffers((IntPtr)handle)) throw new SetupUnknown("flush_unknown");
        }
    }
}
