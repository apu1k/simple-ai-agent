// UNWIRED protected-policy consumption / request-guardian BODY, not a starter.
// Trusted OS/CLR/self-load and separately reviewed protected policy installation
// MUST precede use. Never compile/load checkout code elevated. No Main or tool.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;
using AiAgent.NativeValidator;
using AiAgent.ValidatorAdmission;
using AiAgent.ValidatorGuardian;
using AiAgent.ValidatorHandoff;
using AiAgent.ValidatorLaunch;
using AiAgent.ValidatorRequest;
namespace AiAgent.ValidatorApproval {
    public sealed class ApprovalRefused : Exception {
        internal ApprovalRefused(string label) : base(label) { }
    }
    public sealed class ApprovalUnknown : Exception {
        internal ApprovalUnknown(string label) : base(label) { }
    }
    public sealed class ApprovalAnchorPlan {
        // Forgeable references to ONE separately installed approval. A plan or
        // hash is not authority; the protected held policy must match it exactly.
        public readonly string Root,OperatorSid,PolicySha256,RequestSha256;
        public readonly uint Volume;
        public readonly ulong Index;
        public readonly long PolicyBytes,RequestBytes,ExpiresUnix;
        public readonly int BudgetSeconds;
        public ApprovalAnchorPlan(string root,uint volume,ulong index,string sid,long policyBytes,string policySha256,
            long requestBytes,string requestSha256,int seconds,long expiresUnix) {
            Root=root; Volume=volume; Index=index; OperatorSid=sid; PolicyBytes=policyBytes; PolicySha256=policySha256;
            RequestBytes=requestBytes; RequestSha256=requestSha256; BudgetSeconds=seconds; ExpiresUnix=expiresUnix;
        }
    }
    public sealed class ApprovalProvisionGuardian {
        internal const string PolicyName="approval.json";
        readonly object sync=new object();
        readonly ApprovalAnchorPlan plan;
        readonly IBoundaryFiles api;
        readonly ILaunchFiles targets;
        readonly IGuardianKernel kernel;
        readonly HandoffClock clock;
        readonly double deadline;
        readonly byte[] policyBytes,claimBytes;
        readonly List<Held> held=new List<Held>();
        readonly HashSet<string> identities=new HashSet<string>(StringComparer.Ordinal);
        Held root,claims,policy,claim;
        RequestProvisionGuardian guardian;
        bool used,closed,claimAttempted;
        public ApprovalProvisionGuardian(ApprovalAnchorPlan value)
            : this(value,new WindowsBoundaryFiles(),new WindowsLaunchFiles(),new WindowsGuardianKernel(),new GuardianClock()) { }
        internal ApprovalProvisionGuardian(ApprovalAnchorPlan value,IBoundaryFiles files,ILaunchFiles launchFiles,
            IGuardianKernel processKernel,IGuardianClock time) {
            Validate(value);
            if (files==null || launchFiles==null || processKernel==null || time==null) throw new ApprovalRefused("plan");
            plan=value; api=files; targets=launchFiles; kernel=processKernel;
            policyBytes=PolicyBytes(value);
            if (policyBytes.Length!=value.PolicyBytes || InstallBoundary.Sha(policyBytes)!=value.PolicySha256)
                throw new ApprovalRefused("policy_pin");
            claimBytes=ClaimBytes(value);
            try {
                clock=new HandoffClock(time);
                double now=clock.Seconds; long remaining=plan.ExpiresUnix-clock.Unix;
                if (remaining<6 || remaining>86400) throw new ApprovalRefused("attempt_window");
                deadline=now+Math.Min(plan.BudgetSeconds,remaining);
                if (Double.IsNaN(deadline) || Double.IsInfinity(deadline) ||
                    deadline-ProvisionProcessGuardian.StopReserveSeconds<=now) throw new ApprovalRefused("attempt_window");
            } catch (ApprovalRefused) { throw; }
              catch { throw new ApprovalUnknown("clock_unknown"); }
        }
        static void Validate(ApprovalAnchorPlan p) {
            if (p==null || p.Index==0 || p.Root==null || p.Root.Length<4 || p.Root.Length>240 ||
                !Regex.IsMatch(p.Root,"\\A[A-Z]:\\\\") || p.OperatorSid==null || p.OperatorSid.Length>80 ||
                !Regex.IsMatch(p.OperatorSid,"\\AS-1-5-21-[0-9]+-[0-9]+-[0-9]+-[0-9]+\\z") ||
                p.PolicyBytes<1 || p.PolicyBytes>1024 || !InstallBoundary.Digest(p.PolicySha256) ||
                p.RequestBytes<1 || p.RequestBytes>InstallationRequest.MaxRequestBytes || !InstallBoundary.Digest(p.RequestSha256) ||
                p.BudgetSeconds<6 || p.BudgetSeconds>900 || p.ExpiresUnix<1 || p.ExpiresUnix>253402300799L)
                throw new ApprovalRefused("plan");
            try { InstallBoundary.PathParts(p.Root); } catch { throw new ApprovalRefused("path"); }
            string[] sid=p.OperatorSid.Split('-');
            for (int i=4;i<sid.Length;i++) {
                uint number;
                if (!UInt32.TryParse(sid[i],NumberStyles.None,CultureInfo.InvariantCulture,out number) ||
                    number.ToString(CultureInfo.InvariantCulture)!=sid[i]) throw new ApprovalRefused("sid");
            }
        }
        internal static byte[] PolicyBytes(ApprovalAnchorPlan p) {
            // Exact fixed bytes, no incoming policy JSON parser or unknown fields.
            string text="{\"budget_seconds\":"+p.BudgetSeconds.ToString(CultureInfo.InvariantCulture)+
                ",\"expires_unix\":"+p.ExpiresUnix.ToString(CultureInfo.InvariantCulture)+
                ",\"operation\":\"native_validator_provision_once\",\"operator_sid\":\""+p.OperatorSid+
                "\",\"request_bytes\":"+p.RequestBytes.ToString(CultureInfo.InvariantCulture)+
                ",\"request_sha256\":\""+p.RequestSha256+
                "\",\"scope\":\"protected_native_validator_install_approval_once\",\"version\":1}\n";
            return Encoding.ASCII.GetBytes(text);
        }
        static byte[] ClaimBytes(ApprovalAnchorPlan p) {
            string digest;
            using (var data=new MemoryStream()) {
                using (var writer=new BinaryWriter(data,Encoding.UTF8,true)) {
                    writer.Write("native-validator-approval-anchor-v1"); writer.Write(p.Root); writer.Write(p.Volume); writer.Write(p.Index);
                    writer.Write(p.OperatorSid); writer.Write(p.PolicyBytes); writer.Write(p.PolicySha256);
                    writer.Write(p.RequestBytes); writer.Write(p.RequestSha256); writer.Write(p.BudgetSeconds); writer.Write(p.ExpiresUnix);
                }
                digest=InstallBoundary.Sha(data.ToArray());
            }
            return Encoding.ASCII.GetBytes("{\"approval_sha256\":\""+p.PolicySha256+"\",\"plan_sha256\":\""+digest+
                "\",\"request_sha256\":\""+p.RequestSha256+
                "\",\"scope\":\"approval_attempt_consumed_not_acceptance\",\"version\":1}\n");
        }
        void Budget(bool work) {
            if (clock.Seconds>=(work?deadline-ProvisionProcessGuardian.StopReserveSeconds:deadline) || clock.Unix>=plan.ExpiresUnix)
                throw new ApprovalRefused("attempt_window");
        }
        Held Own(object handle,bool directory,bool ancestor) {
            if (handle==null) throw new ApprovalUnknown("handle_unknown");
            foreach (Held h in held) if (Object.Equals(h.Handle,handle)) throw new ApprovalUnknown("handle_alias");
            var item=new Held {Handle=handle,Directory=directory,Ancestor=ancestor}; held.Add(item);
            item.Before=api.Observe(handle,directory,ancestor);
            if (item.Before==null || !identities.Add(item.Before.Identity)) throw new ApprovalRefused("identity_alias");
            return item;
        }
        void Match(Held item,bool work) {
            Budget(work);
            if (!item.Before.Same(api.Observe(item.Handle,item.Directory,item.Ancestor),item.Directory,false))
                throw new ApprovalRefused("metadata_drift");
        }
        Held Open(Held parent,string name,bool directory,bool ancestor) {
            Match(parent,true); Held item=Own(api.Open(parent.Handle,name,directory),directory,ancestor);
            if (item.Before.Volume!=parent.Before.Volume || item.Before.FinalName!=parent.Before.FinalName.TrimEnd('\\')+"\\"+name)
                throw new ApprovalRefused("path_drift");
            Match(parent,true); return item;
        }
        void Names(Held directory,string[] expected,bool work) {
            Match(directory,work); string[] names=api.Names(directory.Handle);
            if (names==null || names.Length!=expected.Length || !new SortedSet<string>(expected,StringComparer.Ordinal).SetEquals(names))
                throw new ApprovalRefused("inventory");
            Match(directory,work);
        }
        void Exact(Held item,byte[] expected,bool work) {
            Match(item,work);
            if (item.Before.Bytes!=expected.Length) throw new ApprovalRefused("file_size");
            api.Rewind(item.Handle); byte[] buffer=new byte[1024]; int total=0;
            while (total<expected.Length) {
                Budget(work); int wanted=expected.Length-total,count=api.Read(item.Handle,buffer,wanted);
                if (count<1 || count>wanted) throw new ApprovalRefused("read_extent");
                for (int i=0;i<count;i++) if (buffer[i]!=expected[total+i]) throw new ApprovalRefused("file_bytes");
                total+=count;
            }
            Budget(work); if (api.Read(item.Handle,buffer,1)!=0) throw new ApprovalRefused("read_extent"); Match(item,work);
        }
        void Acquire() {
            Budget(true); api.RequireOperator(plan.OperatorSid); Budget(true);
            Held parent=Own(api.Root(plan.Root.Substring(0,3)),true,true);
            string[] parts=InstallBoundary.PathParts(plan.Root);
            for (int i=0;i<parts.Length;i++) parent=Open(parent,parts[i],true,i+1!=parts.Length);
            root=parent;
            if (root.Before.Volume!=plan.Volume || root.Before.Index!=plan.Index) throw new ApprovalRefused("root_identity");
            Names(root,new string[] {PolicyName,"claims"},true);
            policy=Open(root,PolicyName,false,false); Exact(policy,policyBytes,true);
            claims=Open(root,"claims",true,false); Names(claims,new string[0],true);
            // Only after authentic protected policy bytes match the independently
            // reviewed pin. Fixed leaf across ALL request IDs/digests, no reset.
            Match(claims,true); Budget(true); claimAttempted=true;
            claim=Own(api.CreateClaim(claims.Handle),false,false);
            if (claim.Before.Volume!=claims.Before.Volume || claim.Before.Bytes!=0 ||
                claim.Before.FinalName!=claims.Before.FinalName+"\\"+InstallBoundary.ClaimName)
                throw new ApprovalRefused("claim_shape");
            Budget(true); api.WriteClaim(claim.Handle,claimBytes); Budget(true);
            Stamp after=api.Observe(claim.Handle,false,false);
            if (after==null || after.Bytes!=claimBytes.Length || !claim.Before.Same(after,true,true))
                throw new ApprovalRefused("claim_drift");
            claim.Before=after; Exact(claim,claimBytes,true);
            Stamp directoryAfter=api.Observe(claims.Handle,true,false);
            if (!claims.Before.Same(directoryAfter,true,true)) throw new ApprovalRefused("metadata_drift");
            claims.Before=directoryAfter; Verify(true);
        }
        void Verify(bool work) {
            foreach (Held h in held) Match(h,work);
            Names(root,new string[] {PolicyName,"claims"},work);
            Names(claims,new string[] {InstallBoundary.ClaimName},work);
            Exact(policy,policyBytes,work); Exact(claim,claimBytes,work);
            foreach (Held h in held) Match(h,work);
        }
        void CloseAll() {
            if (closed) return;
            closed=true; bool failed=false;
            for (int i=held.Count-1;i>=0;i--) {
                object handle=held[i].Handle; held[i].Handle=null;
                try { api.Close(handle); } catch { failed=true; }
            }
            if (failed) throw new ApprovalUnknown("close_unknown");
        }
        public bool ClaimCreationAttempted { get { lock (sync) { return claimAttempted; } } }
        public bool ApprovalLeaseRetained { get { lock (sync) { return held.Count!=0 && !closed; } } }
        public bool LaunchLeaseRetained { get { lock (sync) { return guardian!=null && guardian.LaunchLeaseRetained; } } }
        public LocalProcessObservation Run(byte[] request) {
            lock (sync) {
                if (used) throw new ApprovalRefused("one_shot"); used=true;
                bool entered=false,returned=false; LocalProcessObservation answer=null; Exception failure=null;
                try {
                    Acquire(); // permanent claim write/flush/read-back BEFORE request decoding, including null
                    BoundInstallationInputs inputs=InstallationRequest.Bind(request,plan.RequestBytes,plan.RequestSha256);
                    Budget(true); inputs.RequireSeparateApprovalAnchor(plan.Root,plan.Volume,plan.Index);
                    guardian=new RequestProvisionGuardian(plan.RequestBytes,plan.RequestSha256,plan.BudgetSeconds,
                        plan.ExpiresUnix,targets,kernel,clock,deadline);
                    Verify(true); Budget(true); entered=true;
                    // Rebind the same independent pin inside the existing request
                    // body; caller-byte mutation cannot swap the checked request.
                    answer=guardian.Run(request); returned=true; Verify(false);
                } catch (ApprovalRefused ex) { failure=ex; }
                  catch (ApprovalUnknown ex) { failure=ex; }
                  catch (BoundaryRefused) { failure=new ApprovalRefused("approval_files_refused"); }
                  catch (InstallRequestRefused) { failure=new ApprovalRefused("request_refused"); }
                  catch (RequestGuardianRefused) { failure=new ApprovalRefused("request_guardian_refused"); }
                  catch { failure=new ApprovalUnknown("approval_guardian_unknown"); }
                // Do not use LaunchLeaseRetained==false as proof of child absence.
                // Any exception after entering the inner Run retains this policy
                // lease, even a pre-create refusal. Only a NORMAL return permits release.
                if (!entered || returned) {
                    try { CloseAll(); } catch { failure=new ApprovalUnknown("close_unknown"); }
                }
                if (held.Count!=0 && !closed) throw new ApprovalUnknown("approval_retained_outcome_unknown");
                if (failure!=null) throw failure;
                if (answer==null) throw new ApprovalUnknown("observation_unknown");
                try { Budget(false); } catch { throw new ApprovalUnknown("deadline_outcome_unknown"); }
                return answer; // unchanged local observations, never installation acceptance
            }
        }
    }
}
