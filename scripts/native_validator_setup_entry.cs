// Uninstalled fixed setup HOST. Never build/load checkout code elevated.
// Reviewed protected self/OS/CLR load trust and authentic whole-attempt delivery
// MUST precede this entry. Profiles/hashes/argv are consistency data, not trust.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.Principal;
using System.Text;
using AiAgent.NativeValidator;
using AiAgent.ValidatorDelivery;
using AiAgent.ValidatorGuardian;
namespace AiAgent.ValidatorSetup {
    internal sealed class SetupLocation {
        internal readonly string Root;
        internal readonly uint Volume;
        internal readonly ulong Index,Claims,Receipts,Scratch;
        internal SetupLocation(string root,uint volume,ulong index,ulong claims,ulong receipts,ulong scratch) {
            if (root==null || root.Length<4 || root.Length>180 || root[0]<'A' || root[0]>'Z') throw new SetupRefused("host_location");
            try { InstallBoundary.PathParts(root); } catch { throw new SetupRefused("host_location"); }
            var ids=new HashSet<ulong>(new ulong[] {index,claims,receipts,scratch});
            if (ids.Count!=4 || ids.Contains(0)) throw new SetupRefused("host_location");
            Root=root; Volume=volume; Index=index; Claims=claims; Receipts=receipts; Scratch=scratch;
        }
    }
    internal sealed class SetupHostProfile {
        internal const string HostExe="validator-setup-host.exe",WatchdogExe="validator-setup-watchdog.exe";
        internal readonly SetupParent Parent;
        internal readonly SetupLocation Location;
        internal readonly SetupReferences References;
        internal readonly string AttemptId,Operation,PacketSha256,Digest;
        internal readonly int Seconds,PacketBytes;
        internal readonly long ExpiresUnix;
        internal SetupHostProfile(SetupParent parent,SetupLocation location,string id,string operation,int seconds,long until,
            int packetBytes,string packetSha,SetupReferences refs) {
            if (parent==null || location==null || !System.Text.RegularExpressions.Regex.IsMatch(id??"","\\A[0-9a-f]{32}\\z") ||
                (operation!="prepare" && operation!="publish") || seconds<6 || seconds>300 || until<1 || until>253402300799L)
                throw new SetupRefused("host_profile");
            if (String.Equals(parent.Path,location.Root,StringComparison.OrdinalIgnoreCase) ||
                parent.Path.StartsWith(location.Root+"\\",StringComparison.OrdinalIgnoreCase) ||
                location.Root.StartsWith(parent.Path+"\\",StringComparison.OrdinalIgnoreCase)) throw new SetupRefused("host_overlap");
            if (operation=="prepare") {
                if (refs!=null || packetBytes!=0 || packetSha!="") throw new SetupRefused("host_prepare_profile");
            } else {
                if (refs==null || refs.Parent.Path!=parent.Path || refs.Parent.Volume!=parent.Volume || refs.Parent.Index!=parent.Index ||
                    refs.Parent.OperatorSid!=parent.OperatorSid || packetBytes<1 || packetBytes>SetupPayload.MaxPacketBytes ||
                    !InstallBoundary.Digest(packetSha)) throw new SetupRefused("host_publish_profile");
            }
            Parent=parent; Location=location; AttemptId=id; Operation=operation; Seconds=seconds; ExpiresUnix=until;
            PacketBytes=packetBytes; PacketSha256=packetSha; References=refs; Digest=InstallBoundary.Sha(Binding());
        }
        static void Text(BinaryWriter w,string value) { byte[] bytes=Encoding.ASCII.GetBytes(value); w.Write(bytes.Length); w.Write(bytes); }
        byte[] Binding() {
            using (var s=new MemoryStream()) {
                using (var w=new BinaryWriter(s,Encoding.ASCII,true)) {
                    w.Write(1); Text(w,Operation); Text(w,Parent.OperatorSid); Text(w,Parent.Path); w.Write(Parent.Volume); w.Write(Parent.Index);
                    Text(w,Location.Root); w.Write(Location.Volume); w.Write(Location.Index); w.Write(Location.Claims); w.Write(Location.Receipts); w.Write(Location.Scratch);
                    Text(w,AttemptId); w.Write(Seconds); w.Write(ExpiresUnix); w.Write(PacketBytes); Text(w,PacketSha256);
                    foreach (string n in SetupTransaction.Anchors) w.Write(References==null?0UL:References.Index(n));
                }
                return s.ToArray();
            }
        }
    }
    internal sealed class SetupSupervisorProfile {
        internal readonly SetupHostProfile Host;
        internal readonly int HostBytes;
        internal readonly string HostSha256;
        internal SetupSupervisorProfile(SetupHostProfile host,int bytes,string digest) {
            if (host==null || bytes<1 || bytes>16*1024*1024 || !InstallBoundary.Digest(digest)) throw new SetupRefused("supervisor_profile");
            Host=host; HostBytes=bytes; HostSha256=digest;
        }
        internal byte[] Policy() {
            return Encoding.ASCII.GetBytes("{\"host_bytes\":"+HostBytes.ToString(CultureInfo.InvariantCulture)+",\"host_sha256\":\""+HostSha256+
                "\",\"profile_sha256\":\""+Host.Digest+"\",\"scope\":\"protected_setup_operation_approval_once\",\"version\":1}\n");
        }
        internal byte[] OuterClaim() {
            return Encoding.ASCII.GetBytes("{\"policy_sha256\":\""+InstallBoundary.Sha(Policy())+"\",\"profile_sha256\":\""+Host.Digest+
                "\",\"scope\":\"setup_outer_attempt_consumed_not_acceptance\",\"version\":1}\n");
        }
        internal byte[] Claim() {
            return Encoding.ASCII.GetBytes("{\"policy_sha256\":\""+InstallBoundary.Sha(Policy())+"\",\"profile_sha256\":\""+Host.Digest+
                "\",\"scope\":\"setup_host_attempt_consumed_not_acceptance\",\"version\":1}\n");
        }
    }
    internal sealed class SetupClock : IGuardianClock,IBoundaryClock {
        readonly IGuardianClock source;
        double last=Double.NegativeInfinity; long wall=Int64.MinValue;
        internal SetupClock(IGuardianClock value) { if (value==null) throw new SetupRefused("host_clock"); source=value; }
        public double Seconds { get {
            double n=source.Seconds;
            if (Double.IsNaN(n) || Double.IsInfinity(n) || n<0 || n>1e9 || n<last) throw new SetupUnknown("host_clock_unknown");
            last=n; return n;
        } }
        public long Unix { get { long n=source.Unix; if (n<1 || n<wall) throw new SetupUnknown("host_clock_unknown"); wall=n; return n; } }
        internal void Require(double cap,long until) { if (Seconds>=cap || Unix>=until) throw new SetupRefused("host_window"); }
        internal double Start(SetupHostProfile p) {
            double first=Seconds; long remaining=p.ExpiresUnix-Unix;
            if (remaining<6 || remaining>86400) throw new SetupRefused("host_window");
            double cap=first+Math.Min(p.Seconds,remaining); Require(cap,p.ExpiresUnix); return cap;
        }
    }
    internal sealed class SetupCounter : ISectionCounter {
        [DllImport("kernel32.dll",ExactSpelling=true)] static extern bool QueryPerformanceCounter(out long n);
        [DllImport("kernel32.dll",ExactSpelling=true)] static extern bool QueryPerformanceFrequency(out long n);
        public long Read() { long n; if (!QueryPerformanceCounter(out n)) throw new SetupUnknown("host_counter_unknown"); return n; }
        public long Frequency() { long n; if (!QueryPerformanceFrequency(out n)) throw new SetupUnknown("host_counter_unknown"); return n; }
    }
    internal sealed class SetupHostFrame {
        internal const string Mode="--setup-once-qpc-v1";
        internal readonly long Limit,Frequency;
        internal readonly SetupSupervisorProfile Profile;
        SetupHostFrame(long limit,long rate,SetupSupervisorProfile profile) { Limit=limit; Frequency=rate; Profile=profile; }
        internal static long N(string s,long max) {
            long n;
            if (s==null || s.Length>19 || !Int64.TryParse(s,System.Globalization.NumberStyles.None,CultureInfo.InvariantCulture,out n) ||
                n<1 || n>max || n.ToString(CultureInfo.InvariantCulture)!=s) throw new SetupRefused("host_frame"); return n;
        }
        internal static SetupHostFrame Parse(SetupHostProfile p,string[] args) {
            if (args==null || args.Length!=5) throw new SetupRefused("host_frame"); string[] a=(string[])args.Clone();
            if (a[0]!=Mode) throw new SetupRefused("host_frame");
            return new SetupHostFrame(N(a[1],Int64.MaxValue),N(a[2],1000000000L),
                new SetupSupervisorProfile(p,(int)N(a[3],16*1024*1024),a[4]));
        }
        internal static string Command(SetupSupervisorProfile p,SectionCounterFrame f) {
            return "\""+p.Host.Location.Root+"\\"+SetupHostProfile.HostExe+"\" "+Mode+" "+f.Limit.ToString(CultureInfo.InvariantCulture)+
                " "+f.Frequency.ToString(CultureInfo.InvariantCulture)+" "+p.HostBytes.ToString(CultureInfo.InvariantCulture)+" "+p.HostSha256;
        }
        internal double Translate(SetupClock clock,ISectionCounter counter) {
            return TranslateWindow(Profile.Host,Limit,Frequency,clock,counter);
        }
        internal static double TranslateWindow(SetupHostProfile profile,long limit,long frequency,SetupClock clock,ISectionCounter counter) {
            double first=clock.Seconds; long rate=counter.Frequency(),start=counter.Read(),end=counter.Read(),again=counter.Frequency();
            double last=clock.Seconds; long wall=clock.Unix;
            if (rate<1 || rate!=frequency || again!=rate || start<1 || end<start || end-start>rate/4 || last-first>0.25 || limit<=end || wall>=profile.ExpiresUnix)
                throw new SetupRefused("host_counter");
            decimal remaining=Math.Min((decimal)(limit-end)/rate,(decimal)profile.ExpiresUnix-wall);
            double cap=first+(double)remaining-0.001001;
            if (remaining<=0 || remaining>300 || Double.IsNaN(cap) || Double.IsInfinity(cap) || cap<=last) throw new SetupRefused("host_counter"); return cap;
        }
    }
    internal static class SetupResult {
        internal const int Bytes=97;
        internal static byte[] Encode(SetupHostProfile p,SetupReferences refs) {
            if (refs==null || refs.Parent.Path!=p.Parent.Path || refs.Parent.Volume!=p.Parent.Volume || refs.Parent.Index!=p.Parent.Index ||
                refs.Parent.OperatorSid!=p.Parent.OperatorSid) throw new SetupRefused("result_binding");
            using (var s=new MemoryStream()) using (var w=new BinaryWriter(s)) {
                w.Write(Encoding.ASCII.GetBytes("NVSR0001")); w.Write((byte)(p.Operation=="prepare"?0:1));
                for (int i=0;i<64;i+=2) w.Write(Convert.ToByte(p.Digest.Substring(i,2),16));
                foreach (string n in SetupTransaction.Anchors) {
                    ulong index=refs.Index(n);
                    if (p.References!=null && index!=p.References.Index(n)) throw new SetupRefused("result_binding"); w.Write(index);
                }
                return s.ToArray();
            }
        }
        internal static SetupReferences Parse(SetupHostProfile p,byte[] raw) {
            if (raw==null || raw.Length!=Bytes) throw new SetupRefused("result_frame");
            using (var s=new MemoryStream(raw,false)) using (var r=new BinaryReader(s)) {
                if (Encoding.ASCII.GetString(r.ReadBytes(8))!="NVSR0001" || r.ReadByte()!=(p.Operation=="prepare"?0:1) ||
                    BitConverter.ToString(r.ReadBytes(32)).Replace("-","").ToLowerInvariant()!=p.Digest) throw new SetupRefused("result_frame");
                var indices=new Dictionary<string,ulong>(StringComparer.Ordinal);
                foreach (string n in SetupTransaction.Anchors) indices.Add(n,r.ReadUInt64());
                var refs=new SetupReferences(p.Parent,indices); SetupPayload.Exact(raw,Encode(p,refs)); return refs;
            }
        }
    }
    internal interface ISetupRole { void Require(SetupHostProfile profile,bool watchdog); }
    internal sealed class WindowsSetupRole : ISetupRole {
        [DllImport("kernel32.dll",ExactSpelling=true,CharSet=CharSet.Unicode)] static extern uint GetModuleFileNameW(IntPtr h,StringBuilder s,uint n);
        public void Require(SetupHostProfile p,bool watchdog) {
            using (WindowsIdentity impersonation=WindowsIdentity.GetCurrent(true))
                if (impersonation!=null) throw new SetupRefused("host_impersonation");
            new WindowsBoundaryFiles().RequireOperator(p.Parent.OperatorSid);
            var path=new StringBuilder(512); uint n=GetModuleFileNameW(IntPtr.Zero,path,512);
            if (n<1 || n>=512 || path.ToString()!=p.Location.Root+"\\"+(watchdog?SetupHostProfile.WatchdogExe:SetupHostProfile.HostExe))
                throw new SetupRefused("fixed_setup_host");
        }
    }
    internal interface ISetupAttemptFiles : IGuardianLaunchGate {
        void Acquire(); void Reverify(); byte[] Packet(); void WriteResult(byte[] raw); byte[] ReadResult(); void WriteReceipt(byte[] raw); void Close();
    }
    internal interface ISetupFilesFactory { ISetupAttemptFiles Host(SetupSupervisorProfile p,SetupClock clock,double cap); }
    internal interface ISetupOperation { SetupReferences Run(SetupHostProfile p,SetupClock clock,double cap,byte[] packet); }
    internal sealed class NativeSetupOperation : ISetupOperation {
        public SetupReferences Run(SetupHostProfile p,SetupClock clock,double cap,byte[] packet) {
            var tx=new SetupTransaction(p.Parent,p.Seconds,new WindowsSetupFiles(),clock,cap);
            if (p.Operation=="prepare") return tx.Prepare();
            tx.Publish(p.References,packet,p.PacketBytes,p.PacketSha256); return p.References;
        }
    }
    internal sealed class SetupHostEntry {
        readonly SetupHostProfile profile; readonly SetupClock clock; readonly ISectionCounter counter;
        readonly ISetupRole role; readonly ISetupFilesFactory factory; readonly ISetupOperation operation;
        bool used;
        internal SetupHostEntry(SetupHostProfile p,IGuardianClock time,ISectionCounter qpc,ISetupRole gate,ISetupFilesFactory files,ISetupOperation action) {
            if (p==null || qpc==null || gate==null || files==null || action==null) throw new SetupRefused("host_entry");
            profile=p; clock=new SetupClock(time); counter=qpc; role=gate; factory=files; operation=action;
        }
        internal int Run(string[] args) {
            if (used) return 126; used=true; ISetupAttemptFiles files=null; int code=125; double cap=0;
            try {
                SetupHostFrame frame=SetupHostFrame.Parse(profile,args); role.Require(profile,false); cap=frame.Translate(clock,counter);
                files=factory.Host(frame.Profile,clock,cap); files.Acquire(); clock.Require(cap,profile.ExpiresUnix);
                byte[] packet=profile.Operation=="publish"?files.Packet():null; clock.Require(cap,profile.ExpiresUnix);
                SetupReferences refs=operation.Run(profile,clock,cap,packet); clock.Require(cap,profile.ExpiresUnix);
                files.Reverify(); files.WriteResult(SetupResult.Encode(profile,refs)); files.Reverify(); clock.Require(cap,profile.ExpiresUnix); code=0;
            } catch (SetupRefused) { code=126; } catch (BoundaryRefused) { code=126; } catch { code=125; }
            finally { if (files!=null) try { files.Close(); } catch { code=125; } }
            if (code==0) try { clock.Require(cap,profile.ExpiresUnix); } catch { code=125; }
            return code; // local observation ONLY, never setup/installation acceptance
        }
    }
    internal static class ValidatorSetupHostProgram {
        static int Main(string[] args) {
            try {
                return new SetupHostEntry(ReviewedSetupHost.Create(),new GuardianClock(),new SetupCounter(),new WindowsSetupRole(),
                    new WindowsSetupFilesFactory(),new NativeSetupOperation()).Run(args);
            } catch { return 125; }
        }
    }
}
