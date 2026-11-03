"""Unelevated CLR held-target models; never invoke the new native adapter.

Only ordinary compiler/model processes and inert temporary harness text are
used. No guardian/worker executable, private anchor, claim or launch is created.
"""
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / 'scripts/native_validator_launch_boundary.cs'
WINDOWS = ROOT / 'scripts/native_validator_launch_windows.cs'
SCENARIOS = (
    'construct_no_io', 'success_retains_handles', 'hash_all_before_return',
    'reverify_without_reopen', 'short_reads', 'plan_copies_dictionary',
    'one_shot_success', 'one_shot_failure', 'one_shot_concurrent',
    'closed_lease', 'poison_retains_locks', 'poison_dispose_once',
    'directory_size_not_identity', 'all_closes_attempted', 'close_failure_terminal',
    'close_reverse_order', 'native_error_sanitized', 'config_exact',
    'plan:null', 'plan:relative', 'plan:unc', 'plan:dot', 'plan:ads',
    'plan:trailing', 'plan:reserved', 'plan:device', 'plan:long', 'plan:sid',
    'plan:id', 'plan:approval', 'plan:root_zero', 'plan:scratch_zero', 'plan:identity_alias',
    'plan:budget_zero', 'plan:budget_large', 'plan:expired', 'plan:window',
    'plan:files_null', 'plan:missing', 'plan:extra', 'plan:case_alias',
    'plan:pin_null', 'plan:pin_empty', 'plan:pin_large', 'plan:pin_hash',
    'plan:config_changed_rehashed',
    'fault:operator', 'fault:root', 'fault:open', 'fault:observe',
    'fault:root_identity', 'fault:volume', 'fault:scratch_identity',
    'fault:object_alias', 'fault:handle_alias', 'fault:null_handle',
    'fault:path_drift', 'fault:parent_drift', 'fault:security_drift',
    'fault:attribute_drift', 'fault:link_drift', 'fault:extra_root',
    'fault:missing_root', 'fault:duplicate_root', 'fault:case_root',
    'fault:dirty_scratch', 'fault:directory_query', 'fault:rewind',
    'fault:changed_exe', 'fault:size', 'fault:zero_read', 'fault:excess_read',
    'fault:trailing_read', 'fault:read_error', 'fault:expiry_before_open',
    'fault:expiry_in_hash', 'fault:wall_expiry', 'fault:clock_nan',
    'security:private_file', 'security:private_directory', 'security:system_owner',
    'security:untrusted_owner', 'security:trustedinstaller_owner',
    'security:unprotected', 'security:wrong_group', 'security:missing_rule',
    'security:duplicate_sid', 'security:private_extra', 'security:private_inherited',
    'security:private_deny', 'security:ancestor_read', 'security:ancestor_sibling_create',
    'security:ancestor_inherit_only', 'security:ancestor_delete',
    'security:ancestor_delete_child', 'security:ancestor_write_ea',
    'security:ancestor_attributes', 'security:ancestor_write_dacl',
    'security:ancestor_write_owner', 'security:ancestor_generic_write',
    'security:ancestor_generic_all',
    'directory:valid', 'directory:dot', 'directory:two', 'directory:odd',
    'directory:zero', 'directory:oversize', 'directory:next', 'directory:unaligned',
    'directory:duplicate', 'directory:bound', 'directory:unsafe',
    'layout:unicode', 'layout:attributes', 'layout:status', 'layout:fileinfo',
)

