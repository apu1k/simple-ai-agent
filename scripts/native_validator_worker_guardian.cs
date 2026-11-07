// UNWIRED worker lifetime composition, not an executable or protected transport.
// Never compile/load checkout code elevated. Trusted pre-load provenance,
// permanent approval and original-deadline delivery MUST precede this body.
// No native Python adapter is supplied: no fallback to the guardian's worker EXE.
using System;
using System.Text.RegularExpressions;
using AiAgent.NativeValidator;
using AiAgent.ValidatorGuardian;
using AiAgent.ValidatorRequest;
namespace AiAgent.ValidatorWorker {
    internal sealed class WorkerGuardianRefused : Exception {
        internal WorkerGuardianRefused(string label) : base(label) { }
    }
    internal sealed class WorkerGuardianUnknown : Exception {
        internal WorkerGuardianUnknown(string label) : base(label) { }
    }
    internal sealed class WorkerClock : IGuardianClock,IBoundaryClock {
        readonly IGuardianClock source;
        readonly object sync=new object();
        double last=Double.NegativeInfinity;
        internal WorkerClock(IGuardianClock value) { source=value; }
        public double Seconds {
            get {
                lock (sync) {
                    double now=source.Seconds;
                    if (Double.IsNaN(now) || Double.IsInfinity(now) || now<last)
                        throw new WorkerGuardianUnknown("clock_unknown");
                    last=now; return now;
                }
            }
        }
        public long Unix { get { return source.Unix; } }
    }
    internal sealed class WorkerLaunchContext {
        // Immutable consistency data, NOT authenticated transport or approval.
        // RunDeadline is in the SAME supplied clock origin, with stop time removed.
        readonly byte[] request;
        internal readonly string LaunchRoot,ImportRoot,InstallationId,OperatorSid;
        internal readonly string RequestSha256,WorkerSha256;
        internal readonly int BudgetSeconds;
        internal readonly long ApprovedUntilUnix,WorkerBytes;
        internal readonly double RunDeadline;
        internal WorkerLaunchContext(GuardianPlan process,InstallBoundaryPlan imports,byte[] raw,double stopAt) {
            FilePin pin=imports.Files["provision-request.json"];
            if (raw==null || raw.Length!=pin.Bytes || InstallBoundary.Sha(raw)!=pin.Sha256)
                throw new WorkerGuardianRefused("worker_pin");
            request=(byte[])raw.Clone(); WorkerBytes=pin.Bytes; WorkerSha256=pin.Sha256;
            LaunchRoot=process.Root; ImportRoot=imports.Root; InstallationId=process.InstallationId;
            OperatorSid=process.OperatorSid; RequestSha256=process.ApprovalSha256;
            BudgetSeconds=process.BudgetSeconds; ApprovedUntilUnix=process.ApprovedUntilUnix;
            RunDeadline=stopAt;
        }
        internal byte[] CopyRequest() { return (byte[])request.Clone(); }
    }
    // Internal compile-time seam, not a public callback/command API. There is NO
    // production implementation yet. A future reviewed fixed Python adapter must
    // authenticate/translate delivery before load, enforce worker host role and
    // fixed interpreter/import/environment/DLL policy, and atomically contain it.
    // Bind ONLY stages bounded data; it MUST NOT create/resume a process. ONLY
    // CreateSuspended may cross that boundary, exactly as in IGuardianKernel.
    internal interface IWorkerPythonKernel : IGuardianKernel {
        void Bind(WorkerLaunchContext context);
    }
    internal sealed class WorkerProvisionGuardian {
        // Same-assembly composition only: deliberately no public constructor,
        // default native kernel, Main, reset, Dispose, finalizer or unlock path.
        readonly object sync=new object();
        readonly long expectedBytes,approvedUntil;
        readonly string expectedSha256;
        readonly int budgetSeconds;
        readonly double deadline;
        readonly WorkerClock clock;
        readonly IBoundaryFiles files;
        readonly IWorkerPythonKernel kernel;
        ImportClosureLease lease;
        ProvisionProcessGuardian guardian;
        InstallBoundaryPlan importPlan;
        GuardianPlan processPlan;
        bool used;
        sealed class ImportGate : IGuardianLaunchGate {
            readonly WorkerProvisionGuardian owner;
            internal ImportGate(WorkerProvisionGuardian value) { owner=value; }
            public void BeforeCreate() {
                owner.BeforeWork();
                // Fixed held reader; complete closure checks BEFORE AND AFTER
                // copying. No raw outer projection can bypass actual held bytes.
                byte[] raw=owner.lease.CopyWorkerRequest();
                owner.BeforeWork();
                var context=new WorkerLaunchContext(owner.processPlan,owner.importPlan,raw,
                    owner.deadline-ProvisionProcessGuardian.StopReserveSeconds);
                owner.kernel.Bind(context);
                owner.BeforeWork();
            }
            public void BeforeResume() {
                owner.BeforeWork(); owner.lease.Reverify(); owner.BeforeWork();
            }
        }
        // Construct BEFORE request reception. originalDeadline is mandatory and
        // already earlier in THIS monotonic origin; it is never optional/fresh.
        internal WorkerProvisionGuardian(long requestBytes,string requestSha256,int seconds,long expiresUnix,
            double originalDeadline,IBoundaryFiles importFiles,IWorkerPythonKernel python,IGuardianClock time) {
            if (requestBytes<1 || requestBytes>InstallationRequest.MaxRequestBytes || requestSha256==null ||
                !Regex.IsMatch(requestSha256,"\\A[0-9a-f]{64}\\z") || seconds<6 || seconds>900 ||
                expiresUnix<1 || expiresUnix>253402300799L || importFiles==null || python==null || time==null)
                throw new WorkerGuardianRefused("attempt_plan");
            expectedBytes=requestBytes; expectedSha256=requestSha256; budgetSeconds=seconds;
            approvedUntil=expiresUnix; files=importFiles; kernel=python;
            try {
                clock=new WorkerClock(time);
                double now=clock.Seconds; long remaining=approvedUntil-clock.Unix;
                if (remaining<6 || remaining>86400) throw new WorkerGuardianRefused("attempt_window");
                if (Double.IsNaN(originalDeadline) || Double.IsInfinity(originalDeadline) || originalDeadline<=now)
                    throw new WorkerGuardianRefused("shared_deadline");
                deadline=Math.Min(originalDeadline,now+Math.Min(seconds,remaining));
                if (Double.IsNaN(deadline) || Double.IsInfinity(deadline) ||
                    deadline-ProvisionProcessGuardian.StopReserveSeconds<=now)
                    throw new WorkerGuardianRefused("attempt_window");
            } catch (WorkerGuardianRefused) { throw; }
              catch { throw new WorkerGuardianUnknown("clock_unknown"); }
        }
        void BeforeWork() {
            if (clock.Seconds>=deadline-ProvisionProcessGuardian.StopReserveSeconds || clock.Unix>=approvedUntil)
                throw new WorkerGuardianRefused("attempt_window");
        }
        internal bool ImportLeaseRetained { get { lock (sync) { return lease!=null; } } }
        internal LocalProcessObservation Run(byte[] request) {
            lock (sync) {
                if (used) throw new WorkerGuardianRefused("one_shot"); used=true;
                LocalProcessObservation answer=null; Exception failure=null;
                try {
                    BeforeWork();
                    BoundInstallationInputs inputs=InstallationRequest.Bind(request,expectedBytes,expectedSha256);
                    BeforeWork();
                    var launch=inputs.CreateLaunchPlan();
                    if (launch.BudgetSeconds!=budgetSeconds || launch.ApprovedUntilUnix!=approvedUntil)
                        throw new WorkerGuardianRefused("request_window_mismatch");
                    importPlan=inputs.CreateImportPlan();
                    processPlan=new GuardianPlan(launch.Root,launch.OperatorSid,launch.InstallationId,
                        launch.ApprovalSha256,launch.ApprovedUntilUnix,launch.BudgetSeconds);
                    var boundary=new InstallBoundary(importPlan,budgetSeconds,files,clock,
                        deadline-ProvisionProcessGuardian.StopReserveSeconds);
                    guardian=new ProvisionProcessGuardian(processPlan,kernel,clock,deadline,new ImportGate(this));
                    // Check the WORKER role before consuming the fixed import
                    // claim; the process core checks it again before job setup.
                    BeforeWork(); kernel.RequireHost(processPlan); BeforeWork();
                    lease=boundary.Acquire();
                    answer=guardian.Run();
                } catch (WorkerGuardianRefused ex) { failure=ex; }
                  catch (InstallRequestRefused) { failure=new WorkerGuardianRefused("request_refused"); }
                  catch (BoundaryRefused) { failure=new WorkerGuardianRefused("imports_refused"); }
                  catch (GuardianRefused) { failure=new WorkerGuardianRefused("process_refused"); }
                  catch { failure=new WorkerGuardianUnknown("worker_unknown"); }
                // This terminal core fact requires no creation attempt OR a
                // successful empty-job/root observation, closes and original cap.
                // Any core exception after creation attempt deliberately retains
                // imports, even when stop may have worked. NEVER unconditional
                // using/finally disposal around a live or uncertain interpreter.
                if (lease!=null && guardian!=null && guardian.LaunchTargetsReleasable) {
                    ImportClosureLease current=lease; lease=null; // disarm once
                    try { current.Dispose(); }
                    catch { failure=new WorkerGuardianUnknown("import_close_unknown"); }
                }
                if (lease!=null) throw new WorkerGuardianUnknown("imports_retained_outcome_unknown");
                if (failure!=null) throw failure;
                if (answer==null) throw new WorkerGuardianUnknown("observation_unknown");
                try {
                    if (clock.Seconds>=deadline || clock.Unix>=approvedUntil)
                        throw new WorkerGuardianUnknown("deadline_outcome_unknown");
                } catch (WorkerGuardianUnknown) { throw; }
                  catch { throw new WorkerGuardianUnknown("clock_unknown"); }
                return answer; // LOCAL process facts, never provisioning acceptance
            }
        }
    }
}
