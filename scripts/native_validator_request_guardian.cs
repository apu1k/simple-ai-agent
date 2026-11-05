// UNWIRED same-process request / original-window / held-guardian composition.
// NOT an authorization API, protected starter, transport or executable. Trusted
// load provenance and permanent authenticated approval MUST precede this body.
// Never compile/load checkout code elevated. No Main, installer or tool wiring.
using System;
using System.Text.RegularExpressions;
using AiAgent.ValidatorGuardian;
using AiAgent.ValidatorHandoff;
using AiAgent.ValidatorLaunch;
using AiAgent.ValidatorRequest;
namespace AiAgent.ValidatorAdmission {
    public sealed class RequestGuardianRefused : Exception {
        internal RequestGuardianRefused(string label) : base(label) { }
    }
    public sealed class RequestGuardianUnknown : Exception {
        internal RequestGuardianUnknown(string label) : base(label) { }
    }
    public sealed class RequestProvisionGuardian {
        // Pins and time metadata are independently supplied CONSISTENCY DATA,
        // not authentication. Construct BEFORE receiving/decoding the request.
        // A new object cannot authorize another attempt or consume durable approval.
        readonly object sync=new object();
        readonly long expectedBytes,approvedUntil;
        readonly string expectedSha256;
        readonly int budgetSeconds;
        readonly double deadline;
        readonly HandoffClock clock;
        readonly ILaunchFiles files;
        readonly IGuardianKernel kernel;
        HeldProvisionGuardian guardian;
        bool used;
        public RequestProvisionGuardian(long requestBytes,string requestSha256,int seconds,long expiresUnix)
            : this(requestBytes,requestSha256,seconds,expiresUnix,
                new WindowsLaunchFiles(),new WindowsGuardianKernel(),new GuardianClock()) { }
        internal RequestProvisionGuardian(long requestBytes,string requestSha256,int seconds,long expiresUnix,
            ILaunchFiles targetFiles,IGuardianKernel processKernel,IGuardianClock time) {
            if (requestBytes<1 || requestBytes>InstallationRequest.MaxRequestBytes || requestSha256==null ||
                !Regex.IsMatch(requestSha256,"\\A[0-9a-f]{64}\\z") ||
                seconds<ProvisionProcessGuardian.StopReserveSeconds+1 || seconds>ProvisionProcessGuardian.MaxSeconds ||
                expiresUnix<1 || expiresUnix>253402300799L || targetFiles==null || processKernel==null || time==null)
                throw new RequestGuardianRefused("attempt_plan");
            expectedBytes=requestBytes; expectedSha256=requestSha256; budgetSeconds=seconds; approvedUntil=expiresUnix;
            files=targetFiles; kernel=processKernel;
            try {
                clock=new HandoffClock(time);
                double now=clock.Seconds; long remaining=approvedUntil-clock.Unix;
                if (remaining<ProvisionProcessGuardian.StopReserveSeconds+1 || remaining>86400)
                    throw new RequestGuardianRefused("attempt_window");
                deadline=now+Math.Min(budgetSeconds,remaining);
                if (Double.IsNaN(deadline) || Double.IsInfinity(deadline) || deadline<=now ||
                    deadline-ProvisionProcessGuardian.StopReserveSeconds<=now)
                    throw new RequestGuardianRefused("attempt_window");
            } catch (RequestGuardianRefused) { throw; }
              catch { throw new RequestGuardianUnknown("clock_unknown"); }
        }
        void BeforeRunWork() {
            if (clock.Seconds>=deadline-ProvisionProcessGuardian.StopReserveSeconds || clock.Unix>=approvedUntil)
                throw new RequestGuardianRefused("attempt_window");
        }
        // False is NOT a cleanup certificate; true conservatively retains the
        // whole inner guardian/lease. No public unlock/dispose/reset or finalizer.
        public bool LaunchLeaseRetained {
            get { lock (sync) { return guardian!=null && guardian.LaunchLeaseRetained; } }
        }
        public LocalProcessObservation Run(byte[] request) {
            lock (sync) {
                if (used) throw new RequestGuardianRefused("one_shot"); used=true;
                try {
                    BeforeRunWork();
                    // Pin-first, bounded clone/decode/canonical check of actual
                    // bytes. Never accept a separately supplied mutable plan.
                    BoundInstallationInputs inputs=InstallationRequest.Bind(request,expectedBytes,expectedSha256);
                    BeforeRunWork();
                    LaunchPlan plan=inputs.CreateLaunchPlan();
                    if (plan.BudgetSeconds!=budgetSeconds || plan.ApprovedUntilUnix!=approvedUntil)
                        throw new RequestGuardianRefused("request_window_mismatch");
                    // Pass BOTH the same monotonic origin and the earlier cap.
                    // Nothing here serializes or authenticates a cross-process cap.
                    guardian=new HeldProvisionGuardian(plan,files,kernel,clock,deadline);
                    BeforeRunWork();
                    LocalProcessObservation answer=guardian.Run();
                    if (clock.Seconds>=deadline || clock.Unix>=approvedUntil)
                        throw new RequestGuardianUnknown("deadline_outcome_unknown");
                    return answer; // unchanged LOCAL observations, not acceptance
                } catch (RequestGuardianRefused) { throw; }
                  catch (RequestGuardianUnknown) { throw; }
                  catch (InstallRequestRefused) { throw new RequestGuardianRefused("request_refused"); }
                  catch (HeldGuardianRefused) { throw new RequestGuardianRefused("held_guardian_refused"); }
                  catch { throw new RequestGuardianUnknown("request_guardian_unknown"); }
                // Do not release or drop guardian on failure. Its post-create
                // uncertainty retains locks and needs independent reconciliation.
            }
        }
    }
}
