// UNINSTALLED worker entry/receiver candidate. NEVER build/load checkout code
// elevated. A separately trusted parent MUST consume permanent approval, hold
// the load/launch closure, publish an immutable read-only section, use an exact
// HANDLE_LIST plus atomic JOB_LIST and supervise the original process deadline.
// Matching argv/handle/pins are consistency checks, NOT parent authentication.
using System;
using System.Globalization;
using System.Runtime.InteropServices;
using System.Security.Principal;
using System.Text;
using System.Text.RegularExpressions;
using AiAgent.NativeValidator;
using AiAgent.ValidatorGuardian;
namespace AiAgent.ValidatorWorker {
    internal sealed class WorkerEntryRefused : Exception {
        internal WorkerEntryRefused(string label) : base(label) { }
    }
    internal sealed class WorkerEntryFrame {
        internal const string Mode="--provision-once-section-v1";
        internal readonly long Handle,RequestBytes,ExpiresUnix,CounterLimit,Frequency;
        internal readonly int BudgetSeconds;
        internal readonly string RequestSha256;
        WorkerEntryFrame(long handle,long bytes,string digest,int seconds,long until,long limit,long frequency) {
            Handle=handle; RequestBytes=bytes; RequestSha256=digest; BudgetSeconds=seconds;
            ExpiresUnix=until; CounterLimit=limit; Frequency=frequency;
        }
        static long Number(string text,long min,long max) {
            long value;
            if (text==null || text.Length>19 || !Regex.IsMatch(text,"\\A[1-9][0-9]*\\z") ||
                !Int64.TryParse(text,NumberStyles.None,CultureInfo.InvariantCulture,out value) || value<min || value>max)
                throw new WorkerEntryRefused("entry_frame");
            return value;
        }
        internal static WorkerEntryFrame Parse(string[] args) {
            if (args==null || args.Length!=8) throw new WorkerEntryRefused("entry_frame");
            string[] copy=(string[])args.Clone(); // strings immutable; no caller-array alias
            if (copy[0]!=Mode || copy[3]==null || !Regex.IsMatch(copy[3],"\\A[0-9a-f]{64}\\z"))
                throw new WorkerEntryRefused("entry_frame");
            long handle=Number(copy[1],4,Int64.MaxValue);
            if (handle%4!=0) throw new WorkerEntryRefused("entry_frame");
            return new WorkerEntryFrame(handle,Number(copy[2],1,32768),copy[3],(int)Number(copy[4],6,900),
                Number(copy[5],1,253402300799L),Number(copy[6],1,Int64.MaxValue),Number(copy[7],1,1000000000L));
        }
    }
    internal static class WorkerEntryDeadline {
        internal static double Translate(WorkerEntryFrame frame,IGuardianClock clock,IWorkerCounter counter) {
            // The LOCAL sample is first, and the LATER common counter is used.
            // Loading, argument parsing and reception consume the original cap.
            // Never treat another process's Stopwatch value as a local timestamp.
            double first=clock.Seconds;
            long rate=counter.Frequency(),start=counter.Read(),end=counter.Read(),again=counter.Frequency();
            double last=clock.Seconds; long wall=clock.Unix;
            if (Double.IsNaN(first) || Double.IsInfinity(first) || first<0 || first>1000000000 ||
                Double.IsNaN(last) || Double.IsInfinity(last) || last<first || last-first>0.25 ||
                rate!=frame.Frequency || again!=rate || start<1 || end<start || end-start>rate/4 ||
                frame.CounterLimit<=end || wall<1 || wall>=frame.ExpiresUnix)
                throw new WorkerEntryRefused("entry_counter");
            decimal remaining=Math.Min((decimal)(frame.CounterLimit-end)/rate,(decimal)frame.ExpiresUnix-wall);
            if (remaining<=0 || remaining>900) throw new WorkerEntryRefused("entry_window");
            // At local values <=1e9, 1 microsecond exceeds conversion/addition
            // rounding error. Extra millisecond is the same conservative margin
            // as the worker-to-Python edge, not a renewed execution allowance.
            double deadline=first+(double)remaining-0.001-0.000001;
            if (Double.IsNaN(deadline) || Double.IsInfinity(deadline) ||
                deadline-ProvisionProcessGuardian.StopReserveSeconds<=last)
                throw new WorkerEntryRefused("entry_window");
            return deadline;
        }
    }
    internal interface IWorkerEntryInput {
        void RequireHost();
        byte[] Read(WorkerEntryFrame frame);
    }
    internal sealed class WorkerEntry {
        readonly object sync=new object();
        readonly IBoundaryFiles files;
        readonly IWorkerPythonKernel python;
        readonly IGuardianClock clock;
        readonly IWorkerCounter counter;
        readonly IWorkerEntryInput input;
        WorkerProvisionGuardian owner;
        bool used;
        internal WorkerEntry(IBoundaryFiles importFiles,IWorkerPythonKernel kernel,IGuardianClock time,
            IWorkerCounter commonCounter,IWorkerEntryInput receiver) {
            if (importFiles==null || kernel==null || time==null || commonCounter==null || receiver==null)
                throw new WorkerEntryRefused("entry_plan");
            // ONE rollback/nonfinite guard spans translation, owner construction
            // and reception; a new inner wrapper must not forget earlier samples.
            files=importFiles; python=kernel; clock=new WorkerClock(time); counter=commonCounter; input=receiver;
        }
        internal bool MustParkForSupervisor {
            get { lock (sync) { return owner!=null && owner.ImportLeaseRetained; } }
        }
        internal int Run(string[] args) {
            lock (sync) {
                if (used) return 126; used=true; // before any platform/clock/I/O boundary
                try {
                    WorkerEntryFrame frame=WorkerEntryFrame.Parse(args);
                    input.RequireHost();
                    double deadline=WorkerEntryDeadline.Translate(frame,clock,counter);
                    // Construct the terminal owner BEFORE reading/decoding raw bytes.
                    owner=new WorkerProvisionGuardian(frame.RequestBytes,frame.RequestSha256,frame.BudgetSeconds,
                        frame.ExpiresUnix,deadline,files,python,clock);
                    byte[] raw=input.Read(frame);
                    LocalProcessObservation answer=owner.Run(raw);
                    if (answer.End!=LocalProcessEnd.RootExited || !answer.Resumed || !answer.EmptyObserved ||
                        !answer.ExitCode.HasValue) return 125;
                    return answer.ExitCode.Value==0?0:(answer.ExitCode.Value==126?126:125);
                } catch (WorkerEntryRefused) { return 126; }
                  catch (WorkerGuardianRefused) { return 126; }
                  catch { return 125; }
                // NEVER discard owner or dispose its imports on an uncertain run.
                // Exit codes are LOCAL consistency observations, NOT acceptance.
            }
        }
    }
    internal sealed class WindowsWorkerEntryInput : IWorkerEntryInput {
        // One unnamed SECTION_MAP_READ-only handle from the protected parent.
        // No file reopen, pipe, stdin, environment, shell or named-object fallback.
        const uint SectionMapRead=4,HandleInherit=1;
        bool host,used;
        [StructLayout(LayoutKind.Sequential)] struct BasicInfo {
            internal uint Attributes,GrantedAccess,HandleCount,PointerCount;
            [MarshalAs(UnmanagedType.ByValArray,SizeConst=10)] internal uint[] Reserved;
        }
        [DllImport("ntdll.dll",ExactSpelling=true)]
        static extern int NtQueryObject(IntPtr handle,int kind,out BasicInfo info,uint size,out uint returned);
        [DllImport("kernel32.dll",ExactSpelling=true,CharSet=CharSet.Unicode)]
        static extern uint GetModuleFileNameW(IntPtr module,StringBuilder path,uint size);
        [DllImport("kernel32.dll",ExactSpelling=true)] static extern bool GetHandleInformation(IntPtr handle,out uint flags);
        [DllImport("kernel32.dll",ExactSpelling=true)] static extern bool SetHandleInformation(IntPtr handle,uint mask,uint flags);
        [DllImport("kernel32.dll",ExactSpelling=true)]
        static extern IntPtr MapViewOfFile(IntPtr handle,uint access,uint high,uint low,UIntPtr size);
        [DllImport("kernel32.dll",ExactSpelling=true)] static extern bool UnmapViewOfFile(IntPtr address);
        [DllImport("kernel32.dll",ExactSpelling=true)] static extern bool CloseHandle(IntPtr handle);
        public void RequireHost() {
            if (host) throw new WorkerEntryRefused("entry_host_one_shot");
            if (Environment.OSVersion.Platform!=PlatformID.Win32NT || IntPtr.Size!=8)
                throw new WorkerEntryRefused("entry_native_x64");
            var path=new StringBuilder(512); uint count=GetModuleFileNameW(IntPtr.Zero,path,512);
            if (count<1 || count>=512 || !path.ToString().EndsWith("\\"+ProvisionProcessGuardian.WorkerExe,StringComparison.Ordinal))
                throw new WorkerEntryRefused("entry_worker_role");
            using (WindowsIdentity identity=WindowsIdentity.GetCurrent()) {
                if (!new WindowsPrincipal(identity).IsInRole(WindowsBuiltInRole.Administrator))
                    throw new WorkerEntryRefused("entry_enabled_operator");
            }
            host=true; // basename/token shape is NOT pre-load/parent authentication
        }
        public byte[] Read(WorkerEntryFrame frame) {
            if (used) throw new WorkerEntryRefused("entry_input_one_shot"); used=true;
            if (!host || frame==null) throw new WorkerEntryRefused("entry_input_binding");
            return ReadSection(frame);
        }
        // Shared ONLY by the two fixed host-gated entries in the reviewed
        // assembly. Canonical frame already bounded; no path/name or public API.
        // Native read/rights/inheritance/adoption/close policy remains identical.
        internal static byte[] ReadSection(WorkerEntryFrame frame) {
            if (frame==null) throw new WorkerEntryRefused("entry_input_binding");
            IntPtr handle=new IntPtr(frame.Handle),view=IntPtr.Zero;
            bool adopted=false;
            try {
                uint flags,returned; BasicInfo actual;
                uint size=(uint)Marshal.SizeOf(typeof(BasicInfo));
                if (!GetHandleInformation(handle,out flags) || flags!=HandleInherit ||
                    NtQueryObject(handle,0,out actual,size,out returned)!=0 || returned!=size || actual.GrantedAccess!=SectionMapRead)
                    throw new WorkerEntryRefused("entry_section_rights");
                view=MapViewOfFile(handle,SectionMapRead,0,0,new UIntPtr((uint)frame.RequestBytes));
                if (view==IntPtr.Zero) throw new WorkerEntryRefused("entry_section_map");
                adopted=true; // mapping proves SECTION type; never adopt arbitrary argv handles
                if (!SetHandleInformation(handle,HandleInherit,0) || !GetHandleInformation(handle,out flags) || flags!=0)
                    throw new WorkerEntryRefused("entry_section_inheritance");
                byte[] raw=new byte[(int)frame.RequestBytes]; Marshal.Copy(view,raw,0,raw.Length);
                return raw; // actual owner verifies complete length/hash BEFORE JSON
            } finally {
                bool unknown=false;
                IntPtr oldView=view; view=IntPtr.Zero;
                try { if (oldView!=IntPtr.Zero && !UnmapViewOfFile(oldView)) unknown=true; } catch { unknown=true; }
                IntPtr oldHandle=handle; handle=IntPtr.Zero;
                try { if (adopted && !CloseHandle(oldHandle)) unknown=true; } catch { unknown=true; }
                if (unknown) throw new GuardianUnknown("entry_section_close_unknown");
            }
        }
    }
    internal static class ValidatorWorkerProgram {
        [DllImport("kernel32.dll",ExactSpelling=true)] static extern void Sleep(uint milliseconds);
        // Compiled only into the future separately reviewed worker EXE. Model
        // tests compile as a library and NEVER invoke Main or a native receiver.
        static int Main(string[] args) {
            WorkerEntry entry;
            try {
                entry=new WorkerEntry(new WindowsBoundaryFiles(),new WindowsWorkerPythonKernel(),
                    new GuardianClock(),new WindowsWorkerCounter(),new WindowsWorkerEntryInput());
            } catch { return 125; }
            int code=entry.Run(args);
            if (entry.MustParkForSupervisor) {
                // Exiting would drop import locks while Python absence is UNKNOWN.
                // Deliberately NO local exit timer/unlock/retry: the independent
                // outer job/watchdog must terminate the exact worker/Python tree.
                for (;;) { Sleep(UInt32.MaxValue); GC.KeepAlive(entry); }
            }
            return code;
        }
    }
}
