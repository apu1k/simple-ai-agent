// Uninstalled SETUP candidate. Never load checkout code elevated. Independently
// reviewed OS/CLR/self-load, authentic setup approval and an external watchdog
// MUST precede production use. No executable entry, launch or acceptance grant.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;
using AiAgent.NativeValidator;
using AiAgent.ValidatorLaunch;
using AiAgent.ValidatorRequest;
namespace AiAgent.ValidatorSetup {
    public sealed class SetupRefused : Exception { internal SetupRefused(string label) : base(label) { } }
    public sealed class SetupUnknown : Exception { internal SetupUnknown(string label) : base(label) { } }
    public sealed class SetupParent {
        public readonly string Path,OperatorSid;
        public readonly uint Volume;
        public readonly ulong Index;
        public SetupParent(string path,uint volume,ulong index,string sid) {
            if (path==null || path.Length<4 || path.Length>150 || !Regex.IsMatch(path,"\\A[A-Z]:\\\\") || index==0 ||
                sid==null || sid.Length>80 || !Regex.IsMatch(sid,"\\AS-1-5-21-[0-9]+-[0-9]+-[0-9]+-[0-9]+\\z"))
                throw new SetupRefused("parent");
            try { InstallBoundary.PathParts(path); } catch { throw new SetupRefused("parent"); }
            string[] parts=sid.Split('-');
            for (int i=4;i<parts.Length;i++) {
                uint n;
                if (!UInt32.TryParse(parts[i],NumberStyles.None,CultureInfo.InvariantCulture,out n) ||
                    n.ToString(CultureInfo.InvariantCulture)!=parts[i]) throw new SetupRefused("operator");
            }
            Path=path; Volume=volume; Index=index; OperatorSid=sid;
        }
        public string Root { get { return Path+"\\native-validator-bootstrap"; } }
    }
    public sealed class SetupReferences {
        // Forgeable observations to re-review BETWEEN preparation and publication.
        public readonly SetupParent Parent;
        readonly SortedDictionary<string,ulong> indices;
        public SetupReferences(SetupParent parent,IDictionary<string,ulong> observed) {
            if (parent==null || observed==null || observed.Count!=SetupTransaction.Anchors.Length) throw new SetupRefused("references");
            Parent=parent; indices=new SortedDictionary<string,ulong>(observed,StringComparer.Ordinal);
            var unique=new HashSet<ulong>(); unique.Add(parent.Index);
            foreach (string name in SetupTransaction.Anchors) {
                ulong index;
                if (!indices.TryGetValue(name,out index) || index==0 || !unique.Add(index)) throw new SetupRefused("references");
            }
        }
        public ulong Index(string name) { return indices[name]; }
        public byte[] ProfileBytes() {
            return Encoding.ASCII.GetBytes("// GENERATED REVIEW DATA ONLY; not authorization or pre-load trust.\n"+
                "// Independently review before compilation; never build/load checkout elevated.\n"+
                "namespace AiAgent.ValidatorEntry {\n    internal static class ReviewedGuardianProfile {\n"+
                "        internal static GuardianEntryProfile Create() {\n"+
                "            return new GuardianEntryProfile(@\""+Parent.Root+"\\approval\","+
                Parent.Volume.ToString(CultureInfo.InvariantCulture)+"u,"+Index("approval").ToString(CultureInfo.InvariantCulture)+
                "UL,\""+Parent.OperatorSid+"\",@\""+Parent.Root+"\\launch\");\n"+
                "        }\n    }\n}\n");
        }
    }
    internal interface ISetupFiles {
        void RequireOperator(string sid);
        object Root(string drive);
        object Open(object parent,string name,bool directory);
        object Create(object parent,string name,bool directory);
        Stamp Observe(object handle,bool directory,bool ancestor);
        string[] Names(object directory);
        void Rewind(object handle);
        int Read(object handle,byte[] buffer,int count);
        void Write(object handle,byte[] bytes);
        void Close(object handle);
    }
    internal sealed class SetupPayload {
        internal const int MaxPacketBytes=129*1024*1024;
        internal readonly SortedDictionary<string,byte[]> Files=new SortedDictionary<string,byte[]>(StringComparer.Ordinal);
        internal readonly string Digest;
        internal readonly BoundInstallationInputs Bound;
        internal readonly LaunchPlan Launch;
        internal SetupPayload(SetupReferences refs,byte[] packet,int expectedBytes,string expectedSha) {
            if (refs==null || packet==null || expectedBytes<1 || expectedBytes>MaxPacketBytes || packet.Length!=expectedBytes ||
                !InstallBoundary.Digest(expectedSha)) throw new SetupRefused("packet_pin");
            byte[] copy=(byte[])packet.Clone(); // pin/parse ONE private snapshot
            if (InstallBoundary.Sha(copy)!=expectedSha) throw new SetupRefused("packet_pin"); Digest=expectedSha;
            var names=new SortedSet<string>(StringComparer.Ordinal) {"request.json","reviewed-profile.cs","approval/approval.json"};
            foreach (string n in InstallBoundary.Catalog()) names.Add("imports/"+n);
            foreach (string n in LaunchBoundary.FileNames) names.Add("launch/"+n);
            try {
                using (var s=new MemoryStream(copy,false)) using (var r=new BinaryReader(s,Encoding.ASCII)) {
                    if (Encoding.ASCII.GetString(r.ReadBytes(8))!="NVSU0001" || r.ReadUInt32()!=names.Count) throw new SetupRefused("packet_frame");
                    foreach (string expected in names) {
                        int length=r.ReadUInt16();
                        if (length!=expected.Length || Encoding.ASCII.GetString(r.ReadBytes(length))!=expected) throw new SetupRefused("packet_inventory");
                        uint size=r.ReadUInt32();
                        int max=expected=="request.json"?32768:(expected=="reviewed-profile.cs"?2048:
                            (expected=="approval/approval.json"?1024:(expected=="imports/provision-request.json"?8192:32*1024*1024)));
                        if (size>max || size>s.Length-s.Position) throw new SetupRefused("packet_extent");
                        byte[] raw=r.ReadBytes((int)size); if (raw.Length!=size) throw new SetupRefused("packet_extent"); Files.Add(expected,raw);
                    }
                    if (s.Position!=s.Length) throw new SetupRefused("packet_trailer");
                }
                byte[] request=Files["request.json"];
                Bound=InstallationRequest.Bind(request,request.Length,InstallBoundary.Sha(request));
                Launch=Bound.CreateLaunchPlan(); InstallBoundaryPlan imports=Bound.CreateImportPlan();
                if (Launch.Root!=refs.Parent.Root+"\\launch" || imports.Root!=refs.Parent.Root+"\\imports" ||
                    Launch.OperatorSid!=refs.Parent.OperatorSid || imports.OperatorSid!=refs.Parent.OperatorSid ||
                    Launch.Volume!=refs.Parent.Volume || imports.Volume!=refs.Parent.Volume || Launch.RootIndex!=refs.Index("launch") ||
                    Launch.ScratchIndex!=refs.Index("launch/scratch") || imports.Index!=refs.Index("imports")) throw new SetupRefused("anchor_binding");
                Bound.RequireSeparateApprovalAnchor(refs.Parent.Root+"\\approval",refs.Parent.Volume,refs.Index("approval"));
                var reserved=new List<ulong>(); reserved.Add(refs.Parent.Index);
                foreach (string n in SetupTransaction.Anchors) reserved.Add(refs.Index(n));
                Bound.RequireSeparateSetupTree(refs.Parent.Root,refs.Parent.Volume,reserved.ToArray());
                Exact(Files["reviewed-profile.cs"],refs.ProfileBytes());
                Exact(Files["imports/provision-request.json"],Bound.WorkerRequestBytes());
                foreach (KeyValuePair<string,LaunchFilePin> p in Launch.Files) Pin(Files["launch/"+p.Key],p.Value.Bytes,p.Value.Sha256);
                foreach (KeyValuePair<string,FilePin> p in imports.Files) Pin(Files["imports/"+p.Key],p.Value.Bytes,p.Value.Sha256);
                Exact(Files["approval/approval.json"],PolicyBytes(Launch,request.Length,Bound.RequestSha256));
            } catch (SetupRefused) { throw; }
              catch (InstallRequestRefused) { throw new SetupRefused("request"); }
              catch (EndOfStreamException) { throw new SetupRefused("packet_extent"); }
              catch { throw new SetupRefused("packet_data"); }
        }
        internal static byte[] PolicyBytes(LaunchPlan p,int count,string digest) {
            return Encoding.ASCII.GetBytes("{\"budget_seconds\":"+p.BudgetSeconds.ToString(CultureInfo.InvariantCulture)+
                ",\"expires_unix\":"+p.ApprovedUntilUnix.ToString(CultureInfo.InvariantCulture)+
                ",\"operation\":\"native_validator_provision_once\",\"operator_sid\":\""+p.OperatorSid+
                "\",\"request_bytes\":"+count.ToString(CultureInfo.InvariantCulture)+",\"request_sha256\":\""+digest+
                "\",\"scope\":\"protected_native_validator_install_approval_once\",\"version\":1}\n");
        }
        static void Pin(byte[] raw,long count,string digest) {
            if (raw.Length!=count || InstallBoundary.Sha(raw)!=digest) throw new SetupRefused("leaf_pin");
        }
        internal static void Exact(byte[] a,byte[] b) {
            if (a.Length!=b.Length) throw new SetupRefused("fixed_bytes");
            for (int i=0;i<a.Length;i++) if (a[i]!=b[i]) throw new SetupRefused("fixed_bytes");
        }
    }
    public sealed class SetupTransaction {
        internal static readonly string[] Anchors={"","approval","approval/claims","imports","imports/claims","launch","launch/scratch"};
        readonly object sync=new object();
        readonly SetupParent plan;
        readonly ISetupFiles api;
        readonly IBoundaryClock clock;
        double deadline,last=Double.NegativeInfinity;
        long lastWall=Int64.MinValue;
        long? expiry;
        byte[] claimBytes;
        readonly List<Held> held=new List<Held>();
        readonly Dictionary<string,Held> tree=new Dictionary<string,Held>(StringComparer.Ordinal);
        readonly HashSet<string> identities=new HashSet<string>(StringComparer.Ordinal);
        bool used,closed;
        public SetupTransaction(SetupParent value,int seconds) : this(value,seconds,new WindowsSetupFiles(),new BoundaryClock()) { }
        internal SetupTransaction(SetupParent value,int seconds,ISetupFiles files,IBoundaryClock time)
            : this(value,seconds,files,time,null) { }
        internal SetupTransaction(SetupParent value,int seconds,ISetupFiles files,IBoundaryClock time,double? originalDeadline) {
            if (value==null || seconds<6 || seconds>300 || files==null || time==null) throw new SetupRefused("plan");
            plan=value; api=files; clock=time; double now=Now(); deadline=now+seconds;
            if (originalDeadline.HasValue) {
                double cap=originalDeadline.Value;
                if (Double.IsNaN(cap) || Double.IsInfinity(cap) || cap<=now) throw new SetupRefused("shared_deadline");
                deadline=Math.Min(deadline,cap);
            }
        }
        double Now() {
            double n=clock.Seconds;
            if (Double.IsNaN(n) || Double.IsInfinity(n) || n<0 || n<last || n>1e12) throw new SetupUnknown("clock_unknown"); last=n; return n;
        }
        long Wall() { long n=clock.Unix; if (n<1 || n<lastWall) throw new SetupUnknown("clock_unknown"); lastWall=n; return n; }
        void Budget() {
            if (Now()>=deadline) throw new SetupRefused("deadline");
            if (expiry.HasValue && Wall()>=expiry.Value) throw new SetupRefused("approval_window");
        }
        void Start() { if (used) throw new SetupRefused("one_shot"); used=true; Budget(); }
        Held Own(object handle,bool dir,bool ancestor) {
            if (handle==null) throw new SetupUnknown("handle_unknown");
            foreach (Held h in held) if (h.Handle!=null && Object.Equals(h.Handle,handle)) throw new SetupUnknown("handle_alias");
            var item=new Held {Handle=handle,Directory=dir,Ancestor=ancestor}; held.Add(item); item.Before=api.Observe(handle,dir,ancestor);
            if (item.Before==null || !identities.Add(item.Before.Identity)) throw new SetupRefused("identity_alias"); return item;
        }
        void Match(Held item) {
            Budget(); if (!item.Before.Same(api.Observe(item.Handle,item.Directory,item.Ancestor),item.Directory,false)) throw new SetupRefused("metadata_drift");
        }
        Held Child(Held parent,string name,bool dir,bool ancestor,bool create) {
            Match(parent); Held value=Own(create?api.Create(parent.Handle,name,dir):api.Open(parent.Handle,name,dir),dir,ancestor);
            if (value.Before.Volume!=parent.Before.Volume || value.Before.FinalName!=parent.Before.FinalName.TrimEnd('\\')+"\\"+name) throw new SetupRefused("path_drift");
            Stamp after=api.Observe(parent.Handle,true,parent.Ancestor);
            if (!parent.Before.Same(after,true,create)) throw new SetupRefused("parent_drift"); parent.Before=after; Budget(); return value;
        }
        Held Parent() {
            Budget(); api.RequireOperator(plan.OperatorSid); Budget(); Held parent=Own(api.Root(plan.Path.Substring(0,3)),true,true);
            string[] parts=InstallBoundary.PathParts(plan.Path);
            for (int i=0;i<parts.Length;i++) parent=Child(parent,parts[i],true,i+1!=parts.Length,false);
            if (parent.Before.Volume!=plan.Volume || parent.Before.Index!=plan.Index) throw new SetupRefused("parent_identity"); return parent;
        }
        void Names(Held item,IEnumerable<string> expected) {
            Match(item); string[] names=api.Names(item.Handle); var want=new SortedSet<string>(expected,StringComparer.Ordinal);
            if (names==null || names.Length!=want.Count || !want.SetEquals(names)) throw new SetupRefused("inventory"); Match(item);
        }
        void AcquireAnchors(bool create,SetupReferences refs) {
            tree.Add("",Child(Parent(),"native-validator-bootstrap",true,false,create));
            foreach (string path in Anchors) {
                if (path.Length==0) continue; int slash=path.LastIndexOf('/');
                tree.Add(path,Child(tree[slash<0?"":path.Substring(0,slash)],path.Substring(slash+1),true,false,create));
            }
            foreach (string path in Anchors) {
                if (refs!=null && tree[path].Before.Index!=refs.Index(path)) throw new SetupRefused("anchor_identity");
                var expected=new List<string>();
                foreach (string child in Anchors) {
                    int slash=child.LastIndexOf('/');
                    if (child.Length!=0 && (slash<0?"":child.Substring(0,slash))==path) expected.Add(child.Substring(slash+1));
                }
                Names(tree[path],expected);
            }
        }
        void ReadExact(Held item,byte[] bytes) {
            Match(item); if (item.Before.Bytes!=bytes.Length) throw new SetupRefused("file_size");
            api.Rewind(item.Handle); byte[] buffer=new byte[65536]; int offset=0;
            while (offset<bytes.Length) {
                Budget(); int wanted=Math.Min(buffer.Length,bytes.Length-offset),count=api.Read(item.Handle,buffer,wanted);
                if (count<1 || count>wanted) throw new SetupRefused("read_extent");
                for (int i=0;i<count;i++) if (bytes[offset+i]!=buffer[i]) throw new SetupRefused("file_bytes"); offset+=count;
            }
            Budget(); if (api.Read(item.Handle,buffer,1)!=0) throw new SetupRefused("read_extent"); Match(item);
        }
        void WriteFile(string path,byte[] bytes) {
            int slash=path.LastIndexOf('/'); string parent=slash<0?"":path.Substring(0,slash),leaf=path.Substring(slash+1);
            Held item=Child(tree[parent],leaf,false,false,true); tree.Add(path,item);
            if (item.Before.Bytes!=0) throw new SetupRefused("new_file_shape");
            Budget(); api.Write(item.Handle,bytes); Budget(); Stamp after=api.Observe(item.Handle,false,false);
            if (after==null || after.Bytes!=bytes.Length || !item.Before.Same(after,true,true)) throw new SetupRefused("write_drift");
            item.Before=after; ReadExact(item,bytes);
            // No child exists. Seal under held BA/SYSTEM-only parent, with checked
            // writer close and SAME identity/security/bytes after reopening.
            object old=item.Handle; item.Handle=null; api.Close(old); Budget(); item.Handle=api.Open(tree[parent].Handle,leaf,false);
            if (item.Handle==null) throw new SetupUnknown("seal_handle_unknown");
            foreach (Held other in held)
                if (other!=item && other.Handle!=null && Object.Equals(other.Handle,item.Handle)) { item.Handle=null; throw new SetupUnknown("handle_alias"); }
            ReadExact(item,bytes); Match(tree[parent]);
        }
        void CloseAll() {
            if (closed) return; closed=true; bool unknown=false;
            for (int i=held.Count-1;i>=0;i--) {
                object old=held[i].Handle; held[i].Handle=null; if (old==null) continue;
                try { api.Close(old); } catch { unknown=true; }
            }
            if (unknown) throw new SetupUnknown("close_unknown");
        }
        public SetupReferences Prepare() {
            lock (sync) {
                Start(); SetupReferences answer;
                try {
                    AcquireAnchors(true,null); var ids=new Dictionary<string,ulong>(StringComparer.Ordinal);
                    foreach (string path in Anchors) { Match(tree[path]); ids.Add(path,tree[path].Before.Index); }
                    answer=new SetupReferences(plan,ids); Budget();
                } catch (SetupRefused) { throw; } catch (SetupUnknown) { throw; }
                  catch { throw new SetupUnknown("prepare_unknown"); }
                finally { CloseAll(); }
                Budget(); return answer;
            }
        }
        public string Publish(SetupReferences refs,byte[] packet,int expectedBytes,string expectedSha) {
            lock (sync) {
                Start();
                try {
                    if (refs==null || refs.Parent.Path!=plan.Path || refs.Parent.OperatorSid!=plan.OperatorSid ||
                        refs.Parent.Volume!=plan.Volume || refs.Parent.Index!=plan.Index) throw new SetupRefused("reference_binding");
                    var payload=new SetupPayload(refs,packet,expectedBytes,expectedSha); Budget();
                    // Sample monotonic time BEFORE UTC: time spent obtaining
                    // the wall observation must never move the translated cap later.
                    double sampledAt=Now(); long remaining=payload.Launch.ApprovedUntilUnix-Wall();
                    if (remaining<6 || remaining>86400) throw new SetupRefused("approval_window");
                    expiry=payload.Launch.ApprovedUntilUnix; deadline=Math.Min(deadline,sampledAt+remaining); Budget();
                    AcquireAnchors(false,refs);
                    claimBytes=Encoding.ASCII.GetBytes("{\"packet_sha256\":\""+payload.Digest+"\",\"request_sha256\":\""+
                        payload.Bound.RequestSha256+"\",\"scope\":\"setup_publication_consumed_not_acceptance\",\"version\":1}\n");
                    WriteFile("publication.claim",claimBytes); // permanent, fixed leaf, BEFORE payload
                    foreach (string name in payload.Files.Keys) {
                        int slash=name.LastIndexOf('/'); if (slash<0) continue; string directory=name.Substring(0,slash),prefix="";
                        foreach (string part in directory.Split('/')) {
                            string next=prefix.Length==0?part:prefix+"/"+part;
                            if (!tree.ContainsKey(next)) tree.Add(next,Child(tree[prefix],part,true,false,true)); prefix=next;
                        }
                    }
                    foreach (KeyValuePair<string,byte[]> entry in payload.Files)
                        if (entry.Key!="approval/approval.json") WriteFile(entry.Key,entry.Value);
                    Verify(payload,false); // approval is deliberately LAST
                    WriteFile("approval/approval.json",payload.Files["approval/approval.json"]); Verify(payload,true); Budget();
                } catch (SetupRefused) { throw; } catch (SetupUnknown) { throw; }
                  catch { throw new SetupUnknown("publication_unknown"); }
                finally { CloseAll(); }
                Budget(); return "local_setup_bytes_not_installation_acceptance";
            }
        }
        void Verify(SetupPayload payload,bool policy) {
            foreach (KeyValuePair<string,Held> pair in tree) {
                if (pair.Value.Directory) {
                    var children=new List<string>(); string prefix=pair.Key.Length==0?"":pair.Key+"/";
                    foreach (string path in tree.Keys)
                        if (path.StartsWith(prefix,StringComparison.Ordinal) && path.Length>prefix.Length && path.IndexOf('/',prefix.Length)<0)
                            children.Add(path.Substring(prefix.Length));
                    Names(pair.Value,children);
                } else if (pair.Key=="publication.claim") ReadExact(pair.Value,claimBytes);
                else if (pair.Key!="approval/approval.json" || policy) ReadExact(pair.Value,payload.Files[pair.Key]);
            }
            foreach (Held item in held) Match(item); Budget();
        }
    }
}
