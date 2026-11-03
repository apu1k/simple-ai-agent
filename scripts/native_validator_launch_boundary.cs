// UNWIRED held executable-target acquisition BODY; not a trusted starter.
// The protected starter must establish OS/CLR/guardian provenance BEFORE load,
// authenticate the plan and consume its permanent approval. No Main or launch.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
namespace AiAgent.ValidatorLaunch {
    public sealed class LaunchRefused : Exception { internal LaunchRefused(string label) : base(label) { } }
    public sealed class LaunchUnknown : Exception { internal LaunchUnknown(string label) : base(label) { } }
    public sealed class LaunchFilePin {
        public readonly long Bytes; public readonly string Sha256;
        public LaunchFilePin(long bytes,string sha256) { Bytes=bytes; Sha256=sha256; }
    }
    public sealed class LaunchPlan {
        // Forgeable consistency data. Neither a self-hash nor this type is approval.
        public readonly string Root,OperatorSid,InstallationId,ApprovalSha256;
        public readonly uint Volume;
        public readonly ulong RootIndex,ScratchIndex;
        public readonly long ApprovedUntilUnix;
        public readonly int BudgetSeconds;
        internal readonly SortedDictionary<string,LaunchFilePin> Files;
        public LaunchPlan(string root,uint volume,ulong rootIndex,ulong scratchIndex,string sid,
            string id,string approval,long until,int seconds,IDictionary<string,LaunchFilePin> files) {
            Root=root; Volume=volume; RootIndex=rootIndex; ScratchIndex=scratchIndex;
            OperatorSid=sid; InstallationId=id; ApprovalSha256=approval;
            ApprovedUntilUnix=until; BudgetSeconds=seconds;
            if (files==null) throw new LaunchRefused("plan");
            Files=new SortedDictionary<string,LaunchFilePin>(files,StringComparer.Ordinal);
        }
    }
    internal sealed class LaunchStamp {
        internal uint Volume,Attributes,Links;
        internal ulong Index;
        internal long Bytes;
        internal string Security,FinalName;
        internal bool Same(LaunchStamp other,bool directory) {
            return other!=null && Volume==other.Volume && Index==other.Index &&
                Attributes==other.Attributes && Links==other.Links && Security==other.Security &&
                FinalName==other.FinalName && (directory || Bytes==other.Bytes);
        }
        internal string Identity { get { return Volume+":"+Index; } }
    }
    internal interface ILaunchFiles {
        void RequireOperator(string sid);
        object Root(string drive);
        object Open(object parent,string name,bool directory);
        LaunchStamp Observe(object handle,bool directory,bool ancestor);
        string[] Names(object directory);
        void Rewind(object handle);
        int Read(object handle,byte[] bytes,int count);
        void Close(object handle);
    }
    internal interface ILaunchClock { double Seconds { get; } long Unix { get; } }
    internal sealed class LaunchClock : ILaunchClock {
        readonly Stopwatch clock=Stopwatch.StartNew();
        public double Seconds { get { return clock.Elapsed.TotalSeconds; } }
        public long Unix { get { return (long)(DateTime.UtcNow-new DateTime(1970,1,1)).TotalSeconds; } }
    }
    internal sealed class LaunchHeld {
        internal object Handle; internal bool Directory,Ancestor; internal LaunchStamp Before;
    }
    public sealed class HeldLaunchLease : IDisposable {
        // Local held-target consistency ONLY, never approval or installation acceptance.
        // Caller MUST NOT dispose while child termination is unknown. No finalizer.
        readonly object sync=new object();
        LaunchBoundary owner;
        internal HeldLaunchLease(LaunchBoundary value) { owner=value; }
        public void ReverifyBeforeLaunch() {
            lock (sync) {
                if (owner==null) throw new LaunchRefused("lease_closed");
                // Keep locks even on failure: this API cannot know whether another
                // component has started a child. Failure poisons, never unlocks.
                owner.Reverify();
            }
        }
        public void Dispose() {
            lock (sync) {
                LaunchBoundary current=owner; owner=null;
                if (current!=null) current.CloseAll();
            }
        }
    }
    public sealed class LaunchBoundary {
        internal const long MaxExecutableBytes=16L*1024*1024;
        internal static readonly string[] FileNames={
            "validator-install-guardian.exe","validator-install-guardian.exe.config",
            "validator-provision-worker.exe","validator-provision-worker.exe.config"
        };
        // Fixed build profile, not an incoming .config or arbitrary CLR policy.
        internal static readonly byte[] Config=Encoding.ASCII.GetBytes(
            "<?xml version=\"1.0\" encoding=\"utf-8\"?>\n<configuration><startup useLegacyV2RuntimeActivationPolicy=\"false\">"+
            "<supportedRuntime version=\"v4.0\" sku=\".NETFramework,Version=v4.8\"/></startup>"+
            "<runtime><loadFromRemoteSources enabled=\"false\"/></runtime></configuration>\n");
        readonly object sync=new object();
        readonly LaunchPlan plan;
        readonly ILaunchFiles api;
        readonly ILaunchClock clock;
        readonly double deadline;
        readonly List<LaunchHeld> held=new List<LaunchHeld>();
        readonly Dictionary<string,LaunchHeld> tree=new Dictionary<string,LaunchHeld>(StringComparer.Ordinal);
        readonly HashSet<string> identities=new HashSet<string>(StringComparer.Ordinal);
        bool used,closed,poisoned;
        public LaunchBoundary(LaunchPlan value) : this(value,new WindowsLaunchFiles(),new LaunchClock()) { }
        internal LaunchBoundary(LaunchPlan value,ILaunchFiles files,ILaunchClock time) {
            plan=value; api=files; clock=time; Validate(value);
            double now=Now(); long remaining=plan.ApprovedUntilUnix-clock.Unix;
            if (remaining<1 || remaining>86400) throw new LaunchRefused("approval_window");
            deadline=now+Math.Min(plan.BudgetSeconds,remaining);
        }
        internal static void Component(string text) {
            if (text==null || text.Length<1 || text.Length>120 ||
                !Regex.IsMatch(text,"\\A[A-Za-z0-9_ .()\\-]+\\z") || text=="." || text==".." ||
                text.EndsWith(" ",StringComparison.Ordinal) || text.EndsWith(".",StringComparison.Ordinal) ||
                Regex.IsMatch(text,"\\A(?:CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])(?:\\..*)?\\z",RegexOptions.IgnoreCase))
                throw new LaunchRefused("path_component");
        }
        static bool Digest(string text) { return text!=null && Regex.IsMatch(text,"\\A[0-9a-f]{64}\\z"); }
        static void Validate(LaunchPlan p) {
            if (p==null || p.Root==null || p.Root.Length<4 || p.Root.Length>200 ||
                !Regex.IsMatch(p.Root,"\\A[A-Za-z]:\\\\") || p.RootIndex==0 || p.ScratchIndex==0 ||
                p.RootIndex==p.ScratchIndex || p.OperatorSid==null ||
                !Regex.IsMatch(p.OperatorSid,"\\AS-1-5-21-[0-9]+-[0-9]+-[0-9]+-[0-9]+\\z") ||
                p.InstallationId==null || !Regex.IsMatch(p.InstallationId,"\\A[0-9a-f]{32}\\z") ||
                !Digest(p.ApprovalSha256)) throw new LaunchRefused("plan");
            foreach (string part in p.Root.Substring(3).Split('\\')) Component(part);
            if (p.BudgetSeconds<1 || p.BudgetSeconds>900) throw new LaunchRefused("budget");
            if (p.Files.Count!=FileNames.Length) throw new LaunchRefused("inventory");
            foreach (string name in FileNames) {
                LaunchFilePin pin;
                if (!p.Files.TryGetValue(name,out pin)) throw new LaunchRefused("inventory");
                bool config=name.EndsWith(".config",StringComparison.Ordinal);
                if (pin==null || !Digest(pin.Sha256) || pin.Bytes<1 || pin.Bytes>MaxExecutableBytes ||
                    (config && (pin.Bytes!=Config.Length || pin.Sha256!=Sha(Config)))) throw new LaunchRefused("pin");
            }
        }
        double Now() {
            double value=clock.Seconds;
            if (Double.IsNaN(value) || Double.IsInfinity(value)) throw new LaunchUnknown("clock_unknown");
            return value;
        }
        void Budget() { if (Now()>=deadline || clock.Unix>=plan.ApprovedUntilUnix) throw new LaunchRefused("deadline"); }
        LaunchHeld Own(object handle,bool directory,bool ancestor) {
            if (handle==null) throw new LaunchUnknown("handle_unknown");
            foreach (LaunchHeld prior in held)
                if (Object.Equals(prior.Handle,handle)) throw new LaunchUnknown("handle_alias");
            var value=new LaunchHeld {Handle=handle,Directory=directory,Ancestor=ancestor};
            held.Add(value); // take ownership BEFORE observation/identity rejection
            value.Before=api.Observe(handle,directory,ancestor);
            if (value.Before==null || !identities.Add(value.Before.Identity)) throw new LaunchRefused("identity_alias");
            return value;
        }
        void Match(LaunchHeld value) {
            Budget();
            if (!value.Before.Same(api.Observe(value.Handle,value.Directory,value.Ancestor),value.Directory))
                throw new LaunchRefused("metadata_drift");
        }
        LaunchHeld Open(LaunchHeld parent,string leaf,bool directory,bool ancestor) {
            Match(parent); LaunchHeld value=Own(api.Open(parent.Handle,leaf,directory),directory,ancestor);
            if (value.Before.Volume!=parent.Before.Volume || value.Before.FinalName!=parent.Before.FinalName.TrimEnd('\\')+"\\"+leaf)
                throw new LaunchRefused("path_drift");
            Match(parent); return value;
        }
        internal static string Sha(byte[] bytes) {
            using (SHA256 sha=SHA256.Create()) return Hex(sha.ComputeHash(bytes));
        }
        static string Hex(byte[] bytes) { return BitConverter.ToString(bytes).Replace("-","").ToLowerInvariant(); }
        void Hash(LaunchHeld value,LaunchFilePin pin,byte[] exact) {
            Match(value);
            if (value.Before.Bytes!=pin.Bytes) throw new LaunchRefused("file_size");
            api.Rewind(value.Handle);
            using (SHA256 sha=SHA256.Create()) {
                byte[] buffer=new byte[65536]; long total=0;
                while (total<pin.Bytes) {
                    Budget(); int wanted=(int)Math.Min(buffer.Length,pin.Bytes-total), count=api.Read(value.Handle,buffer,wanted);
                    if (count<1 || count>wanted) throw new LaunchRefused("read_extent");
                    if (exact!=null) for (int i=0;i<count;i++)
                        if (buffer[i]!=exact[(int)total+i]) throw new LaunchRefused("fixed_config");
                    sha.TransformBlock(buffer,0,count,buffer,0); total+=count;
                }
                Budget(); if (api.Read(value.Handle,buffer,1)!=0) throw new LaunchRefused("read_extent");
                sha.TransformFinalBlock(new byte[0],0,0);
                if (Hex(sha.Hash)!=pin.Sha256) throw new LaunchRefused("file_hash");
            }
            Match(value);
        }
        void Names(LaunchHeld directory,string[] expected) {
            Match(directory); string[] names=api.Names(directory.Handle);
            if (names==null || names.Length!=expected.Length ||
                !new SortedSet<string>(expected,StringComparer.Ordinal).SetEquals(names)) throw new LaunchRefused("unexpected_entry");
            Match(directory);
        }
        public HeldLaunchLease Acquire() { lock (sync) { return AcquireOnce(); } }
        HeldLaunchLease AcquireOnce() {
            if (used) throw new LaunchRefused("one_shot"); used=true;
            try {
                Budget(); api.RequireOperator(plan.OperatorSid); Budget();
                LaunchHeld parent=Own(api.Root(plan.Root.Substring(0,3)),true,true);
                string[] parts=plan.Root.Substring(3).Split('\\');
                for (int i=0;i<parts.Length;i++) parent=Open(parent,parts[i],true,i+1!=parts.Length);
                if (parent.Before.Volume!=plan.Volume || parent.Before.Index!=plan.RootIndex) throw new LaunchRefused("root_identity");
                tree.Add("",parent);
                LaunchHeld scratch=Open(parent,"scratch",true,false); tree.Add("scratch",scratch);
                if (scratch.Before.Index!=plan.ScratchIndex) throw new LaunchRefused("scratch_identity");
                Names(parent,new string[] {FileNames[0],FileNames[1],FileNames[2],FileNames[3],"scratch"});
                Names(scratch,new string[0]);
                foreach (string name in FileNames) tree.Add(name,Open(parent,name,false,false));
                Reverify(); return new HeldLaunchLease(this);
            } catch (LaunchRefused) { CloseAll(); throw; }
              catch (LaunchUnknown) { CloseAll(); throw; }
              catch { CloseAll(); throw new LaunchUnknown("launch_boundary_unknown"); }
        }
        internal void Reverify() {
            if (closed || poisoned) throw new LaunchRefused("lease_terminal");
            try {
                foreach (LaunchHeld value in held) Match(value);
                Names(tree[""],new string[] {FileNames[0],FileNames[1],FileNames[2],FileNames[3],"scratch"});
                Names(tree["scratch"],new string[0]);
                foreach (string name in FileNames) Hash(tree[name],plan.Files[name],name.EndsWith(".config",StringComparison.Ordinal)?Config:null);
                foreach (LaunchHeld value in held) Match(value); Budget();
            } catch (LaunchRefused) { poisoned=true; throw; }
              catch (LaunchUnknown) { poisoned=true; throw; }
              catch { poisoned=true; throw new LaunchUnknown("launch_boundary_unknown"); }
        }
        internal void CloseAll() {
            if (closed) return;
            closed=true; bool unknown=false;
            for (int i=held.Count-1;i>=0;i--) {
                object handle=held[i].Handle; held[i].Handle=null;
                if (handle==null) continue;
                try { api.Close(handle); } catch { unknown=true; }
            }
            if (unknown) throw new LaunchUnknown("close_unknown");
        }
    }
}