HARNESS = r'''
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading.Tasks;
namespace AiAgent.ValidatorLaunch {
    internal sealed class TestClock : ILaunchClock {
        internal double Time=100; internal long Wall=1000;
        public double Seconds { get { return Time; } }
        public long Unix { get { return Wall; } }
    }
    internal sealed class TestHandle {
        internal string Name; internal bool Closed; internal int Closes,Position;
    }
    internal sealed class TestFiles : ILaunchFiles {
        internal readonly TestClock Clock;
        internal readonly Dictionary<string,LaunchStamp> Meta=new Dictionary<string,LaunchStamp>();
        internal readonly Dictionary<string,byte[]> Data=new Dictionary<string,byte[]>();
        internal readonly List<TestHandle> Handles=new List<TestHandle>();
        internal readonly List<string> Events=new List<string>();
        internal Action<string> Hook;
        internal string Fault,CloseFault,ReadMode,RootNames;
        internal bool Operator=true,DirtyScratch,ShortReads,HandleAlias,NullHandle;
        internal TestFiles(TestClock clock) {
            Clock=clock; Add("@",1,true); Add("",2,true); Add("scratch",3,true);
            for (int i=0;i<LaunchBoundary.FileNames.Length;i++) {
                string name=LaunchBoundary.FileNames[i]; Add(name,(ulong)(10+i),false);
                byte[] bytes;
                if (name.EndsWith(".config",StringComparison.Ordinal)) bytes=(byte[])LaunchBoundary.Config.Clone();
                else { bytes=new byte[65537]; for (int j=0;j<bytes.Length;j++) bytes[j]=(byte)(j%251); }
                Data.Add(name,bytes); Meta[name].Bytes=bytes.Length;
            }
        }
        void Add(string name,ulong index,bool dir) {
            string root=@"\\?\Volume{11111111-1111-1111-1111-111111111111}\";
            Meta.Add(name,new LaunchStamp {Volume=77,Index=index,Attributes=dir?16u:32u,Links=1,Bytes=0,
                Security=dir?"MODEL_PRIVATE_DIRECTORY":"MODEL_PRIVATE_FILE",
                FinalName=name=="@"?root:(root+"Private Anchor"+(name==""?"":"\\"+name))});
        }
        void Event(string name) {
            Events.Add(name); if (Hook!=null) Hook(name);
            if (Fault==name) throw new InvalidOperationException("SYNTHETIC_NATIVE_CANARY");
        }
        TestHandle Make(string name) { var h=new TestHandle {Name=name}; Handles.Add(h); return h; }
        static TestHandle Live(object handle) {
            var h=(TestHandle)handle; LaunchHarness.Check(!h.Closed); return h;
        }
        public void RequireOperator(string sid) {
            Event("operator"); if (!Operator) throw new LaunchRefused("enabled_operator_required");
        }
        public object Root(string drive) { LaunchHarness.Check(drive==@"C:\"); Event("root"); return Make("@"); }
        public object Open(object parent,string name,bool directory) {
            TestHandle up=Live(parent); Event("open:"+name);
            string key=up.Name=="@"?"":name;
            if (up.Name=="@") LaunchHarness.Check(name=="Private Anchor" && directory);
            else LaunchHarness.Check(up.Name=="" && (directory==(name=="scratch")));
            if (NullHandle && name=="scratch") return null;
            if (HandleAlias && name=="scratch") return parent;
            return Make(key);
        }
        public LaunchStamp Observe(object handle,bool directory,bool ancestor) {
            TestHandle h=Live(handle); Event("observe:"+h.Name); LaunchStamp s=Meta[h.Name];
            LaunchHarness.Check(directory==((s.Attributes&16)!=0));
            LaunchHarness.Check(ancestor==(h.Name=="@"));
            return new LaunchStamp {Volume=s.Volume,Index=s.Index,Attributes=s.Attributes,Links=s.Links,
                Bytes=s.Bytes,Security=s.Security,FinalName=s.FinalName};
        }
        public string[] Names(object directory) {
            TestHandle h=Live(directory); Event("names:"+h.Name);
            if (h.Name=="scratch") return DirtyScratch?new string[] {"leftover.tmp"}:new string[0];
            LaunchHarness.Check(h.Name=="");
            var names=new List<string>(LaunchBoundary.FileNames); names.Add("scratch");
            if (RootNames=="extra") names.Add("evil.dll");
            if (RootNames=="missing") names.RemoveAt(0);
            if (RootNames=="duplicate") names[0]=names[1];
            if (RootNames=="case") names[0]=names[0].ToUpperInvariant();
            return names.ToArray();
        }
        public void Rewind(object handle) { TestHandle h=Live(handle); Event("rewind:"+h.Name); h.Position=0; }
        public int Read(object handle,byte[] bytes,int count) {
            TestHandle h=Live(handle); Event("read:"+h.Name);
            if (ReadMode=="zero") return 0;
            if (ReadMode=="excess") return count+1;
            byte[] raw=Data[h.Name]; int n=Math.Min(count,raw.Length-h.Position);
            if (ReadMode=="trailing" && n==0) return 1;
            if (ShortReads) n=Math.Min(n,71);
            Array.Copy(raw,h.Position,bytes,0,n); h.Position+=n; return n;
        }
        public void Close(object handle) {
            var h=(TestHandle)handle; LaunchHarness.Check(!h.Closed); h.Closed=true; h.Closes++;
            Event("close:"+h.Name);
            if (h.Name==CloseFault) throw new InvalidOperationException("SYNTHETIC_CLOSE_CANARY");
        }
        internal void AllClosed() { foreach (TestHandle h in Handles) LaunchHarness.Check(h.Closed && h.Closes==1); }
        internal void AllLive() { foreach (TestHandle h in Handles) LaunchHarness.Check(!h.Closed && h.Closes==0); }
    }
    internal sealed class Env {
        internal TestClock Clock=new TestClock(); internal TestFiles Api;
        internal Dictionary<string,LaunchFilePin> Pins=new Dictionary<string,LaunchFilePin>();
        internal Env() {
            Api=new TestFiles(Clock);
            foreach (KeyValuePair<string,byte[]> pair in Api.Data) Pins.Add(pair.Key,new LaunchFilePin(pair.Value.Length,LaunchBoundary.Sha(pair.Value)));
        }
        internal LaunchPlan Plan(string root=@"C:\Private Anchor",uint volume=77,ulong index=2,ulong scratch=3,
            string sid="S-1-5-21-1-2-3-1001",string id="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            string approval="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            long until=1900,int seconds=10) {
            return new LaunchPlan(root,volume,index,scratch,sid,id,approval,until,seconds,Pins);
        }
        internal LaunchBoundary Gate() { return new LaunchBoundary(Plan(),Api,Clock); }
    }
    public static class LaunchHarness {
        internal static void Check(bool yes) { if (!yes) throw new Exception("MODEL_ASSERTION"); }
        static void Failure(Action action,bool unknown=false,string label=null) {
            try { action(); }
            catch (Exception ex) {
                Check((unknown?ex is LaunchUnknown:ex is LaunchRefused) && (label==null || ex.Message==label));
                Check(!ex.Message.Contains("CANARY")); return;
            }
            throw new Exception("MODEL_EXPECTED_FAILURE");
        }
        static void PlanCase(string name) {
            var e=new Env(); Action run=delegate { e.Gate(); };
            string exe=LaunchBoundary.FileNames[0],config=LaunchBoundary.FileNames[1];
            switch (name) {
                case "null": run=delegate { new LaunchBoundary(null,e.Api,e.Clock); }; break;
                case "relative": run=delegate { new LaunchBoundary(e.Plan(root:"relative"),e.Api,e.Clock); }; break;
                case "unc": run=delegate { new LaunchBoundary(e.Plan(root:@"\\host\anchor"),e.Api,e.Clock); }; break;
                case "dot": run=delegate { new LaunchBoundary(e.Plan(root:@"C:\Anchor\..\x"),e.Api,e.Clock); }; break;
                case "ads": run=delegate { new LaunchBoundary(e.Plan(root:@"C:\Anchor:ads"),e.Api,e.Clock); }; break;
                case "trailing": run=delegate { new LaunchBoundary(e.Plan(root:@"C:\Anchor "),e.Api,e.Clock); }; break;
                case "reserved": run=delegate { new LaunchBoundary(e.Plan(root:@"C:\NUL.txt"),e.Api,e.Clock); }; break;
                case "device": run=delegate { new LaunchBoundary(e.Plan(root:@"\\?\C:\Anchor"),e.Api,e.Clock); }; break;
                case "long": run=delegate { new LaunchBoundary(e.Plan(root:@"C:\"+new string('x',200)),e.Api,e.Clock); }; break;
                case "sid": run=delegate { new LaunchBoundary(e.Plan(sid:"S-1-5-18"),e.Api,e.Clock); }; break;
                case "id": run=delegate { new LaunchBoundary(e.Plan(id:new string('A',32)),e.Api,e.Clock); }; break;
                case "approval": run=delegate { new LaunchBoundary(e.Plan(approval:"self-approved"),e.Api,e.Clock); }; break;
                case "root_zero": run=delegate { new LaunchBoundary(e.Plan(index:0),e.Api,e.Clock); }; break;
                case "scratch_zero": run=delegate { new LaunchBoundary(e.Plan(scratch:0),e.Api,e.Clock); }; break;
                case "identity_alias": run=delegate { new LaunchBoundary(e.Plan(scratch:2),e.Api,e.Clock); }; break;
                case "budget_zero": run=delegate { new LaunchBoundary(e.Plan(seconds:0),e.Api,e.Clock); }; break;
                case "budget_large": run=delegate { new LaunchBoundary(e.Plan(seconds:901),e.Api,e.Clock); }; break;
                case "expired": run=delegate { new LaunchBoundary(e.Plan(until:1000),e.Api,e.Clock); }; break;
                case "window": run=delegate { new LaunchBoundary(e.Plan(until:87401),e.Api,e.Clock); }; break;
                case "files_null": run=delegate { new LaunchPlan(@"C:\Private Anchor",77,2,3,"S-1-5-21-1-2-3-1001",new string('a',32),new string('b',64),1900,10,null); }; break;
                case "missing": e.Pins.Remove(exe); break;
                case "extra": e.Pins.Add("evil.dll",e.Pins[exe]); break;
                case "case_alias": e.Pins.Add(exe.ToUpperInvariant(),e.Pins[exe]); e.Pins.Remove(exe); break;
                case "pin_null": e.Pins[exe]=null; break;
                case "pin_empty": e.Pins[exe]=new LaunchFilePin(0,new string('b',64)); break;
                case "pin_large": e.Pins[exe]=new LaunchFilePin(LaunchBoundary.MaxExecutableBytes+1,new string('b',64)); break;
                case "pin_hash": e.Pins[exe]=new LaunchFilePin(1,new string('B',64)); break;
                case "config_changed_rehashed": byte[] changed=(byte[])LaunchBoundary.Config.Clone(); changed[0]^=1;
                    e.Pins[config]=new LaunchFilePin(changed.Length,LaunchBoundary.Sha(changed)); break;
                default: throw new Exception("UNKNOWN_MODEL_CASE");
            }
            Failure(run); Check(e.Api.Events.Count==0);
        }
        static void FaultCase(string name) {
            var e=new Env(); bool unknown=false; string label=null,exe=LaunchBoundary.FileNames[0];
            switch (name) {
                case "operator": e.Api.Operator=false; break;
                case "root": e.Api.Fault="root"; unknown=true; break;
                case "open": e.Api.Fault="open:scratch"; unknown=true; break;
                case "observe": e.Api.Fault="observe:scratch"; unknown=true; break;
                case "root_identity": e.Api.Meta[""].Index=99; label="root_identity"; break;
                case "volume": e.Api.Meta[""].Volume=78; label="path_drift"; break;
                case "scratch_identity": e.Api.Meta["scratch"].Index=99; label="scratch_identity"; break;
                case "object_alias": e.Api.Meta["scratch"].Index=2; label="identity_alias"; break;
                case "handle_alias": e.Api.HandleAlias=true; unknown=true; label="handle_alias"; break;
                case "null_handle": e.Api.NullHandle=true; unknown=true; label="handle_unknown"; break;
                case "path_drift": e.Api.Meta["scratch"].FinalName+="-other"; label="path_drift"; break;
                case "parent_drift": e.Api.Hook=delegate(string at) { if (at=="open:scratch") e.Api.Meta[""].Security="CHANGED"; }; label="metadata_drift"; break;
                case "security_drift": e.Api.Hook=delegate(string at) { if (at=="read:"+exe) e.Api.Meta[exe].Security="CHANGED"; }; label="metadata_drift"; break;
                case "attribute_drift": e.Api.Hook=delegate(string at) { if (at=="read:"+exe) e.Api.Meta[exe].Attributes=0; }; label="metadata_drift"; break;
                case "link_drift": e.Api.Hook=delegate(string at) { if (at=="read:"+exe) e.Api.Meta[exe].Links=2; }; label="metadata_drift"; break;
                case "extra_root": e.Api.RootNames="extra"; label="unexpected_entry"; break;
                case "missing_root": e.Api.RootNames="missing"; label="unexpected_entry"; break;
                case "duplicate_root": e.Api.RootNames="duplicate"; label="unexpected_entry"; break;
                case "case_root": e.Api.RootNames="case"; label="unexpected_entry"; break;
                case "dirty_scratch": e.Api.DirtyScratch=true; label="unexpected_entry"; break;
                case "directory_query": e.Api.Fault="names:"; unknown=true; break;
                case "rewind": e.Api.Fault="rewind:"+exe; unknown=true; break;
                case "changed_exe": e.Api.Data[exe][0]^=1; label="file_hash"; break;
                case "size": e.Api.Meta[exe].Bytes++; label="file_size"; break;
                case "zero_read": e.Api.ReadMode="zero"; label="read_extent"; break;
                case "excess_read": e.Api.ReadMode="excess"; label="read_extent"; break;
                case "trailing_read": e.Api.ReadMode="trailing"; label="read_extent"; break;
                case "read_error": e.Api.Fault="read:"+exe; unknown=true; break;
                case "expiry_before_open": e.Api.Hook=delegate(string at) { if (at=="operator") e.Clock.Time=111; }; label="deadline"; break;
                case "expiry_in_hash": e.Api.Hook=delegate(string at) { if (at=="read:"+exe) e.Clock.Time=111; }; label="deadline"; break;
                case "wall_expiry": e.Api.Hook=delegate(string at) { if (at=="read:"+exe) e.Clock.Wall=1900; }; label="deadline"; break;
                case "clock_nan": e.Api.Hook=delegate(string at) { if (at=="operator") e.Clock.Time=Double.NaN; }; unknown=true; label="clock_unknown"; break;
                default: throw new Exception("UNKNOWN_MODEL_CASE");
            }
            var gate=e.Gate(); Failure(delegate { gate.Acquire(); },unknown,label); e.Api.AllClosed();
            Failure(delegate { gate.Acquire(); },false,"one_shot");
        }
        static void SecurityCase(string name) {
            const string user="S-1-5-21-1-2-3-1001";
            string text="O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)"; bool dir=false,ancestor=false,valid=false;
            uint mask=0;
            switch (name) {
                case "private_file": valid=true; break;
                case "private_directory": text="O:BAG:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)"; dir=true; valid=true; break;
                case "system_owner": text="O:SYG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)"; valid=true; break;
                case "untrusted_owner": text="O:"+user+"G:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)"; break;
                case "trustedinstaller_owner": text="O:S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464G:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)"; break;
                case "unprotected": text="O:BAG:BAD:(A;;FA;;;SY)(A;;FA;;;BA)"; break;
                case "wrong_group": text="O:BAG:SYD:P(A;;FA;;;SY)(A;;FA;;;BA)"; break;
                case "missing_rule": text="O:BAG:BAD:P(A;;FA;;;BA)"; break;
                case "duplicate_sid": text="O:BAG:BAD:P(A;;FA;;;BA)(A;;FA;;;BA)"; break;
                case "private_extra": text="O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;FR;;;"+user+")"; break;
                case "private_inherited": text="O:BAG:BAD:P(A;ID;FA;;;SY)(A;;FA;;;BA)"; break;
                case "private_deny": text="O:BAG:BAD:P(D;;FA;;;SY)(A;;FA;;;BA)"; break;
                case "ancestor_read": text="O:BAG:BAD:(A;;FRFX;;;"+user+")"; ancestor=dir=valid=true; break;
                case "ancestor_sibling_create": mask=6; ancestor=dir=valid=true; break;
                case "ancestor_inherit_only": text="O:BAG:BAD:(A;CIIO;FA;;;"+user+")"; ancestor=dir=valid=true; break;
                case "ancestor_delete": mask=0x10000; break;
                case "ancestor_delete_child": mask=0x40; break;
                case "ancestor_write_ea": mask=0x10; break;
                case "ancestor_attributes": mask=0x100; break;
                case "ancestor_write_dacl": mask=0x40000; break;
                case "ancestor_write_owner": mask=0x80000; break;
                case "ancestor_generic_write": mask=0x40000000; break;
                case "ancestor_generic_all": mask=0x10000000; break;
                default: throw new Exception("UNKNOWN_MODEL_CASE");
            }
            if (mask!=0) {
                text="O:BAG:BAD:(A;;0x"+mask.ToString("x8")+";;;"+user+")"; ancestor=dir=true;
                var parsed=new System.Security.AccessControl.RawSecurityDescriptor(text);
                Check(unchecked((uint)((System.Security.AccessControl.CommonAce)parsed.DiscretionaryAcl[0]).AccessMask)==mask);
            }
            Action run=delegate { LaunchSecurity.Check(text,dir,ancestor); }; if (valid) run(); else Failure(run);
        }
        static byte[] Record(string name) {
            byte[] bytes=new byte[256],raw=Encoding.Unicode.GetBytes(name);
            BitConverter.GetBytes((uint)raw.Length).CopyTo(bytes,60); raw.CopyTo(bytes,104); return bytes;
        }
        static void DirectoryCase(string name) {
            byte[] bytes=Record("x"); var names=new List<string>(); bool valid=false;
            switch (name) {
                case "valid": valid=true; break;
                case "dot": bytes=Record("."); valid=true; break;
                case "two": BitConverter.GetBytes(112u).CopyTo(bytes,0); Array.Copy(Record("y"),0,bytes,112,144); valid=true; break;
                case "odd": BitConverter.GetBytes(3u).CopyTo(bytes,60); break;
                case "zero": BitConverter.GetBytes(0u).CopyTo(bytes,60); break;
                case "oversize": BitConverter.GetBytes(242u).CopyTo(bytes,60); break;
                case "next": BitConverter.GetBytes(8u).CopyTo(bytes,0); break;
                case "unaligned": BitConverter.GetBytes(111u).CopyTo(bytes,0); break;
                case "duplicate": names.Add("x"); break;
                case "bound": for (int i=0;i<16;i++) names.Add(i.ToString()); break;
                case "unsafe": bytes=Record("bad:name"); break;
                default: throw new Exception("UNKNOWN_MODEL_CASE");
            }
            Action run=delegate { WindowsLaunchFiles.DecodeNames(bytes,names); };
            if (valid) { run(); Check(names.Count==(name=="dot"?0:(name=="two"?2:1))); } else Failure(run);
        }
        static void Scenario(string name) {
            if (name.StartsWith("plan:",StringComparison.Ordinal)) { PlanCase(name.Substring(5)); return; }
            if (name.StartsWith("fault:",StringComparison.Ordinal)) { FaultCase(name.Substring(6)); return; }
            if (name.StartsWith("security:",StringComparison.Ordinal)) { SecurityCase(name.Substring(9)); return; }
            if (name.StartsWith("directory:",StringComparison.Ordinal)) { DirectoryCase(name.Substring(10)); return; }
            if (name.StartsWith("layout:",StringComparison.Ordinal)) {
                Check(IntPtr.Size==8);
                switch (name.Substring(7)) {
                    case "unicode": Check(Marshal.SizeOf(typeof(WindowsLaunchFiles.UnicodeName))==16 && Marshal.OffsetOf(typeof(WindowsLaunchFiles.UnicodeName),"Buffer").ToInt32()==8); break;
                    case "attributes": Check(Marshal.SizeOf(typeof(WindowsLaunchFiles.ObjectAttributes))==48 && Marshal.OffsetOf(typeof(WindowsLaunchFiles.ObjectAttributes),"Security").ToInt32()==32); break;
                    case "status": Check(Marshal.SizeOf(typeof(WindowsLaunchFiles.IoStatus))==16); break;
                    case "fileinfo": Check(Marshal.SizeOf(typeof(WindowsLaunchFiles.FileInfo))==52); break;
                    default: throw new Exception("UNKNOWN_MODEL_CASE");
                }
                return;
            }
            var e=new Env(); var gate=e.Gate(); string exe=LaunchBoundary.FileNames[0];
            switch (name) {
                case "construct_no_io": Check(e.Api.Events.Count==0); return;
                case "plan_copies_dictionary": e.Pins.Clear(); using (gate.Acquire()) { } e.Api.AllClosed(); return;
                case "short_reads": e.Api.ShortReads=true; using (gate.Acquire()) { } e.Api.AllClosed(); return;
                case "one_shot_success": using (gate.Acquire()) { } Failure(delegate { gate.Acquire(); },false,"one_shot"); e.Api.AllClosed(); return;
                case "one_shot_failure": e.Api.Operator=false; Failure(delegate { gate.Acquire(); }); Failure(delegate { gate.Acquire(); },false,"one_shot"); return;
                case "one_shot_concurrent":
                    Func<int> run=delegate { try { using (gate.Acquire()) { } return 1; } catch (LaunchRefused ex) { Check(ex.Message=="one_shot"); return 0; } };
                    Task<int> a=Task.Run(run),b=Task.Run(run); Task.WaitAll(a,b); Check(a.Result+b.Result==1); e.Api.AllClosed(); return;
                case "closed_lease": HeldLaunchLease closed=gate.Acquire(); closed.Dispose(); closed.Dispose();
                    Failure(delegate { closed.ReverifyBeforeLaunch(); },false,"lease_closed"); e.Api.AllClosed(); return;
                case "poison_retains_locks":
                case "poison_dispose_once": HeldLaunchLease failed=gate.Acquire(); e.Api.Data[exe][0]^=1;
                    Failure(delegate { failed.ReverifyBeforeLaunch(); },false,"file_hash"); e.Api.AllLive();
                    e.Api.Data[exe][0]^=1; Failure(delegate { failed.ReverifyBeforeLaunch(); },false,"lease_terminal"); e.Api.AllLive();
                    failed.Dispose(); failed.Dispose(); e.Api.AllClosed(); return;
                case "directory_size_not_identity": using (HeldLaunchLease lease=gate.Acquire()) { e.Api.Meta[""].Bytes=999; lease.ReverifyBeforeLaunch(); } e.Api.AllClosed(); return;
                case "all_closes_attempted": e.Api.Fault="read:"+exe; e.Api.CloseFault="scratch";
                    Failure(delegate { gate.Acquire(); },true,"close_unknown"); e.Api.AllClosed(); return;
                case "close_failure_terminal": HeldLaunchLease uncertain=gate.Acquire(); e.Api.CloseFault=exe;
                    Failure(delegate { uncertain.Dispose(); },true,"close_unknown"); uncertain.Dispose(); e.Api.AllClosed(); return;
                case "close_reverse_order": using (gate.Acquire()) { }
                    int n=e.Api.Events.Count; for (int i=0;i<e.Api.Handles.Count;i++) Check(e.Api.Events[n-1-i]=="close:"+e.Api.Handles[i].Name);
                    e.Api.AllClosed(); return;
                case "native_error_sanitized": e.Api.Fault="read:"+exe; Failure(delegate { gate.Acquire(); },true,"launch_boundary_unknown"); e.Api.AllClosed(); return;
                case "config_exact": string cfg=Encoding.ASCII.GetString(LaunchBoundary.Config);
                    Check(cfg.Contains(".NETFramework,Version=v4.8") && cfg.Contains("loadFromRemoteSources enabled=\"false\"")); return;
                case "success_retains_handles":
                case "hash_all_before_return":
                case "reverify_without_reopen":
                    using (HeldLaunchLease lease=gate.Acquire()) {
                        Check(e.Api.Handles.Count==7); e.Api.AllLive();
                        foreach (string file in LaunchBoundary.FileNames) Check(e.Api.Events.Contains("read:"+file));
                        if (name=="reverify_without_reopen") { int start=e.Api.Events.Count; lease.ReverifyBeforeLaunch();
                            Check(e.Api.Handles.Count==7); for (int i=start;i<e.Api.Events.Count;i++) Check(!e.Api.Events[i].StartsWith("open:",StringComparison.Ordinal)); }
                    } e.Api.AllClosed(); return;
                default: throw new Exception("UNKNOWN_MODEL_CASE");
            }
        }
        public static string[] RunAll() {
            string[] cases=__CASES__; var answers=new List<string>();
            foreach (string name in cases) {
                try { Scenario(name); answers.Add(name+"|PASS"); }
                catch (Exception ex) { answers.Add(name+"|FAIL|"+ex.GetType().Name+"|"+ex.Message); }
            }
            return answers.ToArray();
        }
    }
}
'''


