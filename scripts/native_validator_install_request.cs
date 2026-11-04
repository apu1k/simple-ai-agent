// UNWIRED request codec / plan derivation ONLY; no protected approval or starter.
// Never compile/load checkout code elevated. The trusted OS/CLR/self-load and
// permanent authenticated whole-attempt approval boundary MUST precede use.
// No Main, file/token/clock access, claim, process launch, Python import or VM.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Runtime.Serialization;
using System.Runtime.Serialization.Json;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Xml;
using AiAgent.NativeValidator;
using AiAgent.ValidatorLaunch;
namespace AiAgent.ValidatorRequest {
    public sealed class InstallRequestRefused : Exception {
        internal InstallRequestRefused(string label) : base(label) { }
    }
    // Concrete sealed data contracts only; no incoming type resolver/surrogate,
    // object-valued members, application imports or deserialization callbacks.
    // Trivial auto-properties support serializer population without CS0649
    // suppression or fabricated field initializers. Required wire members stay fixed.
    [DataContract] internal sealed class IdentityData {
        [DataMember(Name="volume",IsRequired=true)] public uint Volume { get; set; }
        [DataMember(Name="index",IsRequired=true)] public ulong Index { get; set; }
    }
    [DataContract] internal sealed class PinData {
        [DataMember(Name="bytes",IsRequired=true)] public long Bytes { get; set; }
        [DataMember(Name="sha256",IsRequired=true)] public string Sha { get; set; }
    }
    [DataContract] internal sealed class MemberData {
        [DataMember(Name="name",IsRequired=true)] public string Name { get; set; }
        [DataMember(Name="bytes",IsRequired=true)] public long Bytes { get; set; }
        [DataMember(Name="sha256",IsRequired=true)] public string Sha { get; set; }
    }
    [DataContract] internal sealed class PlaceData {
        [DataMember(Name="path",IsRequired=true)] public string Path { get; set; }
        [DataMember(Name="identity",IsRequired=true)] public IdentityData Identity { get; set; }
    }
    [DataContract] internal sealed class ImportData {
        [DataMember(Name="path",IsRequired=true)] public string Path { get; set; }
        [DataMember(Name="identity",IsRequired=true)] public IdentityData Identity { get; set; }
        [DataMember(Name="files",IsRequired=true)] public MemberData[] Files { get; set; }
    }
    [DataContract] internal sealed class LaunchData {
        [DataMember(Name="path",IsRequired=true)] public string Path { get; set; }
        [DataMember(Name="identity",IsRequired=true)] public IdentityData Identity { get; set; }
        [DataMember(Name="scratch_identity",IsRequired=true)] public IdentityData Scratch { get; set; }
        [DataMember(Name="files",IsRequired=true)] public MemberData[] Files { get; set; }
    }
    [DataContract] internal sealed class RecipeData {
        [DataMember(Name="code_tree_sha256",IsRequired=true)] public string Code { get; set; }
        [DataMember(Name="codec_tree_sha256",IsRequired=true)] public string Codec { get; set; }
        [DataMember(Name="runtime_sha256",IsRequired=true)] public string Runtime { get; set; }
        [DataMember(Name="runtime_bytes",IsRequired=true)] public long RuntimeBytes { get; set; }
        [DataMember(Name="recovery_sha256",IsRequired=true)] public string Recovery { get; set; }
        [DataMember(Name="recovery_bytes",IsRequired=true)] public long RecoveryBytes { get; set; }
    }
    [DataContract] internal sealed class ProvisionData {
        [DataMember(Name="source",IsRequired=true)] public PlaceData Source { get; set; }
        [DataMember(Name="output_parent",IsRequired=true)] public PlaceData Parent { get; set; }
        [DataMember(Name="bundle",IsRequired=true)] public PinData Bundle { get; set; }
        [DataMember(Name="pins",IsRequired=true)] public RecipeData Pins { get; set; }
    }
    [DataContract] internal sealed class RequestData {
        [DataMember(Name="version",IsRequired=true)] public int Version { get; set; }
        [DataMember(Name="scope",IsRequired=true)] public string Scope { get; set; }
        [DataMember(Name="operation",IsRequired=true)] public string Operation { get; set; }
        [DataMember(Name="installation_id",IsRequired=true)] public string Id { get; set; }
        [DataMember(Name="operator_sid",IsRequired=true)] public string Sid { get; set; }
        [DataMember(Name="budget_seconds",IsRequired=true)] public int Budget { get; set; }
        [DataMember(Name="expires_unix",IsRequired=true)] public long Until { get; set; }
        [DataMember(Name="launch_anchor",IsRequired=true)] public LaunchData Launch { get; set; }
        [DataMember(Name="import_anchor",IsRequired=true)] public ImportData Import { get; set; }
        [DataMember(Name="provision",IsRequired=true)] public ProvisionData Provision { get; set; }
    }
    public sealed class BoundInstallationInputs {
        // Immutable local projections. The raw request hash is consistency data,
        // NOT an approval authenticator, claim, lifetime grant or receipt.
        readonly RequestData data;
        readonly byte[] worker;
        public readonly string RequestSha256;
        internal BoundInstallationInputs(RequestData value,string digest,byte[] projection) {
            data=value; RequestSha256=digest; worker=projection;
        }
        public byte[] WorkerRequestBytes() { return (byte[])worker.Clone(); }
        public LaunchPlan CreateLaunchPlan() {
            var files=new Dictionary<string,LaunchFilePin>(StringComparer.Ordinal);
            foreach (MemberData m in data.Launch.Files) files.Add(m.Name,new LaunchFilePin(m.Bytes,m.Sha));
            return new LaunchPlan(data.Launch.Path,data.Launch.Identity.Volume,data.Launch.Identity.Index,
                data.Launch.Scratch.Index,data.Sid,data.Id,RequestSha256,data.Until,data.Budget,files);
        }
        public InstallBoundaryPlan CreateImportPlan() {
            var files=new Dictionary<string,FilePin>(StringComparer.Ordinal);
            foreach (MemberData m in data.Import.Files) files.Add(m.Name,new FilePin(m.Bytes,m.Sha));
            files.Add("provision-request.json",new FilePin(worker.Length,InstallationRequest.Sha(worker)));
            return new InstallBoundaryPlan(data.Import.Path,data.Import.Identity.Volume,data.Import.Identity.Index,
                data.Id,RequestSha256,data.Sid,data.Until,files);
        }
    }
    public static class InstallationRequest {
        public const int MaxRequestBytes=32768,MaxWorkerBytes=8192;
        internal const string Operation="native_validator_provision_once";
        internal const string Scope="reviewed_installation_inputs_not_authorization";
        internal const string WorkerScope="bound_worker_request_not_authorization";
        internal static string Sha(byte[] bytes) {
            using (SHA256 sha=SHA256.Create()) return BitConverter.ToString(sha.ComputeHash(bytes)).Replace("-","").ToLowerInvariant();
        }
        static void Digest(string text) {
            if (text==null || !Regex.IsMatch(text,"\\A[0-9a-f]{64}\\z")) throw new InstallRequestRefused("digest");
        }
        static void Path(string path,int max) {
            if (path==null || path.Length<4 || path.Length>max || !Regex.IsMatch(path,"\\A[A-Z]:\\\\"))
                throw new InstallRequestRefused("path");
            foreach (string part in path.Substring(3).Split('\\')) {
                if (part.Length<1 || part.Length>120 || !Regex.IsMatch(part,"\\A[A-Za-z0-9_ .()\\-]+\\z") ||
                    part=="." || part==".." || part.EndsWith(" ",StringComparison.Ordinal) || part.EndsWith(".",StringComparison.Ordinal) ||
                    Regex.IsMatch(part,"\\A(?:CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])(?:\\..*)?\\z",RegexOptions.IgnoreCase))
                    throw new InstallRequestRefused("path");
            }
        }
        static string Identity(IdentityData id) {
            if (id==null || id.Index==0) throw new InstallRequestRefused("identity");
            return id.Volume.ToString(CultureInfo.InvariantCulture)+":"+id.Index.ToString(CultureInfo.InvariantCulture);
        }
        static void Place(PlaceData place) {
            if (place==null) throw new InstallRequestRefused("schema");
            Path(place.Path,240); Identity(place.Identity);
        }
        static void Pin(PinData pin,long max) {
            if (pin==null || pin.Bytes<1 || pin.Bytes>max) throw new InstallRequestRefused("pin");
            Digest(pin.Sha);
        }
        static void Files(MemberData[] files,IEnumerable<string> expected,bool launch) {
            var names=new List<string>(expected);
            if (files==null || files.Length!=names.Count) throw new InstallRequestRefused("inventory");
            long total=0;
            for (int i=0;i<files.Length;i++) {
                MemberData m=files[i]; string name=names[i];
                if (m==null || m.Name!=name) throw new InstallRequestRefused("inventory");
                bool empty=name=="payload/night_shifts/__init__.py" || name=="payload/night_shifts/guest/__init__.py";
                if (m.Bytes<(empty?0:1) || m.Bytes>(launch?16L:32L)*1024*1024) throw new InstallRequestRefused("pin");
                Digest(m.Sha); total+=m.Bytes;
                byte[] exact=empty?new byte[0]:(name=="runtime/python314._pth"?InstallBoundary.Pth:
                    (name.EndsWith(".exe.config",StringComparison.Ordinal)?LaunchBoundary.Config:null));
                if (exact!=null && (m.Bytes!=exact.Length || m.Sha!=Sha(exact))) throw new InstallRequestRefused("fixed_pin");
            }
            if (!launch && total>96L*1024*1024-MaxWorkerBytes) throw new InstallRequestRefused("closure_bound");
        }
        static SortedDictionary<string,object> D(params object[] pairs) {
            var result=new SortedDictionary<string,object>(StringComparer.Ordinal);
            for (int i=0;i<pairs.Length;i+=2) result.Add((string)pairs[i],pairs[i+1]);
            return result;
        }
        static object IdObject(IdentityData id) { return D("index",id.Index,"volume",id.Volume); }
        static object PinObject(PinData pin) { return D("bytes",pin.Bytes,"sha256",pin.Sha); }
        static object PlaceObject(PlaceData place) { return D("identity",IdObject(place.Identity),"path",place.Path); }
        static object Members(MemberData[] members) {
            return Array.ConvertAll(members,delegate(MemberData m) { return (object)D("bytes",m.Bytes,"name",m.Name,"sha256",m.Sha); });
        }
        static object ProvisionObject(ProvisionData provision) {
            RecipeData p=provision.Pins;
            return D("bundle",PinObject(provision.Bundle),"source",PlaceObject(provision.Source),
                "output_parent",PlaceObject(provision.Parent),"pins",D("code_tree_sha256",p.Code,"codec_tree_sha256",p.Codec,
                    "runtime_sha256",p.Runtime,"runtime_bytes",p.RuntimeBytes,"recovery_sha256",p.Recovery,"recovery_bytes",p.RecoveryBytes));
        }
        static SortedDictionary<string,object> Document(RequestData r,bool worker,string digest) {
            var launch=D("identity",IdObject(r.Launch.Identity),"path",r.Launch.Path,"scratch_identity",IdObject(r.Launch.Scratch));
            var import=D("identity",IdObject(r.Import.Identity),"path",r.Import.Path);
            if (!worker) { launch.Add("files",Members(r.Launch.Files)); import.Add("files",Members(r.Import.Files)); }
            var result=D("version",1,"scope",worker?WorkerScope:Scope,"operation",Operation,
                "installation_id",r.Id,"operator_sid",r.Sid,"budget_seconds",r.Budget,"expires_unix",r.Until,
                "launch_anchor",launch,"import_anchor",import,"provision",ProvisionObject(r.Provision));
            if (worker) result.Add("request_sha256",digest);
            return result;
        }
        static void Json(StringBuilder text,object value) {
            var map=value as SortedDictionary<string,object>;
            if (map!=null) {
                text.Append('{'); bool first=true;
                foreach (KeyValuePair<string,object> pair in map) {
                    if (!first) text.Append(','); first=false; Json(text,pair.Key); text.Append(':'); Json(text,pair.Value);
                }
                text.Append('}'); return;
            }
            var array=value as object[];
            if (array!=null) {
                text.Append('['); for (int i=0;i<array.Length;i++) { if (i!=0) text.Append(','); Json(text,array[i]); }
                text.Append(']'); return;
            }
            var s=value as string;
            if (s!=null) {
                text.Append('"');
                foreach (char c in s) {
                    if (c<32 || c>126) throw new InstallRequestRefused("text");
                    if (c=='"' || c=='\\') text.Append('\\'); text.Append(c);
                }
                text.Append('"'); return;
            }
            if (!(value is int) && !(value is long) && !(value is uint) && !(value is ulong)) throw new InstallRequestRefused("schema");
            text.Append(((IFormattable)value).ToString(null,CultureInfo.InvariantCulture));
        }
        static byte[] Encode(object value) { var text=new StringBuilder(); Json(text,value); text.Append('\n'); return Encoding.ASCII.GetBytes(text.ToString()); }
        static string Tree(MemberData[] files,bool code) {
            var tree=new SortedDictionary<string,object>(StringComparer.Ordinal);
            foreach (MemberData m in files) {
                bool isCode=m.Name.StartsWith("payload/night_shifts/",StringComparison.Ordinal);
                if (m.Name.StartsWith("payload/",StringComparison.Ordinal) && isCode==code)
                    tree.Add(m.Name.Substring(8),D("bytes",m.Bytes,"sha256",m.Sha));
            }
            return Sha(Encode(tree));
        }
        static void Validate(RequestData r) {
            if (r==null || r.Version!=1 || r.Scope!=Scope || r.Operation!=Operation || r.Id==null ||
                !Regex.IsMatch(r.Id,"\\A[0-9a-f]{32}\\z") || r.Launch==null || r.Import==null || r.Provision==null)
                throw new InstallRequestRefused("schema");
            if (r.Sid==null || r.Sid.Length>80 || !Regex.IsMatch(r.Sid,"\\AS-1-5-21-[0-9]+-[0-9]+-[0-9]+-[0-9]+\\z"))
                throw new InstallRequestRefused("sid");
            string[] sid=r.Sid.Split('-');
            for (int i=4;i<sid.Length;i++) {
                uint number;
                if (!UInt32.TryParse(sid[i],NumberStyles.None,CultureInfo.InvariantCulture,out number) ||
                    number.ToString(CultureInfo.InvariantCulture)!=sid[i]) throw new InstallRequestRefused("sid");
            }
            if (r.Budget<6 || r.Budget>900 || r.Until<1 || r.Until>253402300799L) throw new InstallRequestRefused("number");
            Path(r.Launch.Path,200); Path(r.Import.Path,240); Place(r.Provision.Source); Place(r.Provision.Parent);
            if ((r.Provision.Parent.Path+"\\native-validator-"+r.Id).Length>240) throw new InstallRequestRefused("output_path");
            var identities=new HashSet<string>(StringComparer.Ordinal);
            foreach (IdentityData id in new IdentityData[] {r.Launch.Identity,r.Import.Identity,r.Launch.Scratch,r.Provision.Source.Identity,r.Provision.Parent.Identity})
                if (!identities.Add(Identity(id))) throw new InstallRequestRefused("identity_alias");
            if (r.Launch.Scratch.Volume!=r.Launch.Identity.Volume) throw new InstallRequestRefused("identity_alias");
            string[] paths={r.Launch.Path,r.Import.Path,r.Provision.Source.Path,r.Provision.Parent.Path};
            for (int i=0;i<paths.Length;i++) for (int j=i+1;j<paths.Length;j++)
                if (String.Equals(paths[i],paths[j],StringComparison.OrdinalIgnoreCase) ||
                    paths[i].StartsWith(paths[j]+"\\",StringComparison.OrdinalIgnoreCase) ||
                    paths[j].StartsWith(paths[i]+"\\",StringComparison.OrdinalIgnoreCase)) throw new InstallRequestRefused("path_overlap");
            Files(r.Launch.Files,LaunchBoundary.FileNames,true);
            SortedSet<string> imports=InstallBoundary.Catalog(); imports.Remove("provision-request.json");
            Files(r.Import.Files,imports,false); Pin(r.Provision.Bundle,64L*1024*1024);
            RecipeData p=r.Provision.Pins;
            if (p==null) throw new InstallRequestRefused("schema");
            Digest(p.Code); Digest(p.Codec); Digest(p.Runtime); Digest(p.Recovery);
            if (p.RuntimeBytes<1 || p.RuntimeBytes>32L*1024*1024 || p.RecoveryBytes<20*2048 ||
                p.RecoveryBytes>8L*1024*1024*1024 || p.RecoveryBytes%2048!=0) throw new InstallRequestRefused("number");
            if (p.Code!=Tree(r.Import.Files,true) || p.Codec!=Tree(r.Import.Files,false)) throw new InstallRequestRefused("tree_pin");
        }
        public static BoundInstallationInputs Bind(byte[] raw,long expectedBytes,string expectedSha256) {
            if (raw==null || expectedBytes<1 || expectedBytes>MaxRequestBytes || raw.Length!=expectedBytes)
                throw new InstallRequestRefused("request_pin");
            Digest(expectedSha256);
            byte[] snapshot=(byte[])raw.Clone(); // bound before allocation; never parse caller-mutable bytes
            if (Sha(snapshot)!=expectedSha256) throw new InstallRequestRefused("request_pin");
            RequestData r;
            try {
                var quota=new XmlDictionaryReaderQuotas {MaxDepth=12,MaxStringContentLength=MaxRequestBytes,
                    MaxArrayLength=128,MaxBytesPerRead=4096,MaxNameTableCharCount=8192};
                var settings=new DataContractJsonSerializerSettings {MaxItemsInObjectGraph=1024};
                var serializer=new DataContractJsonSerializer(typeof(RequestData),settings);
                using (XmlDictionaryReader reader=JsonReaderWriterFactory.CreateJsonReader(snapshot,quota))
                    r=(RequestData)serializer.ReadObject(reader);
            } catch { throw new InstallRequestRefused("request_json"); }
            Validate(r);
            byte[] canonical=Encode(Document(r,false,null));
            if (canonical.Length!=snapshot.Length) throw new InstallRequestRefused("canonical");
            for (int i=0;i<canonical.Length;i++) if (canonical[i]!=snapshot[i]) throw new InstallRequestRefused("canonical");
            byte[] worker=Encode(Document(r,true,expectedSha256));
            if (worker.Length>MaxWorkerBytes) throw new InstallRequestRefused("worker_bound");
            return new BoundInstallationInputs(r,expectedSha256,worker);
        }
    }
}
