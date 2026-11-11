// Fixed protected setup-attempt files. No install, ACL repair, deletion, process
// start or approval synthesis. The policy and host deployment must ALREADY have
// been separately installed/reviewed. Self-file observation is NOT pre-load trust.
using System;
using System.Collections.Generic;
using System.Text;
using AiAgent.NativeValidator;
namespace AiAgent.ValidatorSetup {
    internal sealed class WindowsSetupFilesFactory : ISetupFilesFactory {
        public ISetupAttemptFiles Host(SetupSupervisorProfile p,SetupClock clock,double cap) {
            return WindowsSetupAttemptFiles.ForHost(p,clock,cap);
        }
    }
    internal sealed class WindowsSetupAttemptFiles : ISetupAttemptFiles {
        const string ClaimName="install-attempt.claim",ResultName="operation-result.bin",ReceiptName="supervisor-receipt.json";
        readonly SetupSupervisorProfile profile;
        readonly SetupClock clock;
        readonly double cap;
        readonly bool supervisor;
        readonly ISetupFiles api=new WindowsSetupFiles();
        readonly List<Held> all=new List<Held>();
        readonly Dictionary<string,Held> tree=new Dictionary<string,Held>(StringComparer.Ordinal);
        readonly Dictionary<string,byte[]> exact=new Dictionary<string,byte[]>(StringComparer.Ordinal);
        readonly HashSet<string> identities=new HashSet<string>(StringComparer.Ordinal);
        Held root,claims,receipts,scratch;
        bool used,closed,resultRead,resultPresent,receiptPresent;
        WindowsSetupAttemptFiles(SetupSupervisorProfile p,SetupClock time,double deadline,bool owner) {
            if (p==null || time==null || Double.IsNaN(deadline) || Double.IsInfinity(deadline)) throw new SetupRefused("attempt_files");
            profile=p; clock=time; cap=deadline; supervisor=owner;
        }
        internal static WindowsSetupAttemptFiles ForHost(SetupSupervisorProfile p,SetupClock clock,double cap) {
            return new WindowsSetupAttemptFiles(p,clock,cap,false);
        }
        internal static WindowsSetupAttemptFiles ForWatchdog(SetupSupervisorProfile p,SetupClock clock,double cap) {
            return new WindowsSetupAttemptFiles(p,clock,cap,true);
        }
        void Budget() { clock.Require(cap,profile.Host.ExpiresUnix); }
        Held Own(object handle,bool dir,bool ancestor) {
            if (handle==null) throw new SetupUnknown("attempt_handle_unknown");
            foreach (Held h in all) if (h.Handle!=null && Object.Equals(h.Handle,handle)) throw new SetupUnknown("attempt_handle_alias");
            var item=new Held {Handle=handle,Directory=dir,Ancestor=ancestor}; all.Add(item); item.Before=api.Observe(handle,dir,ancestor);
            if (item.Before==null || !identities.Add(item.Before.Identity)) throw new SetupRefused("attempt_identity_alias"); return item;
        }
        void Match(Held h) {
            Budget(); if (!h.Before.Same(api.Observe(h.Handle,h.Directory,h.Ancestor),h.Directory,false)) throw new SetupRefused("attempt_metadata_drift");
        }
        Held Open(Held parent,string name,bool dir,bool ancestor) {
            Match(parent); Held h=Own(api.Open(parent.Handle,name,dir),dir,ancestor);
            if (h.Before.Volume!=parent.Before.Volume || h.Before.FinalName!=parent.Before.FinalName.TrimEnd('\\')+"\\"+name)
                throw new SetupRefused("attempt_path_drift"); Match(parent); return h;
        }
        void Names(Held h,params string[] names) {
            Match(h); string[] actual=api.Names(h.Handle);
            if (actual==null || actual.Length!=names.Length || !new SortedSet<string>(names,StringComparer.Ordinal).SetEquals(actual))
                throw new SetupRefused("attempt_inventory"); Match(h);
        }
        byte[] Read(Held h,int maximum,byte[] expected) {
            Match(h); if (h.Before.Bytes<0 || h.Before.Bytes>maximum) throw new SetupRefused("attempt_read_bound");
            int length=(int)h.Before.Bytes; byte[] raw=new byte[length],buffer=new byte[65536]; api.Rewind(h.Handle); int offset=0;
            while (offset<length) {
                Budget(); int wanted=Math.Min(buffer.Length,length-offset),count=api.Read(h.Handle,buffer,wanted);
                if (count<1 || count>wanted) throw new SetupRefused("attempt_read_extent"); Array.Copy(buffer,0,raw,offset,count); offset+=count;
            }
            Budget(); if (api.Read(h.Handle,buffer,1)!=0) throw new SetupRefused("attempt_read_extent"); Match(h);
            if (expected!=null) SetupPayload.Exact(raw,expected); return raw;
        }
        void Input(string name,int maximum,long count,string digest,byte[] expected) {
            Held h=Open(root,name,false,false); tree.Add(name,h); byte[] raw=Read(h,maximum,expected);
            if (count>=0 && (raw.Length!=count || InstallBoundary.Sha(raw)!=digest)) throw new SetupRefused("attempt_input_pin");
            exact.Add(name,raw);
        }
        void WriteNew(Held parent,string path,string leaf,byte[] bytes) {
            Match(parent); Held h=Own(api.Create(parent.Handle,leaf,false),false,false); tree.Add(path,h);
            if (h.Before.Volume!=parent.Before.Volume || h.Before.FinalName!=parent.Before.FinalName+"\\"+leaf || h.Before.Bytes!=0)
                throw new SetupRefused("attempt_new_shape");
            Stamp afterParent=api.Observe(parent.Handle,true,false);
            if (!parent.Before.Same(afterParent,true,true)) throw new SetupRefused("attempt_parent_drift"); parent.Before=afterParent;
            Budget(); api.Write(h.Handle,bytes); Budget(); Stamp after=api.Observe(h.Handle,false,false);
            if (after==null || after.Bytes!=bytes.Length || !h.Before.Same(after,true,true)) throw new SetupRefused("attempt_write_drift");
            h.Before=after; Read(h,bytes.Length,bytes);
            object old=h.Handle; h.Handle=null; api.Close(old); Budget(); h.Handle=api.Open(parent.Handle,leaf,false);
            if (h.Handle==null) throw new SetupUnknown("attempt_seal_unknown");
            foreach (Held other in all) if (other!=h && other.Handle!=null && Object.Equals(other.Handle,h.Handle)) {
                h.Handle=null; throw new SetupUnknown("attempt_handle_alias");
            }
            Read(h,bytes.Length,bytes); Match(parent); exact.Add(path,(byte[])bytes.Clone());
        }
        public void Acquire() {
            if (used) throw new SetupRefused("attempt_one_shot"); used=true; Budget(); api.RequireOperator(profile.Host.Parent.OperatorSid); Budget();
            SetupLocation p=profile.Host.Location;
            Held parent=Own(api.Root(p.Root.Substring(0,3)),true,true); string[] parts=InstallBoundary.PathParts(p.Root);
            for (int i=0;i<parts.Length;i++) parent=Open(parent,parts[i],true,i+1!=parts.Length); root=parent;
            if (root.Before.Volume!=p.Volume || root.Before.Index!=p.Index) throw new SetupRefused("attempt_root_identity");
            claims=Open(root,"claims",true,false); receipts=Open(root,"receipts",true,false); scratch=Open(root,"scratch",true,false);
            if (claims.Before.Index!=p.Claims || receipts.Before.Index!=p.Receipts || scratch.Before.Index!=p.Scratch)
                throw new SetupRefused("attempt_directory_identity");
            var names=new List<string>(new string[] {SetupHostProfile.HostExe,SetupHostProfile.HostExe+".config",SetupHostProfile.WatchdogExe,
                SetupHostProfile.WatchdogExe+".config","policy.json","claims","receipts","scratch"});
            if (profile.Host.Operation=="publish") names.Add("setup.packet"); Names(root,names.ToArray()); Names(receipts); Names(scratch);
            Input("policy.json",1024,-1,null,profile.Policy()); // AUTHENTIC private policy BEFORE claim/load
            if (supervisor) {
                Names(claims); WriteNew(claims,"claims/"+ClaimName,ClaimName,profile.Claim());
            } else {
                Names(claims,ClaimName); Held h=Open(claims,ClaimName,false,false); tree.Add("claims/"+ClaimName,h);
                exact.Add("claims/"+ClaimName,Read(h,1024,profile.Claim()));
            }
            Input(SetupHostProfile.HostExe,16*1024*1024,profile.HostBytes,profile.HostSha256,null);
            Input(SetupHostProfile.HostExe+".config",4096,-1,null,AiAgent.ValidatorLaunch.LaunchBoundary.Config);
            // Already-loaded watchdog/self/OS/CLR authenticity is an EXTERNAL
            // prerequisite. Observe/hold the bytes; never promote this to review.
            Input(SetupHostProfile.WatchdogExe,16*1024*1024,-1,null,null);
            Input(SetupHostProfile.WatchdogExe+".config",4096,-1,null,AiAgent.ValidatorLaunch.LaunchBoundary.Config);
            if (profile.Host.Operation=="publish") Input("setup.packet",SetupPayload.MaxPacketBytes,profile.Host.PacketBytes,profile.Host.PacketSha256,null);
            Reverify();
        }
        public void Reverify() {
            if (!used || closed) throw new SetupRefused("attempt_terminal");
            foreach (Held h in all) Match(h);
            foreach (KeyValuePair<string,byte[]> p in exact) Read(tree[p.Key],p.Value.Length,p.Value);
            Names(claims,ClaimName); Names(scratch);
            var names=new List<string>(); if (resultPresent) names.Add(ResultName); if (receiptPresent) names.Add(ReceiptName); Names(receipts,names.ToArray());
            var rootNames=new List<string>(new string[] {SetupHostProfile.HostExe,SetupHostProfile.HostExe+".config",SetupHostProfile.WatchdogExe,
                SetupHostProfile.WatchdogExe+".config","policy.json","claims","receipts","scratch"});
            if (profile.Host.Operation=="publish") rootNames.Add("setup.packet"); Names(root,rootNames.ToArray()); Budget();
        }
        public void BeforeCreate() { if (!supervisor) throw new SetupRefused("attempt_role"); Reverify(); }
        public void BeforeResume() { if (!supervisor) throw new SetupRefused("attempt_role"); Reverify(); }
        public byte[] Packet() {
            if (profile.Host.Operation!="publish" || !used || closed) throw new SetupRefused("attempt_packet_role");
            Reverify(); byte[] raw=Read(tree["setup.packet"],SetupPayload.MaxPacketBytes,exact["setup.packet"]); Reverify(); return raw;
        }
        public void WriteResult(byte[] raw) {
            if (supervisor || resultPresent) throw new SetupRefused("attempt_result_role"); SetupResult.Parse(profile.Host,raw); Reverify();
            WriteNew(receipts,"receipts/"+ResultName,ResultName,raw); resultPresent=true; Reverify();
        }
        public byte[] ReadResult() {
            if (!supervisor || resultRead) throw new SetupRefused("attempt_result_role"); resultRead=true; Match(receipts);
            string[] names=api.Names(receipts.Handle);
            if (names==null || names.Length>1 || (names.Length==1 && names[0]!=ResultName)) throw new SetupRefused("attempt_result_inventory");
            if (names.Length==0) { Reverify(); return null; }
            Held h=Open(receipts,ResultName,false,false); tree.Add("receipts/"+ResultName,h);
            byte[] raw=Read(h,SetupResult.Bytes,null); exact.Add("receipts/"+ResultName,raw); resultPresent=true; Reverify(); return raw;
        }
        public void WriteReceipt(byte[] raw) {
            if (!supervisor || !resultRead || receiptPresent || raw==null || raw.Length<1 || raw.Length>2048) throw new SetupRefused("attempt_receipt_role");
            Reverify(); WriteNew(receipts,"receipts/"+ReceiptName,ReceiptName,raw); receiptPresent=true; Reverify();
        }
        public void Close() {
            if (closed) return; closed=true; bool unknown=false;
            for (int i=all.Count-1;i>=0;i--) {
                object old=all[i].Handle; all[i].Handle=null; if (old==null) continue;
                try { api.Close(old); } catch { unknown=true; }
            }
            if (unknown) throw new SetupUnknown("attempt_close_unknown");
        }
    }
}
