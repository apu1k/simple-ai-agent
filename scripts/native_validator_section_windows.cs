// UNINSTALLED fixed section publisher / guardian worker adapter. NEVER load
// checkout code elevated. Trusted pre-load/approval/held-target/watchdog route
// MUST precede use. No Main, default registration, tool, shell or fallback.
using System;
using System.Runtime.InteropServices;
using System.Text;
using AiAgent.ValidatorGuardian;
using WG=AiAgent.ValidatorGuardian.WindowsGuardianKernel;
namespace AiAgent.ValidatorDelivery {
    internal sealed class WindowsSectionCounter : ISectionCounter {
        [DllImport("kernel32.dll",ExactSpelling=true)] static extern bool QueryPerformanceCounter(out long value);
        [DllImport("kernel32.dll",ExactSpelling=true)] static extern bool QueryPerformanceFrequency(out long value);
        public long Frequency() {
            long value; if (!QueryPerformanceFrequency(out value)) throw new GuardianUnknown("section_counter_unknown"); return value;
        }
        public long Read() {
            long value; if (!QueryPerformanceCounter(out value)) throw new GuardianUnknown("section_counter_unknown"); return value;
        }
    }
    internal sealed class WindowsSectionMemory : ISectionMemory {
        internal const uint SectionMapRead=4,SectionAllAccess=0x000f001f;
        const uint PageReadWrite=4,FileMapWrite=2;
        [StructLayout(LayoutKind.Sequential)] struct BasicInfo {
            internal uint Attributes,GrantedAccess,HandleCount,PointerCount;
            [MarshalAs(UnmanagedType.ByValArray,SizeConst=10)] internal uint[] Reserved;
        }
        [DllImport("ntdll.dll",ExactSpelling=true)]
        static extern int NtQueryObject(IntPtr handle,int kind,out BasicInfo info,uint size,out uint returned);
        [DllImport("kernel32.dll",ExactSpelling=true,CharSet=CharSet.Unicode)]
        static extern IntPtr CreateFileMappingW(IntPtr file,ref WG.SecurityAttributes security,uint protect,uint high,uint low,string name);
        [DllImport("kernel32.dll",ExactSpelling=true)]
        static extern IntPtr MapViewOfFile(IntPtr handle,uint access,uint high,uint low,UIntPtr size);
        [DllImport("kernel32.dll",ExactSpelling=true)] static extern bool UnmapViewOfFile(IntPtr view);
        [DllImport("kernel32.dll",ExactSpelling=true)]
        static extern bool DuplicateHandle(IntPtr source,IntPtr handle,IntPtr target,out IntPtr copy,uint access,bool inherit,uint options);
        [DllImport("kernel32.dll",ExactSpelling=true)] static extern bool GetHandleInformation(IntPtr handle,out uint flags);
        [DllImport("kernel32.dll",ExactSpelling=true)] static extern bool CloseHandle(IntPtr handle);
        [DllImport("kernel32.dll",ExactSpelling=true)] static extern IntPtr LocalFree(IntPtr value);
        [DllImport("advapi32.dll",ExactSpelling=true,CharSet=CharSet.Unicode)]
        static extern bool ConvertStringSecurityDescriptorToSecurityDescriptorW(string text,uint revision,out IntPtr descriptor,out uint size);
        internal static void CloseNative(ref IntPtr value) {
            IntPtr old=value; value=IntPtr.Zero;
            if (old!=IntPtr.Zero && !CloseHandle(old)) throw new GuardianUnknown("section_native_close_unknown");
        }
        internal static void FreeLocal(ref IntPtr value) {
            IntPtr old=value; value=IntPtr.Zero;
            if (old!=IntPtr.Zero && LocalFree(old)!=IntPtr.Zero) throw new GuardianUnknown("section_native_release_unknown");
        }
        internal static void FreeBuffer(ref IntPtr value) {
            IntPtr old=value; value=IntPtr.Zero; if (old!=IntPtr.Zero) Marshal.FreeHGlobal(old);
        }
        internal static WG.SecurityAttributes Descriptor(out IntPtr value) {
            uint size;
            if (!ConvertStringSecurityDescriptorToSecurityDescriptorW(WG.ObjectSddl,1,out value,out size))
                throw new GuardianRefused("section_descriptor");
            return new WG.SecurityAttributes {Length=(uint)Marshal.SizeOf(typeof(WG.SecurityAttributes)),Descriptor=value,Inherit=0};
        }
        static void Bound(int bytes) { if (bytes<1 || bytes>32768) throw new GuardianRefused("section_extent"); }
        public object NewSection(int bytes) {
            Bound(bytes); IntPtr descriptor=IntPtr.Zero,handle=IntPtr.Zero;
            try {
                WG.SecurityAttributes security=Descriptor(out descriptor);
                handle=CreateFileMappingW(new IntPtr(-1),ref security,PageReadWrite,0,(uint)bytes,null);
                if (handle==IntPtr.Zero || handle==new IntPtr(-1)) throw new GuardianRefused("section_create");
                FreeLocal(ref descriptor); object owned=handle; handle=IntPtr.Zero; return owned;
            } finally {
                bool unknown=false;
                try { CloseNative(ref handle); } catch { unknown=true; }
                try { FreeLocal(ref descriptor); } catch { unknown=true; }
                if (unknown) throw new GuardianUnknown("section_native_release_unknown");
            }
        }
        public void RequireHandle(object handle,bool readOnly,bool inheritable) {
            IntPtr value=(IntPtr)handle; uint flags,returned; BasicInfo actual;
            uint size=(uint)Marshal.SizeOf(typeof(BasicInfo));
            if (value==IntPtr.Zero || value==new IntPtr(-1) || !GetHandleInformation(value,out flags) || flags!=(inheritable?1u:0u) ||
                NtQueryObject(value,0,out actual,size,out returned)!=0 || returned!=size ||
                actual.GrantedAccess!=(readOnly?SectionMapRead:SectionAllAccess)) throw new GuardianRefused("section_rights");
        }
        public object Map(object handle,int bytes,bool write) {
            Bound(bytes); IntPtr view=MapViewOfFile((IntPtr)handle,write?FileMapWrite:SectionMapRead,0,0,new UIntPtr((uint)bytes));
            if (view==IntPtr.Zero) throw new GuardianRefused("section_map"); return view;
        }
        public void Write(object view,byte[] bytes) {
            if (bytes==null) throw new GuardianRefused("section_extent"); Bound(bytes.Length);
            Marshal.Copy(bytes,0,(IntPtr)view,bytes.Length);
        }
        public byte[] Copy(object view,int bytes) {
            Bound(bytes); byte[] raw=new byte[bytes]; Marshal.Copy((IntPtr)view,raw,0,bytes); return raw;
        }
        public object ReadOnlyDuplicate(object writer) {
            IntPtr read=IntPtr.Zero;
            try {
                if (!DuplicateHandle(new IntPtr(-1),(IntPtr)writer,new IntPtr(-1),out read,SectionMapRead,true,0) ||
                    read==IntPtr.Zero || read==new IntPtr(-1)) throw new GuardianRefused("section_duplicate");
                object owned=read; read=IntPtr.Zero; return owned;
            } finally { CloseNative(ref read); }
        }
        public void Unmap(object view) {
            if (!UnmapViewOfFile((IntPtr)view)) throw new GuardianUnknown("section_native_unmap_unknown");
        }
        public void Close(object handle) { IntPtr value=(IntPtr)handle; CloseNative(ref value); }
    }
    internal sealed class WindowsSectionGuardianKernel : IGuardianRequestKernel {
        internal const uint HandleListAttribute=0x00020002;
        readonly WG control=new WG();
        readonly ISectionMemory memory=new WindowsSectionMemory();
        readonly ISectionCounter counter;
        GuardianRequest request;
        GuardianPlan plan;
        SectionWindow window;
        object exactJob;
        bool requestBound,windowBound,jobAttempted,createAttempted;
        internal WindowsSectionGuardianKernel() : this(new WindowsSectionCounter()) { }
        internal WindowsSectionGuardianKernel(ISectionCounter value) {
            if (value==null) throw new GuardianRefused("section_counter_plan"); counter=value;
        }
        static bool Same(GuardianPlan a,GuardianPlan b) {
            return a!=null && b!=null && a.Root==b.Root && a.OperatorSid==b.OperatorSid &&
                a.InstallationId==b.InstallationId && a.ApprovalSha256==b.ApprovalSha256 &&
                a.ApprovedUntilUnix==b.ApprovedUntilUnix && a.BudgetSeconds==b.BudgetSeconds;
        }
        public void BindRequest(GuardianRequest value) {
            if (requestBound) throw new GuardianRefused("section_request_one_shot"); requestBound=true;
            if (value==null) throw new GuardianRefused("section_request_binding"); request=value;
        }
        public void BindWindow(GuardianPlan value,IGuardianClock clock,double stopAt) {
            if (windowBound) throw new GuardianRefused("section_window_one_shot"); windowBound=true;
            if (request==null || plan==null || exactJob==null || !Same(value,request.Plan) || !Same(value,plan))
                throw new GuardianRefused("section_window_binding");
            window=new SectionWindow(clock,stopAt,value.ApprovedUntilUnix); // NO native work/sampling
        }
        public void RequireHost(GuardianPlan value) {
            if (request==null || !Same(value,request.Plan) || (plan!=null && !Same(plan,value)))
                throw new GuardianRefused("section_host_binding");
            control.RequireHost(value); plan=value; // role check, NOT pre-load/approval authentication
        }
        public object NewJob() {
            if (jobAttempted || plan==null) throw new GuardianRefused("section_job_one_shot"); jobAttempted=true;
            exactJob=control.NewJob(); return exactJob; // exact private two-process kill-on-close job
        }
        [DllImport("kernel32.dll",ExactSpelling=true,SetLastError=true)]
        static extern bool InitializeProcThreadAttributeList(IntPtr list,int count,uint flags,ref UIntPtr size);
        [DllImport("kernel32.dll",ExactSpelling=true,SetLastError=true)]
        static extern bool UpdateProcThreadAttribute(IntPtr list,uint flags,UIntPtr attribute,IntPtr value,UIntPtr size,IntPtr previous,IntPtr returned);
        [DllImport("kernel32.dll",ExactSpelling=true)] static extern void DeleteProcThreadAttributeList(IntPtr list);
        [DllImport("kernel32.dll",ExactSpelling=true,CharSet=CharSet.Unicode)] static extern uint GetWindowsDirectoryW(StringBuilder path,uint size);
        [DllImport("kernel32.dll",ExactSpelling=true,CharSet=CharSet.Unicode)] static extern uint GetSystemDirectoryW(StringBuilder path,uint size);
        [DllImport("kernel32.dll",ExactSpelling=true,CharSet=CharSet.Unicode)]
        static extern bool CreateProcessW(string exe,StringBuilder command,ref WG.SecurityAttributes processSecurity,
            ref WG.SecurityAttributes threadSecurity,bool inherit,uint flags,IntPtr environment,string cwd,ref WG.StartupEx startup,out WG.ProcessInfo info);
        sealed class State {
            internal IntPtr Attributes,JobArray,HandleArray,Environment,Descriptor;
            internal bool Ready;
            internal WG.ProcessInfo Child;
            internal ReadOnlyRequestSection Section;
            internal void Scratch() {
                bool unknown=false;
                if (Ready) { Ready=false; try { DeleteProcThreadAttributeList(Attributes); } catch { unknown=true; } }
                try { WindowsSectionMemory.FreeBuffer(ref Attributes); } catch { unknown=true; }
                try { WindowsSectionMemory.FreeBuffer(ref JobArray); } catch { unknown=true; }
                try { WindowsSectionMemory.FreeBuffer(ref HandleArray); } catch { unknown=true; }
                try { WindowsSectionMemory.FreeBuffer(ref Environment); } catch { unknown=true; }
                try { WindowsSectionMemory.FreeLocal(ref Descriptor); } catch { unknown=true; }
                ReadOnlyRequestSection old=Section; Section=null;
                try { if (old!=null) old.Close(); } catch { unknown=true; }
                if (unknown) throw new GuardianUnknown("section_launch_release_unknown");
            }
            internal void Close() {
                bool unknown=false;
                try { WindowsSectionMemory.CloseNative(ref Child.Thread); } catch { unknown=true; }
                try { WindowsSectionMemory.CloseNative(ref Child.Process); } catch { unknown=true; }
                try { Scratch(); } catch { unknown=true; }
                if (unknown) throw new GuardianUnknown("section_launch_release_unknown");
            }
        }
        public ChildPair CreateSuspended(object job,string root) {
            if (createAttempted) throw new GuardianRefused("section_create_one_shot"); createAttempted=true;
            if (request==null || plan==null || window==null || exactJob==null || !Object.Equals(job,exactJob) || root!=plan.Root)
                throw new GuardianRefused("section_create_binding");
            var state=new State(); var answer=new ChildPair();
            try {
                window.Require(); state.Section=new SectionPublisher(memory,request,window).Publish(); window.Require();
                UIntPtr size=UIntPtr.Zero;
                bool probe=InitializeProcThreadAttributeList(IntPtr.Zero,2,0,ref size);
                if (probe || Marshal.GetLastWin32Error()!=122 || size.ToUInt64()<1 || size.ToUInt64()>4096)
                    throw new GuardianRefused("section_attribute_extent");
                state.Attributes=Marshal.AllocHGlobal((int)size.ToUInt64());
                if (!InitializeProcThreadAttributeList(state.Attributes,2,0,ref size)) throw new GuardianRefused("section_attribute_initialize");
                state.Ready=true; state.JobArray=Marshal.AllocHGlobal(IntPtr.Size); state.HandleArray=Marshal.AllocHGlobal(IntPtr.Size);
                Marshal.WriteIntPtr(state.JobArray,(IntPtr)job);
                IntPtr read=(IntPtr)state.Section.ReadHandle; Marshal.WriteIntPtr(state.HandleArray,read);
                if (!UpdateProcThreadAttribute(state.Attributes,0,new UIntPtr(WG.JobListAttribute),state.JobArray,
                    new UIntPtr((uint)IntPtr.Size),IntPtr.Zero,IntPtr.Zero)) throw new GuardianRefused("section_atomic_job_required");
                if (!UpdateProcThreadAttribute(state.Attributes,0,new UIntPtr(HandleListAttribute),state.HandleArray,
                    new UIntPtr((uint)IntPtr.Size),IntPtr.Zero,IntPtr.Zero)) throw new GuardianRefused("section_exact_handle_list_required");
                window.Require();
                var windows=new StringBuilder(512); var system=new StringBuilder(512);
                uint wc=GetWindowsDirectoryW(windows,512),sc=GetSystemDirectoryW(system,512);
                if (wc<1 || wc>=512 || sc<1 || sc>=512) throw new GuardianRefused("system_directory");
                byte[] environment=Encoding.Unicode.GetBytes(WG.EnvironmentBlock(root,windows.ToString(),system.ToString()));
                if (environment.Length>8192) throw new GuardianRefused("environment_extent");
                state.Environment=Marshal.AllocHGlobal(environment.Length); Marshal.Copy(environment,0,state.Environment,environment.Length);
                WG.SecurityAttributes security=WindowsSectionMemory.Descriptor(out state.Descriptor);
                var startup=new WG.StartupEx(); startup.Startup.Size=(uint)Marshal.SizeOf(typeof(WG.StartupEx)); startup.Attributes=state.Attributes;
                state.Section.Reverify(); window.Require();
                SectionCounterFrame frame=SectionCounterFrame.Capture(window,counter);
                string command=SectionWorkerCommand.Command(request,read.ToInt64(),frame); window.Require();
                // Inheritance TRUE only with this exact ONE-read-handle list AND
                // atomic job assignment. No standard handles, names, shell,
                // arbitrary commands or create-then-assign/retry fallback.
                if (!CreateProcessW(root+"\\"+ProvisionProcessGuardian.WorkerExe,new StringBuilder(command),ref security,ref security,
                    true,WG.ProcessFlags,state.Environment,root,ref startup,out state.Child)) throw new GuardianRefused("section_atomic_create_refused");
                if (state.Child.Process==IntPtr.Zero || state.Child.Process==new IntPtr(-1) || state.Child.Thread==IntPtr.Zero ||
                    state.Child.Thread==new IntPtr(-1) || state.Child.Id==0 || state.Child.ThreadId==0)
                    throw new GuardianUnknown("section_process_info_unknown");
                state.Scratch(); window.Require();
                answer.Process=state.Child.Process; answer.Thread=state.Child.Thread; answer.Id=state.Child.Id;
                state.Child.Process=IntPtr.Zero; state.Child.Thread=IntPtr.Zero; return answer;
            } finally { state.Close(); }
        }
        public bool Member(object process,object job) { return control.Member(process,job); }
        public uint Resume(object thread) { return control.Resume(thread); }
        public uint Wait(object process,uint ms) { return control.Wait(process,ms); }
        public uint ExitCode(object process) { return control.ExitCode(process); }
        public uint Active(object job) { return control.Active(job); }
        public void Stop(object job) { control.Stop(job); }
        public void Pause(int ms) { control.Pause(ms); }
        public void Close(object handle) { control.Close(handle); }
    }
}
