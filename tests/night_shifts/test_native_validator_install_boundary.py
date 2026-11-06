"""Unelevated CLR models; NEVER invoke the native adapter or carried runtime.

Compile both C# inputs with a same-assembly fake token/file/clock backend.
The temporary harness and compiler outputs are ordinary non-secret test data,
not protected installation, native claim/ACL evidence, provisioning or a VM.
"""
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

from night_shifts import bootstrap_native_deployment as deployment

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / 'scripts/native_validator_install_boundary.cs'
WINDOWS = ROOT / 'scripts/native_validator_install_windows.cs'
SCENARIOS = (
    'construct_no_io', 'success_retains_all_handles', 'claim_before_hash',
    'claim_rehash_and_reverify', 'claim_binds_inventory', 'plan_copies_dictionary',
    'short_successful_reads', 'one_shot_success', 'one_shot_failure', 'one_shot_concurrent',
    'new_object_cannot_retry', 'new_id_cannot_retry', 'closed_lease',
    'directory_size_not_identity', 'reverify_failure_terminal', 'close_failure_terminal',
    'all_closes_attempted', 'native_text_sanitized', 'claim_json_not_acceptance',
    'plan:null', 'plan:missing', 'plan:extra', 'plan:case_alias', 'plan:null_pin',
    'plan:negative_size', 'plan:oversize', 'plan:total_size', 'plan:digest',
    'plan:empty_noninitializer', 'plan:nonempty_initializer', 'plan:pth_size',
    'plan:request_size', 'plan:root', 'plan:dot', 'plan:ads', 'plan:unc',
    'plan:reserved', 'plan:trailing', 'plan:index', 'plan:id', 'plan:approval',
    'plan:operator', 'plan:expired', 'plan:window', 'plan:budget_zero', 'plan:budget_large',
    'fault:operator', 'fault:root_identity', 'fault:root_volume', 'fault:path',
    'fault:alias', 'fault:claim_collision', 'fault:claim_write', 'fault:claim_flush',
    'fault:claim_bytes', 'fault:unexpected_root', 'fault:unexpected_runtime',
    'fault:unexpected_claim', 'fault:missing_entry', 'fault:duplicate_entry',
    'fault:metadata', 'fault:file_size', 'fault:file_hash', 'fault:pth_rehashed',
    'fault:read_zero', 'fault:read_over', 'fault:read_error', 'fault:trailing',
    'fault:early_expiry', 'fault:late_expiry', 'fault:wall_expiry',
    'security:private_file', 'security:private_directory', 'security:system_owner',
    'security:ancestor_read', 'security:ancestor_sibling_create', 'security:ancestor_deny',
    'security:inherit_only', 'security:untrusted_owner', 'security:trustedinstaller_owner',
    'security:unprotected', 'security:wrong_group', 'security:missing_rule',
    'security:duplicate_sid', 'security:private_read_grant', 'security:private_inherited',
    'security:private_deny', 'security:ancestor_delete', 'security:ancestor_delete_child',
    'security:ancestor_write_dacl', 'security:ancestor_attributes', 'security:ancestor_generic_write',
    'security:ds_delete_child_is_create_bit', 'security:ancestor_write_ea',
    'security:ancestor_write_owner', 'security:ancestor_generic_all',
    'directory:valid', 'directory:dot', 'directory:two', 'directory:odd',
    'directory:oversize', 'directory:zero', 'directory:next', 'directory:unaligned',
    'directory:duplicate', 'directory:bound', 'directory:unsafe',
    'layout:unicode', 'layout:attributes', 'layout:status', 'layout:fileinfo',
    'cap:shorter', 'cap:cannot_extend', 'cap:nan', 'cap:infinite', 'cap:past', 'cap:equal',
    'cap:arrival_consumes', 'cap:hash_consumes', 'cap:copy_consumes', 'cap:wall_expiry_copy',
    'cap:rollback_before_acquire', 'cap:rollback_copy', 'cap:nonfinite_copy',
    'cap:null_files', 'cap:null_clock',
    'copy:fixed_bytes', 'copy:short_reads', 'copy:snapshot_independent', 'copy:no_reopen',
    'copy:max_bytes', 'copy:oversize', 'copy:hash_drift', 'copy:metadata_drift',
    'copy:extra_inventory', 'copy:zero_read', 'copy:overread', 'copy:read_error',
    'copy:unexpected_read', 'copy:trailing', 'copy:post_copy_drift', 'copy:closed',
    'copy:poisoned', 'copy:concurrent', 'lease:reverify_retains',
    'lease:reverify_native_failure_retains', 'lease:poison_no_io', 'lease:dispose_poison_close_failure',
)

