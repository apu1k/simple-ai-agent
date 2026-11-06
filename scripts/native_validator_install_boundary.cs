// Unwired PRE-IMPORT ACQUISITION BODY, not a trusted executable or installer.
// Never compile/load checkout code elevated. A separately protected OS/.NET/
// bootstrap closure and independent process watchdog must precede assembly load.
// No Main, Python import, process launch, VM, repair, deletion or activation.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
namespace AiAgent.NativeValidator {
    public sealed class BoundaryRefused : Exception {
        internal BoundaryRefused(string label) : base(label) { }
    }
    public sealed class BoundaryUnknown : Exception {
        internal BoundaryUnknown(string label) : base(label) { }
    }
    public sealed class FilePin {
        public readonly long Bytes;
        public readonly string Sha256;
        public FilePin(long bytes,string sha256) { Bytes=bytes; Sha256=sha256; }
    }
    public sealed class InstallBoundaryPlan {
        // Independent external approval is mandatory; this object is forgeable.
        public readonly string Root, InstallationId, ApprovalSha256, OperatorSid;
        public readonly uint Volume;
        public readonly ulong Index;
        public readonly long ApprovedUntilUnix;
        internal readonly SortedDictionary<string,FilePin> Files;
        public InstallBoundaryPlan(string root,uint volume,ulong index,string installationId,
            string approvalSha256,string operatorSid,long approvedUntilUnix,IDictionary<string,FilePin> files) {
            Root=root; Volume=volume; Index=index; InstallationId=installationId;
            ApprovalSha256=approvalSha256; OperatorSid=operatorSid; ApprovedUntilUnix=approvedUntilUnix;
            if (files==null) throw new BoundaryRefused("plan");
            Files=new SortedDictionary<string,FilePin>(files,StringComparer.Ordinal);
        }
    }
    internal sealed class Stamp {
        internal uint Volume, Attributes, Links;
        internal ulong Index;
        internal long Bytes;
        internal string Security, FinalName;
        internal bool Private;
        internal string Identity { get { return Volume+":"+Index; } }
        internal bool Same(Stamp other,bool ignoreSize,bool archiveDelta) {
            return other!=null && Volume==other.Volume && Index==other.Index && Links==other.Links &&
                Security==other.Security && Private==other.Private && FinalName==other.FinalName &&
                (ignoreSize || Bytes==other.Bytes) &&
                (archiveDelta ? (Attributes|32)==(other.Attributes|32) : Attributes==other.Attributes);
        }
    }
    internal interface IBoundaryFiles {
        void RequireOperator(string sid);
        object Root(string drive);
        object Open(object parent,string name,bool directory);
        object CreateClaim(object parent); // fixed leaf, FILE_CREATE, exact DACL
        Stamp Observe(object handle,bool directory,bool ancestor);
        string[] Names(object directory);
        void Rewind(object handle);
        int Read(object handle,byte[] bytes,int count);
        void WriteClaim(object handle,byte[] bytes); // one checked write and flush
        void Close(object handle); // caller disarms before the one close attempt
    }
    internal interface IBoundaryClock { double Seconds { get; } long Unix { get; } }
    internal sealed class BoundaryClock : IBoundaryClock {
        readonly Stopwatch clock=Stopwatch.StartNew();
        public double Seconds { get { return clock.Elapsed.TotalSeconds; } }
        public long Unix { get { return (long)(DateTime.UtcNow-new DateTime(1970,1,1)).TotalSeconds; } }
    }
    internal sealed class Held {
        internal object Handle;
        internal bool Directory, Ancestor;
        internal Stamp Before;
    }
    public sealed class ImportClosureLease : IDisposable {
        // Local consistency and held handles ONLY; not authority to launch.
        // Reverification/copy failure poisons but NEVER automatically unlocks.
        // The lifetime owner must prove child absence before explicit disposal.
        readonly object sync=new object();
        InstallBoundary owner;
        internal ImportClosureLease(InstallBoundary value) { owner=value; }
        public void Reverify() {
            lock (sync) {
                if (owner==null) throw new BoundaryRefused("lease_closed");
                owner.Reverify();
            }
        }
        public byte[] CopyWorkerRequest() {
            lock (sync) {
                if (owner==null) throw new BoundaryRefused("lease_closed");
                return owner.CopyWorkerRequest();
            }
        }
        public void Dispose() {
            lock (sync) {
                InstallBoundary current=owner; owner=null;
                if (current!=null) current.CloseAll();
            }
        }
    }
    public sealed class InstallBoundary {
        internal const string ClaimName="install-attempt.claim";
        internal const int MaxWorkerRequestBytes=8192;
        internal const long MaxFileBytes=32L*1024*1024, MaxClosureBytes=96L*1024*1024;
        internal static readonly byte[] Pth=Encoding.ASCII.GetBytes(
            "python314.zip\r\n.\r\n\r\n# Uncomment to run site.main() automatically\r\n#import site\r\n");
        // Deliberate independent catalog, cross-checked against deployment.
        // A manifest/request cannot select import paths, files or executables.
        internal static readonly string[] RuntimeNames = {
            "python.exe","pythonw.exe","python314.dll","python3.dll","vcruntime140.dll",
            "vcruntime140_1.dll","LICENSE.txt","pyexpat.pyd","select.pyd","unicodedata.pyd",
            "winsound.pyd","_asyncio.pyd","_bz2.pyd","_ctypes.pyd","_decimal.pyd",
            "_elementtree.pyd","_hashlib.pyd","_lzma.pyd","_multiprocessing.pyd","_overlapped.pyd",
            "_queue.pyd","_remote_debugging.pyd","_socket.pyd","_sqlite3.pyd","_ssl.pyd",
            "_uuid.pyd","_wmi.pyd","_zoneinfo.pyd","_zstd.pyd","libcrypto-3.dll","libffi-8.dll",
            "libssl-3.dll","libtommath.dll","sqlite3.dll","python314.zip","python314._pth","python.cat"
        };
        internal static readonly string[] CodeNames = {
            "__init__.py","guest/__init__.py","bootstrap_daemon_asset.py","bootstrap_probe_seed.py",
            "bootstrap_native_deployment.py","bootstrap_native_provision.py","bootstrap_native_handoff.py",
            "bootstrap_native_media.py","bootstrap_native_media_store.py","bootstrap_native_fixture.py",
            "bootstrap_native_denials.py","bootstrap_native_supervision.py","bootstrap_native_ram.py",
            "bootstrap_native_child_plan.py","bootstrap_native_owner.py","bootstrap_native_capture.py",
            "bootstrap_native_sequence.py","guest/bootstrap_native_child.py","guest/bootstrap_native_worker.py",
            "guest/bootstrap_native_boot.py","guest/bootstrap_public_probe.py","guest/bootstrap-public-probe.apparmor",
            "guest/publish_public_bootstrap.py","public_bootstrap_kvp.py","maintenance_credentials_prototype.py",
            "maintenance_tls_prototype.py","maintenance_store_native_prototype.py","ubuntu_preparation_control.py",
            "hyperv_image_preflight.py"
        };
        internal static readonly string[] CodecNames = {
            "__init__.py","dates.py","dr.py","eltorito.py","facade.py","headervd.py","inode.py",
            "inplaceeditor.py","isohybrid.py","path_table_record.py","pycdlib.py","pycdlibexception.py",
            "pycdlibio.py","rockridge.py","udf.py","utils.py","py.typed"
        };
        internal static SortedSet<string> Catalog() {
            var names=new SortedSet<string>(StringComparer.Ordinal);
            foreach (string n in RuntimeNames) names.Add("runtime/"+n);
            foreach (string n in CodeNames) names.Add("payload/night_shifts/"+n);
            foreach (string n in CodecNames) names.Add("payload/pycdlib/"+n);
            foreach (string n in new string[] {"METADATA","WHEEL","licenses/COPYING"})
                names.Add("payload/pycdlib-1.21.0.dist-info/"+n);
            names.Add("provision-request.json"); return names;
        }
        readonly object sync=new object();
        readonly InstallBoundaryPlan plan;
        readonly IBoundaryFiles api;
        readonly IBoundaryClock clock;
        readonly double deadline;
        readonly List<Held> held=new List<Held>();
        readonly Dictionary<string,Held> tree=new Dictionary<string,Held>(StringComparer.Ordinal);
        readonly HashSet<string> identities=new HashSet<string>(StringComparer.Ordinal);
        readonly SortedDictionary<string,SortedSet<string>> inventory=
            new SortedDictionary<string,SortedSet<string>>(StringComparer.Ordinal);
        bool used, closed, poisoned;
        double lastSeconds=Double.NegativeInfinity;
        public InstallBoundary(InstallBoundaryPlan value,int budgetSeconds)
            : this(value,budgetSeconds,new WindowsBoundaryFiles(),new BoundaryClock()) { }
        internal InstallBoundary(InstallBoundaryPlan value,int budgetSeconds,IBoundaryFiles files,IBoundaryClock time)
            : this(value,budgetSeconds,files,time,null) { }
        // Same-process cap ONLY: caller must supply this clock's SAME origin.
        // This does not authenticate or translate a deadline across processes.
        internal InstallBoundary(InstallBoundaryPlan value,int budgetSeconds,IBoundaryFiles files,IBoundaryClock time,
            double? originalDeadline) {
            // No filesystem/token/native acquisition in the constructor.
            plan=value; api=files; clock=time; Validate(value);
            if (files==null || time==null) throw new BoundaryRefused("plan");
            if (budgetSeconds<1 || budgetSeconds>900) throw new BoundaryRefused("deadline");
            double now=Now();
            long remaining=plan.ApprovedUntilUnix-clock.Unix;
            if (remaining<1 || remaining>86400) throw new BoundaryRefused("approval_window");
            double limit=now+Math.Min(budgetSeconds,remaining);
            if (originalDeadline.HasValue) {
                double bound=originalDeadline.Value;
                if (Double.IsNaN(bound) || Double.IsInfinity(bound) || bound<=now)
                    throw new BoundaryRefused("shared_deadline");
                limit=Math.Min(limit,bound); // shorten, never renew, the earlier window
            }
            deadline=limit;
            inventory.Add("",new SortedSet<string>(StringComparer.Ordinal));
            foreach (string name in Catalog()) AddInventory(name);
            AddInventory("claims/"+ClaimName);
        }
        internal static bool Digest(string text) { return text!=null && Regex.IsMatch(text,"\\A[0-9a-f]{64}\\z"); }
        internal static void Component(string name) {
            if (name==null || name.Length<1 || name.Length>120 ||
                !Regex.IsMatch(name,"\\A[A-Za-z0-9_ .()\\-]+\\z") || name=="." || name==".." ||
                name.EndsWith(" ",StringComparison.Ordinal) || name.EndsWith(".",StringComparison.Ordinal) ||
                Regex.IsMatch(name,"\\A(?:CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])(?:\\..*)?\\z",RegexOptions.IgnoreCase))
                throw new BoundaryRefused("path_component");
        }
        internal static string[] PathParts(string path) {
            if (path==null || path.Length<4 || path.Length>240 || !Regex.IsMatch(path,"\\A[A-Za-z]:\\\\"))
                throw new BoundaryRefused("path");
            string[] parts=path.Substring(3).Split('\\'); foreach (string part in parts) Component(part); return parts;
        }
        static void Validate(InstallBoundaryPlan p) {
            if (p==null || p.Index==0 || p.InstallationId==null || !Regex.IsMatch(p.InstallationId,"\\A[0-9a-f]{32}\\z") ||
                !Digest(p.ApprovalSha256) || p.OperatorSid==null ||
                !Regex.IsMatch(p.OperatorSid,"\\AS-1-5-21-[0-9]+-[0-9]+-[0-9]+-[0-9]+\\z")) throw new BoundaryRefused("plan");
            PathParts(p.Root);
            if (!Catalog().SetEquals(p.Files.Keys)) throw new BoundaryRefused("inventory");
            long total=0;
            foreach (KeyValuePair<string,FilePin> pair in p.Files) {
                FilePin pin=pair.Value;
                if (pin==null || pin.Bytes<0 || pin.Bytes>MaxFileBytes || !Digest(pin.Sha256)) throw new BoundaryRefused("pin");
                total+=pin.Bytes;
                bool empty=pair.Key=="payload/night_shifts/__init__.py" || pair.Key=="payload/night_shifts/guest/__init__.py";
                if (empty ? pin.Bytes!=0 : pin.Bytes==0) throw new BoundaryRefused("pin_size");
            }
            if (total>MaxClosureBytes || p.Files["provision-request.json"].Bytes>32768 ||
                p.Files["runtime/python314._pth"].Bytes!=Pth.Length) throw new BoundaryRefused("pin_size");
        }
        void AddInventory(string name) {
            string parent=""; string[] parts=name.Split('/');
            for (int i=0;i<parts.Length;i++) {
                inventory[parent].Add(parts[i]); parent=parent.Length==0?parts[i]:parent+"/"+parts[i];
                if (i+1<parts.Length && !inventory.ContainsKey(parent)) inventory.Add(parent,new SortedSet<string>(StringComparer.Ordinal));
            }
        }
        double Now() {
            double now=clock.Seconds;
            if (Double.IsNaN(now) || Double.IsInfinity(now) || now<lastSeconds)
                throw new BoundaryRefused("deadline");
            lastSeconds=now; return now;
        }
        void Budget() {
            if (Now()>=deadline || clock.Unix>=plan.ApprovedUntilUnix)
                throw new BoundaryRefused("deadline");
        }
        Held Own(object handle,string name,bool directory,bool ancestor) {
            var value=new Held { Handle=handle,Directory=directory,Ancestor=ancestor };
            held.Add(value); // own before any observation/alias failure
            value.Before=api.Observe(handle,directory,ancestor);
            if (!identities.Add(value.Before.Identity)) throw new BoundaryRefused("alias");
            if (!ancestor) tree.Add(name,value); return value;
        }
        void Match(Held value) {
            Budget();
            if (!value.Before.Same(api.Observe(value.Handle,value.Directory,value.Ancestor),value.Directory,false))
                throw new BoundaryRefused("metadata_drift");
        }
        Held Open(Held parent,string leaf,string relative,bool directory) {
            Match(parent); Held value=Own(api.Open(parent.Handle,leaf,directory),relative,directory,false);
            if (value.Before.Volume!=parent.Before.Volume || value.Before.FinalName!=parent.Before.FinalName.TrimEnd('\\')+"\\"+leaf)
                throw new BoundaryRefused("path_drift");
            return value;
        }
        internal static string Sha(byte[] bytes) { using (SHA256 sha=SHA256.Create()) return Hex(sha.ComputeHash(bytes)); }
        static string Hex(byte[] bytes) { return BitConverter.ToString(bytes).Replace("-","").ToLowerInvariant(); }
        internal byte[] ClaimBytes() {
            // Hash an unambiguous length-prefixed complete plan, not a grant.
            using (var data=new MemoryStream()) {
                using (var writer=new BinaryWriter(data,Encoding.UTF8,true)) {
                    writer.Write("native-validator-install-boundary-v1"); writer.Write(plan.Root);
                    writer.Write(plan.Volume); writer.Write(plan.Index); writer.Write(plan.InstallationId);
                    writer.Write(plan.ApprovalSha256); writer.Write(plan.OperatorSid); writer.Write(plan.ApprovedUntilUnix);
                    foreach (KeyValuePair<string,FilePin> pair in plan.Files) {
                        writer.Write(pair.Key); writer.Write(pair.Value.Bytes); writer.Write(pair.Value.Sha256);
                    }
                }
                string text="{\"scope\":\"install_attempt_consumed_not_acceptance\",\"version\":1,\"installation_id\":\""+
                    plan.InstallationId+"\",\"plan_sha256\":\""+Sha(data.ToArray())+"\",\"approval_sha256\":\""+
                    plan.ApprovalSha256+"\",\"approved_until_unix\":"+
                    plan.ApprovedUntilUnix.ToString(System.Globalization.CultureInfo.InvariantCulture)+"}\n";
                return Encoding.ASCII.GetBytes(text);
            }
        }
        void Hash(Held value,FilePin pin,byte[] exact,byte[] copy=null) {
            Match(value);
            if (value.Before.Bytes!=pin.Bytes) throw new BoundaryRefused("file_size");
            api.Rewind(value.Handle);
            using (SHA256 sha=SHA256.Create()) {
                byte[] buffer=new byte[65536]; long total=0;
                while (total<pin.Bytes) {
                    Budget(); int wanted=(int)Math.Min(buffer.Length,pin.Bytes-total), count=api.Read(value.Handle,buffer,wanted);
                    if (count<1 || count>wanted) throw new BoundaryRefused("read_extent");
                    if (exact!=null) for (int i=0;i<count;i++)
                        if (buffer[i]!=exact[(int)total+i]) throw new BoundaryRefused("fixed_bytes");
                    if (copy!=null) Buffer.BlockCopy(buffer,0,copy,(int)total,count);
                    sha.TransformBlock(buffer,0,count,buffer,0); total+=count;
                }
                Budget(); if (api.Read(value.Handle,buffer,1)!=0) throw new BoundaryRefused("read_extent");
                sha.TransformFinalBlock(new byte[0],0,0);
                if (Hex(sha.Hash)!=pin.Sha256) throw new BoundaryRefused("file_hash");
            }
            Match(value);
        }
        public ImportClosureLease Acquire() {
            lock (sync) { return AcquireOnce(); }
        }
        ImportClosureLease AcquireOnce() {
            if (used) throw new BoundaryRefused("one_shot"); used=true;
            try {
                Budget(); api.RequireOperator(plan.OperatorSid); Budget();
                Held parent=Own(api.Root(plan.Root.Substring(0,3)),"@volume",true,true);
                string[] parts=PathParts(plan.Root);
                for (int i=0;i<parts.Length;i++) {
                    Match(parent); string expected=parent.Before.FinalName.TrimEnd('\\')+"\\"+parts[i];
                    Held next=Own(api.Open(parent.Handle,parts[i],true),i+1==parts.Length?"":"@"+i,true,i+1!=parts.Length);
                    if (next.Before.Volume!=parent.Before.Volume || next.Before.FinalName!=expected) throw new BoundaryRefused("path_drift");
                    parent=next;
                }
                if (parent.Before.Volume!=plan.Volume || parent.Before.Index!=plan.Index) throw new BoundaryRefused("root_identity");
                Held claims=Open(parent,"claims","claims",true);
                // Fixed leaf across ALL IDs. New objects/IDs cannot reset it.
                Match(claims); Budget(); Held claim=Own(api.CreateClaim(claims.Handle),"claims/"+ClaimName,false,false);
                if (claim.Before.Volume!=claims.Before.Volume || claim.Before.Bytes!=0 ||
                    claim.Before.FinalName!=claims.Before.FinalName+"\\"+ClaimName) throw new BoundaryRefused("claim_shape");
                byte[] bytes=ClaimBytes(); Budget(); api.WriteClaim(claim.Handle,bytes); Budget();
                Stamp after=api.Observe(claim.Handle,false,false);
                if (after.Bytes!=bytes.Length || !claim.Before.Same(after,true,true)) throw new BoundaryRefused("claim_drift");
                claim.Before=after; Hash(claim,new FilePin(bytes.Length,Sha(bytes)),bytes);
                Stamp claimsAfter=api.Observe(claims.Handle,true,false);
                if (!claims.Before.Same(claimsAfter,true,true)) throw new BoundaryRefused("metadata_drift");
                claims.Before=claimsAfter;
                foreach (string directory in inventory.Keys) {
                    if (directory.Length==0 || directory=="claims") continue;
                    int slash=directory.LastIndexOf('/'); string up=slash<0?"":directory.Substring(0,slash);
                    Open(tree[up],slash<0?directory:directory.Substring(slash+1),directory,true);
                }
                foreach (KeyValuePair<string,FilePin> pair in plan.Files) {
                    int slash=pair.Key.LastIndexOf('/'); string up=slash<0?"":pair.Key.Substring(0,slash);
                    Open(tree[up],slash<0?pair.Key:pair.Key.Substring(slash+1),pair.Key,false);
                }
                Reverify(); return new ImportClosureLease(this);
            } catch (BoundaryRefused) { CloseAll(); throw; }
              catch (BoundaryUnknown) { CloseAll(); throw; }
              catch { CloseAll(); throw new BoundaryUnknown("boundary_unknown"); }
        }
        void RequireUsable() {
            if (closed) throw new BoundaryRefused("lease_closed");
            if (poisoned) throw new BoundaryRefused("lease_poisoned");
        }
        internal void Reverify() {
            RequireUsable();
            try {
                foreach (Held value in held) Match(value);
                foreach (KeyValuePair<string,SortedSet<string>> pair in inventory) {
                    Budget(); string[] names=api.Names(tree[pair.Key].Handle);
                    if (names==null || names.Length!=pair.Value.Count || !pair.Value.SetEquals(names)) throw new BoundaryRefused("unexpected_entry");
                }
                foreach (KeyValuePair<string,FilePin> pair in plan.Files)
                    Hash(tree[pair.Key],pair.Value,pair.Key=="runtime/python314._pth"?Pth:null);
                byte[] bytes=ClaimBytes(); Hash(tree["claims/"+ClaimName],new FilePin(bytes.Length,Sha(bytes)),bytes);
                foreach (Held value in held) Match(value); Budget();
            } catch (BoundaryRefused) { poisoned=true; throw; }
              catch (BoundaryUnknown) { poisoned=true; throw; }
              catch { poisoned=true; throw new BoundaryUnknown("boundary_unknown"); }
        }
        internal byte[] CopyWorkerRequest() {
            RequireUsable();
            try {
                FilePin pin=plan.Files["provision-request.json"];
                if (pin.Bytes<1 || pin.Bytes>MaxWorkerRequestBytes) throw new BoundaryRefused("worker_request_size");
                Reverify();
                // Fixed leaf through the ALREADY HELD reader, no reopen/path input.
                // Never parse here; only a private bounded copy whose complete
                // hash/EOF/metadata match the independently bound import pin.
                byte[] copy=new byte[(int)pin.Bytes];
                Hash(tree["provision-request.json"],pin,null,copy);
                Reverify(); // full closure/claim/inventory again BEFORE releasing bytes
                return copy;
            } catch (BoundaryRefused) { poisoned=true; throw; }
              catch (BoundaryUnknown) { poisoned=true; throw; }
              catch { poisoned=true; throw new BoundaryUnknown("boundary_unknown"); }
        }
        internal void CloseAll() {
            if (closed) return;
            closed=true; bool failed=false;
            for (int i=held.Count-1;i>=0;i--) {
                object handle=held[i].Handle; held[i].Handle=null;
                if (handle==null) continue;
                try { api.Close(handle); } catch { failed=true; }
            }
            if (failed) throw new BoundaryUnknown("close_unknown");
        }
    }
}
