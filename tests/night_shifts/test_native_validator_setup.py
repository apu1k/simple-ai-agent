"""Compiled setup models plus real UNELEVATED production-gate refusal.

No production profile/approval is installed; neither product Main is invoked.
Ordinary native creation fixtures live in test_native_validator_setup_windows.
"""
from __future__ import annotations

import base64
import os
import subprocess
from pathlib import Path

import pytest

from night_shifts import bootstrap_native_build as build
from night_shifts import bootstrap_native_install_request as request
from tests.night_shifts.test_bootstrap_native_setup import packet
from tests.night_shifts.test_native_validator_guardian_entry import _profile

ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = ('prepare', 'prepare_replay', 'prepare_close', 'prepare_identity', 'success', 'short_reads',
    'publish_replay', 'changed_refs', 'wrong_parent', 'caller_mutation', 'pin_hash', 'pin_length',
    'frame_magic', 'frame_count', 'frame_name', 'frame_extent', 'frame_truncated', 'frame_trailer',
    'leaf_pin', 'policy_bytes', 'profile_bytes', 'worker_bytes', 'claim_collision', 'extra_entry',
    'identity_drift', 'write_fault', 'flush_fault', 'read_fault', 'read_zero', 'read_over',
    'seal_drift', 'late_corruption', 'claim_corruption', 'clock_rollback', 'clock_nan', 'deadline',
    'wall_expiry', 'wall_rollback', 'utc_shorten', 'expiry_sample_cost', 'expiry_sample_expired',
    'outside_source_path', 'outside_output_path', 'outside_source_parent', 'outside_source_alias',
    'outside_output_alias', 'outside_cross_volume', 'outside_prefix', 'final_close_deadline', 'final_close_expiry',
    'close_fault', 'all_closes', 'one_shot_failure', 'claim_order', 'policy_last', 'policy_compatibility', 'native_gate')
