"""Compiled host -> existing lifetime core -> host/frame/result fault models.

No production input, native process, protected claim or VM. Native process tests
are separate; forgeable fake receipts never confer acceptance.
"""
from __future__ import annotations

import hashlib
import os

import pytest

from night_shifts import bootstrap_native_setup_build as setup_build
from tests.night_shifts.test_bootstrap_native_setup import packet
from tests.night_shifts.test_bootstrap_native_setup_build import profile
from tests.night_shifts.test_native_validator_setup import ROOT, powershell, quote

SCENARIOS = ('prepare', 'publish', 'binding', 'window_hook', 'deadline', 'missing_result', 'bad_result',
    'claim_replay', 'supervisor_args', 'one_shot', 'host_one_shot', 'host_frame', 'host_expired', 'host_counter',
    'host_rollback', 'host_close', 'host_body', 'host_result', 'acquire_fault', 'before_create_fault', 'create_fault',
    'resume_fault', 'wait_fault', 'stop_fault', 'kernel_close_fault', 'receipt_fault', 'file_close_fault',
    'cap_nan', 'cap_infinite', 'cap_equal', 'cap_past', 'native_role_refusal',
    'accounting_empty', 'accounting_root', 'accounting_total_two', 'accounting_active_two',
    'accounting_total_overflow', 'accounting_active_overflow', 'delivered', 'delivered_admission_cost',
    'delivered_expired', 'delivered_frequency', 'delivered_frame', 'delivered_excess', 'outer_claim')
