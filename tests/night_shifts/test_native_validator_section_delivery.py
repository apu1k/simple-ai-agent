"""Offline parent publisher/composition, never a native section/worker launch.

Compile fifteen actual C# sources as a library with fake policy/file/process/
section/counter backends. The actual approval/request/held/process bodies reach
actual frame, canonical codec and worker deadline receiver logic, NOT Main.
"""
from __future__ import annotations

import base64
import os
import re
import subprocess
from pathlib import Path

import pytest

from night_shifts import bootstrap_native_install_request as profile
from tests.night_shifts import test_native_validator_approval_guardian as approval_models
from tests.night_shifts import test_native_validator_request_guardian as request_models

ROOT = Path(__file__).resolve().parents[2]
BOUNDARY = ROOT / 'scripts/native_validator_section_boundary.cs'
WINDOWS = ROOT / 'scripts/native_validator_section_windows.cs'
SOURCES = (BOUNDARY, WINDOWS, *(ROOT / 'scripts' / f'native_validator_{name}.cs' for name in (
    'worker_entry', 'worker_guardian', 'worker_windows',
)), *approval_models.SOURCES)
SCENARIOS = (
    'helper:failure', 'helper:memory',
    'publish', 'publish_isolation', 'publish_once', 'lease_close_once', 'command', 'frame_receiver',
    'pin:null', 'pin:length', 'pin:hash', 'pin:upper', 'pin:budget', 'pin:expiry', 'pin:copy',
    'memory:new', 'memory:rights:w', 'memory:map:w', 'memory:write', 'memory:copy:w',
    'memory:unmap:w', 'memory:duplicate', 'memory:rights:r', 'memory:close:w',
    'memory:map:r', 'memory:copy:r', 'memory:unmap:r', 'memory:close:r',
    'shape:null_writer', 'shape:null_view', 'shape:alias_reader', 'shape:partial_write',
    'shape:short_copy', 'shape:corrupt_read', 'shape:reader_rights', 'shape:writer_rights',
    'window:expired', 'window:wall', 'window:rollback', 'window:nan', 'window:infinite',
    'window:late_write', 'window:late_duplicate', 'window:late_close',
    'counter:zero_rate', 'counter:negative_rate', 'counter:large_rate', 'counter:changed_rate',
    'counter:zero', 'counter:negative', 'counter:rollback', 'counter:wide', 'counter:expired',
    'counter:large_window', 'counter:overflow', 'counter:near', 'counter:wall_cap', 'counter:setup_delay',
    'native:null_counter', 'native:null_request', 'native:request_twice', 'native:job_without_host',
    'native:window_without_host', 'native:create_without_binding', 'native:host_mismatch',
    'compose:normal', 'compose:nonzero', 'compose:timeout', 'compose:residual',
    'compose:arrival', 'compose:policy_cost', 'compose:publication_cost', 'compose:shortened_core_cap',
    'compose:copy_isolation', 'compose:claim_replay', 'compose:invalid_request',
    'compose:bind_request', 'compose:bind_window', 'compose:late_window',
    'compose:section_corrupt', 'compose:create', 'compose:membership', 'compose:preresume',
    'compose:stop', 'compose:parent_read_close', 'compose:late_parent_read_close',
)

