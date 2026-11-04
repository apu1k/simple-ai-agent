// UNWIRED held-target / provisioning-process guardian COMPOSITION, not a starter.
// OS/CLR/self-load provenance and authenticated permanent approval MUST precede
// this assembly. Never compile/load checkout code elevated. No Main or tool.
using System;
using AiAgent.ValidatorGuardian;
using AiAgent.ValidatorLaunch;
namespace AiAgent.ValidatorHandoff {
    public sealed class HeldGuardianRefused : Exception {
        internal HeldGuardianRefused(string label) : base(label) { }
    }
    public sealed class HeldGuardianUnknown : Exception {
        internal HeldGuardianUnknown(string label) : base(label) { }
    }
    // One monotonic origin is shared across acquisition, both launch gates,
    // process execution and cleanup. A rollback/nonfinite observation refuses.
    internal sealed class HandoffClock : IGuardianClock,ILaunchClock {
        readonly IGuardianClock source;
        readonly object sync=new object();
        double last=Double.NegativeInfinity;
        internal HandoffClock(IGuardianClock value) { source=value; }
        public double Seconds {
            get {
                lock (sync) {
                    double now=source.Seconds;
                    if (Double.IsNaN(now) || Double.IsInfinity(now) || now<last)
                        throw new HeldGuardianUnknown("clock_unknown");
                    last=now; return now;
                }
            }
        }
        public long Unix { get { return source.Unix; } }
    }
    public sealed class HeldProvisionGuardian {
        // NOT an authorization API. A new instance cannot grant another attempt.
        // Future guardian entry point compiles this and both bodies into ONE
        // protected application assembly; it must not dynamically load a bridge.
        readonly object sync=new object();
        readonly LaunchBoundary boundary;
        readonly ProvisionProcessGuardian guardian;
        readonly HandoffClock clock;
        readonly double deadline;
        readonly long approvedUntil;
        HeldLaunchLease lease;
        bool used;
        sealed class LaunchGate : IGuardianLaunchGate {
            readonly HeldProvisionGuardian owner;
            internal LaunchGate(HeldProvisionGuardian value) { owner=value; }
            void Check() {
                if (owner.lease==null) throw new GuardianRefused("held_targets_missing");
                try { owner.lease.ReverifyBeforeLaunch(); }
                catch (LaunchRefused) { throw new GuardianRefused("held_targets_refused"); }
                catch { throw new GuardianUnknown("held_targets_unknown"); }
            }
            public void BeforeCreate() { Check(); }
            public void BeforeResume() { Check(); }
        }
        public HeldProvisionGuardian(LaunchPlan value)
            : this(value,new WindowsLaunchFiles(),new WindowsGuardianKernel(),new GuardianClock()) { }
        internal HeldProvisionGuardian(LaunchPlan value,ILaunchFiles files,IGuardianKernel kernel,IGuardianClock time) {
            if (value==null || files==null || kernel==null || time==null) throw new HeldGuardianRefused("plan");
            try {
                clock=new HandoffClock(time);
                double now=clock.Seconds; long remaining=value.ApprovedUntilUnix-clock.Unix;
                if (value.BudgetSeconds<ProvisionProcessGuardian.StopReserveSeconds+1 ||
                    value.BudgetSeconds>ProvisionProcessGuardian.MaxSeconds ||
                    remaining<ProvisionProcessGuardian.StopReserveSeconds+1 || remaining>86400)
                    throw new HeldGuardianRefused("attempt_window");
                approvedUntil=value.ApprovedUntilUnix;
                deadline=now+Math.Min(value.BudgetSeconds,remaining);
                // Acquisition/hashing must finish BEFORE the stop reserve, not
                // consume it and grant the process a fresh full execution budget.
                boundary=new LaunchBoundary(value,files,clock,deadline-ProvisionProcessGuardian.StopReserveSeconds);
                // No second caller-supplied plan: shared fields are derived once.
                var processPlan=new GuardianPlan(value.Root,value.OperatorSid,value.InstallationId,
                    value.ApprovalSha256,value.ApprovedUntilUnix,value.BudgetSeconds);
                guardian=new ProvisionProcessGuardian(processPlan,kernel,clock,deadline,new LaunchGate(this));
            } catch (HeldGuardianRefused) { throw; }
              catch (HeldGuardianUnknown) { throw; }
              catch (LaunchRefused) { throw new HeldGuardianRefused("target_plan"); }
              catch (GuardianRefused) { throw new HeldGuardianRefused("process_plan"); }
              catch { throw new HeldGuardianUnknown("construction_unknown"); }
        }
        // Terminal local observation only. False is NOT proof every native close
        // succeeded; true means locks deliberately remain owned by this object.
        public bool LaunchLeaseRetained { get { lock (sync) { return lease!=null; } } }
        public LocalProcessObservation Run() {
            lock (sync) {
                if (used) throw new HeldGuardianRefused("one_shot"); used=true;
                LocalProcessObservation answer=null; Exception failure=null;
                try {
                    lease=boundary.Acquire();
                    answer=guardian.Run();
                } catch (LaunchRefused) { failure=new HeldGuardianRefused("targets_refused"); }
                  catch (GuardianRefused) { failure=new HeldGuardianRefused("process_refused"); }
                  catch { failure=new HeldGuardianUnknown("handoff_unknown"); }
                if (lease!=null && guardian.LaunchTargetsReleasable) {
                    HeldLaunchLease current=lease; lease=null; // disarm before single close
                    try { current.Dispose(); }
                    catch { failure=new HeldGuardianUnknown("target_close_unknown"); }
                }
                // Do NOT put lease in a using/finally. Any guardian failure after
                // entering CreateSuspended retains it, even if stop may have worked.
                // No public unlock/retry/dispose/finalizer: independent protected
                // reconciliation remains mandatory before an uncertain host exits.
                if (lease!=null) throw new HeldGuardianUnknown("targets_retained_outcome_unknown");
                if (failure!=null) throw failure;
                if (answer==null) throw new HeldGuardianUnknown("observation_unknown");
                // Target closure consumes the SAME original window. A late close
                // cannot turn into success just because process observation finished.
                try {
                    if (clock.Seconds>=deadline || clock.Unix>=approvedUntil)
                        throw new HeldGuardianUnknown("deadline_outcome_unknown");
                } catch (HeldGuardianUnknown) { throw; }
                  catch { throw new HeldGuardianUnknown("clock_unknown"); }
                return answer; // local process observations, never install acceptance
            }
        }
    }
}
