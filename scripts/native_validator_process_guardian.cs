// UNWIRED provisioning-process guardian BODY, not an installed executable.
// Must run in a separately protected guardian process BEFORE the worker loads
// the acquisition/provisioning assemblies. No Main, approval authenticator,
// installation, Python invocation, VM control, claim reset or fallback launcher.
using System;
using System.Diagnostics;
using System.Security.Cryptography;
using System.Text.RegularExpressions;
namespace AiAgent.ValidatorGuardian {
    public sealed class GuardianRefused : Exception {
        internal GuardianRefused(string label) : base(label) { }
    }
    public sealed class GuardianUnknown : Exception {
        internal GuardianUnknown(string label) : base(label) { }
    }
    public sealed class GuardianPlan {
        // Forgeable data: the future protected starter must authenticate the
        // approval and hold the complete guardian/worker/CLR/DLL/scratch closure.
        public readonly string Root, OperatorSid, InstallationId, ApprovalSha256;
        public readonly long ApprovedUntilUnix;
        public readonly int BudgetSeconds;
        public GuardianPlan(string root,string sid,string id,string approval,long until,int seconds) {
            Root=root; OperatorSid=sid; InstallationId=id; ApprovalSha256=approval;
            ApprovedUntilUnix=until; BudgetSeconds=seconds;
        }
    }
    // Immutable NON-SECRET consistency bytes for the fixed optional section
    // delivery path. No codec, file access, authorization or application import.
    internal sealed class GuardianRequest {
        readonly byte[] raw;
        internal readonly GuardianPlan Plan;
        internal readonly long Bytes;
        internal readonly string Sha256;
        internal GuardianRequest(GuardianPlan plan,byte[] request,long bytes,string digest) {
            ProvisionProcessGuardian.Validate(plan);
            if (request==null || bytes<1 || bytes>32768 || request.Length!=bytes || digest!=plan.ApprovalSha256 ||
                plan.ApprovedUntilUnix<1 || plan.ApprovedUntilUnix>253402300799L)
                throw new GuardianRefused("delivery_request_pin");
            Plan=plan; Bytes=bytes; Sha256=digest; raw=(byte[])request.Clone();
            if (!Matches(raw)) throw new GuardianRefused("delivery_request_pin");
        }
        internal bool Matches(byte[] value) {
            if (value==null || value.Length!=Bytes) return false;
            using (SHA256 sha=SHA256.Create())
                return BitConverter.ToString(sha.ComputeHash(value)).Replace("-","").ToLowerInvariant()==Sha256;
        }
        internal byte[] CopyRequest() { return (byte[])raw.Clone(); }
    }
    public enum LocalProcessEnd { RootExited, DeadlineStopped, ResidualTreeStopped }
    public sealed class LocalProcessObservation {
        public const string Scope="local_process_observations_only_not_install_acceptance";
        public readonly string InstallationId, ApprovalSha256;
        public readonly uint ProcessId;
        public readonly uint? ExitCode;
        public readonly LocalProcessEnd End;
        public readonly bool Resumed, EmptyObserved;
        internal LocalProcessObservation(GuardianPlan plan,ChildPair pair,uint? code,
            LocalProcessEnd end,bool resumed) {
            InstallationId=plan.InstallationId; ApprovalSha256=plan.ApprovalSha256;
            ProcessId=pair.Id; ExitCode=code; End=end; Resumed=resumed; EmptyObserved=true;
        }
    }
    internal sealed class ChildPair { internal object Process, Thread; internal uint Id; }
    internal interface IGuardianClock { double Seconds { get; } long Unix { get; } }
    internal sealed class GuardianClock : IGuardianClock {
        readonly Stopwatch clock=Stopwatch.StartNew();
        public double Seconds { get { return clock.Elapsed.TotalSeconds; } }
        public long Unix { get { return (long)(DateTime.UtcNow-new DateTime(1970,1,1)).TotalSeconds; } }
    }
    // Internal composition hook only. No caller-selected command or public callback.
    internal interface IGuardianLaunchGate {
        void BeforeCreate();
        void BeforeResume();
    }
    internal interface IGuardianKernel {
        void RequireHost(GuardianPlan plan);
        object NewJob();
        ChildPair CreateSuspended(object job,string root); // atomic JOB_LIST assignment
        bool Member(object process,object job);
        uint Resume(object thread);
        uint Wait(object process,uint milliseconds);
        uint ExitCode(object process);
        uint Active(object job);
        void Stop(object job); // whole exact-owned job, never PID/name lookup
        void Pause(int milliseconds);
        void Close(object handle);
    }
    // Same-assembly OPTIONAL fixed delivery seam. Both binds ONLY stage data:
    // no native/file/process operation or callback into caller-selected code.
    // BindWindow supplies THIS core's actual clock and stopAt AFTER its held
    // pre-create gate, not a cap guessed earlier by request admission.
    internal interface IGuardianWindowKernel {
        void BindWindow(GuardianPlan plan,IGuardianClock clock,double runDeadline);
    }
    internal interface IGuardianRequestKernel : IGuardianKernel,IGuardianWindowKernel {
        void BindRequest(GuardianRequest request);
    }
    public sealed class ProvisionProcessGuardian {
        internal const string GuardianExe="validator-install-guardian.exe";
        internal const string WorkerExe="validator-provision-worker.exe";
        internal const string WorkerArguments="--provision-once";
        internal const int MaxSeconds=900, StopReserveSeconds=5, WaitSliceMs=500, PollMs=20;
        readonly object sync=new object();
        readonly GuardianPlan plan;
        readonly IGuardianClock clock;
        readonly IGuardianKernel api;
        readonly IGuardianLaunchGate launchGate;
        readonly double deadline, stopAt;
        readonly object[] owned=new object[3]; // job, root process, primary thread
        int ownedCount;
        bool used, closed, stopAttempted, resumed, timedOut, residual, creationAttempted;
        // Terminal local fact for the held-target composition, NOT approval/evidence.
        // Any failure after entering creation conservatively keeps the target lease.
        internal bool LaunchTargetsReleasable { get; private set; }
        object job;
        ChildPair child;
        uint? exitCode;
        public ProvisionProcessGuardian(GuardianPlan value)
            : this(value,new WindowsGuardianKernel(),new GuardianClock()) { }
        internal ProvisionProcessGuardian(GuardianPlan value,IGuardianKernel kernel,IGuardianClock time)
            : this(value,kernel,time,null,null) { }
        internal ProvisionProcessGuardian(GuardianPlan value,IGuardianKernel kernel,IGuardianClock time,
            double? originalDeadline,IGuardianLaunchGate gate) {
            plan=value; api=kernel; clock=time; launchGate=gate; Validate(value);
            double now=Now(); long remaining=plan.ApprovedUntilUnix-clock.Unix;
            if (remaining<StopReserveSeconds+1 || remaining>86400) throw new GuardianRefused("approval_window");
            double limit=now+Math.Min(plan.BudgetSeconds,remaining);
            if (originalDeadline.HasValue) {
                double bound=originalDeadline.Value;
                if (Double.IsNaN(bound) || Double.IsInfinity(bound) || bound<=now)
                    throw new GuardianRefused("shared_deadline");
                limit=Math.Min(limit,bound); // never renew the original attempt budget
            }
            deadline=limit; stopAt=deadline-StopReserveSeconds;
        }
        internal static void Component(string text) {
            if (text==null || text.Length<1 || text.Length>120 ||
                !Regex.IsMatch(text,"\\A[A-Za-z0-9_ .()\\-]+\\z") || text=="." || text==".." ||
                text.EndsWith(" ",StringComparison.Ordinal) || text.EndsWith(".",StringComparison.Ordinal) ||
                Regex.IsMatch(text,"\\A(?:CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])(?:\\..*)?\\z",RegexOptions.IgnoreCase))
                throw new GuardianRefused("path_component");
        }
        internal static void Validate(GuardianPlan p) {
            if (p==null || p.Root==null || p.Root.Length<4 || p.Root.Length>200 ||
                !Regex.IsMatch(p.Root,"\\A[A-Za-z]:\\\\") || p.OperatorSid==null ||
                !Regex.IsMatch(p.OperatorSid,"\\AS-1-5-21-[0-9]+-[0-9]+-[0-9]+-[0-9]+\\z") ||
                p.InstallationId==null || !Regex.IsMatch(p.InstallationId,"\\A[0-9a-f]{32}\\z") ||
                p.ApprovalSha256==null || !Regex.IsMatch(p.ApprovalSha256,"\\A[0-9a-f]{64}\\z"))
                throw new GuardianRefused("plan");
            foreach (string part in p.Root.Substring(3).Split('\\')) Component(part);
            if (p.BudgetSeconds<StopReserveSeconds+1 || p.BudgetSeconds>MaxSeconds) throw new GuardianRefused("budget");
        }
        double Now() {
            double value=clock.Seconds;
            if (Double.IsNaN(value) || Double.IsInfinity(value)) throw new GuardianUnknown("clock_unknown");
            return value;
        }
        bool RunExpired() { return Now()>=stopAt || clock.Unix>=plan.ApprovedUntilUnix; }
        void BeforeStart() { if (RunExpired()) throw new GuardianRefused("start_window"); }
        bool Own(object handle) {
            if (handle==null) return false;
            for (int i=0;i<ownedCount;i++) if (Object.Equals(owned[i],handle)) return false;
            if (ownedCount==owned.Length) throw new GuardianUnknown("handle_extent");
            owned[ownedCount++]=handle; return true;
        }
        uint Count() {
            uint active=api.Active(job);
            if (active>2) throw new GuardianUnknown("job_accounting_unknown");
            return active;
        }
        void StopOnce() {
            if (stopAttempted) return;
            stopAttempted=true; // disarm BEFORE the single termination attempt
            api.Stop(job);
        }
        void ObserveEnd(bool forceStop) {
            Exception failure=null;
            if (forceStop) { try { StopOnce(); } catch { failure=new GuardianUnknown("stop_unknown"); } }
            double end=Math.Min(deadline,Now()+StopReserveSeconds);
            bool empty=false;
            for (int poll=0;poll<=StopReserveSeconds*1000/PollMs;poll++) {
                if (Now()>=end) break;
                uint active;
                try { active=Count(); }
                catch { failure=new GuardianUnknown("job_accounting_unknown"); break; }
                uint wait=0;
                try { if (child!=null && child.Process!=null) wait=api.Wait(child.Process,0); }
                catch { failure=new GuardianUnknown("root_wait_unknown"); break; }
                if (wait!=0 && wait!=258) { failure=new GuardianUnknown("root_wait_unknown"); break; }
                if (active==0 && wait==0) { empty=true; break; }
                if (!stopAttempted) {
                    residual=true;
                    try { StopOnce(); } catch { failure=new GuardianUnknown("stop_unknown"); }
                }
                int delay=(int)Math.Min(PollMs,Math.Floor((end-Now())*1000));
                if (delay<1) break;
                try { api.Pause(delay); } catch { failure=new GuardianUnknown("pause_unknown"); break; }
            }
            if (!empty && failure==null) failure=new GuardianUnknown("termination_unknown");
            if (failure!=null) throw failure;
        }
        void CloseAll() {
            if (closed) return;
            closed=true; bool failed=false;
            for (int i=ownedCount-1;i>=0;i--) {
                object handle=owned[i]; owned[i]=null;
                try { api.Close(handle); } catch { failed=true; }
            }
            if (failed) throw new GuardianUnknown("close_unknown");
        }
        public LocalProcessObservation Run() { lock (sync) { return RunOnce(); } }
        LocalProcessObservation RunOnce() {
            if (used) throw new GuardianRefused("one_shot"); used=true;
            Exception failure=null;
            try {
                BeforeStart(); api.RequireHost(plan); BeforeStart();
                object created=api.NewJob();
                if (!Own(created)) throw new GuardianUnknown("job_handle_unknown"); job=created;
                BeforeStart(); if (launchGate!=null) launchGate.BeforeCreate(); BeforeStart();
                var delivery=api as IGuardianWindowKernel;
                if (delivery!=null) {
                    delivery.BindWindow(plan,clock,stopAt);
                    BeforeStart();
                }
                creationAttempted=true; // disarm BEFORE crossing the native creation boundary
                child=api.CreateSuspended(job,plan.Root);
                if (child==null) throw new GuardianUnknown("child_unknown");
                // Adopt BOTH outputs before rejecting malformed/aliased pairs.
                bool process=Own(child.Process), thread=Own(child.Thread);
                if (!process || !thread || child.Id==0) throw new GuardianUnknown("child_handles_unknown");
                if (!api.Member(child.Process,job) || Count()!=1) throw new GuardianUnknown("atomic_membership_unknown");
                if (launchGate!=null) launchGate.BeforeResume(); BeforeStart();
                if (api.Resume(child.Thread)!=1) throw new GuardianUnknown("resume_unknown");
                resumed=true;
                for (int poll=0;poll<=MaxSeconds*1000/WaitSliceMs;poll++) {
                    if (RunExpired()) { timedOut=true; break; }
                    uint ms=(uint)Math.Min(WaitSliceMs,Math.Floor((stopAt-Now())*1000));
                    if (ms<1) { timedOut=true; break; }
                    uint wait=api.Wait(child.Process,ms);
                    if (wait==0) {
                        exitCode=api.ExitCode(child.Process); // valid even when code==259
                        timedOut=RunExpired(); residual=Count()!=0; break;
                    }
                    if (wait!=258) throw new GuardianUnknown("root_wait_unknown");
                    if (poll==MaxSeconds*1000/WaitSliceMs) throw new GuardianUnknown("wait_progress_unknown");
                }
            } catch (GuardianRefused ex) { failure=ex; }
              catch (GuardianUnknown ex) { failure=ex; }
              catch { failure=new GuardianUnknown("guardian_unknown"); }
            if (job!=null) {
                try { ObserveEnd(failure!=null || timedOut || residual); }
                catch { failure=new GuardianUnknown("termination_unknown"); }
            }
            bool closeKnown=true, windowKnown=true;
            try { CloseAll(); } catch { closeKnown=false; failure=new GuardianUnknown("close_unknown"); }
            try { if (job!=null && Now()>=deadline) { windowKnown=false; failure=new GuardianUnknown("deadline_outcome_unknown"); } }
            catch { windowKnown=false; failure=new GuardianUnknown("clock_unknown"); }
            if (!creationAttempted && closeKnown && windowKnown) LaunchTargetsReleasable=true;
            if (failure!=null) throw failure;
            if (child==null) throw new GuardianUnknown("child_unknown");
            LaunchTargetsReleasable=true; // checked empty job/root, closes and original window
            return new LocalProcessObservation(plan,child,exitCode,
                timedOut?LocalProcessEnd.DeadlineStopped:(residual?LocalProcessEnd.ResidualTreeStopped:LocalProcessEnd.RootExited),resumed);
        }
    }
}