HARNESS = r'''
using System;
using System.Collections.Generic;
using AiAgent.NativeValidator;
using AiAgent.ValidatorApproval;
using AiAgent.ValidatorAdmission;
using AiAgent.ValidatorGuardian;
using AiAgent.ValidatorHandoff;
using AiAgent.ValidatorRequest;
using AiAgent.ValidatorWorker;
namespace AiAgent.ValidatorDelivery {
    internal sealed class MemoryObject {
        internal string Kind;
        internal bool Closed;
        internal int Closes;
    }
    internal sealed class MemoryModel : ISectionMemory {
        internal readonly List<MemoryObject> Objects=new List<MemoryObject>();
        internal readonly List<string> Events=new List<string>();
        internal byte[] Data;
        internal string Fault,Shape;
        internal Action<string> Hook;
        void Event(string name) {
            Events.Add(name); if (Hook!=null) Hook(name);
            if (Fault==name) throw new Exception("MEMORY_CANARY");
        }
        MemoryObject Add(string kind) { var item=new MemoryObject {Kind=kind}; Objects.Add(item); return item; }
        static MemoryObject Live(object value) { var h=(MemoryObject)value; SectionHarness.Check(!h.Closed); return h; }
        internal void Closed() { foreach (MemoryObject h in Objects) SectionHarness.Check(h.Closed && h.Closes==1); }
        internal void OnlyRead() {
            int live=0; foreach (MemoryObject h in Objects) if (!h.Closed) { live++; SectionHarness.Check(h.Kind=="r"); }
            SectionHarness.Check(live==1);
        }
        public object NewSection(int bytes) {
            Event("new"); Data=new byte[bytes]; return Shape=="null_writer"?null:Add("w");
        }
        public void RequireHandle(object handle,bool readOnly,bool inheritable) {
            MemoryObject h=Live(handle); SectionHarness.Check(h.Kind==(readOnly?"r":"w") && inheritable==readOnly);
            Event("rights:"+h.Kind);
            if (Shape==(readOnly?"reader_rights":"writer_rights")) throw new GuardianRefused("MODEL_RIGHTS");
        }
        public object Map(object handle,int bytes,bool write) {
            MemoryObject h=Live(handle); SectionHarness.Check(bytes==Data.Length && h.Kind==(write?"w":"r"));
            if (!write) OnlyRead(); Event("map:"+h.Kind);
            return Shape=="null_view"?null:Add(write?"vw":"vr");
        }
        public void Write(object view,byte[] raw) {
            SectionHarness.Check(Live(view).Kind=="vw" && raw.Length==Data.Length); Event("write");
            Array.Copy(raw,Data,raw.Length-(Shape=="partial_write"?1:0));
        }
        public byte[] Copy(object view,int bytes) {
            MemoryObject h=Live(view); SectionHarness.Check(bytes==Data.Length); Event("copy:"+(h.Kind=="vw"?"w":"r"));
            byte[] copy=(byte[])Data.Clone();
            if (Shape=="corrupt_read" && h.Kind=="vr") copy[0]^=1;
            return Shape=="short_copy"?new byte[bytes-1]:copy;
        }
        public object ReadOnlyDuplicate(object writer) {
            SectionHarness.Check(Live(writer).Kind=="w");
            foreach (MemoryObject h in Objects) if (h.Kind=="vw") SectionHarness.Check(h.Closed);
            Event("duplicate"); return Shape=="alias_reader"?writer:Add("r");
        }
        public void Unmap(object view) {
            MemoryObject h=Live(view); h.Closed=true; h.Closes++; Event("unmap:"+(h.Kind=="vw"?"w":"r"));
        }
        public void Close(object handle) {
            MemoryObject h=Live(handle); h.Closed=true; h.Closes++; Event("close:"+h.Kind);
        }
    }
    internal sealed class SectionClockModel : IGuardianClock {
        internal double Time=100;
        internal long Wall=1000;
        public double Seconds { get { return Time; } }
        public long Unix { get { return Wall; } }
    }
    internal sealed class CounterModel : ISectionCounter,IWorkerCounter {
        internal long Rate=1000,Again=1000,First=10000,Second=10010,LastFirst,LastSecond;
        internal int Reads,Rates;
        internal bool TrackTime;
        internal Action OnFirst;
        public long Frequency() { return ++Rates==1?Rate:Again; }
        public long Read() {
            long offset=TrackTime?(long)((SharedModelTime.Time-100)*1000):0;
            long value=(++Reads==1?First:Second)+offset;
            if (Reads==1) { LastFirst=value; if (OnFirst!=null) OnFirst(); } else LastSecond=value;
            return value;
        }
    }
    internal sealed class DeliveryModel : IGuardianRequestKernel {
        internal readonly ApprovalEnv Env;
        internal readonly MemoryModel Memory=new MemoryModel();
        internal readonly CounterModel Counter=new CounterModel {TrackTime=true};
        internal GuardianRequest Request;
        internal SectionWindow Window;
        internal SectionCounterFrame Frame;
        internal string[] Arguments;
        internal string Fault;
        internal int RequestBinds,WindowBinds;
        internal DeliveryModel(ApprovalEnv env) {
            Env=env; Memory.Hook=delegate(string s) {
                Env.Events.Add("S:"+s); if (Env.Hook!=null) Env.Hook("S:"+s);
                Env.A.AllLive(); Env.F.Api.AllLive();
            };
        }
        void Event(string name) {
            Env.Events.Add("D:"+name); if (Env.Hook!=null) Env.Hook("D:"+name);
            if (Fault==name) throw new GuardianRefused("MODEL_DELIVERY");
        }
        public void BindRequest(GuardianRequest value) {
            SectionHarness.Check(++RequestBinds==1 && value!=null && Memory.Events.Count==0 && Counter.Reads==0);
            SectionHarness.Check(Env.A.Creates==1 && Env.A.Writes==1 && Env.A.Flushes==1 && Env.F.Api.Handles.Count==0);
            Request=value; Event("request");
        }
        public void BindWindow(GuardianPlan plan,IGuardianClock clock,double stopAt) {
            SectionHarness.Check(++WindowBinds==1 && Request!=null && Request.Plan.ApprovalSha256==plan.ApprovalSha256);
            SectionHarness.Check(Memory.Events.Count==0 && Counter.Reads==0); Env.F.Api.AllLive();
            Window=new SectionWindow(clock,stopAt,plan.ApprovedUntilUnix); Event("window");
        }
        public void RequireHost(GuardianPlan plan) { SectionHarness.Check(Request!=null); Env.K.Api.RequireHost(plan); }
        public object NewJob() { return Env.K.Api.NewJob(); }
        public ChildPair CreateSuspended(object job,string root) {
            ChildPair child=null; ReadOnlyRequestSection lease=null; bool transferred=false;
            try {
                SectionHarness.Check(Request!=null && Window!=null); Event("publish");
                lease=new SectionPublisher(Memory,Request,Window).Publish(); lease.Reverify(); Memory.OnlyRead();
                Frame=SectionCounterFrame.Capture(Window,Counter);
                Arguments=SectionWorkerCommand.Arguments(Request,256,Frame);
                WorkerEntryFrame received=WorkerEntryFrame.Parse(Arguments);
                SectionHarness.Check(received.RequestBytes==Request.Bytes && received.RequestSha256==Request.Sha256 &&
                    received.BudgetSeconds==Request.Plan.BudgetSeconds && received.ExpiresUnix==Request.Plan.ApprovedUntilUnix);
                BoundInstallationInputs decoded=InstallationRequest.Bind((byte[])Memory.Data.Clone(),received.RequestBytes,received.RequestSha256);
                SectionHarness.Check(decoded.CreateLaunchPlan().Root==root && Request.Matches(Memory.Data));
                var local=new SectionClockModel {Time=20,Wall=Window.Unix};
                var remote=new CounterModel {First=Counter.LastSecond+10,Second=Counter.LastSecond+20};
                double cap=WorkerEntryDeadline.Translate(received,local,remote);
                SectionHarness.Check(cap>25 && cap<20+(Window.Deadline-Window.Seconds));
                Event("receiver"); child=Env.K.Api.CreateSuspended(job,root);
                ReadOnlyRequestSection old=lease; lease=null; old.Close(); Window.Require();
                transferred=true; return child;
            } finally {
                bool unknown=false;
                if (!transferred && child!=null) {
                    try { if (child.Thread!=null) Env.K.Api.Close(child.Thread); } catch { unknown=true; }
                    try { if (child.Process!=null) Env.K.Api.Close(child.Process); } catch { unknown=true; }
                }
                ReadOnlyRequestSection old=lease; lease=null;
                try { if (old!=null) old.Close(); } catch { unknown=true; }
                if (unknown) throw new GuardianUnknown("MODEL_DELIVERY_RELEASE");
            }
        }
        public bool Member(object process,object job) { return Env.K.Api.Member(process,job); }
        public uint Resume(object thread) { return Env.K.Api.Resume(thread); }
        public uint Wait(object process,uint ms) { return Env.K.Api.Wait(process,ms); }
        public uint ExitCode(object process) { return Env.K.Api.ExitCode(process); }
        public uint Active(object job) { return Env.K.Api.Active(job); }
        public void Stop(object job) { Env.K.Api.Stop(job); }
        public void Pause(int ms) { Env.K.Api.Pause(ms); }
        public void Close(object handle) { Env.K.Api.Close(handle); }
    }
    public static class SectionHarness {
        internal static void Check(bool yes) { if (!yes) throw new Exception("SECTION_ASSERTION"); }
        static GuardianRequest Bound(byte[] raw) {
            var p=InstallationRequest.Bind(raw,raw.Length,InstallBoundary.Sha(raw)).CreateLaunchPlan();
            return new GuardianRequest(new GuardianPlan(p.Root,p.OperatorSid,p.InstallationId,p.ApprovalSha256,p.ApprovedUntilUnix,p.BudgetSeconds),
                raw,raw.Length,InstallBoundary.Sha(raw));
        }
        static void Failure(Action action) {
            try { action(); }
            catch (Exception ex) {
                Check((ex is GuardianRefused || ex is GuardianUnknown || ex is ApprovalRefused || ex is ApprovalUnknown ||
                    ex is RequestGuardianRefused || ex is RequestGuardianUnknown) && !ex.Message.Contains("CANARY"));
                return;
            }
            throw new Exception("EXPECTED_SECTION_FAILURE");
        }
        static void MemoryFailure(string name,MemoryModel memory,Action action) {
            try { action(); }
            catch (Exception ex) {
                bool injected=name.StartsWith("memory:",StringComparison.Ordinal) && ex.Message=="MEMORY_CANARY";
                Check(ex is GuardianRefused || ex is GuardianUnknown || injected);
                string phase=null;
                if (name.StartsWith("memory:",StringComparison.Ordinal)) phase=name.Substring(7);
                else switch (name) {
                    case "shape:null_writer": phase="new"; break;
                    case "shape:null_view": phase="map:w"; break;
                    case "shape:alias_reader": phase="duplicate"; break;
                    case "shape:partial_write": case "shape:short_copy": phase="copy:w"; break;
                    case "shape:corrupt_read": phase="copy:r"; break;
                    case "shape:reader_rights": phase="rights:r"; break;
                    case "shape:writer_rights": phase="rights:w"; break;
                    case "window:late_write": phase="write"; break;
                    case "window:late_duplicate": phase="duplicate"; break;
                    case "window:late_close": phase="close:w"; break;
                }
                if (phase!=null) Check(memory.Events.Contains(phase));
                memory.Closed(); return;
            }
            throw new Exception("EXPECTED_MEMORY_OR_WINDOW_FAILURE");
        }
        static void GuardHelper(string name) {
            bool rejected=false;
            try {
                Action unrelated=delegate { throw new InvalidOperationException("UNRELATED_FAILURE"); };
                if (name=="failure") Failure(unrelated);
                else { Check(name=="memory"); MemoryFailure("window:expired",new MemoryModel(),unrelated); }
            } catch (Exception ex) { Check(ex.Message=="SECTION_ASSERTION"); rejected=true; }
            Check(rejected);
        }
        static void Pin(string name,byte[] raw) {
            GuardianRequest value=Bound(raw); byte[] input=(byte[])raw.Clone();
            if (name=="copy") { byte[] a=value.CopyRequest(),b=value.CopyRequest(); a[0]^=1; Check(value.Matches(b) && !value.Matches(a)); return; }
            long count=input.Length; string digest=value.Sha256; GuardianPlan p=value.Plan;
            switch (name) {
                case "null": input=null; break;
                case "length": count++; break;
                case "hash": input[0]^=1; break;
                case "upper": digest=new string('A',64); break;
                case "budget": p=new GuardianPlan(p.Root,p.OperatorSid,p.InstallationId,p.ApprovalSha256,p.ApprovedUntilUnix,901); break;
                case "expiry": p=new GuardianPlan(p.Root,p.OperatorSid,p.InstallationId,p.ApprovalSha256,253402300800L,20); break;
                default: throw new Exception("UNKNOWN_PIN_CASE");
            }
            Failure(delegate { new GuardianRequest(p,input,count,digest); });
        }
        static void Counter(string name,GuardianRequest request) {
            var clock=new SectionClockModel(); double stop=115; var counter=new CounterModel();
            switch (name) {
                case "zero_rate": counter.Rate=counter.Again=0; break;
                case "negative_rate": counter.Rate=counter.Again=-1; break;
                case "large_rate": counter.Rate=counter.Again=1000000001; break;
                case "changed_rate": counter.Again=999; break;
                case "zero": counter.First=0; break;
                case "negative": counter.First=-1; break;
                case "rollback": counter.Second=9999; break;
                case "wide": counter.Second=10251; break;
                case "expired": stop=100; break;
                case "large_window": stop=1001; clock.Wall=999; break;
                case "overflow": counter.First=counter.Second=Int64.MaxValue-1; break;
                case "near": stop=100.001; break;
                case "wall_cap": clock.Wall=1890; break;
                case "setup_delay": counter.OnFirst=delegate { clock.Time=102; }; break;
                default: throw new Exception("UNKNOWN_COUNTER_CASE");
            }
            var window=new SectionWindow(clock,stop,1900);
            if (name!="wall_cap" && name!="setup_delay") { Failure(delegate { SectionCounterFrame.Capture(window,counter); }); return; }
            SectionCounterFrame frame=SectionCounterFrame.Capture(window,counter);
            Check(frame.Limit==(name=="wall_cap"?19998:22998) && frame.Frequency==1000 && counter.Reads==2);
        }
        static void Native(string name,GuardianRequest request) {
            var counter=new CounterModel(); var kernel=new WindowsSectionGuardianKernel(counter);
            switch (name) {
                case "null_counter": Failure(delegate { new WindowsSectionGuardianKernel(null); }); break;
                case "null_request": Failure(delegate { kernel.BindRequest(null); }); Failure(delegate { kernel.BindRequest(request); }); break;
                case "request_twice": kernel.BindRequest(request); Failure(delegate { kernel.BindRequest(request); }); break;
                case "job_without_host": kernel.BindRequest(request); Failure(delegate { kernel.NewJob(); }); break;
                case "window_without_host": kernel.BindRequest(request); Failure(delegate { kernel.BindWindow(request.Plan,new SectionClockModel(),115); }); break;
                case "create_without_binding": Failure(delegate { kernel.CreateSuspended(null,request.Plan.Root); }); break;
                case "host_mismatch": kernel.BindRequest(request); Failure(delegate { kernel.RequireHost(null); }); break;
                default: throw new Exception("UNKNOWN_NATIVE_GUARD_CASE");
            }
            Check(counter.Reads==0 && counter.Rates==0); // no P/Invoke boundary is reached
        }
        static void Compose(string name,byte[] raw,byte[] policy,byte[] claim) {
            var e=new ApprovalEnv(policy); var kernel=new DeliveryModel(e);
            var p=e.Plan(policy,raw.Length,InstallBoundary.Sha(raw),20,1900);
            var run=new ApprovalProvisionGuardian(p,e.A,e.F.Api,kernel,e.Clock);
            byte[] incoming=(byte[])raw.Clone(); bool fail=false,targets=false,approval=false;
            switch (name) {
                case "normal": break;
                case "nonzero": e.K.Api.Code=7; break;
                case "timeout": e.K.Api.NeverExit=true; break;
                case "residual": e.K.Api.Residue=true; break;
                case "arrival": SharedModelTime.Time=102; break;
                case "policy_cost":
                    int count=0; e.Hook=delegate(string s) { if (s=="A:rewind:approval.json" && ++count==1) SharedModelTime.Time+=2; }; break;
                case "publication_cost": e.Hook=delegate(string s) { if (s=="S:write") SharedModelTime.Time+=2; }; break;
                case "shortened_core_cap": e.Hook=delegate(string s) { if (s=="D:request") SharedModelTime.Wall=1884; }; break;
                case "copy_isolation": e.Hook=delegate(string s) { if (s=="D:request") Array.Clear(incoming,0,incoming.Length); }; break;
                case "claim_replay": e.A.Existing(); fail=true; break;
                case "invalid_request": incoming[0]^=1; fail=true; break;
                case "bind_request": kernel.Fault="request"; fail=approval=true; break;
                case "bind_window": kernel.Fault="window"; fail=approval=true; break;
                case "late_window": e.Hook=delegate(string s) { if (s=="D:window") SharedModelTime.Time=116; }; fail=approval=true; break;
                case "section_corrupt": kernel.Memory.Shape="corrupt_read"; fail=approval=targets=true; break;
                case "create": e.K.Api.Fault="create"; fail=approval=targets=true; break;
                case "membership": e.K.Api.MemberValue=false; fail=approval=targets=true; break;
                case "preresume": e.Hook=delegate(string s) { if (s=="K:member") e.F.Api.Data["validator-install-guardian.exe"][0]^=1; }; fail=approval=targets=true; break;
                case "stop": e.K.Api.NeverExit=e.K.Api.StopFails=true; fail=approval=targets=true; break;
                case "parent_read_close": kernel.Memory.Fault="close:r"; fail=approval=targets=true; break;
                case "late_parent_read_close": e.Hook=delegate(string s) { if (s=="S:close:r") SharedModelTime.Time=116; }; fail=approval=targets=true; break;
                default: throw new Exception("UNKNOWN_COMPOSITION_CASE");
            }
            if (fail) Failure(delegate { run.Run(incoming); });
            else {
                LocalProcessObservation answer=run.Run(incoming); Check(answer.EmptyObserved && answer.Resumed);
                Check(answer.End==(name=="timeout"?LocalProcessEnd.DeadlineStopped:(name=="residual"?LocalProcessEnd.ResidualTreeStopped:LocalProcessEnd.RootExited)));
                Check(e.A.Creates==1 && e.A.Writes==1 && e.A.Flushes==1 && kernel.RequestBinds==1 && kernel.WindowBinds==1);
                Check(kernel.Request.Bytes==raw.Length && kernel.Request.Bytes>8192 && kernel.Request.Matches(raw));
                Check(kernel.Window.Deadline==(name=="shortened_core_cap"?111:115));
                Check(kernel.Frame.Limit==(name=="shortened_core_cap"?20998:24998));
                Check(Convert.ToBase64String(e.A.Data["claims/install-attempt.claim"])==Convert.ToBase64String(claim));
            }
            Check(run.ApprovalLeaseRetained==approval && run.LaunchLeaseRetained==targets);
            e.K.Api.AllClosed(); kernel.Memory.Closed();
            if (targets) e.F.Api.AllLive(); else e.F.Api.AllClosed();
            if (approval) e.A.AllLive(); else e.A.Closed();
            if (name=="bind_request" || name=="bind_window" || name=="late_window" || name=="invalid_request" || name=="claim_replay")
                Check(kernel.Memory.Events.Count==0 && !e.K.Api.Events.Contains("create"));
            int events=e.Events.Count; Failure(delegate { run.Run(raw); }); Check(e.Events.Count==events);
        }
        static void Scenario(string name,byte[] raw,byte[] policy,byte[] claim) {
            if (name.StartsWith("helper:",StringComparison.Ordinal)) { GuardHelper(name.Substring(7)); return; }
            if (name.StartsWith("compose:",StringComparison.Ordinal)) { Compose(name.Substring(8),raw,policy,claim); return; }
            if (name.StartsWith("pin:",StringComparison.Ordinal)) { Pin(name.Substring(4),raw); return; }
            GuardianRequest request=Bound(raw);
            if (name.StartsWith("counter:",StringComparison.Ordinal)) { Counter(name.Substring(8),request); return; }
            if (name.StartsWith("native:",StringComparison.Ordinal)) { Native(name.Substring(7),request); return; }
            var clock=new SectionClockModel(); var window=new SectionWindow(clock,115,1900); var memory=new MemoryModel();
            var publisher=new SectionPublisher(memory,request,window); bool fail=false;
            if (name.StartsWith("memory:",StringComparison.Ordinal)) { memory.Fault=name.Substring(7); fail=true; }
            else if (name.StartsWith("shape:",StringComparison.Ordinal)) { memory.Shape=name.Substring(6); fail=true; }
            else if (name.StartsWith("window:",StringComparison.Ordinal)) {
                fail=true;
                switch (name.Substring(7)) {
                    case "expired": clock.Time=115; break;
                    case "wall": clock.Wall=1900; break;
                    case "rollback": window.Require(); clock.Time=99; break;
                    case "nan": clock.Time=Double.NaN; break;
                    case "infinite": clock.Time=Double.PositiveInfinity; break;
                    case "late_write": memory.Hook=delegate(string s) { if (s=="write") clock.Time=115; }; break;
                    case "late_duplicate": memory.Hook=delegate(string s) { if (s=="duplicate") clock.Time=115; }; break;
                    case "late_close": memory.Hook=delegate(string s) { if (s=="close:w") clock.Time=115; }; break;
                    default: throw new Exception("UNKNOWN_WINDOW_CASE");
                }
            }
            Action exercise=delegate {
                ReadOnlyRequestSection section=null;
                try {
                    section=publisher.Publish(); memory.OnlyRead();
                    Check(memory.Events.IndexOf("unmap:w")<memory.Events.IndexOf("duplicate") &&
                        memory.Events.IndexOf("close:w")<memory.Events.IndexOf("map:r"));
                    if (name=="publish_isolation") { byte[] copy=request.CopyRequest(); copy[0]^=1; Check(request.Matches(memory.Data)); }
                    if (name=="publish_once") Failure(delegate { publisher.Publish(); });
                    if (name=="command" || name=="frame_receiver") {
                        SectionCounterFrame frame=SectionCounterFrame.Capture(window,new CounterModel());
                        string[] args=SectionWorkerCommand.Arguments(request,256,frame);
                        string command=SectionWorkerCommand.Command(request,256,frame);
                        Check(command.Length<1024 && !command.Contains(Convert.ToBase64String(raw)));
                        WorkerEntryFrame received=WorkerEntryFrame.Parse(args);
                        Check(received.RequestBytes==raw.Length && received.RequestSha256==request.Sha256);
                        if (name=="frame_receiver") {
                            var receiver=new SectionClockModel {Time=20};
                            double deadline=WorkerEntryDeadline.Translate(received,receiver,new CounterModel {First=10020,Second=10030});
                            Check(deadline>34.966 && deadline<34.967);
                        }
                    }
                    section.Reverify();
                } finally {
                    if (section!=null) { section.Close(); if (name=="lease_close_once") section.Close(); }
                }
            };
            if (fail) { MemoryFailure(name,memory,exercise); return; }
            exercise(); memory.Closed();
        }
        public static string Run(string name,byte[] raw,byte[] policy,byte[] claim) {
            try { Scenario(name,raw,policy,claim); return name+"|PASS"; }
            catch (Exception ex) { return name+"|FAIL|"+ex.GetType().Name+"|"+ex.Message; }
        }
    }
}
'''


