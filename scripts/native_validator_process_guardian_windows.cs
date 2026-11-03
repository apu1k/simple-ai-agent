// Native adapter for the UNWIRED provisioning-process guardian BODY.
// Future protected executable/approval/held-target verification is NOT supplied.
// Atomic JOB_LIST assignment only: never create-then-assign, break away, retry,
// look up/kill a PID, alter security, run a shell, operate a VM or inherit secrets.
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Security.Principal;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
namespace AiAgent.ValidatorGuardian {
    internal sealed class WindowsGuardianKernel : IGuardianKernel {
        internal const string ObjectSddl="O:BAG:BAD:P(A;;GA;;;SY)(A;;GA;;;BA)";
        internal const uint JobFlags=0x2008, ProcessFlags=0x08080404;
        internal const uint JobListAttribute=0x0002000d;
        [StructLayout(LayoutKind.Sequential)] internal struct SecurityAttributes {
            internal uint Length; internal IntPtr Descriptor; internal int Inherit;
        }
        [StructLayout(LayoutKind.Sequential)] internal struct JobBasicLimits {
            internal long ProcessTime,JobTime; internal uint Flags;
            internal UIntPtr MinWorkingSet,MaxWorkingSet; internal uint ActiveLimit;
            internal UIntPtr Affinity; internal uint Priority,Scheduling;
        }
        [StructLayout(LayoutKind.Sequential)] internal struct IoCounters { internal ulong A,B,C,D,E,F; }
        [StructLayout(LayoutKind.Sequential)] internal struct JobLimits {
            internal JobBasicLimits Basic; internal IoCounters Io;
            internal UIntPtr ProcessMemory,JobMemory,PeakProcess,PeakJob;
        }
        [StructLayout(LayoutKind.Sequential)] internal struct Accounting {
            internal long User,Kernel,PeriodUser,PeriodKernel;
            internal uint Faults,Total,Active,Terminated;
        }
        [StructLayout(LayoutKind.Sequential,CharSet=CharSet.Unicode)] internal struct Startup {
            internal uint Size; internal string Reserved,Desktop,Title;
            internal uint X,Y,XSize,YSize,XChars,YChars,Fill,Flags;
            internal ushort Show,ReservedSize;
            internal IntPtr ReservedPointer,Input,Output,Error;
        }
        [StructLayout(LayoutKind.Sequential)] internal struct StartupEx { internal Startup Startup; internal IntPtr Attributes; }
        [StructLayout(LayoutKind.Sequential)] internal struct ProcessInfo { internal IntPtr Process,Thread; internal uint Id,ThreadId; }
        [DllImport("kernel32.dll",ExactSpelling=true,CharSet=CharSet.Unicode,SetLastError=true)]
        static extern IntPtr CreateJobObjectW(ref SecurityAttributes security,string name);
        [DllImport("kernel32.dll",ExactSpelling=true,SetLastError=true)]
        static extern bool SetInformationJobObject(IntPtr job,int kind,ref JobLimits limits,uint size);
        [DllImport("kernel32.dll",EntryPoint="QueryInformationJobObject",ExactSpelling=true,SetLastError=true)]
        static extern bool QueryLimits(IntPtr job,int kind,out JobLimits limits,uint size,IntPtr length);
        [DllImport("kernel32.dll",EntryPoint="QueryInformationJobObject",ExactSpelling=true,SetLastError=true)]
        static extern bool QueryAccounting(IntPtr job,int kind,out Accounting info,uint size,IntPtr length);
        [DllImport("kernel32.dll",ExactSpelling=true,SetLastError=true)] static extern bool GetHandleInformation(IntPtr handle,out uint flags);
        [DllImport("kernel32.dll",ExactSpelling=true,SetLastError=true)]
        static extern bool InitializeProcThreadAttributeList(IntPtr list,int count,uint flags,ref UIntPtr size);
        [DllImport("kernel32.dll",ExactSpelling=true,SetLastError=true)]
        static extern bool UpdateProcThreadAttribute(IntPtr list,uint flags,UIntPtr attribute,IntPtr value,UIntPtr size,IntPtr previous,IntPtr returned);
        [DllImport("kernel32.dll",ExactSpelling=true)] static extern void DeleteProcThreadAttributeList(IntPtr list);
        [DllImport("kernel32.dll",ExactSpelling=true,CharSet=CharSet.Unicode,SetLastError=true)]
        static extern bool CreateProcessW(string exe,StringBuilder command,ref SecurityAttributes processSecurity,
            ref SecurityAttributes threadSecurity,bool inherit,uint flags,IntPtr environment,string cwd,ref StartupEx startup,out ProcessInfo info);
        [DllImport("kernel32.dll",ExactSpelling=true,SetLastError=true)] static extern bool IsProcessInJob(IntPtr process,IntPtr job,out bool member);
        [DllImport("kernel32.dll",ExactSpelling=true,SetLastError=true)] static extern uint ResumeThread(IntPtr thread);
        [DllImport("kernel32.dll",ExactSpelling=true,SetLastError=true)] static extern uint WaitForSingleObject(IntPtr process,uint milliseconds);
        [DllImport("kernel32.dll",ExactSpelling=true,SetLastError=true)] static extern bool GetExitCodeProcess(IntPtr process,out uint code);
        [DllImport("kernel32.dll",ExactSpelling=true,SetLastError=true)] static extern bool TerminateJobObject(IntPtr job,uint code);
        [DllImport("kernel32.dll",ExactSpelling=true,SetLastError=true)] static extern bool CloseHandle(IntPtr handle);
        [DllImport("kernel32.dll",ExactSpelling=true,CharSet=CharSet.Unicode,SetLastError=true)] static extern uint GetModuleFileNameW(IntPtr module,StringBuilder path,uint size);
        [DllImport("kernel32.dll",ExactSpelling=true,CharSet=CharSet.Unicode)] static extern uint GetWindowsDirectoryW(StringBuilder path,uint size);
        [DllImport("kernel32.dll",ExactSpelling=true,CharSet=CharSet.Unicode)] static extern uint GetSystemDirectoryW(StringBuilder path,uint size);
        [DllImport("advapi32.dll",ExactSpelling=true,CharSet=CharSet.Unicode,SetLastError=true)]
        static extern bool ConvertStringSecurityDescriptorToSecurityDescriptorW(string text,uint revision,out IntPtr descriptor,out uint size);
        [DllImport("kernel32.dll",ExactSpelling=true)] static extern IntPtr LocalFree(IntPtr value);
        static void FreeLocal(ref IntPtr value) {
            IntPtr old=value; value=IntPtr.Zero;
            if (old!=IntPtr.Zero && LocalFree(old)!=IntPtr.Zero) throw new GuardianUnknown("native_release_unknown");
        }
        static void FreeBuffer(ref IntPtr value) {
            IntPtr old=value; value=IntPtr.Zero; if (old!=IntPtr.Zero) Marshal.FreeHGlobal(old);
        }
        static void CloseNative(ref IntPtr value) {
            IntPtr old=value; value=IntPtr.Zero;
            if (old!=IntPtr.Zero && !CloseHandle(old)) throw new GuardianUnknown("native_close_unknown");
        }
        static SecurityAttributes Descriptor(out IntPtr pointer) {
            uint size;
            if (!ConvertStringSecurityDescriptorToSecurityDescriptorW(ObjectSddl,1,out pointer,out size))
                throw new GuardianRefused("object_descriptor");
            return new SecurityAttributes {Length=(uint)Marshal.SizeOf(typeof(SecurityAttributes)),Descriptor=pointer,Inherit=0};
        }
        public void RequireHost(GuardianPlan plan) {
            if (Environment.OSVersion.Platform!=PlatformID.Win32NT || IntPtr.Size!=8) throw new GuardianRefused("native_windows_x64");
            var path=new StringBuilder(512); uint count=GetModuleFileNameW(IntPtr.Zero,path,512);
            // A future separately installed, reviewed EXE must host this body.
            // Loading it into a checkout interpreter/PowerShell is not that EXE.
            if (count<1 || count>=512 || path.ToString()!=plan.Root+"\\"+ProvisionProcessGuardian.GuardianExe)
                throw new GuardianRefused("protected_host_role");
            using (WindowsIdentity identity=WindowsIdentity.GetCurrent()) {
                if (identity.User==null || identity.User.Value!=plan.OperatorSid ||
                    !new WindowsPrincipal(identity).IsInRole(WindowsBuiltInRole.Administrator)) throw new GuardianRefused("enabled_operator_required");
            }
        }
        public object NewJob() {
            IntPtr descriptor=IntPtr.Zero,job=IntPtr.Zero;
            try {
                SecurityAttributes security=Descriptor(out descriptor);
                job=CreateJobObjectW(ref security,null); // private, unnamed, non-inheritable
                if (job==IntPtr.Zero) throw new GuardianRefused("job_create");
                var limits=new JobLimits(); limits.Basic.Flags=JobFlags; limits.Basic.ActiveLimit=2;
                if (!SetInformationJobObject(job,9,ref limits,(uint)Marshal.SizeOf(typeof(JobLimits)))) throw new GuardianRefused("job_limits");
                JobLimits actual; uint handleFlags;
                if (!QueryLimits(job,9,out actual,(uint)Marshal.SizeOf(typeof(JobLimits)),IntPtr.Zero) ||
                    actual.Basic.Flags!=JobFlags || actual.Basic.ActiveLimit!=2 ||
                    !GetHandleInformation(job,out handleFlags) || (handleFlags&1)!=0) throw new GuardianRefused("job_readback");
                FreeLocal(ref descriptor);
                object owned=job; job=IntPtr.Zero; return owned;
            } finally {
                bool unknown=false;
                try { CloseNative(ref job); } catch { unknown=true; }
                try { FreeLocal(ref descriptor); } catch { unknown=true; }
                if (unknown) throw new GuardianUnknown("native_release_unknown");
            }
        }
        internal static string Command(string root) {
            return "\""+root+"\\"+ProvisionProcessGuardian.WorkerExe+"\" "+ProvisionProcessGuardian.WorkerArguments;
        }
        internal static string EnvironmentBlock(string root,string windows,string system) {
            if (windows==null || windows.Length<4 || windows.Length>240 || !Regex.IsMatch(windows,@"\A[A-Za-z]:\\") ||
                !String.Equals(system,windows+"\\System32",StringComparison.OrdinalIgnoreCase)) throw new GuardianRefused("system_directory");
            foreach (string part in windows.Substring(3).Split('\\')) ProvisionProcessGuardian.Component(part);
            var vars=new SortedDictionary<string,string>(StringComparer.OrdinalIgnoreCase) {
                {"PATH",system},{"SystemRoot",windows},{"TEMP",root+"\\scratch"},{"TMP",root+"\\scratch"},{"WINDIR",windows}
            };
            var block=new StringBuilder();
            foreach (KeyValuePair<string,string> pair in vars) block.Append(pair.Key).Append('=').Append(pair.Value).Append('\0');
            block.Append('\0'); return block.ToString(); // complete block; never inherit the parent environment
        }
        sealed class LaunchState {
            internal IntPtr Attributes,JobArray,Environment,Descriptor;
            internal bool AttributesReady;
            internal ProcessInfo Child;
            internal void ReleaseScratch() {
                bool unknown=false;
                if (AttributesReady) {
                    AttributesReady=false;
                    try { DeleteProcThreadAttributeList(Attributes); } catch { unknown=true; }
                }
                try { FreeBuffer(ref Attributes); } catch { unknown=true; }
                try { FreeBuffer(ref JobArray); } catch { unknown=true; }
                try { FreeBuffer(ref Environment); } catch { unknown=true; }
                try { FreeLocal(ref Descriptor); } catch { unknown=true; }
                if (unknown) throw new GuardianUnknown("native_release_unknown");
            }
            internal void CloseAll() {
                bool unknown=false;
                try { CloseNative(ref Child.Thread); } catch { unknown=true; }
                try { CloseNative(ref Child.Process); } catch { unknown=true; }
                try { ReleaseScratch(); } catch { unknown=true; }
                if (unknown) throw new GuardianUnknown("native_release_unknown");
            }
        }
        public ChildPair CreateSuspended(object job,string root) {
            var state=new LaunchState(); var answer=new ChildPair();
            try {
                UIntPtr size=UIntPtr.Zero;
                bool probe=InitializeProcThreadAttributeList(IntPtr.Zero,1,0,ref size);
                if (probe || Marshal.GetLastWin32Error()!=122 || size.ToUInt64()<1 || size.ToUInt64()>4096)
                    throw new GuardianRefused("attribute_extent");
                state.Attributes=Marshal.AllocHGlobal((int)size.ToUInt64());
                if (!InitializeProcThreadAttributeList(state.Attributes,1,0,ref size)) throw new GuardianRefused("attribute_initialize");
                state.AttributesReady=true; state.JobArray=Marshal.AllocHGlobal(IntPtr.Size);
                Marshal.WriteIntPtr(state.JobArray,(IntPtr)job);
                if (!UpdateProcThreadAttribute(state.Attributes,0,new UIntPtr(JobListAttribute),state.JobArray,
                    new UIntPtr((uint)IntPtr.Size),IntPtr.Zero,IntPtr.Zero)) throw new GuardianRefused("atomic_job_list_required");
                var windows=new StringBuilder(512); var system=new StringBuilder(512);
                uint wc=GetWindowsDirectoryW(windows,512),sc=GetSystemDirectoryW(system,512);
                if (wc<1 || wc>=512 || sc<1 || sc>=512) throw new GuardianRefused("system_directory");
                byte[] environment=Encoding.Unicode.GetBytes(EnvironmentBlock(root,windows.ToString(),system.ToString()));
                if (environment.Length>8192) throw new GuardianRefused("environment_extent");
                state.Environment=Marshal.AllocHGlobal(environment.Length); Marshal.Copy(environment,0,state.Environment,environment.Length);
                SecurityAttributes security=Descriptor(out state.Descriptor);
                var startup=new StartupEx(); startup.Startup.Size=(uint)Marshal.SizeOf(typeof(StartupEx)); startup.Attributes=state.Attributes;
                if (!CreateProcessW(root+"\\"+ProvisionProcessGuardian.WorkerExe,new StringBuilder(Command(root)),ref security,ref security,
                    false,ProcessFlags,state.Environment,root,ref startup,out state.Child)) throw new GuardianRefused("atomic_create_refused");
                if (state.Child.Process==IntPtr.Zero || state.Child.Process==new IntPtr(-1) || state.Child.Thread==IntPtr.Zero ||
                    state.Child.Thread==new IntPtr(-1) || state.Child.Id==0 || state.Child.ThreadId==0) throw new GuardianUnknown("process_info_unknown");
                // Scratch cleanup and handle boxing precede ownership transfer.
                // A failure here closes both local handles; the caller still
                // holds the KILL_ON_JOB_CLOSE job and stops/observes the job.
                state.ReleaseScratch(); answer.Process=state.Child.Process; answer.Thread=state.Child.Thread; answer.Id=state.Child.Id;
                state.Child.Process=IntPtr.Zero; state.Child.Thread=IntPtr.Zero; return answer;
            } finally { state.CloseAll(); }
        }
        public bool Member(object process,object job) {
            bool member;
            if (!IsProcessInJob((IntPtr)process,(IntPtr)job,out member)) throw new GuardianUnknown("membership_unknown"); return member;
        }
        public uint Resume(object thread) { return ResumeThread((IntPtr)thread); }
        public uint Wait(object process,uint milliseconds) {
            if (milliseconds>ProvisionProcessGuardian.WaitSliceMs) throw new GuardianRefused("wait_extent");
            return WaitForSingleObject((IntPtr)process,milliseconds);
        }
        public uint ExitCode(object process) {
            uint code; if (!GetExitCodeProcess((IntPtr)process,out code)) throw new GuardianUnknown("exit_code_unknown"); return code;
        }
        public uint Active(object job) {
            Accounting info;
            if (!QueryAccounting((IntPtr)job,1,out info,(uint)Marshal.SizeOf(typeof(Accounting)),IntPtr.Zero)) throw new GuardianUnknown("job_accounting_unknown");
            return info.Active;
        }
        public void Stop(object job) { if (!TerminateJobObject((IntPtr)job,124)) throw new GuardianUnknown("stop_unknown"); }
        public void Pause(int milliseconds) {
            if (milliseconds<1 || milliseconds>ProvisionProcessGuardian.PollMs) throw new GuardianRefused("pause_extent"); Thread.Sleep(milliseconds);
        }
        public void Close(object handle) { IntPtr value=(IntPtr)handle; CloseNative(ref value); }
    }
}
