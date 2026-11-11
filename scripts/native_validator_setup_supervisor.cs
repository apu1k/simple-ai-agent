// Uninstalled independent SETUP-process supervisor. No VM supervision, install
// acceptance, protected tool wiring or recovery/reset route. Never elevate a
// checkout. Trusted OS/CLR/self-load and authentic whole-attempt delivery precede
// this Main, INCLUDING failures/cancellation before its filesystem claim.
using System;
using System.Globalization;
using System.Runtime.InteropServices;
using System.Text;
using AiAgent.NativeValidator;
using AiAgent.ValidatorDelivery;
using AiAgent.ValidatorGuardian;
namespace AiAgent.ValidatorSetup {
    internal interface ISetupSupervisorFilesFactory {
        ISetupAttemptFiles Create(SetupSupervisorProfile profile,SetupClock clock,double cap);
    }
    internal sealed class WindowsSupervisorFilesFactory : ISetupSupervisorFilesFactory {
        public ISetupAttemptFiles Create(SetupSupervisorProfile p,SetupClock clock,double cap) {
            return WindowsSetupAttemptFiles.ForWatchdog(p,clock,cap);
        }
    }
    internal sealed class SetupSupervisorEntry {
        readonly object sync=new object();
        readonly SetupSupervisorProfile profile;
        readonly SetupClock clock;
        readonly ISetupRole role;
        readonly ISetupSupervisorFilesFactory factory;
        readonly IGuardianKernel kernel;
        ISetupAttemptFiles files;
        ProvisionProcessGuardian owner;
        bool used,retained;
        internal SetupSupervisorEntry(SetupSupervisorProfile p,IGuardianClock time,ISetupRole gate,
            ISetupSupervisorFilesFactory inputs,IGuardianKernel process) {
            if (p==null || gate==null || inputs==null || process==null) throw new SetupRefused("supervisor_entry");
            profile=p; clock=new SetupClock(time); role=gate; factory=inputs; kernel=process;
        }
        internal bool MustParkForSupervisor { get { lock (sync) { return retained; } } }
        static byte[] Receipt(SetupSupervisorProfile p,LocalProcessObservation o,byte[] result,bool valid) {
            string text="{\"attempt_id\":\""+p.Host.AttemptId+"\",\"empty_job_observed\":true,\"end\":\""+o.End.ToString()+
                "\",\"exit_code\":"+(o.ExitCode.HasValue?o.ExitCode.Value.ToString(CultureInfo.InvariantCulture):"null")+
                ",\"process_id\":"+o.ProcessId.ToString(CultureInfo.InvariantCulture)+",\"profile_sha256\":\""+p.Host.Digest+
                "\",\"result_sha256\":"+(result==null?"null":"\""+InstallBoundary.Sha(result)+"\"")+
                ",\"result_valid\":"+(valid?"true":"false")+",\"scope\":\"local_setup_process_observations_not_acceptance\",\"version\":1}\n";
            return Encoding.ASCII.GetBytes(text);
        }
        // Historical internal model seam. Production Main MUST use RunDelivered.
        internal int Run(string[] args) { return RunCore(args,null); }
        internal int RunDelivered(string[] args,ISectionCounter counter) {
            if (counter==null) return 126;
            return RunCore(args,counter);
        }
        int RunCore(string[] args,ISectionCounter counter) {
            lock (sync) {
                if (used) return 126; used=true; bool entered=false,returned=false; int code=125; double cap=0;
                try {
                    cap=clock.Start(profile.Host);
                    if (counter==null) {
                        if (args==null || args.Length!=0) throw new SetupRefused("supervisor_frame");
                    } else {
                        if (args==null || args.Length!=3) throw new SetupRefused("supervisor_frame");
                        string[] frame=(string[])args.Clone();
                        if (frame[0]!="--setup-supervise-qpc-v1") throw new SetupRefused("supervisor_frame");
                        long limit=SetupHostFrame.N(frame[1],Int64.MaxValue),rate=SetupHostFrame.N(frame[2],1000000000L);
                        cap=Math.Min(cap,SetupHostFrame.TranslateWindow(profile.Host,limit,rate,clock,counter));
                    }
                    role.Require(profile.Host,true); clock.Require(cap,profile.Host.ExpiresUnix);
                    files=factory.Create(profile,clock,cap); files.Acquire(); clock.Require(cap,profile.Host.ExpiresUnix);
                    var plan=new GuardianPlan(profile.Host.Location.Root,profile.Host.Parent.OperatorSid,profile.Host.AttemptId,
                        InstallBoundary.Sha(profile.Policy()),profile.Host.ExpiresUnix,profile.Host.Seconds);
                    owner=new ProvisionProcessGuardian(plan,kernel,clock,cap,files);
                    entered=true; LocalProcessObservation observation=owner.Run(); returned=true;
                    byte[] raw=files.ReadResult(); bool valid=false;
                    if (observation.End==LocalProcessEnd.RootExited && observation.Resumed && observation.ExitCode.HasValue && observation.ExitCode.Value==0) {
                        try { SetupResult.Parse(profile.Host,raw); valid=true; } catch (SetupRefused) { }
                    }
                    files.Reverify(); clock.Require(cap,profile.Host.ExpiresUnix);
                    files.WriteReceipt(Receipt(profile,observation,raw,valid)); files.Reverify(); clock.Require(cap,profile.Host.ExpiresUnix);
                    code=valid?0:(observation.End==LocalProcessEnd.DeadlineStopped?124:125);
                } catch (SetupRefused) { code=126; } catch (BoundaryRefused) { code=126; } catch { code=125; }
                finally {
                    // Only a NORMAL core return proves its exact job/root/close
                    // observations. Never infer absence from a later partial fact.
                    retained=entered && !returned;
                    if (files!=null && !retained) try { files.Close(); } catch { code=125; }
                }
                if (code==0) try { clock.Require(cap,profile.Host.ExpiresUnix); } catch { code=125; }
                return code; // process consistency ONLY, never installation approval
            }
        }
    }
    internal static class ValidatorSetupWatchdogProgram {
        [DllImport("kernel32.dll",ExactSpelling=true)] static extern void Sleep(uint milliseconds);
        static int Main(string[] args) {
            SetupSupervisorEntry entry;
            try {
                SetupSupervisorProfile p=ReviewedSetupSupervisor.Create(); var role=new WindowsSetupRole();
                entry=new SetupSupervisorEntry(p,new GuardianClock(),role,new WindowsSupervisorFilesFactory(),
                    new WindowsSetupSupervisorKernel(p,role,new SetupCounter()));
            } catch { return 125; }
            int code=entry.RunDelivered(args,new SetupCounter());
            if (entry.MustParkForSupervisor) for (;;) { Sleep(UInt32.MaxValue); GC.KeepAlive(entry); }
            return code;
        }
    }
}