def _quote(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


@pytest.fixture(scope='module')
def models(tmp_path_factory):
    if os.name != 'nt':
        pytest.skip('requires Windows CLR compiler; not native launch-boundary evidence')
    exe = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    assert exe.is_file(), 'required Windows model compiler unavailable'
    harness = tmp_path_factory.mktemp('validator-launch-model') / 'models.cs'
    cases = 'new string[] {' + ','.join(json.dumps(n) for n in SCENARIOS) + '}'
    harness.write_text(HARNESS.replace('__CASES__', cases), encoding='utf-8')
    script = (
        "$ErrorActionPreference='Stop'; "
        f"Add-Type -Path @({_quote(CORE)},{_quote(WINDOWS)},{_quote(harness)}) -ErrorAction Stop; "
        "[AiAgent.ValidatorLaunch.LaunchHarness]::RunAll()"
    )
    encoded = base64.b64encode(script.encode('utf-16le')).decode('ascii')
    completed = subprocess.run(
        [str(exe), '-NoLogo', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
        capture_output=True, text=True, timeout=25, check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    observations = {}
    for line in completed.stdout.splitlines():
        name, separator, result = line.partition('|')
        assert separator and name not in observations, line
        observations[name] = result
    assert set(observations) == set(SCENARIOS)
    return observations


@pytest.mark.parametrize('scenario', SCENARIOS)
def test_launch_boundary_clr_models(models, scenario):
    assert models[scenario] == 'PASS'


def test_fixed_launch_names_match_guardian_without_loading_worker_assemblies():
    core = CORE.read_text(encoding='utf-8')
    guardian = (ROOT / 'scripts/native_validator_process_guardian.cs').read_text(encoding='utf-8')
    for role in ('validator-install-guardian.exe', 'validator-provision-worker.exe'):
        assert f'"{role}"' in core and f'"{role}"' in guardian
        assert f'"{role}.config"' in core
    combined = core + WINDOWS.read_text(encoding='utf-8')
    for forbidden in ('AiAgent.NativeValidator', 'Assembly.Load', 'LoadLibrary', 'night_shifts'):
        assert forbidden not in combined
    assert not re.search(r'\b(?:Main|Process\.Start|CreateProcessW|WriteFile|SetSecurityInfo|DeleteFile)\s*\(', combined)
    assert 'CreateClaim' not in combined


def test_read_only_relative_native_acquisition_and_fixed_sharing():
    text = WINDOWS.read_text(encoding='utf-8')
    assert 'Root=(IntPtr)parent,Name=textBuffer,Attributes=0x1040' in text
    assert 'directory?3u:1u,1,directory?0x200021u:0x200060u' in text
    assert 'CreateFileW(drive,0x1200a1,3,IntPtr.Zero,3,0x02200000' in text
    assert 'info.Links!=1 || (info.Attributes&0x5e00)!=0' in text
    assert 'status.Information.ToUInt64()!=1' in text
    assert 'ReleaseBuffer(ref textBuffer); ReleaseBuffer(ref nameBuffer);' in text
    assert text.index('ReleaseBuffer(ref textBuffer); ReleaseBuffer(ref nameBuffer);') < text.index('object answer=handle;')
    assert 'TrustedInstaller exception' in text
    assert 'if (unknown) throw new LaunchUnknown("native_release_unknown")' in text


def test_poisoning_does_not_release_target_locks_and_no_finalizer():
    text = CORE.read_text(encoding='utf-8')
    lease = text.split('public sealed class HeldLaunchLease', 1)[1].split('public sealed class LaunchBoundary', 1)[0]
    method = lease.split('public void ReverifyBeforeLaunch()', 1)[1].split('public void Dispose()', 1)[0]
    assert 'owner.Reverify();' in method and 'CloseAll(' not in method
    assert 'poisoned=true; throw;' in text
    assert 'closed || poisoned' in text
    assert '~HeldLaunchLease' not in text and '~LaunchBoundary' not in text
    assert 'LaunchBoundary current=owner; owner=null;' in lease
    assert 'object handle=held[i].Handle; held[i].Handle=null;' in text


def test_launch_sources_visible_but_not_wired_or_bundled():
    ignore = (ROOT / '.gitignore').read_text(encoding='utf-8').splitlines()
    for path in (CORE, WINDOWS):
        exception = '!/' + path.relative_to(ROOT).as_posix()
        assert ignore.count(exception) == 1
        assert ignore.index(exception) > ignore.index('/scripts/*')
    for path in [*(ROOT / 'runtime').glob('*.py'), *(ROOT / 'scripts').glob('*.ps1')]:
        assert 'native_validator_launch_' not in path.read_text(encoding='utf-8-sig')
    for name in ('bootstrap_native_deployment.py', 'bootstrap_native_provision.py'):
        assert 'native_validator_launch_' not in (ROOT / 'night_shifts' / name).read_text(encoding='utf-8')