HARNESS = r'''
using System;
using System.Collections.Generic;
using System.Text;
using AiAgent.NativeValidator;
using AiAgent.ValidatorDelivery;
using AiAgent.ValidatorGuardian;
namespace AiAgent.ValidatorSetup {
    internal sealed class ModelTime : IGuardianClock {
        internal double Time=100; internal long Wall=1000;
        public double Seconds { get { return Time; } } public long Unix { get { return Wall; } }
    }
    internal sealed class OffsetTime : IGuardianClock {
        readonly ModelTime time; internal OffsetTime(ModelTime t) { time=t; }
        public double Seconds { get { return time.Time+1000; } } public long Unix { get { return time.Wall; } }
    }
    internal sealed class ModelCounter : ISectionCounter {
        readonly ModelTime time; internal long Rate=1000;
        internal ModelCounter(ModelTime t) { time=t; }
        public long Frequency() { return Rate; } public long Read() { return (long)(time.Time*1000); }
    }
    internal sealed class ModelState {
        internal readonly ModelTime Time=new ModelTime();
        internal readonly List<string> Events=new List<string>();
        internal readonly List<ModelFiles> Files=new List<ModelFiles>();
        internal SetupSupervisorProfile Profile; internal byte[] Packet,Result,Receipt;
        internal bool Claimed,Reached; internal string Fault,Mode="normal";
        internal double HostCap; internal Action<string> Hook;
        internal void Event(string s) { Events.Add(s); if (Hook!=null) Hook(s);
            if (Fault==s) { Reached=true; throw new InvalidOperationException("SYNTHETIC_PRIVATE_CANARY"); } }
        internal SetupReferences Refs() {
            var ids=new Dictionary<string,ulong>(StringComparer.Ordinal); ulong n=100;
            foreach (string name in SetupTransaction.Anchors) ids.Add(name,n++); return new SetupReferences(Profile.Host.Parent,ids);
        }
    }
    internal sealed class ModelRole : ISetupRole {
        readonly ModelState s; internal ModelRole(ModelState state) { s=state; }
        public void Require(SetupHostProfile p,bool watchdog) { s.Event(watchdog?"watchdog_role":"host_role"); }
    }
    internal sealed class ModelFiles : ISetupAttemptFiles {
        readonly ModelState s; readonly bool supervisor; internal bool Closed; internal int Closes;
        internal ModelFiles(ModelState state,bool owner) { s=state; supervisor=owner; s.Files.Add(this); }
        public void Acquire() {
            s.Event(supervisor?"acquire":"host_acquire");
            if (supervisor) { s.Event("claim"); if (s.Claimed) throw new SetupRefused("model_claim_collision"); s.Claimed=true; }
            else SupervisionHarness.Check(s.Claimed);
        }
        public void Reverify() { SupervisionHarness.Check(!Closed); s.Event(supervisor?"verify":"host_verify"); }
        public void BeforeCreate() { SupervisionHarness.Check(s.Claimed); s.Event("before_create"); }
        public void BeforeResume() { SupervisionHarness.Check(s.Claimed); s.Event("before_resume"); }
        public byte[] Packet() { s.Event("packet"); return (byte[])s.Packet.Clone(); }
        public void WriteResult(byte[] raw) { s.Event("result"); s.Result=(byte[])raw.Clone(); }
        public byte[] ReadResult() {
            s.Event("read_result"); if (s.Mode=="missing_result") return null;
            byte[] raw=s.Result==null?null:(byte[])s.Result.Clone(); if (s.Mode=="bad_result" && raw!=null) raw[0]^=1; return raw;
        }
        public void WriteReceipt(byte[] raw) { s.Event("receipt"); s.Receipt=(byte[])raw.Clone(); }
        public void Close() { SupervisionHarness.Check(!Closed); Closed=true; Closes++; s.Event(supervisor?"file_close":"host_close"); }
    }
    internal sealed class ModelFilesFactory : ISetupFilesFactory,ISetupSupervisorFilesFactory {
        readonly ModelState s; internal ModelFilesFactory(ModelState state) { s=state; }
        public ISetupAttemptFiles Host(SetupSupervisorProfile p,SetupClock c,double cap) {
            SupervisionHarness.Check(p.Host.Digest==s.Profile.Host.Digest && p.HostSha256==s.Profile.HostSha256); s.HostCap=cap; return new ModelFiles(s,false);
        }
        public ISetupAttemptFiles Create(SetupSupervisorProfile p,SetupClock c,double cap) { return new ModelFiles(s,true); }
    }
    internal sealed class ModelAction : ISetupOperation {
        readonly ModelState s; internal ModelAction(ModelState state) { s=state; }
        public SetupReferences Run(SetupHostProfile p,SetupClock c,double cap,byte[] packet) {
            s.Event("body"); SupervisionHarness.Check(cap==s.HostCap);
            if (p.Operation=="publish") { var bound=new SetupPayload(p.References,packet,p.PacketBytes,p.PacketSha256); SupervisionHarness.Check(bound.Bound!=null); }
            return s.Refs();
        }
    }
    internal sealed class ModelKernel : IGuardianKernel,IGuardianWindowKernel {
        readonly ModelState s; readonly ModelCounter qpc; readonly object job=new object(),process=new object(),thread=new object();
        internal SectionWindow Window; internal uint ActiveCount; internal int Creates,Stops,Closes; internal uint Exit;
        internal ModelKernel(ModelState state,ModelCounter counter) { s=state; qpc=counter; }
        public void RequireHost(GuardianPlan p) { s.Event("kernel_host"); }
        public object NewJob() { s.Event("job"); return job; }
        public void BindWindow(GuardianPlan p,IGuardianClock clock,double cap) { s.Event("window"); Window=new SectionWindow(clock,cap,p.ApprovedUntilUnix); }
        public ChildPair CreateSuspended(object j,string root) { s.Event("create"); SupervisionHarness.Check(Object.ReferenceEquals(j,job) && Window!=null && s.Claimed); Creates++;
            ActiveCount=1; return new ChildPair {Process=process,Thread=thread,Id=7}; }
        public bool Member(object p,object j) { s.Event("member"); return Object.ReferenceEquals(p,process) && Object.ReferenceEquals(j,job); }
        public uint Resume(object t) {
            s.Event("resume"); if (s.Mode=="deadline") return 1;
            SectionCounterFrame f=SectionCounterFrame.Capture(Window,qpc);
            string[] args={SetupHostFrame.Mode,f.Limit.ToString(),f.Frequency.ToString(),s.Profile.HostBytes.ToString(),s.Profile.HostSha256};
            var entry=new SetupHostEntry(s.Profile.Host,new OffsetTime(s.Time),qpc,new ModelRole(s),new ModelFilesFactory(s),new ModelAction(s));
            Exit=(uint)entry.Run(args); ActiveCount=0; return 1;
        }
        public uint Wait(object p,uint ms) { s.Event("wait"); if (ActiveCount==0) return 0; s.Time.Time+=ms/1000.0; return 258; }
        public uint ExitCode(object p) { s.Event("exit"); return Exit; }
        public uint Active(object j) { s.Event("active"); return ActiveCount; }
        public void Stop(object j) { s.Event("stop"); Stops++; SupervisionHarness.Check(Stops==1); ActiveCount=0; Exit=124; }
        public void Pause(int ms) { s.Time.Time+=ms/1000.0; }
        public void Close(object h) { s.Event("kernel_close"); Closes++; }
    }
    internal sealed class NoFiles : ISetupFiles {
        internal int Calls;
        void Fail() { Calls++; throw new Exception("UNEXPECTED_NATIVE_ACCESS"); }
        public void RequireOperator(string s) { Fail(); } public object Root(string s) { Fail(); return null; }
        public object Open(object p,string n,bool d) { Fail(); return null; } public object Create(object p,string n,bool d) { Fail(); return null; }
        public Stamp Observe(object h,bool d,bool a) { Fail(); return null; } public string[] Names(object h) { Fail(); return null; }
        public void Rewind(object h) { Fail(); } public int Read(object h,byte[] b,int n) { Fail(); return 0; }
        public void Write(object h,byte[] b) { Fail(); } public void Close(object h) { Fail(); }
    }
    public static class SupervisionHarness {
        internal static void Check(bool ok) { if (!ok) throw new Exception("ASSERTION"); }
        static void Case(string name,byte[] packet,string expectedDigest) {
            var s=new ModelState(); SetupHostProfile p=ReviewedSetupHost.Create();
            if (name=="publish") p=new SetupHostProfile(p.Parent,p.Location,p.AttemptId,"publish",20,1600,packet.Length,InstallBoundary.Sha(packet),
                new ModelState {Profile=new SetupSupervisorProfile(p,123,new string('a',64))}.Refs());
            s.Profile=new SetupSupervisorProfile(p,123,new string('a',64)); s.Packet=packet;
            var qpc=new ModelCounter(s.Time); var factory=new ModelFilesFactory(s); var role=new ModelRole(s);
            if (name=="binding") { Check(p.Digest==expectedDigest); SetupResult.Parse(p,SetupResult.Encode(p,s.Refs())); return; }
            if (name=="outer_claim") {
                string claim=Encoding.ASCII.GetString(s.Profile.OuterClaim());
                Check(claim=="{\"policy_sha256\":\""+InstallBoundary.Sha(s.Profile.Policy())+"\",\"profile_sha256\":\""+p.Digest+
                    "\",\"scope\":\"setup_outer_attempt_consumed_not_acceptance\",\"version\":1}\n"); return;
            }
            if (name.StartsWith("delivered",StringComparison.Ordinal)) {
                string[] args={"--setup-supervise-qpc-v1","110000","1000"};
                bool bad=name!="delivered" && name!="delivered_admission_cost";
                if (name=="delivered_expired") args[1]="99000";
                if (name=="delivered_frequency") args[2]="999";
                if (name=="delivered_frame") args[0]="--injected";
                if (name=="delivered_excess") args[1]="999999999";
                if (name=="delivered_admission_cost") s.Hook=delegate(string e) { if (e=="acquire") s.Time.Time+=2; };
                var deliveredKernel=new ModelKernel(s,qpc);
                var delivered=new SetupSupervisorEntry(s.Profile,s.Time,role,factory,deliveredKernel);
                Check(delivered.RunDelivered(args,qpc)==(bad?126:0) && !delivered.MustParkForSupervisor);
                if (bad) Check(s.Files.Count==0 && deliveredKernel.Creates==0);
                else Check(deliveredKernel.Window.Deadline<105 && deliveredKernel.Window.Deadline>104.9 && s.HostCap<1105);
                int count=s.Events.Count; Check(delivered.RunDelivered(args,qpc)==126 && s.Events.Count==count); return;
            }
            if (name.StartsWith("accounting_",StringComparison.Ordinal)) {
                uint total=name=="accounting_empty"?0u:(name=="accounting_root" || name=="accounting_active_overflow"?1u:
                    (name=="accounting_total_overflow"?3u:2u));
                uint active=name=="accounting_root"?1u:(name=="accounting_active_two" || name=="accounting_active_overflow"?2u:0u);
                bool bad=name=="accounting_total_overflow" || name=="accounting_active_overflow", refused=false; uint observed=0;
                try { observed=WindowsSetupSupervisorKernel.ObservedActive(new WindowsGuardianKernel.Accounting {Total=total,Active=active}); }
                catch (GuardianUnknown e) { Check(e.Message=="setup_accounting_unknown"); refused=true; }
                Check(refused==bad && (bad || observed==active)); return;
            }
            if (name.StartsWith("cap_",StringComparison.Ordinal)) {
                var no=new NoFiles(); var clock=new SetupClock(s.Time); double cap=name=="cap_nan"?Double.NaN:(name=="cap_infinite"?Double.PositiveInfinity:(name=="cap_equal"?100:99));
                bool refused=false; try { new SetupTransaction(p.Parent,20,no,clock,cap); } catch (SetupRefused e) { Check(e.Message=="shared_deadline"); refused=true; }
                Check(refused && no.Calls==0); return;
            }
            if (name=="native_role_refusal") {
                bool refused=false; try { new WindowsSetupRole().Require(p,false); } catch (BoundaryRefused e) { Check(e.Message=="enabled_operator_required"); refused=true; }
                Check(refused); return;
            }
            if (name.StartsWith("host_",StringComparison.Ordinal)) {
                s.Claimed=true; string[] args={SetupHostFrame.Mode,"110000","1000","123",new string('a',64)};
                int wanted=0;
                if (name=="host_frame") { args[0]="--injected"; wanted=126; }
                if (name=="host_expired") { args[1]="90000"; wanted=126; }
                if (name=="host_counter") { qpc.Rate=2; wanted=126; }
                if (name=="host_rollback") { s.Hook=delegate(string e) { if (e=="body") s.Time.Time=99; }; wanted=125; }
                if (name=="host_close" || name=="host_body" || name=="host_result") {
                    s.Fault=name=="host_close"?"host_close":(name=="host_body"?"body":"result"); wanted=125;
                }
                var host=new SetupHostEntry(p,new OffsetTime(s.Time),qpc,role,factory,new ModelAction(s));
                Check(host.Run(args)==wanted);
                if (name=="host_one_shot") { int count=s.Events.Count; Check(host.Run(args)==126 && s.Events.Count==count); }
                if (s.Fault!=null) Check(s.Reached); foreach (ModelFiles f in s.Files) Check(f.Closed && f.Closes==1); return;
            }
            int expected=0; bool parked=false;
            if (name=="deadline" || name=="stop_fault") { s.Mode="deadline"; expected=124; }
            if (name=="missing_result" || name=="bad_result") { s.Mode=name; expected=125; }
            if (name=="claim_replay") { s.Claimed=true; expected=126; }
            if (name.EndsWith("_fault",StringComparison.Ordinal)) {
                s.Fault=name.Substring(0,name.Length-6); expected=125;
                parked=name!="acquire_fault" && name!="receipt_fault" && name!="file_close_fault";
            }
            var kernel=new ModelKernel(s,qpc); var entry=new SetupSupervisorEntry(s.Profile,s.Time,role,factory,kernel);
            Check(entry.Run(name=="supervisor_args"?new string[] {"--injected"}:new string[0])==(name=="supervisor_args"?126:expected));
            Check(entry.MustParkForSupervisor==parked); if (s.Fault!=null) Check(s.Reached);
            if (parked) { Check(!s.Files[0].Closed && s.Receipt==null); return; }
            foreach (ModelFiles f in s.Files) Check(f.Closed && f.Closes==1);
            if (name=="claim_replay" || name=="supervisor_args" || name=="acquire_fault") Check(kernel.Creates==0);
            if (expected==0 && name!="supervisor_args") {
                string receipt=Encoding.ASCII.GetString(s.Receipt); Check(receipt.Contains("local_setup_process_observations_not_acceptance") && receipt.Contains("\"result_valid\":true"));
                Check(s.Events.IndexOf("claim")<s.Events.IndexOf("create") && s.Events.IndexOf("before_create")<s.Events.IndexOf("window"));
                Check(kernel.Window.Deadline==115 && s.HostCap<1115 && s.HostCap>1114 && kernel.Creates==1 && kernel.Closes==3);
            }
            if (name=="deadline") Check(kernel.Stops==1 && s.Receipt!=null && s.Result==null);
            if (name=="one_shot") { int count=s.Events.Count; Check(entry.Run(new string[0])==126 && s.Events.Count==count); }
        }
        public static void Run(string name,byte[] packet,string expectedDigest) {
            try { Case(name,packet,expectedDigest); Console.WriteLine(name+"|PASS"); }
            catch (Exception e) { Console.WriteLine(name+"|FAIL:"+e.GetType().Name+":"+e.Message); }
        }
    }
}
'''