HARNESS = r'''
using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using AiAgent.NativeValidator;
using AiAgent.ValidatorApproval;
namespace AiAgent.ValidatorSetup {
    internal sealed class SetupTestClock : IBoundaryClock {
        internal double Time=100; internal long Wall=1000;
        internal Action WallHook;
        public double Seconds { get { return Time; } }
        public long Unix { get { if (WallHook!=null) { Action hook=WallHook; WallHook=null; hook(); } return Wall; } }
    }
    internal sealed class SetupHandle { internal string Name; internal int Position,Closes; internal bool Closed; }
    internal sealed class SetupFiles : ISetupFiles {
        internal const string RootName="native-validator-bootstrap";
        internal const string Prefix=@"\\?\Volume{00000000-0000-4000-8000-000000000001}\";
        internal readonly Dictionary<string,Stamp> Meta=new Dictionary<string,Stamp>(StringComparer.Ordinal);
        internal readonly Dictionary<string,byte[]> Data=new Dictionary<string,byte[]>(StringComparer.Ordinal);
        internal readonly List<SetupHandle> Handles=new List<SetupHandle>();
        internal readonly List<string> Events=new List<string>();
        internal Action<string> Hook;
        internal bool Short,Zero,Over,Reached;
        internal string Fault,CloseFault;
        ulong next=100;
        internal SetupFiles() { Meta.Add("@volume",New(1,true,Prefix)); Meta.Add("",New(2,true,Prefix+"SetupParent")); }
        static Stamp New(ulong index,bool dir,string final) {
            return new Stamp {Volume=42,Index=index,Attributes=dir?16u:128u,Links=1,Bytes=0,
                Security="MODEL SECURITY ONLY",Private=true,FinalName=final};
        }
        internal string At(string path) { return RootName+(path.Length==0?"":"/"+path); }
        void Event(string e) {
            Events.Add(e); if (Hook!=null) Hook(e);
            if (e==Fault || e==CloseFault) { Reached=true; throw new InvalidOperationException("INJECTED_SECRET_TEXT"); }
        }
        static string Child(SetupHandle parent,string name) {
            if (parent.Name=="@volume") { SetupHarness.Check(name=="SetupParent"); return ""; }
            return parent.Name.Length==0?name:parent.Name+"/"+name;
        }
        SetupHandle Handle(string name) { var h=new SetupHandle {Name=name}; Handles.Add(h); return h; }
        public void RequireOperator(string sid) { Event("operator"); SetupHarness.Check(sid=="S-1-5-21-1-2-3-1001"); }
        public object Root(string drive) { Event("root"); SetupHarness.Check(drive==@"C:\"); return Handle("@volume"); }
        public object Open(object parent,string name,bool directory) {
            var p=(SetupHandle)parent; SetupHarness.Check(!p.Closed); string path=Child(p,name); Event("open:"+path);
            SetupHarness.Check(Meta.ContainsKey(path)); return Handle(path);
        }
        public object Create(object parent,string name,bool directory) {
            var p=(SetupHandle)parent; SetupHarness.Check(!p.Closed); string path=Child(p,name); Event("create:"+path);
            if (Meta.ContainsKey(path)) throw new SetupRefused("create_collision_or_refused");
            Meta.Add(path,New(next++,directory,Meta[p.Name].FinalName.TrimEnd('\\')+"\\"+name));
            if (!directory) Data.Add(path,new byte[0]); return Handle(path);
        }
        public Stamp Observe(object handle,bool directory,bool ancestor) {
            var h=(SetupHandle)handle; SetupHarness.Check(!h.Closed); Event("observe:"+h.Name); var s=Meta[h.Name];
            return new Stamp {Volume=s.Volume,Index=s.Index,Attributes=s.Attributes,Links=s.Links,Bytes=s.Bytes,
                Security=s.Security,Private=!ancestor,FinalName=s.FinalName};
        }
        public string[] Names(object handle) {
            var h=(SetupHandle)handle; Event("names:"+h.Name); var names=new List<string>();
            string prefix=h.Name.Length==0?"":h.Name+"/";
            foreach (string n in Meta.Keys)
                if (n!="@volume" && n.Length>prefix.Length && n.StartsWith(prefix,StringComparison.Ordinal) && n.IndexOf('/',prefix.Length)<0)
                    names.Add(n.Substring(prefix.Length));
            return names.ToArray();
        }
        public void Rewind(object handle) { var h=(SetupHandle)handle; Event("rewind:"+h.Name); h.Position=0; }
        public int Read(object handle,byte[] bytes,int count) {
            var h=(SetupHandle)handle; Event("read:"+h.Name); if (Zero) return 0; if (Over) return count+1;
            int got=Math.Min(count,Data[h.Name].Length-h.Position); if (Short) got=Math.Min(got,7);
            Array.Copy(Data[h.Name],h.Position,bytes,0,got); h.Position+=got; return got;
        }
        public void Write(object handle,byte[] bytes) {
            var h=(SetupHandle)handle; Event("write:"+h.Name); Data[h.Name]=(byte[])bytes.Clone();
            Meta[h.Name].Bytes=bytes.Length; Meta[h.Name].Attributes|=32; Event("flush:"+h.Name);
        }
        public void Close(object handle) {
            var h=(SetupHandle)handle; SetupHarness.Check(h.Closes++==0); h.Closed=true; Event("close:"+h.Name);
        }
        internal void ClosedAll() { foreach (SetupHandle h in Handles) SetupHarness.Check(h.Closed && h.Closes==1); }
    }
    public static class SetupHarness {
        internal static void Check(bool ok) { if (!ok) throw new Exception("ASSERTION"); }
        static SetupParent Parent() { return new SetupParent(@"C:\SetupParent",42,2,"S-1-5-21-1-2-3-1001"); }
        static SetupTransaction Tx(SetupFiles f,SetupTestClock c) { return new SetupTransaction(Parent(),20,f,c); }
        static void Refuse(Action action,string label,bool unknown) {
            bool caught=false;
            try { action(); }
            catch (SetupRefused e) { if (unknown || e.Message!=label) throw; caught=true; }
            catch (SetupUnknown e) { if (!unknown || e.Message!=label) throw; caught=true; }
            Check(caught);
        }
        static Dictionary<string,int[]> Offsets(byte[] packet) {
            var result=new Dictionary<string,int[]>(StringComparer.Ordinal);
            using (var s=new MemoryStream(packet,false)) using (var r=new BinaryReader(s)) {
                s.Position=8; uint count=r.ReadUInt32();
                for (int i=0;i<count;i++) { string n=Encoding.ASCII.GetString(r.ReadBytes(r.ReadUInt16()));
                    int size=(int)r.ReadUInt32(); result.Add(n,new int[] {(int)s.Position,size}); s.Position+=size; }
            }
            return result;
        }
        static void Case(string name,byte[] original) {
            var f=new SetupFiles(); var c=new SetupTestClock(); var tx=Tx(f,c);
            if (name=="prepare_close") { f.CloseFault="close:"+f.At("launch/scratch");
                Refuse(delegate { tx.Prepare(); },"close_unknown",true); Check(f.Reached); f.ClosedAll(); return; }
            if (name=="prepare_identity") { f.Meta[""].Index=3;
                Refuse(delegate { tx.Prepare(); },"parent_identity",false); Check(f.Meta.Count==2); f.ClosedAll(); return; }
            SetupReferences refs=tx.Prepare(); f.ClosedAll();
            if (name=="prepare") { Check(refs.Index("")==100 && refs.Index("approval")==101 && refs.Index("launch/scratch")==106); return; }
            if (name=="prepare_replay") { Refuse(delegate { Tx(f,c).Prepare(); },"create_collision_or_refused",false); f.ClosedAll(); return; }
            byte[] raw=(byte[])original.Clone(); var offsets=Offsets(raw); string expected=null; bool unknown=false,success=false;
            string claim=f.At("publication.claim");
            if (name.StartsWith("outside_",StringComparison.Ordinal)) {
                int[] span=offsets["request.json"]; byte[] request=new byte[span[1]];
                Array.Copy(raw,span[0],request,0,request.Length);
                var bound=AiAgent.ValidatorRequest.InstallationRequest.Bind(request,request.Length,InstallBoundary.Sha(request));
                string root=Parent().Root,label=null; uint volume=42; ulong[] reserved={2,100,101,102,103,104,105,106};
                if (name=="outside_source_path") { root=@"C:\Inputs"; label="setup_overlap"; }
                if (name=="outside_output_path") { root=@"C:\Outputs"; label="setup_overlap"; }
                if (name=="outside_source_parent") { root=@"C:\Inputs\Nested"; label="setup_overlap"; }
                if (name=="outside_source_alias") { reserved=new ulong[] {30}; label="setup_alias"; }
                if (name=="outside_output_alias") { reserved=new ulong[] {40}; label="setup_alias"; }
                if (name=="outside_cross_volume") { volume=43; reserved=new ulong[] {30,40}; }
                if (name=="outside_prefix") root=@"C:\Input";
                int events=f.Events.Count; bool caught=false;
                try { bound.RequireSeparateSetupTree(root,volume,reserved); }
                catch (AiAgent.ValidatorRequest.InstallRequestRefused e) { if (e.Message!=label) throw; caught=true; }
                Check(caught==(label!=null) && f.Events.Count==events); f.ClosedAll(); return;
            }
            if (name=="short_reads") f.Short=true;
            if (name=="pin_hash" || name=="pin_length" || name=="one_shot_failure") expected="packet_pin";
            if (name.StartsWith("frame_",StringComparison.Ordinal)) {
                expected="packet_frame";
                if (name=="frame_magic") raw[0]^=1;
                if (name=="frame_count") raw[8]^=1;
                if (name=="frame_name") { raw[14]^=1; expected="packet_inventory"; }
                if (name=="frame_extent") { int at=offsets["approval/approval.json"][0]-4; Array.Copy(BitConverter.GetBytes(UInt32.MaxValue),0,raw,at,4); expected="packet_extent"; }
                if (name=="frame_truncated") { Array.Resize(ref raw,raw.Length-1); expected="packet_extent"; }
                if (name=="frame_trailer") { Array.Resize(ref raw,raw.Length+1); expected="packet_trailer"; }
            }
            if (name=="leaf_pin" || name=="worker_bytes" || name=="policy_bytes" || name=="profile_bytes") {
                string key=name=="leaf_pin"?"launch/validator-install-guardian.exe":
                    (name=="worker_bytes"?"imports/provision-request.json":(name=="policy_bytes"?"approval/approval.json":"reviewed-profile.cs"));
                raw[offsets[key][0]]^=1; expected=name=="leaf_pin"?"leaf_pin":"fixed_bytes";
            }
            if (name=="changed_refs" || name=="wrong_parent") {
                var ids=new Dictionary<string,ulong>(); foreach (string n in SetupTransaction.Anchors) ids.Add(n,refs.Index(n));
                if (name=="changed_refs") ids["approval"]=500;
                refs=new SetupReferences(name=="wrong_parent"?new SetupParent(@"C:\Other",42,2,Parent().OperatorSid):Parent(),ids);
                expected=name=="wrong_parent"?"reference_binding":"fixed_bytes";
            }
            if (name=="claim_collision" || name=="extra_entry") {
                string leaf=name=="claim_collision"?"publication.claim":"foreign";
                f.Meta.Add(f.At(leaf),new Stamp {Volume=42,Index=500,Attributes=128,Links=1,FinalName="inert"}); expected="inventory";
            }
            if (name=="identity_drift") { f.Meta[f.At("approval/claims")].Index=500; expected="anchor_identity"; }
            if (name=="caller_mutation") f.Hook=delegate(string e) { if (e=="operator") raw[0]^=1; };
            if (name=="write_fault" || name=="flush_fault" || name=="read_fault") {
                f.Fault=(name=="write_fault"?"write:":(name=="flush_fault"?"flush:":"read:"))+claim;
                expected="publication_unknown"; unknown=true;
            }
            if (name=="read_zero" || name=="read_over") { f.Zero=name=="read_zero"; f.Over=!f.Zero; expected="read_extent"; }
            if (name=="seal_drift") { f.Hook=delegate(string e) { if (e=="open:"+claim) f.Meta[claim].Index=500; }; expected="metadata_drift"; }
            if (name=="late_corruption" || name=="claim_corruption") {
                f.Hook=delegate(string e) { if (e=="write:"+f.At("request.json"))
                    f.Data[name=="claim_corruption"?claim:f.At("imports/payload/night_shifts/bootstrap_daemon_asset.py")][0]^=1; };
                expected="file_bytes";
            }
            if (name=="clock_rollback" || name=="clock_nan" || name=="deadline" || name=="utc_shorten") {
                if (name=="utc_shorten") c.Wall=1594;
                f.Hook=delegate(string e) { if (e=="write:"+claim) c.Time=name=="clock_rollback"?99:
                    (name=="clock_nan"?Double.NaN:(name=="utc_shorten"?107:121)); };
                unknown=name=="clock_rollback" || name=="clock_nan"; expected=unknown?"clock_unknown":"deadline";
            }
            if (name=="expiry_sample_cost" || name=="expiry_sample_expired") {
                c.Wall=1594; c.WallHook=delegate { c.Time=name=="expiry_sample_expired"?107:104; };
                if (name=="expiry_sample_cost") f.Hook=delegate(string e) { if (e=="write:"+claim) c.Time=107; };
                expected="deadline";
            }
            if (name=="wall_expiry" || name=="wall_rollback") {
                f.Hook=delegate(string e) { if (e=="write:"+claim) c.Wall=name=="wall_expiry"?1600:999; };
                expected=name=="wall_expiry"?"approval_window":"clock_unknown"; unknown=name=="wall_rollback";
            }
            if (name=="final_close_deadline" || name=="final_close_expiry") {
                f.Hook=delegate(string e) { if (e=="close:@volume") { if (name=="final_close_deadline") c.Time=121; else c.Wall=1600; } };
                expected=name=="final_close_deadline"?"deadline":"approval_window";
            }
            if (name=="close_fault" || name=="all_closes") {
                f.CloseFault=name=="all_closes"?"close:"+f.At("launch/scratch"):"close:@volume";
                expected="close_unknown"; unknown=true;
            }
            var pub=Tx(f,c); string digest=InstallBoundary.Sha(raw); int bytes=raw.Length;
            if (name=="pin_hash" || name=="one_shot_failure") digest=new string('0',64); if (name=="pin_length") bytes++;
            Action run=delegate { Check(pub.Publish(refs,raw,bytes,digest)=="local_setup_bytes_not_installation_acceptance"); };
            if (expected!=null) { Refuse(run,expected,unknown); if (f.Fault!=null || f.CloseFault!=null) Check(f.Reached); }
            else { run(); success=true; }
            f.ClosedAll();
            if (name=="expiry_sample_expired") Check(!f.Meta.ContainsKey(claim) && f.Events.FindAll(delegate(string e) { return e=="operator"; }).Count==1);
            if (name=="all_closes") Check(f.Events.IndexOf(f.CloseFault)<f.Events.LastIndexOf("close:@volume"));
            if (name=="one_shot_failure") Refuse(delegate { pub.Publish(refs,raw,bytes,digest); },"one_shot",false);
            if (name=="publish_replay") { Refuse(delegate { Tx(f,c).Publish(refs,raw,bytes,digest); },"inventory",false); f.ClosedAll(); }
            if (name=="claim_order" || name=="policy_last") {
                var writes=f.Events.FindAll(delegate(string e) { return e.StartsWith("write:",StringComparison.Ordinal); });
                Check(writes.Count==95 && writes[0]=="write:"+claim && writes[writes.Count-1]=="write:"+f.At("approval/approval.json"));
            }
            if (success) {
                Check(!f.Meta.ContainsKey(f.At("approval/claims/install-attempt.claim")) && !f.Meta.ContainsKey(f.At("imports/claims/install-attempt.claim")));
                Check(Encoding.ASCII.GetString(f.Data[claim]).Contains("setup_publication_consumed_not_acceptance"));
            }
            if (expected=="packet_pin" || (name.StartsWith("frame_",StringComparison.Ordinal)) ||
                name=="leaf_pin" || name=="policy_bytes" || name=="profile_bytes" || name=="worker_bytes")
                Check(!f.Meta.ContainsKey(claim));
            if (name=="policy_compatibility") {
                byte[] request=f.Data[f.At("request.json")],policy=f.Data[f.At("approval/approval.json")];
                var p=new ApprovalAnchorPlan(@"C:\SetupParent\native-validator-bootstrap\approval",42,101,Parent().OperatorSid,
                    policy.Length,InstallBoundary.Sha(policy),request.Length,InstallBoundary.Sha(request),10,1600);
                SetupPayload.Exact(policy,ApprovalProvisionGuardian.PolicyBytes(p));
                SetupPayload.Exact(refs.ProfileBytes(),f.Data[f.At("reviewed-profile.cs")]);
            }
        }
        public static void Run(string name,byte[] packet) {
            try {
                if (name=="native_gate") {
                    bool refused=false;
                    using (var id=System.Security.Principal.WindowsIdentity.GetCurrent()) {
                        try { new WindowsSetupFiles().RequireOperator(id.User.Value); }
                        catch (BoundaryRefused e) { Check(e.Message=="enabled_operator_required"); refused=true; }
                    }
                    Check(refused);
                } else Case(name,packet);
                Console.WriteLine(name+"|PASS");
            } catch (Exception e) { Console.WriteLine(name+"|FAIL:"+e.GetType().Name+":"+e.Message); }
        }
    }
}
'''