HARNESS = r'''
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading.Tasks;
namespace AiAgent.NativeValidator {
    internal sealed class TestClock : IBoundaryClock {
        internal double Time=100; internal long Wall=1000;
        public double Seconds { get { return Time; } }
        public long Unix { get { return Wall; } }
    }
    internal sealed class TestHandle {
        internal string Name; internal bool Closed; internal int Closes,Position;
    }
    internal sealed class TestFiles : IBoundaryFiles {
        internal const string Prefix=@"\\?\Volume{00000000-0000-4000-8000-000000000001}\";
        internal readonly Dictionary<string,byte[]> Data=new Dictionary<string,byte[]>(StringComparer.Ordinal);
        internal readonly Dictionary<string,Stamp> Meta=new Dictionary<string,Stamp>(StringComparer.Ordinal);
        internal readonly List<TestHandle> Handles=new List<TestHandle>();
        internal readonly List<string> Events=new List<string>();
        internal string Fault,WriteMode,ReadMode,ExtraAt,MissingAt,DuplicateAt,CloseFault;
        internal bool Operator=true,ShortReads;
        internal int Writes;
        internal Action<string> Hook;
        ulong next=3;
        internal TestFiles() {
            Meta.Add("@volume",NewStamp(1,Prefix,true,0)); Meta.Add("",NewStamp(2,Prefix+"Anchor",true,0));
            var dirs=new SortedSet<string>(StringComparer.Ordinal); dirs.Add("claims");
            foreach (string name in InstallBoundary.Catalog()) {
                int slash=name.LastIndexOf('/');
                while (slash>0) { dirs.Add(name.Substring(0,slash)); slash=name.LastIndexOf('/',slash-1); }
            }
            foreach (string dir in dirs) Meta.Add(dir,NewStamp(next++,Final(dir),true,0));
            foreach (string name in InstallBoundary.Catalog()) {
                byte[] raw=Encoding.ASCII.GetBytes("INERT NONRUNNABLE MODEL:"+name);
                if (name=="payload/night_shifts/__init__.py" || name=="payload/night_shifts/guest/__init__.py") raw=new byte[0];
                if (name=="runtime/python314._pth") raw=(byte[])InstallBoundary.Pth.Clone();
                if (name=="provision-request.json") raw=Encoding.ASCII.GetBytes("{}\n");
                Data.Add(name,raw); Meta.Add(name,NewStamp(next++,Final(name),false,raw.Length));
            }
        }
        internal static string Final(string name) { return Prefix+"Anchor\\"+name.Replace('/','\\'); }
        static Stamp NewStamp(ulong index,string path,bool dir,long size) {
            return new Stamp {Volume=42,Index=index,Attributes=dir?16u:128u,Links=1,Bytes=size,
                Security="MODEL PRIVATE SECURITY",Private=true,FinalName=path};
        }
        internal static Stamp Copy(Stamp v) {
            return new Stamp {Volume=v.Volume,Index=v.Index,Attributes=v.Attributes,Links=v.Links,Bytes=v.Bytes,
                Security=v.Security,Private=v.Private,FinalName=v.FinalName};
        }
        void Event(string name) {
            Events.Add(name); if (Hook!=null) Hook(name);
            if (name==Fault) throw new InvalidOperationException("SYNTHETIC_NATIVE_CANARY");
        }
        TestHandle NewHandle(string name) { var h=new TestHandle {Name=name}; Handles.Add(h); return h; }
        public void RequireOperator(string sid) {
            Event("operator"); if (!Operator || sid!="S-1-5-21-1-2-3-1001") throw new BoundaryRefused("enabled_operator_required");
        }
        public object Root(string drive) { Event("root"); BoundaryHarness.Check(drive==@"C:\"); return NewHandle("@volume"); }
        public object Open(object parent,string leaf,bool dir) {
            var h=(TestHandle)parent; BoundaryHarness.Check(!h.Closed);
            string name=h.Name=="@volume"?"":(h.Name.Length==0?leaf:h.Name+"/"+leaf);
            Event("open:"+name); BoundaryHarness.Check(Meta.ContainsKey(name));
            BoundaryHarness.Check(((Meta[name].Attributes&16)!=0)==dir); return NewHandle(name);
        }
        public object CreateClaim(object parent) {
            BoundaryHarness.Check(((TestHandle)parent).Name=="claims"); Event("claim");
            const string name="claims/install-attempt.claim";
            if (Meta.ContainsKey(name)) throw new BoundaryRefused("claim_collision_or_create_refused");
            Data.Add(name,new byte[0]); Meta.Add(name,NewStamp(next++,Final(name),false,0)); return NewHandle(name);
        }
        public Stamp Observe(object handle,bool dir,bool ancestor) {
            var h=(TestHandle)handle; BoundaryHarness.Check(!h.Closed); Event("observe:"+h.Name);
            Stamp result=Copy(Meta[h.Name]); result.Private=!ancestor; return result;
        }
        public string[] Names(object handle) {
            var h=(TestHandle)handle; BoundaryHarness.Check(!h.Closed); Event("names:"+h.Name);
            string prefix=h.Name.Length==0?"":h.Name+"/"; var result=new List<string>();
            foreach (string name in Meta.Keys) {
                if (name=="@volume" || name.Length<=prefix.Length || !name.StartsWith(prefix,StringComparison.Ordinal)) continue;
                string tail=name.Substring(prefix.Length); if (tail.IndexOf('/')<0) result.Add(tail);
            }
            if (h.Name==ExtraAt) result.Add("unexpected.pth");
            if (h.Name==MissingAt && result.Count>0) result.RemoveAt(0);
            if (h.Name==DuplicateAt && result.Count>0) result.Add(result[0]); return result.ToArray();
        }
        public void Rewind(object handle) { var h=(TestHandle)handle; Event("rewind:"+h.Name); h.Position=0; }
        public int Read(object handle,byte[] bytes,int count) {
            var h=(TestHandle)handle; BoundaryHarness.Check(!h.Closed); Event("read:"+h.Name);
            if (ReadMode=="zero") return 0; if (ReadMode=="over") return count+1;
            if (ReadMode=="error") throw new BoundaryUnknown("read_unknown");
            int got=Math.Min(count,Data[h.Name].Length-h.Position); if (ShortReads) got=Math.Min(got,3);
            Array.Copy(Data[h.Name],h.Position,bytes,0,got); h.Position+=got; return got;
        }
        public void WriteClaim(object handle,byte[] raw) {
            var h=(TestHandle)handle; Event("write_claim"); Writes++;
            int count=WriteMode=="short"?raw.Length/2:raw.Length;
            Data[h.Name]=new byte[count]; Array.Copy(raw,Data[h.Name],count); Meta[h.Name].Bytes=count; Meta[h.Name].Attributes|=32;
            if (WriteMode=="corrupt") Data[h.Name][0]^=1;
            if (WriteMode=="short") throw new BoundaryUnknown("claim_write_unknown");
            if (WriteMode=="flush") throw new BoundaryUnknown("claim_flush_unknown");
        }
        public void Close(object handle) {
            var h=(TestHandle)handle; BoundaryHarness.Check(!h.Closed); h.Closed=true; h.Closes++; Events.Add("close:"+h.Name);
            if (h.Name==CloseFault) throw new InvalidOperationException("SYNTHETIC_CLOSE_CANARY");
        }
        internal void AllClosed() { foreach (TestHandle h in Handles) BoundaryHarness.Check(h.Closed && h.Closes==1); }
    }
    internal sealed class Env {
        internal TestFiles Api=new TestFiles(); internal TestClock Clock=new TestClock();
        internal Dictionary<string,FilePin> Pins=new Dictionary<string,FilePin>(StringComparer.Ordinal);
        internal Env() { foreach (KeyValuePair<string,byte[]> p in Api.Data) Pins.Add(p.Key,new FilePin(p.Value.Length,InstallBoundary.Sha(p.Value))); }
        internal InstallBoundaryPlan Plan(string root=@"C:\Anchor",uint volume=42,ulong index=2,
            string id="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",string approval="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            string sid="S-1-5-21-1-2-3-1001",long until=1900) {
            return new InstallBoundaryPlan(root,volume,index,id,approval,sid,until,Pins);
        }
        internal InstallBoundary Gate() { return new InstallBoundary(Plan(),900,Api,Clock); }
    }
    public static class BoundaryHarness {
        internal static void Check(bool yes) { if (!yes) throw new Exception("MODEL_ASSERTION"); }
        static void Refused(Action action,string label=null) { Expect<BoundaryRefused>(action,label); }
        static void Unknown(Action action,string label=null) { Expect<BoundaryUnknown>(action,label); }
        static void Expect<T>(Action action,string label) where T:Exception {
            try { action(); } catch (Exception ex) { Check(ex is T && (label==null || ex.Message==label)); return; }
            throw new Exception("MODEL_EXPECTED_REFUSAL");
        }
        static void FailAcquire(Env e,string label=null,bool unknown=false) {
            InstallBoundary gate=e.Gate();
            if (unknown) Unknown(delegate { gate.Acquire(); },label); else Refused(delegate { gate.Acquire(); },label);
            e.Api.AllClosed(); Refused(delegate { gate.Acquire(); },"one_shot");
        }
        static void PlanCase(string test) {
            var e=new Env(); Action run=delegate { new InstallBoundary(e.Plan(),900,e.Api,e.Clock); };
            switch (test) {
                case "null": run=delegate { new InstallBoundary(null,900,e.Api,e.Clock); }; break;
                case "missing": e.Pins.Remove("runtime/python.exe"); break;
                case "extra": e.Pins.Add("runtime/evil.pth",new FilePin(1,new string('a',64))); break;
                case "case_alias": e.Pins.Add("runtime/PYTHON.exe",e.Pins["runtime/python.exe"]); break;
                case "null_pin": e.Pins["runtime/python.exe"]=null; break;
                case "negative_size": e.Pins["runtime/python.exe"]=new FilePin(-1,new string('a',64)); break;
                case "oversize": e.Pins["runtime/python.exe"]=new FilePin(InstallBoundary.MaxFileBytes+1,new string('a',64)); break;
                case "total_size":
                    foreach (string n in new string[] {"runtime/python.exe","runtime/pythonw.exe","runtime/python314.dll","runtime/python3.dll"})
                        e.Pins[n]=new FilePin(InstallBoundary.MaxFileBytes,new string('a',64)); break;
                case "digest": e.Pins["runtime/python.exe"]=new FilePin(3,new string('A',64)); break;
                case "empty_noninitializer": e.Pins["runtime/python.exe"]=new FilePin(0,InstallBoundary.Sha(new byte[0])); break;
                case "nonempty_initializer": e.Pins["payload/night_shifts/__init__.py"]=new FilePin(1,new string('a',64)); break;
                case "pth_size": e.Pins["runtime/python314._pth"]=new FilePin(1,new string('a',64)); break;
                case "request_size": e.Pins["provision-request.json"]=new FilePin(32769,new string('a',64)); break;
                case "root": run=delegate { new InstallBoundary(e.Plan(root:"relative"),900,e.Api,e.Clock); }; break;
                case "dot": run=delegate { new InstallBoundary(e.Plan(root:@"C:\Anchor\..\x"),900,e.Api,e.Clock); }; break;
                case "ads": run=delegate { new InstallBoundary(e.Plan(root:@"C:\Anchor:ads"),900,e.Api,e.Clock); }; break;
                case "unc": run=delegate { new InstallBoundary(e.Plan(root:@"\\host\anchor"),900,e.Api,e.Clock); }; break;
                case "reserved": run=delegate { new InstallBoundary(e.Plan(root:@"C:\NUL.txt"),900,e.Api,e.Clock); }; break;
                case "trailing": run=delegate { new InstallBoundary(e.Plan(root:@"C:\Anchor "),900,e.Api,e.Clock); }; break;
                case "index": run=delegate { new InstallBoundary(e.Plan(index:0),900,e.Api,e.Clock); }; break;
                case "id": run=delegate { new InstallBoundary(e.Plan(id:new string('A',32)),900,e.Api,e.Clock); }; break;
                case "approval": run=delegate { new InstallBoundary(e.Plan(approval:"self-approved"),900,e.Api,e.Clock); }; break;
                case "operator": run=delegate { new InstallBoundary(e.Plan(sid:"S-1-5-18"),900,e.Api,e.Clock); }; break;
                case "expired": e.Clock.Wall=1900; break;
                case "window": e.Clock.Wall=-90000; break;
                case "budget_zero": run=delegate { new InstallBoundary(e.Plan(),0,e.Api,e.Clock); }; break;
                case "budget_large": run=delegate { new InstallBoundary(e.Plan(),901,e.Api,e.Clock); }; break;
                default: throw new Exception("UNKNOWN_MODEL_CASE");
            }
            Refused(run); Check(e.Api.Events.Count==0);
        }
        static void FaultCase(string test) {
            var e=new Env(); bool unknown=false; string label=null; const string file="runtime/python.exe";
            switch (test) {
                case "operator": e.Api.Operator=false; label="enabled_operator_required"; break;
                case "root_identity": e.Api.Meta[""].Index=9999; label="root_identity"; break;
                case "root_volume": e.Api.Meta[""].Volume=99; label="path_drift"; break;
                case "path": e.Api.Meta["runtime"].FinalName+="-changed"; label="path_drift"; break;
                case "alias": e.Api.Meta[file].Index=e.Api.Meta["claims"].Index; label="alias"; break;
                case "claim_collision": e.Api.Data.Add("claims/install-attempt.claim",new byte[0]);
                    e.Api.Meta.Add("claims/install-attempt.claim",TestFiles.Copy(e.Api.Meta[file])); label="claim_collision_or_create_refused"; break;
                case "claim_write": e.Api.WriteMode="short"; unknown=true; label="claim_write_unknown"; break;
                case "claim_flush": e.Api.WriteMode="flush"; unknown=true; label="claim_flush_unknown"; break;
                case "claim_bytes": e.Api.WriteMode="corrupt"; label="fixed_bytes"; break;
                case "unexpected_root": e.Api.ExtraAt=""; label="unexpected_entry"; break;
                case "unexpected_runtime": e.Api.ExtraAt="runtime"; label="unexpected_entry"; break;
                case "unexpected_claim": e.Api.ExtraAt="claims"; label="unexpected_entry"; break;
                case "missing_entry": e.Api.MissingAt="runtime"; label="unexpected_entry"; break;
                case "duplicate_entry": e.Api.DuplicateAt="runtime"; label="unexpected_entry"; break;
                case "metadata": e.Api.Hook=delegate(string at) { if (at=="read:"+file) e.Api.Meta[file].Security+="CHANGED"; }; label="metadata_drift"; break;
                case "file_size": e.Api.Meta[file].Bytes++; label="file_size"; break;
                case "file_hash": e.Api.Data[file][0]^=1; label="file_hash"; break;
                case "pth_rehashed": byte[] pth=e.Api.Data["runtime/python314._pth"]; pth[0]^=1;
                    e.Pins["runtime/python314._pth"]=new FilePin(pth.Length,InstallBoundary.Sha(pth)); label="fixed_bytes"; break;
                case "read_zero": e.Api.ReadMode="zero"; label="read_extent"; break;
                case "read_over": e.Api.ReadMode="over"; label="read_extent"; break;
                case "read_error": e.Api.ReadMode="error"; unknown=true; label="read_unknown"; break;
                case "trailing": byte[] old=e.Api.Data[file],extra=new byte[e.Api.Data[file].Length+1];
                    Array.Copy(old,extra,old.Length); e.Api.Data[file]=extra; label="read_extent"; break;
                case "early_expiry": InstallBoundary gate=e.Gate(); e.Clock.Time=1001;
                    Refused(delegate { gate.Acquire(); },"deadline"); Check(e.Api.Events.Count==0); return;
                case "late_expiry": e.Api.Hook=delegate(string at) { if (at=="read:"+file) e.Clock.Time=1001; }; label="deadline"; break;
                case "wall_expiry": e.Api.Hook=delegate(string at) { if (at=="write_claim") e.Clock.Wall=1900; }; label="deadline"; break;
                default: throw new Exception("UNKNOWN_MODEL_CASE");
            }
            FailAcquire(e,label,unknown);
        }
        static string FileRight(uint mask,string sid) {
            // SDDL rights mnemonics can name DIRECTORY-SERVICE bits. Require
            // the actual NTFS mask, and assert what the CLR parser produced.
            string text="O:BAG:BAD:(A;;0x"+mask.ToString("x8")+";;;"+sid+")";
            var parsed=new System.Security.AccessControl.RawSecurityDescriptor(text);
            var ace=(System.Security.AccessControl.CommonAce)parsed.DiscretionaryAcl[0];
            Check(unchecked((uint)ace.AccessMask)==mask); return text;
        }
        static void SecurityCase(string test) {
            string user="S-1-5-21-1-2-3-1001",text=BoundarySecurity.ClaimSddl; bool dir=false,ancestor=false,valid=false;
            switch (test) {
                case "private_file": valid=true; break;
                case "private_directory": text="O:BAG:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)"; dir=true; valid=true; break;
                case "system_owner": text="O:SYG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)"; valid=true; break;
                case "ancestor_read": text="O:BAG:BAD:(A;;FRFX;;;"+user+")"; ancestor=dir=true; valid=true; break;
                case "ancestor_sibling_create": text="O:BAG:BAD:(A;;0x00000006;;;"+user+")"; ancestor=dir=true; valid=true; break;
                case "ancestor_deny": text="O:BAG:BAD:(D;;FA;;;"+user+")"; ancestor=dir=true; valid=true; break;
                case "inherit_only": text="O:BAG:BAD:(A;CIIO;FA;;;"+user+")"; ancestor=dir=true; valid=true; break;
                case "untrusted_owner": text="O:"+user+"G:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)"; break;
                case "trustedinstaller_owner": text="O:S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464G:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)"; break;
                case "unprotected": text="O:BAG:BAD:(A;;FA;;;SY)(A;;FA;;;BA)"; break;
                case "wrong_group": text="O:BAG:SYD:P(A;;FA;;;SY)(A;;FA;;;BA)"; break;
                case "missing_rule": text="O:BAG:BAD:P(A;;FA;;;BA)"; break;
                case "duplicate_sid": text="O:BAG:BAD:P(A;;FA;;;BA)(A;;FA;;;BA)"; break;
                case "private_read_grant": text="O:BAG:BAD:P(A;;FR;;;SY)(A;;FA;;;BA)"; break;
                case "private_inherited": text="O:BAG:BAD:P(A;ID;FA;;;SY)(A;;FA;;;BA)"; break;
                case "private_deny": text="O:BAG:BAD:P(D;;FA;;;SY)(A;;FA;;;BA)"; break;
                case "ancestor_delete": text=FileRight(0x00010000u,user); ancestor=dir=true; break;
                case "ancestor_delete_child": text=FileRight(0x00000040u,user); ancestor=dir=true; break;
                case "ancestor_write_dacl": text=FileRight(0x00040000u,user); ancestor=dir=true; break;
                case "ancestor_attributes": text=FileRight(0x00000100u,user); ancestor=dir=true; break;
                case "ancestor_generic_write": text=FileRight(0x40000000u,user); ancestor=dir=true; break;
                case "ancestor_write_ea": text=FileRight(0x00000010u,user); ancestor=dir=true; break;
                case "ancestor_write_owner": text=FileRight(0x00080000u,user); ancestor=dir=true; break;
                case "ancestor_generic_all": text=FileRight(0x10000000u,user); ancestor=dir=true; break;
                case "ds_delete_child_is_create_bit":
                    text="O:BAG:BAD:(A;;DC;;;"+user+")";
                    var parsed=new System.Security.AccessControl.RawSecurityDescriptor(text);
                    var ace=(System.Security.AccessControl.CommonAce)parsed.DiscretionaryAcl[0];
                    Check(ace.AccessMask==2); ancestor=dir=valid=true; break;
                default: throw new Exception("UNKNOWN_MODEL_CASE");
            }
            Action run=delegate { BoundarySecurity.Check(text,dir,ancestor); }; if (valid) run(); else Refused(run);
        }
        static byte[] Record(string name) {
            byte[] result=new byte[256],raw=Encoding.Unicode.GetBytes(name);
            BitConverter.GetBytes((uint)raw.Length).CopyTo(result,60); raw.CopyTo(result,104); return result;
        }
        static void DirectoryCase(string test) {
            byte[] bytes=Record("x"); var names=new List<string>(); bool valid=false;
            switch (test) {
                case "valid": valid=true; break;
                case "dot": bytes=Record("."); valid=true; break;
                case "two": BitConverter.GetBytes(112u).CopyTo(bytes,0); byte[] second=Record("y");
                    Array.Copy(second,0,bytes,112,144); valid=true; break;
                case "odd": BitConverter.GetBytes(3u).CopyTo(bytes,60); break;
                case "oversize": BitConverter.GetBytes(242u).CopyTo(bytes,60); break;
                case "zero": BitConverter.GetBytes(0u).CopyTo(bytes,60); break;
                case "next": BitConverter.GetBytes(8u).CopyTo(bytes,0); break;
                case "unaligned": BitConverter.GetBytes(111u).CopyTo(bytes,0); break;
                case "duplicate": names.Add("x"); break;
                case "bound": for (int i=0;i<128;i++) names.Add(i.ToString()); break;
                case "unsafe": bytes=Record("bad:name"); break;
                default: throw new Exception("UNKNOWN_MODEL_CASE");
            }
            Action run=delegate { WindowsBoundaryFiles.DecodeNames(bytes,names); };
            if (valid) { run(); Check(names.Count==(test=="dot"?0:(test=="two"?2:1))); } else Refused(run);
        }
        static void AllHeld(Env e) {
            foreach (TestHandle h in e.Api.Handles) Check(!h.Closed && h.Closes==0);
        }
        static void PoisonNoIo(Env e,ImportClosureLease lease) {
            int events=e.Api.Events.Count;
            Refused(delegate { lease.Reverify(); },"lease_poisoned");
            Refused(delegate { lease.CopyWorkerRequest(); },"lease_poisoned");
            Check(events==e.Api.Events.Count); AllHeld(e);
        }
        static void CapCase(string name) {
            var e=new Env(); double bound=105; int seconds=900;
            switch (name) {
                case "nan": bound=Double.NaN; break;
                case "infinite": bound=Double.PositiveInfinity; break;
                case "past": bound=99; break;
                case "equal": bound=100; break;
                case "cannot_extend": bound=5000; seconds=10; break;
                case "null_files":
                    Refused(delegate { new InstallBoundary(e.Plan(),900,null,e.Clock,105); },"plan");
                    Check(e.Api.Events.Count==0); return;
                case "null_clock":
                    Refused(delegate { new InstallBoundary(e.Plan(),900,e.Api,null,105); },"plan");
                    Check(e.Api.Events.Count==0); return;
            }
            if (name=="nan" || name=="infinite" || name=="past" || name=="equal") {
                Refused(delegate { new InstallBoundary(e.Plan(),seconds,e.Api,e.Clock,bound); },"shared_deadline");
                Check(e.Api.Events.Count==0); return;
            }
            var gate=new InstallBoundary(e.Plan(),seconds,e.Api,e.Clock,bound);
            if (name=="arrival_consumes" || name=="rollback_before_acquire") {
                e.Clock.Time=name=="arrival_consumes"?105:99;
                Refused(delegate { gate.Acquire(); },"deadline"); Check(e.Api.Events.Count==0);
                Refused(delegate { gate.Acquire(); },"one_shot"); return;
            }
            if (name=="hash_consumes") {
                e.Api.Hook=delegate(string at) { if (at=="read:runtime/python.exe") e.Clock.Time=105; };
                Refused(delegate { gate.Acquire(); },"deadline"); e.Api.AllClosed();
                Check(e.Api.Writes==1); Refused(delegate { gate.Acquire(); },"one_shot"); return;
            }
            if (name=="shorter" || name=="cannot_extend") e.Clock.Time=name=="shorter"?104:109;
            ImportClosureLease lease=gate.Acquire();
            switch (name) {
                case "shorter":
                case "cannot_extend":
                    Check(Encoding.ASCII.GetString(lease.CopyWorkerRequest())=="{}\n");
                    e.Clock.Time=name=="shorter"?105:110; break;
                case "copy_consumes":
                    int rewinds=0;
                    e.Api.Hook=delegate(string at) {
                        if (at=="rewind:provision-request.json") rewinds++;
                        if (at=="read:provision-request.json" && rewinds==2) e.Clock.Time=105;
                    }; break;
                case "wall_expiry_copy": e.Clock.Wall=1900; break;
                case "rollback_copy": e.Clock.Time=99; break;
                case "nonfinite_copy": e.Clock.Time=Double.NaN; break;
                default: throw new Exception("UNKNOWN_MODEL_CAP");
            }
            Refused(delegate { lease.CopyWorkerRequest(); },"deadline");
            PoisonNoIo(e,lease); lease.Dispose(); e.Api.AllClosed();
        }
        static void WorkerLeaseCase(string name) {
            var e=new Env(); const string request="provision-request.json";
            if (name=="copy:max_bytes" || name=="copy:oversize") {
                byte[] bytes=Encoding.ASCII.GetBytes(new string('w',name=="copy:max_bytes"?8192:8193));
                e.Api.Data[request]=bytes; e.Api.Meta[request].Bytes=bytes.Length;
                e.Pins[request]=new FilePin(bytes.Length,InstallBoundary.Sha(bytes));
            }
            InstallBoundary gate=e.Gate(); ImportClosureLease lease=gate.Acquire();
            int count=e.Api.Handles.Count,start=e.Api.Events.Count;
            switch (name) {
                case "copy:fixed_bytes":
                case "copy:short_reads":
                case "copy:snapshot_independent":
                case "copy:no_reopen":
                case "copy:max_bytes":
                    if (name=="copy:short_reads") e.Api.ShortReads=true;
                    byte[] copy=lease.CopyWorkerRequest();
                    Check(copy.Length==e.Pins[request].Bytes && InstallBoundary.Sha(copy)==e.Pins[request].Sha256);
                    Check(!Object.ReferenceEquals(copy,e.Api.Data[request]));
                    if (name=="copy:snapshot_independent") {
                        copy[0]^=1; byte[] again=lease.CopyWorkerRequest();
                        Check(InstallBoundary.Sha(again)==e.Pins[request].Sha256 && !Object.ReferenceEquals(copy,again));
                    }
                    Check(e.Api.Handles.Count==count && e.Api.Writes==1);
                    for (int i=start;i<e.Api.Events.Count;i++) {
                        string at=e.Api.Events[i];
                        Check(!at.StartsWith("open:",StringComparison.Ordinal) && at!="root" && at!="claim" && at!="operator" && at!="write_claim");
                    }
                    AllHeld(e); lease.Dispose(); e.Api.AllClosed(); return;
                case "copy:closed":
                    lease.Dispose(); e.Api.AllClosed(); start=e.Api.Events.Count;
                    Refused(delegate { lease.CopyWorkerRequest(); },"lease_closed");
                    Check(start==e.Api.Events.Count); return;
                case "copy:concurrent":
                    Func<byte[]> run=delegate { return lease.CopyWorkerRequest(); };
                    Task<byte[]> a=Task.Run(run),b=Task.Run(run); Task.WaitAll(a,b);
                    Check(InstallBoundary.Sha(a.Result)==e.Pins[request].Sha256 &&
                        InstallBoundary.Sha(b.Result)==e.Pins[request].Sha256 && !Object.ReferenceEquals(a.Result,b.Result));
                    AllHeld(e); lease.Dispose(); e.Api.AllClosed(); return;
                case "lease:reverify_native_failure_retains":
                    e.Api.Fault="read:runtime/python.exe";
                    Unknown(delegate { lease.Reverify(); },"boundary_unknown");
                    PoisonNoIo(e,lease); lease.Dispose(); e.Api.AllClosed(); return;
                case "lease:reverify_retains":
                case "lease:poison_no_io":
                case "lease:dispose_poison_close_failure":
                case "copy:poisoned":
                    e.Api.Data["runtime/python.exe"][0]^=1;
                    Refused(delegate { lease.Reverify(); },"file_hash"); PoisonNoIo(e,lease);
                    if (name=="lease:dispose_poison_close_failure") {
                        e.Api.CloseFault=request; Unknown(delegate { lease.Dispose(); },"close_unknown");
                        start=e.Api.Events.Count; lease.Dispose(); Check(start==e.Api.Events.Count);
                        Refused(delegate { lease.CopyWorkerRequest(); },"lease_closed");
                    } else lease.Dispose();
                    e.Api.AllClosed(); return;
            }
            string label="file_hash"; bool unknown=false;
            switch (name) {
                case "copy:oversize": label="worker_request_size"; break;
                case "copy:hash_drift": e.Api.Data[request][0]^=1; break;
                case "copy:metadata_drift": e.Api.Meta[request].Security+="CHANGED"; label="metadata_drift"; break;
                case "copy:extra_inventory": e.Api.ExtraAt="runtime"; label="unexpected_entry"; break;
                case "copy:zero_read":
                case "copy:overread":
                case "copy:read_error":
                case "copy:unexpected_read":
                case "copy:trailing":
                case "copy:post_copy_drift":
                    int rewinds=0;
                    e.Api.Hook=delegate(string at) {
                        if (at!="rewind:"+request) return;
                        rewinds++;
                        if (rewinds==2) {
                            if (name=="copy:zero_read") e.Api.ReadMode="zero";
                            if (name=="copy:overread") e.Api.ReadMode="over";
                            if (name=="copy:read_error") e.Api.ReadMode="error";
                            if (name=="copy:unexpected_read") e.Api.Fault="read:"+request;
                            if (name=="copy:trailing") {
                                byte[] raw=e.Api.Data[request],extra=new byte[e.Api.Data[request].Length+1];
                                Array.Copy(raw,extra,raw.Length); e.Api.Data[request]=extra;
                            }
                        }
                        if (rewinds==3 && name=="copy:post_copy_drift") e.Api.Data["runtime/python.exe"][0]^=1;
                    };
                    if (name=="copy:read_error") { unknown=true; label="read_unknown"; }
                    else if (name=="copy:unexpected_read") { unknown=true; label="boundary_unknown"; }
                    else if (name!="copy:post_copy_drift") label="read_extent";
                    break;
                default: throw new Exception("UNKNOWN_MODEL_WORKER");
            }
            if (unknown) Unknown(delegate { lease.CopyWorkerRequest(); },label);
            else Refused(delegate { lease.CopyWorkerRequest(); },label);
            Check(e.Api.Handles.Count==count && e.Api.Writes==1); PoisonNoIo(e,lease);
            lease.Dispose(); e.Api.AllClosed();
        }
        static void Scenario(string name) {
            if (name.StartsWith("cap:",StringComparison.Ordinal)) { CapCase(name.Substring(4)); return; }
            if (name.StartsWith("copy:",StringComparison.Ordinal) || name.StartsWith("lease:",StringComparison.Ordinal)) {
                WorkerLeaseCase(name); return;
            }
            if (name.StartsWith("plan:",StringComparison.Ordinal)) { PlanCase(name.Substring(5)); return; }
            if (name.StartsWith("fault:",StringComparison.Ordinal)) { FaultCase(name.Substring(6)); return; }
            if (name.StartsWith("security:",StringComparison.Ordinal)) { SecurityCase(name.Substring(9)); return; }
            if (name.StartsWith("directory:",StringComparison.Ordinal)) { DirectoryCase(name.Substring(10)); return; }
            if (name.StartsWith("layout:",StringComparison.Ordinal)) {
                Check(IntPtr.Size==8);
                switch (name.Substring(7)) {
                    case "unicode": Check(Marshal.SizeOf(typeof(WindowsBoundaryFiles.UnicodeName))==16 && Marshal.OffsetOf(typeof(WindowsBoundaryFiles.UnicodeName),"Buffer").ToInt32()==8); break;
                    case "attributes": Check(Marshal.SizeOf(typeof(WindowsBoundaryFiles.ObjectAttributes))==48 && Marshal.OffsetOf(typeof(WindowsBoundaryFiles.ObjectAttributes),"Security").ToInt32()==32); break;
                    case "status": Check(Marshal.SizeOf(typeof(WindowsBoundaryFiles.IoStatus))==16); break;
                    case "fileinfo": Check(Marshal.SizeOf(typeof(WindowsBoundaryFiles.FileInfo))==52); break;
                    default: throw new Exception("UNKNOWN_MODEL_CASE");
                }
                return;
            }
            var e=new Env(); InstallBoundary gate=e.Gate();
            switch (name) {
                case "construct_no_io": Check(e.Api.Events.Count==0); return;
                case "success_retains_all_handles":
                    using (ImportClosureLease lease=gate.Acquire()) {
                        Check(e.Api.Handles.Count==InstallBoundary.Catalog().Count+11);
                        foreach (TestHandle h in e.Api.Handles) Check(!h.Closed); Check(e.Api.Writes==1);
                    } e.Api.AllClosed(); return;
                case "claim_before_hash":
                    using (ImportClosureLease lease=gate.Acquire()) {
                        int write=e.Api.Events.IndexOf("write_claim"); Check(write>e.Api.Events.IndexOf("claim"));
                        foreach (string file in InstallBoundary.Catalog()) Check(e.Api.Events.IndexOf("read:"+file)>write);
                    } e.Api.AllClosed(); return;
                case "claim_rehash_and_reverify":
                    using (ImportClosureLease lease=gate.Acquire()) { int count=e.Api.Handles.Count; lease.Reverify(); Check(count==e.Api.Handles.Count && e.Api.Writes==1); }
                    e.Api.AllClosed(); return;
                case "claim_binds_inventory": byte[] before=gate.ClaimBytes(); e.Pins["runtime/python.exe"]=new FilePin(1,new string('c',64));
                    Check(InstallBoundary.Sha(before)!=InstallBoundary.Sha(e.Gate().ClaimBytes())); return;
                case "plan_copies_dictionary": byte[] claim=gate.ClaimBytes(); e.Pins.Clear();
                    Check(InstallBoundary.Sha(claim)==InstallBoundary.Sha(gate.ClaimBytes())); return;
                case "short_successful_reads": e.Api.ShortReads=true; using (gate.Acquire()) { } e.Api.AllClosed(); return;
                case "one_shot_success": using (gate.Acquire()) { } Refused(delegate { gate.Acquire(); },"one_shot"); e.Api.AllClosed(); return;
                case "one_shot_failure": e.Api.Operator=false; FailAcquire(e); return;
                case "one_shot_concurrent":
                    Func<int> attempt=delegate { try { using (gate.Acquire()) { } return 1; } catch (BoundaryRefused ex) { Check(ex.Message=="one_shot"); return 0; } };
                    Task<int> a=Task.Run(attempt),b=Task.Run(attempt); Task.WaitAll(a,b); Check(a.Result+b.Result==1 && e.Api.Writes==1); e.Api.AllClosed(); return;
                case "new_object_cannot_retry":
                case "new_id_cannot_retry":
                    e.Api.Data["runtime/python.exe"][0]^=1; FailAcquire(e,"file_hash");
                    InstallBoundaryPlan p=name=="new_id_cannot_retry"?e.Plan(id:new string('c',32)):e.Plan();
                    var retry=new InstallBoundary(p,900,e.Api,e.Clock); Refused(delegate { retry.Acquire(); },"claim_collision_or_create_refused"); e.Api.AllClosed(); return;
                case "closed_lease": ImportClosureLease done=gate.Acquire(); done.Dispose(); done.Dispose();
                    Refused(delegate { done.Reverify(); },"lease_closed"); e.Api.AllClosed(); return;
                case "directory_size_not_identity":
                    using (ImportClosureLease lease=gate.Acquire()) { e.Api.Meta["runtime"].Bytes=123456; lease.Reverify(); } e.Api.AllClosed(); return;
                case "reverify_failure_terminal": ImportClosureLease failed=gate.Acquire(); e.Api.Data["runtime/python.exe"][0]^=1;
                    Refused(delegate { failed.Reverify(); },"file_hash"); AllHeld(e);
                    PoisonNoIo(e,failed); failed.Dispose(); e.Api.AllClosed(); return;
                case "close_failure_terminal": ImportClosureLease uncertain=gate.Acquire(); e.Api.CloseFault="runtime/python.exe";
                    Unknown(delegate { uncertain.Dispose(); },"close_unknown"); e.Api.AllClosed(); uncertain.Dispose(); return;
                case "all_closes_attempted": e.Api.ReadMode="error"; e.Api.CloseFault="claims/install-attempt.claim";
                    Unknown(delegate { gate.Acquire(); },"close_unknown"); e.Api.AllClosed(); return;
                case "native_text_sanitized": e.Api.Fault="read:runtime/python.exe";
                    Unknown(delegate { gate.Acquire(); },"boundary_unknown"); e.Api.AllClosed(); return;
                case "claim_json_not_acceptance":
                    using (gate.Acquire()) { string text=Encoding.ASCII.GetString(e.Api.Data["claims/install-attempt.claim"]);
                        Check(text.Contains("install_attempt_consumed_not_acceptance") && !text.Contains("\"accepted\"") && text.Length<1024); } return;
                default: throw new Exception("UNKNOWN_MODEL_CASE");
            }
        }
        public static string[] RunAll() {
            string[] cases=__CASES__; var result=new List<string>();
            foreach (string name in cases) {
                try { Scenario(name); result.Add(name+"|PASS"); }
                catch (Exception ex) { result.Add(name+"|FAIL|"+ex.GetType().Name+"|"+ex.Message); }
            }
            return result.ToArray();
        }
    }
}
'''