@pytest.fixture(scope='module')
def models(tmp_path_factory):
    if os.name != 'nt':
        pytest.skip('Windows CLR composition, not protected execution evidence')
    folder = tmp_path_factory.mktemp('setup-supervision-models')
    paths = [ROOT / 'scripts' / n for n in setup_build.WATCHDOG_SOURCES]
    for name, raw in ((setup_build.HOST_PROFILE_NAME, setup_build.emit_setup_host_profile(profile())),
                      (setup_build.WATCHDOG_PROFILE_NAME, setup_build.emit_setup_watchdog_profile({'bytes': 123, 'sha256': 'a' * 64}))):
        path = folder / name
        path.write_bytes(raw)
        paths.append(path)
    harness = folder / 'models.cs'
    harness.write_text(HARNESS, encoding='utf-8')
    paths.append(harness)
    data = folder / 'inert.packet'
    data.write_bytes(packet().packet)
    digest = hashlib.sha256(setup_build.setup_host_binding(profile())).hexdigest()
    script = ("$ErrorActionPreference='Stop'; Add-Type -Path @(" + ','.join(quote(p) for p in paths) + ') '
        "-ReferencedAssemblies @('System.dll','System.Core.dll','System.Xml.dll','System.Runtime.Serialization.dll'); "
        f'$packet=[IO.File]::ReadAllBytes({quote(data)}); foreach($name in @(' + ','.join(quote(n) for n in SCENARIOS) + ')) {'
        f'[AiAgent.ValidatorSetup.SupervisionHarness]::Run($name,$packet,{quote(digest)})' + '}')
    result = powershell(script)
    assert result.returncode == 0, result.stdout + result.stderr
    answers = {}
    for line in result.stdout.splitlines():
        name, separator, answer = line.partition('|')
        assert separator and name not in answers, line
        answers[name] = answer
    assert set(answers) == set(SCENARIOS)
    return answers