def quote(path):
    return "'" + str(path).replace("'", "''") + "'"


def powershell(script, timeout=25):
    exe = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    command = [str(exe), '-NoLogo', '-NoProfile', '-NonInteractive', '-EncodedCommand',
               base64.b64encode(script.encode('utf-16le')).decode('ascii')]
    assert len(subprocess.list2cmdline(command)) < 30000
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)


@pytest.fixture(scope='module')
def models(tmp_path_factory):
    if os.name != 'nt':
        pytest.skip('Windows CLR composition; not protected installation evidence')
    folder = tmp_path_factory.mktemp('setup-models')
    paths = [ROOT / 'scripts' / name for name in build.SOURCE_NAMES]
    paths += [ROOT / 'scripts/native_validator_setup.cs', ROOT / 'scripts/native_validator_setup_windows.cs']
    generated = folder / 'ReviewedGuardianProfile.g.cs'
    generated.write_bytes(request.build_validation_guardian_profile(_profile()))
    paths.append(generated)
    harness = folder / 'setup-models.cs'
    harness.write_text(HARNESS, encoding='utf-8')
    paths.append(harness)
    raw = folder / 'inert-packet.bin'
    raw.write_bytes(packet().packet)
    script = ("$ErrorActionPreference='Stop'; "
        "$id=[Security.Principal.WindowsIdentity]::GetCurrent(); "
        "if((New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'UNELEVATED tests required'}; "
        'Add-Type -Path @(' + ','.join(quote(p) for p in paths) + ') '
        "-ReferencedAssemblies @('System.dll','System.Core.dll','System.Xml.dll','System.Runtime.Serialization.dll'); "
        f'$raw=[IO.File]::ReadAllBytes({quote(raw)}); '
        'foreach($name in @(' + ','.join(quote(n) for n in SCENARIOS) + ')) {[AiAgent.ValidatorSetup.SetupHarness]::Run($name,$raw)}')
    result = powershell(script)
    assert result.returncode == 0, result.stdout + result.stderr
    answers = {}
    for line in result.stdout.splitlines():
        key, separator, answer = line.partition('|')
        assert separator and key not in answers, line
        answers[key] = answer
    assert set(answers) == set(SCENARIOS)
    return answers


