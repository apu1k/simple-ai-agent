// UNINSTALLED fixed guardian entry candidate. NEVER build/load checkout code
// elevated. Separately trusted build/install/pre-load provenance, permanent
// early-failure/cancellation policy and an independent watchdog MUST precede it.
// ReviewedGuardianProfile is REQUIRED generated/reviewed build DATA, deliberately
// absent from the checkout. No default/dummy profile or caller-selected anchor.
using System;
using System.Globalization;
using System.Runtime.InteropServices;
using System.Security.Principal;
using System.Text;
using System.Text.RegularExpressions;
using AiAgent.NativeValidator;
using AiAgent.ValidatorApproval;
using AiAgent.ValidatorDelivery;
using AiAgent.ValidatorGuardian;
using AiAgent.ValidatorLaunch;
using AiAgent.ValidatorWorker;
namespace AiAgent.ValidatorEntry {
    internal sealed class GuardianEntryRefused : Exception {
        internal GuardianEntryRefused(string label) : base(label) { }
    }
    internal sealed class GuardianEntryProfile {
        // FIXED independent build references only. NEVER embed request/policy
        // content hashes here: the outer request itself pins these executables.
        internal readonly string ApprovalRoot,OperatorSid,LaunchRoot;
        internal readonly uint ApprovalVolume;
        internal readonly ulong ApprovalIndex;
        internal GuardianEntryProfile(string approvalRoot,uint volume,ulong index,string sid,string launchRoot) {
            if (index==0 || approvalRoot==null || approvalRoot.Length<4 || approvalRoot.Length>240 ||
                launchRoot==null || launchRoot.Length<4 || launchRoot.Length>200 ||
                !Regex.IsMatch(approvalRoot,"\\A[A-Z]:\\\\") || !Regex.IsMatch(launchRoot,"\\A[A-Z]:\\\\") ||
                sid==null || sid.Length>80 || !Regex.IsMatch(sid,"\\AS-1-5-21-[0-9]+-[0-9]+-[0-9]+-[0-9]+\\z"))
                throw new GuardianEntryRefused("guardian_profile");
            try { InstallBoundary.PathParts(approvalRoot); InstallBoundary.PathParts(launchRoot); }
            catch { throw new GuardianEntryRefused("guardian_profile"); }
            string[] parts=sid.Split('-');
            for (int i=4;i<parts.Length;i++) {
                uint number;
                if (!UInt32.TryParse(parts[i],NumberStyles.None,CultureInfo.InvariantCulture,out number) ||
                    number.ToString(CultureInfo.InvariantCulture)!=parts[i]) throw new GuardianEntryRefused("guardian_profile");
            }
            if (String.Equals(approvalRoot,launchRoot,StringComparison.OrdinalIgnoreCase) ||
                approvalRoot.StartsWith(launchRoot+"\\",StringComparison.OrdinalIgnoreCase) ||
                launchRoot.StartsWith(approvalRoot+"\\",StringComparison.OrdinalIgnoreCase))
                throw new GuardianEntryRefused("guardian_profile_overlap");
            ApprovalRoot=approvalRoot; ApprovalVolume=volume; ApprovalIndex=index; OperatorSid=sid; LaunchRoot=launchRoot;
        }
        internal ApprovalAnchorPlan Plan(GuardianEntryFrame frame) {
            WorkerEntryFrame r=frame.Request;
            return new ApprovalAnchorPlan(ApprovalRoot,ApprovalVolume,ApprovalIndex,OperatorSid,
                frame.PolicyBytes,frame.PolicySha256,r.RequestBytes,r.RequestSha256,r.BudgetSeconds,r.ExpiresUnix);
        }
    }
    internal sealed class GuardianEntryFrame {
        internal const string Mode="--install-once-section-v1";
        internal readonly WorkerEntryFrame Request;
        internal readonly long PolicyBytes;
        internal readonly string PolicySha256;
        GuardianEntryFrame(WorkerEntryFrame frame,long bytes,string digest) {
            Request=frame; PolicyBytes=bytes; PolicySha256=digest;
        }
        internal static GuardianEntryFrame Parse(string[] args) {
            if (args==null || args.Length!=10) throw new GuardianEntryRefused("guardian_frame");
            string[] copy=(string[])args.Clone(); long bytes;
            if (copy[0]!=Mode || copy[8]==null || copy[8].Length>4 || !Regex.IsMatch(copy[8],"\\A[1-9][0-9]*\\z") ||
                !Int64.TryParse(copy[8],NumberStyles.None,CultureInfo.InvariantCulture,out bytes) || bytes<1 || bytes>1024 ||
                copy[9]==null || !Regex.IsMatch(copy[9],"\\A[0-9a-f]{64}\\z")) throw new GuardianEntryRefused("guardian_frame");
            // Reuse the exact existing bounded section/metadata parser, NOT a
            // caller-controlled mode fallback. Guardian mode is required above.
            string[] request=new string[8]; Array.Copy(copy,request,8); request[0]=WorkerEntryFrame.Mode;
            return new GuardianEntryFrame(WorkerEntryFrame.Parse(request),bytes,copy[9]);
        }
    }
    internal interface IGuardianEntryInput {
        void RequireHost(GuardianEntryProfile profile);
        byte[] Read(GuardianEntryFrame frame);
    }
    internal sealed class GuardianEntry {
        readonly object sync=new object();
        readonly GuardianEntryProfile profile;
        readonly IBoundaryFiles files;
        readonly ILaunchFiles targets;
        readonly IGuardianRequestKernel kernel;
        readonly WorkerClock clock;
        readonly IWorkerCounter counter;
        readonly IGuardianEntryInput input;
        ApprovalProvisionGuardian owner;
        bool used;
        internal GuardianEntry(GuardianEntryProfile buildProfile,IBoundaryFiles approvalFiles,ILaunchFiles targetFiles,
            IGuardianRequestKernel processKernel,IGuardianClock time,IWorkerCounter commonCounter,IGuardianEntryInput receiver) {
            if (buildProfile==null || approvalFiles==null || targetFiles==null || processKernel==null ||
                time==null || commonCounter==null || receiver==null) throw new GuardianEntryRefused("guardian_entry_plan");
            profile=buildProfile; files=approvalFiles; targets=targetFiles; kernel=processKernel;
            clock=new WorkerClock(time); counter=commonCounter; input=receiver; // no samples/native work
        }
        internal bool MustParkForSupervisor {
            get { lock (sync) { return owner!=null && (owner.ApprovalLeaseRetained || owner.LaunchLeaseRetained); } }
        }
        internal int Run(string[] args) {
            lock (sync) {
                if (used) return 126; used=true;
                try {
                    GuardianEntryFrame frame=GuardianEntryFrame.Parse(args);
                    input.RequireHost(profile);
                    double earlier=WorkerEntryDeadline.Translate(frame.Request,clock,counter);
                    // Approval metadata is consistency DATA from the protected
                    // starter, never an argv-selected policy root/SID or grant.
                    // Held private policy + permanent claim still precede decoding.
                    owner=new ApprovalProvisionGuardian(profile.Plan(frame),files,targets,kernel,clock,earlier);
                    byte[] raw=input.Read(frame);
                    LocalProcessObservation answer=owner.Run(raw);
                    if (answer.End!=LocalProcessEnd.RootExited || !answer.Resumed || !answer.EmptyObserved ||
                        !answer.ExitCode.HasValue) return 125;
                    return answer.ExitCode.Value==0?0:(answer.ExitCode.Value==126?126:125);
                } catch (GuardianEntryRefused) { return 126; }
                  catch (WorkerEntryRefused) { return 126; }
                  catch (ApprovalRefused) { return 126; }
                  catch { return 125; }
                // Preserve the actual owner after ALL inner-run uncertainty.
                // Main must park, not exit/release these still-owned native locks.
            }
        }
    }
    internal sealed class WindowsGuardianEntryInput : IGuardianEntryInput {
        bool host,hostAttempted,used;
        [DllImport("kernel32.dll",ExactSpelling=true,CharSet=CharSet.Unicode)]
        static extern uint GetModuleFileNameW(IntPtr module,StringBuilder path,uint size);
        public void RequireHost(GuardianEntryProfile profile) {
            if (hostAttempted) throw new GuardianEntryRefused("guardian_host_one_shot"); hostAttempted=true;
            if (profile==null || Environment.OSVersion.Platform!=PlatformID.Win32NT || IntPtr.Size!=8)
                throw new GuardianEntryRefused("guardian_native_x64");
            var path=new StringBuilder(512); uint count=GetModuleFileNameW(IntPtr.Zero,path,512);
            if (count<1 || count>=512 || path.ToString()!=profile.LaunchRoot+"\\"+ProvisionProcessGuardian.GuardianExe)
                throw new GuardianEntryRefused("guardian_fixed_host");
            using (WindowsIdentity identity=WindowsIdentity.GetCurrent()) {
                if (identity.User==null || identity.User.Value!=profile.OperatorSid ||
                    !new WindowsPrincipal(identity).IsInRole(WindowsBuiltInRole.Administrator))
                    throw new GuardianEntryRefused("guardian_enabled_operator");
            }
            host=true; // necessary role consistency, NOT pre-load/parent authentication
        }
        public byte[] Read(GuardianEntryFrame frame) {
            if (used) throw new GuardianEntryRefused("guardian_input_one_shot"); used=true;
            if (!host || frame==null) throw new GuardianEntryRefused("guardian_input_binding");
            return WindowsWorkerEntryInput.ReadSection(frame.Request); // identical read-only rights/close policy
        }
    }
    internal static class ValidatorGuardianProgram {
        [DllImport("kernel32.dll",ExactSpelling=true)] static extern void Sleep(uint milliseconds);
        // Build must supply ONE independently reviewed generated profile source.
        // There is deliberately no shipped profile, stub authorization or fallback.
        // Library model tests supply inert build DATA and NEVER invoke Main.
        static int Main(string[] args) {
            GuardianEntry entry;
            try {
                entry=new GuardianEntry(ReviewedGuardianProfile.Create(),new WindowsBoundaryFiles(),new WindowsLaunchFiles(),
                    new WindowsSectionGuardianKernel(),new GuardianClock(),new WindowsWorkerCounter(),new WindowsGuardianEntryInput());
            } catch { return 125; }
            int code=entry.Run(args);
            if (entry.MustParkForSupervisor) {
                for (;;) { Sleep(UInt32.MaxValue); GC.KeepAlive(entry); }
            }
            return code; // local process consistency only, NEVER install acceptance
        }
    }
}