def _quote(path):
    return "'" + str(path).replace("'", "''") + "'"


@pytest.fixture(scope='module')
def models(tmp_path_factory):
    if os.name != 'nt':
        pytest.skip('requires Windows CLR compiler; NOT native section or installed execution evidence')
    folder = tmp_path_factory.mktemp('section-delivery-models')
    paths = list(SOURCES)
    for name, text in (
        ('launch_models', request_models._backend('launch_boundary')),
        ('process_models', request_models._backend('process_guardian')),
        ('approval_models', approval_models.HARNESS),
        ('section_models', HARNESS),
    ):
        path = folder / f'{name}.cs'
        path.write_text(text, encoding='utf-8')
        paths.append(path)
    value = request_models._candidate()
    value['budget_seconds'] = 20
    raw = profile.build_validation_install_request(value)
    digest = approval_models._sha(raw)
    policy = approval_models._policy(len(raw), digest, 20, 1900)
    claim = approval_models._claim(policy, len(raw), digest, 20, 1900)
    for name, data in (('request', raw), ('policy', policy), ('claim', claim)):
        (folder / f'inert_{name}.bin').write_bytes(data)
    cases = folder / 'inert_cases.txt'
    cases.write_text('\n'.join(SCENARIOS) + '\n', encoding='ascii')
    compiler = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    assert compiler.is_file()
    script = (
        "$ErrorActionPreference='Stop'; Add-Type -Path @(" + ','.join(_quote(p) for p in paths) + ') '
        "-ReferencedAssemblies @('System.dll','System.Core.dll','System.Xml.dll','System.Runtime.Serialization.dll') -ErrorAction Stop; "
        f'$raw=[IO.File]::ReadAllBytes({_quote(folder / "inert_request.bin")}); '
        f'$policy=[IO.File]::ReadAllBytes({_quote(folder / "inert_policy.bin")}); '
        f'$claim=[IO.File]::ReadAllBytes({_quote(folder / "inert_claim.bin")}); '
        f'foreach($name in [IO.File]::ReadAllLines({_quote(cases)})) {{ '
        '[AiAgent.ValidatorDelivery.SectionHarness]::Run($name,$raw,$policy,$claim) }'
    )
    command = [str(compiler), '-NoLogo', '-NoProfile', '-NonInteractive', '-EncodedCommand',
               base64.b64encode(script.encode('utf-16le')).decode('ascii')]
    assert len(subprocess.list2cmdline(command)) < 16384
    result = subprocess.run(command, capture_output=True, text=True, timeout=25, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    answers = {}
    for line in result.stdout.splitlines():
        name, separator, answer = line.partition('|')
        assert separator and name not in answers, line
        answers[name] = answer
    assert set(answers) == set(SCENARIOS)
    return answers


@pytest.mark.parametrize('scenario', SCENARIOS)
def test_section_clr_models(models, scenario):
    assert models[scenario] == 'PASS', models[scenario]


def test_only_explicit_single_read_handle_and_atomic_job_assignment_allow_inheritance():
    text = WINDOWS.read_text(encoding='utf-8')
    assert 'HandleListAttribute=0x00020002' in text
    assert 'InitializeProcThreadAttributeList(IntPtr.Zero,2,0,ref size)' in text
    assert 'new UIntPtr(WG.JobListAttribute),state.JobArray' in text
    assert 'new UIntPtr(HandleListAttribute),state.HandleArray' in text
    assert 'Marshal.AllocHGlobal(IntPtr.Size)' in text
    assert 'Marshal.WriteIntPtr(state.HandleArray,read)' in text
    assert text.index('section_atomic_job_required') < text.index('if (!CreateProcessW(')
    assert text.index('section_exact_handle_list_required') < text.index('if (!CreateProcessW(')
    assert 'true,WG.ProcessFlags,state.Environment,root,ref startup,out state.Child' in text
    assert 'actual.GrantedAccess!=(readOnly?SectionMapRead:SectionAllAccess)' in text
    assert 'out read,SectionMapRead,true,0)' in text
    assert 'CreateFileMappingW(new IntPtr(-1),ref security,PageReadWrite,0,(uint)bytes,null)' in text
    for forbidden in ('AssignProcessToJobObject', 'OpenProcess(', 'TerminateProcess(', 'ShellExecute(', 'OpenFileMapping',
                      'GetEnvironmentVariables', 'DUPLICATE_SAME_ACCESS', 'SetSecurityInfo', 'CreateNamedPipe'):
        assert forbidden not in text
    assert 'Inherit=0' in text and 'WG.EnvironmentBlock(root,' in text


def test_request_snapshot_and_actual_core_stop_point_are_optional_pure_binds():
    request = (ROOT / 'scripts/native_validator_request_guardian.cs').read_text(encoding='utf-8')
    core = (ROOT / 'scripts/native_validator_process_guardian.cs').read_text(encoding='utf-8')
    assert request.index('InstallationRequest.Bind(') < request.index('delivery.BindRequest(') < request.index('guardian=new HeldProvisionGuardian(')
    assert 'new GuardianRequest(process,request,expectedBytes,expectedSha256)' in request
    assert 'raw=(byte[])request.Clone()' in core and 'if (!Matches(raw))' in core
    assert core.index('launchGate.BeforeCreate()') < core.index('delivery.BindWindow(plan,clock,stopAt)') < core.index('creationAttempted=true;')
    assert 'if (delivery!=null)' in core and 'if (delivery!=null)' in request
    assert 'AiAgent.NativeValidator' not in core and 'night_shifts' not in core
    assert 'new WindowsSectionGuardianKernel' not in core + request


def test_section_parent_cleanup_is_not_import_or_target_release():
    text = BOUNDARY.read_text(encoding='utf-8')
    native = WINDOWS.read_text(encoding='utf-8')
    assert text.index('CloseWriter(); window.Require();') < text.index('var answer=new ReadOnlyRequestSection(')
    assert 'reader=null; return answer;' in text and 'finally { CloseAll(); }' in text
    assert 'object old=reader; reader=null;' in text
    assert 'state.Scratch(); window.Require();' in native
    assert native.index('state.Scratch(); window.Require();') < native.index('state.Child.Process=IntPtr.Zero;')
    assert 'finally { state.Close(); }' in native
    assert 'rate/1000-1' in text and 'window.Deadline-now' in text
    for forbidden in ('Dispose()', 'LaunchTargetsReleasable', 'ImportClosureLease', 'HeldLaunchLease'):
        assert forbidden not in text + native


def test_section_sources_are_visible_but_not_installed_wired_or_deployed():
    ignore = (ROOT / '.gitignore').read_text(encoding='utf-8').splitlines()
    for source in (BOUNDARY, WINDOWS):
        exception = '!/' + source.relative_to(ROOT).as_posix()
        assert ignore.count(exception) == 1 and ignore.index(exception) > ignore.index('/scripts/*')
    for path in [*(ROOT / 'runtime').glob('*.py'), *(ROOT / 'scripts').glob('*.ps1')]:
        text = path.read_text(encoding='utf-8-sig')
        assert 'native_validator_section_' not in text
    for name in ('bootstrap_native_provision.py', 'bootstrap_native_deployment.py', 'bootstrap_native_install_request.py'):
        assert 'native_validator_section_' not in (ROOT / 'night_shifts' / name).read_text(encoding='utf-8')
    legacy = (ROOT / 'scripts/native_validator_process_guardian_windows.cs').read_text(encoding='utf-8')
    assert 'false,ProcessFlags,state.Environment,root,ref startup,out state.Child' in legacy
    assert 'HandleListAttribute' not in legacy
    assert not re.search(r'\bMain\s*\(', BOUNDARY.read_text(encoding='utf-8') + WINDOWS.read_text(encoding='utf-8'))