@pytest.mark.parametrize('scenario', SCENARIOS)
def test_setup_supervision_compiled_models(models, scenario):
    assert models[scenario] == 'PASS', models[scenario]


def test_setup_entry_is_fixed_and_window_hook_does_not_change_request_binding():
    text = (ROOT / 'scripts/native_validator_process_guardian.cs').read_text(encoding='utf-8')
    assert 'IGuardianRequestKernel : IGuardianKernel,IGuardianWindowKernel' in text
    assert text.index('launchGate.BeforeCreate()') < text.index('delivery.BindWindow(plan,clock,stopAt)') < text.index('creationAttempted=true')
    assert 'IGuardianRequestKernel' in (ROOT / 'scripts/native_validator_request_guardian.cs').read_text(encoding='utf-8')
    source = (ROOT / 'scripts/native_validator_setup_entry.cs').read_text(encoding='utf-8')
    assert 'new WindowsSetupRole()' in source and 'new NativeSetupOperation()' in source
    assert 'ReviewedSetupHost.Create()' in source and 'cap=frame.Translate(clock,counter)' in source
    assert source.index('cap=frame.Translate(clock,counter)') < source.index('files.Acquire()') < source.index('operation.Run(')
    for name in ('native_validator_setup_entry.cs', 'native_validator_setup_supervisor.cs', 'native_validator_setup_supervisor_windows.cs', 'native_validator_setup_host_files.cs'):
        assert name not in __import__('night_shifts.bootstrap_native_build', fromlist=['SOURCE_NAMES']).SOURCE_NAMES