@pytest.mark.parametrize('scenario', SCENARIOS)
def test_compiled_setup_transaction(models, scenario):
    assert models[scenario] == 'PASS', models[scenario]


def test_native_create_and_flush_are_create_new_relative_private_and_never_repair_or_launch():
    core = (ROOT / 'scripts/native_validator_setup.cs').read_text(encoding='utf-8')
    native = (ROOT / 'scripts/native_validator_setup_windows.cs').read_text(encoding='utf-8')
    assert 'Root=(IntPtr)parent' in native and 'Attributes=0x1040' in native
    assert 'directory?3u:0u,2,directory?0x200021u:0x200060u' in native
    assert 'O:BAG:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)' in native
    assert 'BoundarySecurity.ClaimSddl' in native and 'GetFileInformationByHandleEx((IntPtr)handle,23' in native
    assert core.index('WriteFile("publication.claim",claimBytes)') < core.index('WriteFile(entry.Key,entry.Value)')
    assert core.index('Verify(payload,false)') < core.index('WriteFile("approval/approval.json"')
    assert 'Bound.RequireSeparateSetupTree(' in core
    for forbidden in ('Process.Start', 'CreateProcess', 'SetSecurityInfo', 'SetFileSecurity', 'DeleteFile',
                      'RemoveDirectory', 'Directory.Delete', 'File.Delete', 'Assembly.Load', 'File.WriteAll', 'CreateClaim('):
        assert forbidden not in core + native
    ignore = (ROOT / '.gitignore').read_text(encoding='utf-8')
    for name in ('native_validator_setup.cs', 'native_validator_setup_windows.cs'):
        assert ignore.count('!/scripts/' + name + '\n') == 1
    assert all('native_validator_setup' not in name for name in build.SOURCE_NAMES)