def _quote(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


@pytest.fixture(scope='module')
def models(tmp_path_factory):
    if os.name != 'nt':
        pytest.skip('requires native Windows CLR compiler; not a native-boundary success')
    exe = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    assert exe.is_file(), 'required Windows model compiler unavailable'
    harness = tmp_path_factory.mktemp('validator-preimport-model') / 'models.cs'
    cases = 'new string[] {' + ','.join(json.dumps(n) for n in SCENARIOS) + '}'
    harness.write_text(HARNESS.replace('__CASES__', cases), encoding='utf-8')
    script = (
        "$ErrorActionPreference='Stop'; "
        f"Add-Type -Path @({_quote(CORE)},{_quote(WINDOWS)},{_quote(harness)}) -ErrorAction Stop; "
        "[AiAgent.NativeValidator.BoundaryHarness]::RunAll()"
    )
    encoded = base64.b64encode(script.encode('utf-16le')).decode('ascii')
    result = subprocess.run(
        [str(exe), '-NoLogo', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
        capture_output=True, text=True, timeout=25, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    observations = {}
    for line in result.stdout.splitlines():
        key, separator, value = line.partition('|')
        assert separator and key not in observations, line
        observations[key] = value
    assert set(observations) == set(SCENARIOS)
    return observations


@pytest.mark.parametrize('scenario', SCENARIOS)
def test_preimport_body_clr_models(models, scenario):
    assert models[scenario] == 'PASS'


def _array(name):
    found = re.search(rf'\b{name}\s*=\s*\{{([^}}]+)\}};', CORE.read_text(encoding='utf-8'))
    assert found is not None
    return re.findall(r'"([^"]+)"', found.group(1))


def test_independent_preimport_catalog_matches_exact_host_closure():
    runtime, code, codec = (_array(n) for n in ('RuntimeNames', 'CodeNames', 'CodecNames'))
    assert len(runtime) == len(set(runtime)) == 37
    assert len(code) == len(set(code)) == 29
    assert len(codec) == len(set(codec)) == 17
    assert set(runtime) == set(deployment.RUNTIME_NAMES)
    assert {'night_shifts/' + n for n in code} == set(deployment.CODE_NAMES)
    assert set(codec) == set(deployment.CODEC_FILES)
    assert not any('install_boundary' in n or n.endswith('.cs') for n in deployment.BUNDLE_NAMES)


def test_worker_copy_uses_only_held_fixed_leaf_and_reverifies_complete_closure():
    text = CORE.read_text(encoding='utf-8')
    assert 'public byte[] CopyWorkerRequest()' in text
    assert 'return owner.CopyWorkerRequest();' in text
    assert 'Hash(tree["provision-request.json"],pin,null,copy);' in text
    method = text[text.index('        internal byte[] CopyWorkerRequest()'):text.index('        internal void CloseAll()')]
    assert method.count('Reverify();') == 2
    for forbidden in ('api.Open(', 'api.Root(', 'api.CreateClaim(', 'Json', 'File.Read', 'new Windows'):
        assert forbidden not in method
    from night_shifts import bootstrap_native_install_request as profile
    from night_shifts import bootstrap_native_provision as worker
    limit = re.search(r'const int MaxWorkerRequestBytes=(\d+);', text)
    assert limit and int(limit[1]) == profile.MAX_WORKER_BYTES == worker._MAX_WORKER_BYTES == 8192


def test_import_lease_poison_never_automatically_closes_or_rearms():
    text = CORE.read_text(encoding='utf-8')
    lease = text[text.index('    public sealed class ImportClosureLease'):text.index('    public sealed class InstallBoundary {')]
    verify_and_copy = lease[lease.index('        public void Reverify()'):lease.index('        public void Dispose()')]
    assert 'CloseAll' not in verify_and_copy and 'owner=null' not in verify_and_copy
    assert 'if (poisoned) throw new BoundaryRefused("lease_poisoned");' in text
    assert text.count('catch (BoundaryRefused) { poisoned=true; throw; }') == 2
    assert 'poisoned=false' not in text and '~ImportClosureLease' not in text


def test_import_deadline_cap_is_internal_shorten_only_and_detects_rollback():
    text = CORE.read_text(encoding='utf-8')
    assert 'double? originalDeadline' in text and 'limit=Math.Min(limit,bound)' in text
    assert 'Double.IsNaN(bound) || Double.IsInfinity(bound) || bound<=now' in text
    assert 'now<lastSeconds' in text and 'deadline=limit;' in text
    assert 'public InstallBoundary(InstallBoundaryPlan value,int budgetSeconds)' in text
    assert 'public InstallBoundary(InstallBoundaryPlan value,int budgetSeconds,double' not in text


def test_candidate_remains_no_entrypoint_launcher_or_production_wiring():
    combined = CORE.read_text(encoding='utf-8') + WINDOWS.read_text(encoding='utf-8')
    assert not re.search(r'\b(?:Main|CreateProcess|ShellExecute|SetSecurityInfo|DeleteFile|TerminateProcess)\s*\(', combined)
    assert 'Process.Start(' not in combined
    assert 'FILE_CREATE' in combined and 'install-attempt.claim' in combined
    assert 'TrustedInstaller' not in combined
    paths = [*(ROOT / 'runtime').glob('*.py'), *(ROOT / 'scripts').glob('*.ps1')]
    for path in paths:
        text = path.read_text(encoding='utf-8-sig')
        assert 'native_validator_install_boundary' not in text
        assert 'native_validator_install_windows' not in text


def test_both_boundary_sources_have_exact_tracking_exceptions():
    lines = (ROOT / '.gitignore').read_text(encoding='utf-8').splitlines()
    assert '/scripts/*' in lines
    for path in (CORE, WINDOWS):
        exception = '!/' + path.relative_to(ROOT).as_posix()
        assert lines.count(exception) == 1
        assert lines.index(exception) > lines.index('/scripts/*')


def test_native_open_contract_and_bounded_directory_protocol_are_fixed():
    text = WINDOWS.read_text(encoding='utf-8')
    assert 'Attributes=0x1040' in text
    assert 'directory?3u:(create?0u:1u),create?2u:1u' in text
    assert 'directory ? 0x200021u : 0x200060u' in text
    assert 'page<128' in text and 'names.Count >= 128' in text
    assert 'first?11:10' in text
    assert 'Marshal.GetLastWin32Error() == 18' in text
    assert 'O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)' in text
    # Scratch releases must precede handle transfer, including failure paths.
    assert text.index('ReleaseLocal(ref descriptor); ReleaseBuffer(ref textBuffer); ReleaseBuffer(ref nameBuffer);') < text.index('IntPtr owned=handle;')
