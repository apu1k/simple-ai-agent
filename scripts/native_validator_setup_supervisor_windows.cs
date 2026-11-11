// Fixed setup-host launch ONLY. Atomic JOB_LIST, native active limit ONE,
// no handle inheritance, shell, fallback, PID lookup or VM operation.
using System;
using System.Runtime.InteropServices;
using System.Text;
using AiAgent.ValidatorDelivery;
using AiAgent.ValidatorGuardian;
using WG=AiAgent.ValidatorGuardian.WindowsGuardianKernel;
namespace AiAgent.ValidatorSetup {
    internal sealed class WindowsSetupSupervisorKernel : IGuardianKernel,IGuardianWindowKernel {
        const string ObjectSddl="O:BAG:BAD:P(A;;GA;;;SY)(A;;GA;;;BA)";
        readonly SetupSupervisorProfile profile;
        readonly ISetupRole role;
        readonly ISectionCounter counter;
        readonly WG control=new WG();
        object job;
        SectionWindow window;
        bool host,jobAttempted,createAttempted,windowBound;
        internal WindowsSetupSupervisorKernel(SetupSupervisorProfile p,ISetupRole gate,ISectionCounter qpc) {
            if (p==null || gate==null || qpc==null) throw new SetupRefused("setup_kernel"); profile=p; role=gate; counter=qpc;
        }
        void Plan(GuardianPlan p) {
            if (p==null || p.Root!=profile.Host.Location.Root || p.OperatorSid!=profile.Host.Parent.OperatorSid ||
                p.InstallationId!=profile.Host.AttemptId || p.ApprovedUntilUnix!=profile.Host.ExpiresUnix || p.BudgetSeconds!=profile.Host.Seconds ||
                p.ApprovalSha256!=AiAgent.NativeValidator.InstallBoundary.Sha(profile.Policy())) throw new GuardianRefused("setup_kernel_binding");
        }
        public void RequireHost(GuardianPlan p) { Plan(p); if (host) throw new GuardianRefused("setup_host_one_shot"); role.Require(profile.Host,true); host=true; }
        public void BindWindow(GuardianPlan p,IGuardianClock clock,double stopAt) {
            Plan(p); if (windowBound || !host || job==null) throw new GuardianRefused("setup_window_binding"); windowBound=true;
            window=new SectionWindow(clock,stopAt,p.ApprovedUntilUnix);
        }
        [DllImport("kernel32.dll",ExactSpelling=true,CharSet=CharSet.Unicode)] static extern IntPtr CreateJobObjectW(ref WG.SecurityAttributes security,string name);
        [DllImport("kernel32.dll",ExactSpelling=true)] static extern bool SetInformationJobObject(IntPtr h,int kind,ref WG.JobLimits limits,uint bytes);
        [DllImport("kernel32.dll",EntryPoint="QueryInformationJobObject",ExactSpelling=true)] static extern bool QueryLimits(IntPtr h,int kind,out WG.JobLimits limits,uint bytes,IntPtr returned);
        [DllImport("kernel32.dll",EntryPoint="QueryInformationJobObject",ExactSpelling=true)] static extern bool QueryAccounting(IntPtr h,int kind,out WG.Accounting info,uint bytes,IntPtr returned);
        [DllImport("kernel32.dll",ExactSpelling=true)] static extern bool GetHandleInformation(IntPtr h,out uint flags);
        [DllImport("advapi32.dll",ExactSpelling=true,CharSet=CharSet.Unicode)] static extern bool ConvertStringSecurityDescriptorToSecurityDescriptorW(string s,uint revision,out IntPtr sd,out uint bytes);
        [DllImport("kernel32.dll",ExactSpelling=true)] static extern IntPtr LocalFree(IntPtr h);
        [DllImport("kernel32.dll",ExactSpelling=true,SetLastError=true)] static extern bool InitializeProcThreadAttributeList(IntPtr list,int count,uint flags,ref UIntPtr bytes);
        [DllImport("kernel32.dll",ExactSpelling=true)] static extern bool UpdateProcThreadAttribute(IntPtr list,uint flags,UIntPtr attr,IntPtr value,UIntPtr bytes,IntPtr previous,IntPtr returned);
        [DllImport("kernel32.dll",ExactSpelling=true)] static extern void DeleteProcThreadAttributeList(IntPtr list);
        [DllImport("kernel32.dll",ExactSpelling=true,CharSet=CharSet.Unicode)] static extern uint GetWindowsDirectoryW(StringBuilder s,uint n);
        [DllImport("kernel32.dll",ExactSpelling=true,CharSet=CharSet.Unicode)] static extern uint GetSystemDirectoryW(StringBuilder s,uint n);
        [DllImport("kernel32.dll",ExactSpelling=true,CharSet=CharSet.Unicode)] static extern bool CreateProcessW(string exe,StringBuilder cmd,
            ref WG.SecurityAttributes ps,ref WG.SecurityAttributes ts,bool inherit,uint flags,IntPtr env,string cwd,ref WG.StartupEx start,out WG.ProcessInfo child);
        void FreeLocal(ref IntPtr p) { IntPtr old=p; p=IntPtr.Zero; if (old!=IntPtr.Zero && LocalFree(old)!=IntPtr.Zero) throw new GuardianUnknown("setup_native_release_unknown"); }
        static void Free(ref IntPtr p) { IntPtr old=p; p=IntPtr.Zero; if (old!=IntPtr.Zero) Marshal.FreeHGlobal(old); }
        void CloseNative(ref IntPtr p) { IntPtr old=p; p=IntPtr.Zero; if (old!=IntPtr.Zero) control.Close(old); }
        WG.SecurityAttributes Descriptor(out IntPtr sd) {
            uint bytes; if (!ConvertStringSecurityDescriptorToSecurityDescriptorW(ObjectSddl,1,out sd,out bytes)) throw new GuardianRefused("setup_descriptor");
            return new WG.SecurityAttributes {Length=(uint)Marshal.SizeOf(typeof(WG.SecurityAttributes)),Descriptor=sd,Inherit=0};
        }
        public object NewJob() {
            if (!host || jobAttempted) throw new GuardianRefused("setup_job_one_shot"); jobAttempted=true;
            IntPtr sd=IntPtr.Zero,h=IntPtr.Zero;
            try {
                WG.SecurityAttributes security=Descriptor(out sd); h=CreateJobObjectW(ref security,null);
                if (h==IntPtr.Zero || h==new IntPtr(-1)) throw new GuardianRefused("setup_job_create");
                var limits=new WG.JobLimits(); limits.Basic.Flags=WG.JobFlags; limits.Basic.ActiveLimit=1;
                if (!SetInformationJobObject(h,9,ref limits,(uint)Marshal.SizeOf(typeof(WG.JobLimits)))) throw new GuardianRefused("setup_job_limits");
                WG.JobLimits actual; uint flags;
                if (!QueryLimits(h,9,out actual,(uint)Marshal.SizeOf(typeof(WG.JobLimits)),IntPtr.Zero) || actual.Basic.Flags!=WG.JobFlags ||
                    actual.Basic.ActiveLimit!=1 || !GetHandleInformation(h,out flags) || flags!=0) throw new GuardianRefused("setup_job_readback");
                FreeLocal(ref sd); job=h; h=IntPtr.Zero; return job;
            } finally {
                bool unknown=false; try { CloseNative(ref h); } catch { unknown=true; } try { FreeLocal(ref sd); } catch { unknown=true; }
                if (unknown) throw new GuardianUnknown("setup_native_release_unknown");
            }
        }
        public ChildPair CreateSuspended(object exactJob,string root) {
            if (createAttempted || !windowBound || window==null || job==null || !Object.Equals(exactJob,job) || root!=profile.Host.Location.Root)
                throw new GuardianRefused("setup_create_binding"); createAttempted=true;
            IntPtr attrs=IntPtr.Zero,array=IntPtr.Zero,env=IntPtr.Zero,sd=IntPtr.Zero; bool ready=false; WG.ProcessInfo child=new WG.ProcessInfo();
            try {
                window.Require(); UIntPtr size=UIntPtr.Zero; bool probe=InitializeProcThreadAttributeList(IntPtr.Zero,1,0,ref size);
                if (probe || Marshal.GetLastWin32Error()!=122 || size.ToUInt64()<1 || size.ToUInt64()>4096) throw new GuardianRefused("setup_attributes");
                attrs=Marshal.AllocHGlobal((int)size.ToUInt64());
                if (!InitializeProcThreadAttributeList(attrs,1,0,ref size)) throw new GuardianRefused("setup_attributes"); ready=true;
                array=Marshal.AllocHGlobal(IntPtr.Size); Marshal.WriteIntPtr(array,(IntPtr)job);
                if (!UpdateProcThreadAttribute(attrs,0,new UIntPtr(WG.JobListAttribute),array,new UIntPtr((uint)IntPtr.Size),IntPtr.Zero,IntPtr.Zero))
                    throw new GuardianRefused("setup_atomic_job_required");
                var windows=new StringBuilder(512); var system=new StringBuilder(512);
                uint wc=GetWindowsDirectoryW(windows,512),sc=GetSystemDirectoryW(system,512);
                if (wc<1 || wc>=512 || sc<1 || sc>=512) throw new GuardianRefused("setup_system_directory");
                byte[] block=Encoding.Unicode.GetBytes(WG.EnvironmentBlock(root,windows.ToString(),system.ToString()));
                if (block.Length>8192) throw new GuardianRefused("setup_environment"); env=Marshal.AllocHGlobal(block.Length); Marshal.Copy(block,0,env,block.Length);
                WG.SecurityAttributes security=Descriptor(out sd); var startup=new WG.StartupEx();
                startup.Startup.Size=(uint)Marshal.SizeOf(typeof(WG.StartupEx)); startup.Startup.Flags=0x100; startup.Attributes=attrs;
                window.Require(); SectionCounterFrame frame=SectionCounterFrame.Capture(window,counter);
                string cmd=SetupHostFrame.Command(profile,frame); if (cmd.Length>1024 || cmd.IndexOf('\0')>=0) throw new GuardianRefused("setup_command_bound");
                window.Require();
                if (!CreateProcessW(root+"\\"+SetupHostProfile.HostExe,new StringBuilder(cmd),ref security,ref security,false,WG.ProcessFlags,env,root,ref startup,out child))
                    throw new GuardianRefused("setup_atomic_create_refused");
                if (child.Process==IntPtr.Zero || child.Thread==IntPtr.Zero || child.Process==new IntPtr(-1) || child.Thread==new IntPtr(-1) ||
                    child.Id==0 || child.ThreadId==0) throw new GuardianUnknown("setup_child_unknown");
                // Release scratch BEFORE transferring either process handle.
                ready=false; DeleteProcThreadAttributeList(attrs); Free(ref attrs); Free(ref array); Free(ref env); FreeLocal(ref sd); window.Require();
                var answer=new ChildPair {Process=child.Process,Thread=child.Thread,Id=child.Id}; child.Process=IntPtr.Zero; child.Thread=IntPtr.Zero; return answer;
            } finally {
                bool unknown=false;
                try { CloseNative(ref child.Thread); } catch { unknown=true; } try { CloseNative(ref child.Process); } catch { unknown=true; }
                if (ready) { ready=false; try { DeleteProcThreadAttributeList(attrs); } catch { unknown=true; } }
                try { Free(ref attrs); } catch { unknown=true; } try { Free(ref array); } catch { unknown=true; }
                try { Free(ref env); } catch { unknown=true; } try { FreeLocal(ref sd); } catch { unknown=true; }
                if (unknown) throw new GuardianUnknown("setup_native_release_unknown");
            }
        }
        public bool Member(object p,object j) { if (!Object.Equals(j,job)) throw new GuardianRefused("setup_job_binding"); return control.Member(p,j); }
        public uint Resume(object h) { return control.Resume(h); }
        public uint Wait(object h,uint ms) { return control.Wait(h,ms); }
        public uint ExitCode(object h) { return control.ExitCode(h); }
        public uint Active(object j) {
            if (!Object.Equals(j,job)) throw new GuardianRefused("setup_job_binding"); WG.Accounting info;
            if (!QueryAccounting((IntPtr)j,1,out info,(uint)Marshal.SizeOf(typeof(WG.Accounting)),IntPtr.Zero))
                throw new GuardianUnknown("setup_accounting_unknown"); return ObservedActive(info);
        }
        // Native concurrent admission stays ONE. Cumulative accounting is a
        // separate bounded observation, not the configured admission limit.
        internal static uint ObservedActive(WG.Accounting info) {
            if (info.Total>2 || info.Active>info.Total) throw new GuardianUnknown("setup_accounting_unknown");
            return info.Active;
        }
        public void Stop(object j) { if (!Object.Equals(j,job)) throw new GuardianRefused("setup_job_binding"); control.Stop(j); }
        public void Pause(int ms) { control.Pause(ms); }
        public void Close(object h) { if (Object.Equals(h,job)) job=null; control.Close(h); }
    }
}
