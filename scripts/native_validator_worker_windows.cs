// UNWIRED fixed Python adapter. Never compile/load checkout code elevated.
// Trusted pre-load provenance, permanent approval, protected outer worker/job,
// held imports/targets and independent watchdog MUST precede use. No Main/tool.
using System;
using System.Globalization;
using System.Runtime.InteropServices;
using System.Security.Principal;
using System.Text;
using AiAgent.ValidatorGuardian;
using WG=AiAgent.ValidatorGuardian.WindowsGuardianKernel;
namespace AiAgent.ValidatorWorker {
    internal interface IWorkerCounter { long Frequency(); long Read(); }
    internal sealed class WindowsWorkerCounter : IWorkerCounter {
        [DllImport("kernel32.dll",ExactSpelling=true)] static extern bool QueryPerformanceCounter(out long value);
        [DllImport("kernel32.dll",ExactSpelling=true)] static extern bool QueryPerformanceFrequency(out long value);
        public long Frequency() {
            long value; if (!QueryPerformanceFrequency(out value)) throw new GuardianUnknown("counter_unknown"); return value;
        }
        public long Read() {
            long value; if (!QueryPerformanceCounter(out value)) throw new GuardianUnknown("counter_unknown"); return value;
        }
    }
    internal sealed class WorkerCounterFrame {
        internal readonly long Limit,Frequency;
        internal WorkerCounterFrame(long limit,long frequency) { Limit=limit; Frequency=frequency; }
        internal static WorkerCounterFrame Capture(WorkerLaunchContext context,IWorkerCounter counter) {
            // QPC sample BEFORE the local clock: map remaining time onto an
            // EARLIER common-machine counter instant. One millisecond plus one
            // tick is subtracted for conversion rounding. No duration is renewed.
            long frequency=counter.Frequency(),first=counter.Read();
            double now=context.Clock.Seconds; long wall=context.Clock.Unix;
            long second=counter.Read(),again=counter.Frequency();
            if (frequency<1 || frequency>1000000000L || again!=frequency || first<1 || second<first ||
                second-first>frequency/4 || Double.IsNaN(now) || Double.IsInfinity(now))
                throw new GuardianRefused("counter_sample");
            double remaining=Math.Min(context.RunDeadline-now,context.ApprovedUntilUnix-wall);
            if (Double.IsNaN(remaining) || Double.IsInfinity(remaining) || remaining<=0 || remaining>900)
                throw new GuardianRefused("counter_window");
            try {
                long ticks=(long)Decimal.Floor((decimal)remaining*frequency)-frequency/1000-1;
                long limit=checked(first+ticks);
                if (ticks<1 || limit<=second) throw new GuardianRefused("counter_window");
                return new WorkerCounterFrame(limit,frequency);
            } catch (OverflowException) { throw new GuardianRefused("counter_window"); }
        }
    }
    internal sealed class WindowsWorkerPythonKernel : IWorkerPythonKernel {
        // Fixed source, not input-selected code. Override the disabled-site ._pth
        // profile with ONLY held directories before importing the carried member.
        // No shell, file reopen, stdin parser, named pipe or inherited handle.
        internal const string Bootstrap="import sys;assert len(sys.argv)==10;r=sys.argv[1];"+
            "sys.path[:]=[r+chr(92)+'payload',r+chr(92)+'runtime'+chr(92)+'python314.zip',r+chr(92)+'runtime'];"+
            "from night_shifts.bootstrap_native_provision import _run_fixed_worker;"+
            "sys.exit(_run_fixed_worker(tuple(sys.argv[1:])))";
        internal const int MaxCommandChars=16384;
        readonly WG control=new WG();
        readonly IWorkerCounter counter;
        GuardianPlan plan;
        WorkerLaunchContext context;
        object exactJob;
        bool bound,jobAttempted,createAttempted;
        internal WindowsWorkerPythonKernel() : this(new WindowsWorkerCounter()) { }
        internal WindowsWorkerPythonKernel(IWorkerCounter value) {
            if (value==null) throw new GuardianRefused("counter_plan"); counter=value;
        }
        static bool Same(GuardianPlan a,GuardianPlan b) {
            return a!=null && b!=null && a.Root==b.Root && a.OperatorSid==b.OperatorSid &&
                a.InstallationId==b.InstallationId && a.ApprovalSha256==b.ApprovalSha256 &&
                a.ApprovedUntilUnix==b.ApprovedUntilUnix && a.BudgetSeconds==b.BudgetSeconds;
        }
        public void Bind(WorkerLaunchContext value) {
            if (bound) throw new GuardianRefused("python_one_shot"); bound=true;
            if (value==null || plan==null || value.Clock==null || value.LaunchRoot!=plan.Root ||
                value.OperatorSid!=plan.OperatorSid || value.InstallationId!=plan.InstallationId ||
                value.RequestSha256!=plan.ApprovalSha256 || value.ApprovedUntilUnix!=plan.ApprovedUntilUnix ||
                value.BudgetSeconds!=plan.BudgetSeconds) throw new GuardianRefused("python_binding");
            AiAgent.NativeValidator.InstallBoundary.PathParts(value.ImportRoot);
            context=value; // only immutable bounded consistency data, NO native work
        }
        internal static string Executable(WorkerLaunchContext value) { return value.ImportRoot+"\\runtime\\python.exe"; }
        internal static string Command(WorkerLaunchContext value,WorkerCounterFrame frame) {
            byte[] raw=value.CopyRequest();
            if (raw.Length<1 || raw.Length>8192 || raw.Length!=value.WorkerBytes ||
                AiAgent.NativeValidator.InstallBoundary.Sha(raw)!=value.WorkerSha256 ||
                frame==null || frame.Limit<1 || frame.Frequency<1 || frame.Frequency>1000000000L)
                throw new GuardianRefused("python_frame");
            string command="\""+Executable(value)+"\" -I -S -B -c \""+Bootstrap+"\" \""+value.ImportRoot+"\" "+
                Convert.ToBase64String(raw)+" "+value.WorkerBytes.ToString(CultureInfo.InvariantCulture)+" "+
                value.WorkerSha256+" "+value.RequestSha256+" "+value.BudgetSeconds.ToString(CultureInfo.InvariantCulture)+" "+
                value.ApprovedUntilUnix.ToString(CultureInfo.InvariantCulture)+" "+frame.Limit.ToString(CultureInfo.InvariantCulture)+" "+
                frame.Frequency.ToString(CultureInfo.InvariantCulture);
            if (command.Length>=MaxCommandChars || command.IndexOf('\0')>=0) throw new GuardianRefused("python_command_bound");
            return command;
        }
        [DllImport("kernel32.dll",ExactSpelling=true,CharSet=CharSet.Unicode)] static extern uint GetModuleFileNameW(IntPtr module,StringBuilder path,uint size);
        [DllImport("kernel32.dll",ExactSpelling=true,CharSet=CharSet.Unicode)] static extern uint GetWindowsDirectoryW(StringBuilder path,uint size);
        [DllImport("kernel32.dll",ExactSpelling=true,CharSet=CharSet.Unicode)] static extern uint GetSystemDirectoryW(StringBuilder path,uint size);
        [DllImport("kernel32.dll",ExactSpelling=true,SetLastError=true)] static extern bool CloseHandle(IntPtr value);
        [DllImport("kernel32.dll",ExactSpelling=true)] static extern IntPtr LocalFree(IntPtr value);
        [DllImport("advapi32.dll",ExactSpelling=true,CharSet=CharSet.Unicode)]
        static extern bool ConvertStringSecurityDescriptorToSecurityDescriptorW(string text,uint revision,out IntPtr descriptor,out uint size);
        [DllImport("kernel32.dll",ExactSpelling=true,CharSet=CharSet.Unicode)] static extern IntPtr CreateJobObjectW(ref WG.SecurityAttributes security,string name);
        [DllImport("kernel32.dll",ExactSpelling=true)] static extern bool SetInformationJobObject(IntPtr job,int kind,ref WG.JobLimits limits,uint size);
        [DllImport("kernel32.dll",EntryPoint="QueryInformationJobObject",ExactSpelling=true)]
        static extern bool QueryLimits(IntPtr job,int kind,out WG.JobLimits limits,uint size,IntPtr length);
        [DllImport("kernel32.dll",ExactSpelling=true)] static extern bool GetHandleInformation(IntPtr handle,out uint flags);
        [DllImport("kernel32.dll",ExactSpelling=true,SetLastError=true)]
        static extern bool InitializeProcThreadAttributeList(IntPtr list,int count,uint flags,ref UIntPtr size);
        [DllImport("kernel32.dll",ExactSpelling=true)]
        static extern bool UpdateProcThreadAttribute(IntPtr list,uint flags,UIntPtr attribute,IntPtr value,UIntPtr size,IntPtr previous,IntPtr returned);
        [DllImport("kernel32.dll",ExactSpelling=true)] static extern void DeleteProcThreadAttributeList(IntPtr list);
        [DllImport("kernel32.dll",ExactSpelling=true,CharSet=CharSet.Unicode)]
        static extern bool CreateProcessW(string exe,StringBuilder command,ref WG.SecurityAttributes processSecurity,
            ref WG.SecurityAttributes threadSecurity,bool inherit,uint flags,IntPtr environment,string cwd,ref WG.StartupEx startup,out WG.ProcessInfo info);
        static void CloseNative(ref IntPtr value) {
            IntPtr old=value; value=IntPtr.Zero;
            if (old!=IntPtr.Zero && !CloseHandle(old)) throw new GuardianUnknown("python_close_unknown");
        }
        static void FreeLocal(ref IntPtr value) {
            IntPtr old=value; value=IntPtr.Zero;
            if (old!=IntPtr.Zero && LocalFree(old)!=IntPtr.Zero) throw new GuardianUnknown("python_release_unknown");
        }
        static void FreeBuffer(ref IntPtr value) {
            IntPtr old=value; value=IntPtr.Zero; if (old!=IntPtr.Zero) Marshal.FreeHGlobal(old);
        }
        static WG.SecurityAttributes Descriptor(out IntPtr pointer) {
            uint size;
            if (!ConvertStringSecurityDescriptorToSecurityDescriptorW(WG.ObjectSddl,1,out pointer,out size))
                throw new GuardianRefused("python_descriptor");
            return new WG.SecurityAttributes {Length=(uint)Marshal.SizeOf(typeof(WG.SecurityAttributes)),Descriptor=pointer,Inherit=0};
        }
        public void RequireHost(GuardianPlan value) {
            if (value==null || (plan!=null && !Same(plan,value))) throw new GuardianRefused("python_host_binding");
            if (Environment.OSVersion.Platform!=PlatformID.Win32NT || IntPtr.Size!=8) throw new GuardianRefused("native_windows_x64");
            var path=new StringBuilder(512); uint count=GetModuleFileNameW(IntPtr.Zero,path,512);
            if (count<1 || count>=512 || path.ToString()!=value.Root+"\\"+ProvisionProcessGuardian.WorkerExe)
                throw new GuardianRefused("protected_worker_role");
            using (WindowsIdentity identity=WindowsIdentity.GetCurrent()) {
                if (identity.User==null || identity.User.Value!=value.OperatorSid ||
                    !new WindowsPrincipal(identity).IsInRole(WindowsBuiltInRole.Administrator))
                    throw new GuardianRefused("enabled_operator_required");
            }
            plan=value; // role/path/SID checks are NOT pre-load provenance/approval
        }
        public object NewJob() {
            if (jobAttempted || plan==null) throw new GuardianRefused("python_job_one_shot"); jobAttempted=true;
            IntPtr descriptor=IntPtr.Zero,job=IntPtr.Zero;
            try {
                WG.SecurityAttributes security=Descriptor(out descriptor);
                job=CreateJobObjectW(ref security,null);
                if (job==IntPtr.Zero) throw new GuardianRefused("python_job_create");
                var limits=new WG.JobLimits(); limits.Basic.Flags=WG.JobFlags; limits.Basic.ActiveLimit=1;
                if (!SetInformationJobObject(job,9,ref limits,(uint)Marshal.SizeOf(typeof(WG.JobLimits)))) throw new GuardianRefused("python_job_limits");
                WG.JobLimits actual; uint flags;
                if (!QueryLimits(job,9,out actual,(uint)Marshal.SizeOf(typeof(WG.JobLimits)),IntPtr.Zero) ||
                    actual.Basic.Flags!=WG.JobFlags || actual.Basic.ActiveLimit!=1 ||
                    !GetHandleInformation(job,out flags) || (flags&1)!=0) throw new GuardianRefused("python_job_readback");
                FreeLocal(ref descriptor); object answer=job; job=IntPtr.Zero; exactJob=answer; return answer;
            } finally {
                bool unknown=false;
                try { CloseNative(ref job); } catch { unknown=true; }
                try { FreeLocal(ref descriptor); } catch { unknown=true; }
                if (unknown) throw new GuardianUnknown("python_release_unknown");
            }
        }
        sealed class State {
            internal IntPtr Attributes,JobArray,Environment,Descriptor;
            internal bool Ready;
            internal WG.ProcessInfo Child;
            internal void Scratch() {
                bool unknown=false;
                if (Ready) { Ready=false; try { DeleteProcThreadAttributeList(Attributes); } catch { unknown=true; } }
                try { FreeBuffer(ref Attributes); } catch { unknown=true; }
                try { FreeBuffer(ref JobArray); } catch { unknown=true; }
                try { FreeBuffer(ref Environment); } catch { unknown=true; }
                try { FreeLocal(ref Descriptor); } catch { unknown=true; }
                if (unknown) throw new GuardianUnknown("python_release_unknown");
            }
            internal void Close() {
                bool unknown=false;
                try { CloseNative(ref Child.Thread); } catch { unknown=true; }
                try { CloseNative(ref Child.Process); } catch { unknown=true; }
                try { Scratch(); } catch { unknown=true; }
                if (unknown) throw new GuardianUnknown("python_release_unknown");
            }
        }
        public ChildPair CreateSuspended(object job,string root) {
            if (createAttempted) throw new GuardianRefused("python_create_one_shot"); createAttempted=true;
            if (context==null || plan==null || root!=plan.Root || !Object.Equals(job,exactJob) || exactJob==null)
                throw new GuardianRefused("python_create_binding");
            WorkerCounterFrame frame=WorkerCounterFrame.Capture(context,counter);
            string command=Command(context,frame);
            var state=new State(); var answer=new ChildPair();
            try {
                UIntPtr size=UIntPtr.Zero;
                bool probe=InitializeProcThreadAttributeList(IntPtr.Zero,1,0,ref size);
                if (probe || Marshal.GetLastWin32Error()!=122 || size.ToUInt64()<1 || size.ToUInt64()>4096) throw new GuardianRefused("python_attribute_extent");
                state.Attributes=Marshal.AllocHGlobal((int)size.ToUInt64());
                if (!InitializeProcThreadAttributeList(state.Attributes,1,0,ref size)) throw new GuardianRefused("python_attribute_initialize");
                state.Ready=true; state.JobArray=Marshal.AllocHGlobal(IntPtr.Size); Marshal.WriteIntPtr(state.JobArray,(IntPtr)job);
                if (!UpdateProcThreadAttribute(state.Attributes,0,new UIntPtr(WG.JobListAttribute),state.JobArray,
                    new UIntPtr((uint)IntPtr.Size),IntPtr.Zero,IntPtr.Zero)) throw new GuardianRefused("python_atomic_job_required");
                var windows=new StringBuilder(512); var system=new StringBuilder(512);
                uint wc=GetWindowsDirectoryW(windows,512),sc=GetSystemDirectoryW(system,512);
                if (wc<1 || wc>=512 || sc<1 || sc>=512) throw new GuardianRefused("system_directory");
                byte[] environment=Encoding.Unicode.GetBytes(WG.EnvironmentBlock(root,windows.ToString(),system.ToString()));
                if (environment.Length>8192) throw new GuardianRefused("environment_extent");
                state.Environment=Marshal.AllocHGlobal(environment.Length); Marshal.Copy(environment,0,state.Environment,environment.Length);
                WG.SecurityAttributes security=Descriptor(out state.Descriptor);
                var startup=new WG.StartupEx(); startup.Startup.Size=(uint)Marshal.SizeOf(typeof(WG.StartupEx)); startup.Attributes=state.Attributes;
                if (!CreateProcessW(Executable(context),new StringBuilder(command),ref security,ref security,false,WG.ProcessFlags,
                    state.Environment,root,ref startup,out state.Child)) throw new GuardianRefused("python_atomic_create_refused");
                if (state.Child.Process==IntPtr.Zero || state.Child.Process==new IntPtr(-1) || state.Child.Thread==IntPtr.Zero ||
                    state.Child.Thread==new IntPtr(-1) || state.Child.Id==0 || state.Child.ThreadId==0) throw new GuardianUnknown("python_process_info_unknown");
                state.Scratch(); answer.Process=state.Child.Process; answer.Thread=state.Child.Thread; answer.Id=state.Child.Id;
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
