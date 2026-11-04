"""Unelevated CLR composition models; no native file/job/process adapter calls.

Compile the actual held-target, process-guardian and composition sources together.
Reuse the existing FAKE backends with one shared synthetic time source. Only
ordinary compiler/model processes and disposable harness text are used. Never
install/run the guardian, worker, carried runtime or provisioning from this test.
"""
from __future__ import annotations

import ast
import base64
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / 'scripts/native_validator_held_guardian.cs'
LAUNCH = ROOT / 'scripts/native_validator_launch_boundary.cs'
GUARDIAN = ROOT / 'scripts/native_validator_process_guardian.cs'
SOURCES = (
    CORE, LAUNCH, ROOT / 'scripts/native_validator_launch_windows.cs',
    GUARDIAN, ROOT / 'scripts/native_validator_process_guardian_windows.cs',
)
SCENARIOS = (
    'construct_no_io', 'normal_exit', 'nonzero_exit', 'exit_259',
    'locks_live_through_cleanup', 'timeout', 'residual', 'stop_progress', 'maximum_budget',
    'acquisition_consumes_budget', 'create_gate_consumes_budget', 'resume_gate_consumes_budget',
    'construction_delay_consumes_budget', 'wall_rollback_no_extension', 'near_approval_cap',
    'one_shot_concurrent', 'public_api_fixed',
    'plan:null', 'plan:small_budget', 'plan:large_budget', 'plan:expired',
    'plan:near_expiry', 'plan:far_expiry', 'plan:bad_root', 'plan:bad_pin',
    'plan:clock_nan', 'plan:clock_infinite',
    'cap:launch_nan', 'cap:launch_infinite', 'cap:launch_past',
    'cap:guardian_nan', 'cap:guardian_infinite', 'cap:guardian_past',
    'cap:launch_cannot_extend', 'cap:guardian_cannot_extend',
    'cap:launch_shorter', 'cap:guardian_shorter', 'cap:guardian_no_run_window',
    'fault:operator', 'fault:initial_hash', 'fault:extra_root', 'fault:dirty_scratch',
    'fault:host', 'fault:host_unknown', 'fault:job_unknown',
    'fault:precreate_hash', 'fault:precreate_window', 'fault:precreate_verify_window',
    'fault:create_unknown', 'fault:created_alias', 'fault:membership',
    'fault:preresume_hash', 'fault:preresume_security', 'fault:late_create',
    'fault:preresume_verify_window', 'fault:resume', 'fault:wait', 'fault:accounting',
    'fault:stop', 'fault:never_empty', 'fault:root_not_signaled',
    'fault:close_thread', 'fault:close_process', 'fault:close_job',
    'fault:late_process_close', 'fault:target_close', 'fault:late_target_close',
    'fault:late_target_wall', 'fault:target_clock_unknown',
    'fault:clock_rollback', 'fault:clock_nan', 'fault:acquire_nan',
)

HARNESS = r'''
using System;
using System.Collections.Generic;
using System.Reflection;
using System.Threading.Tasks;
using AiAgent.ValidatorGuardian;
using AiAgent.ValidatorLaunch;
namespace AiAgent.ValidatorHandoff {
    internal static class SharedModelTime { internal static double Time; internal static long Wall; }
    internal sealed class RecordingKernel : IGuardianKernel {
        internal readonly AiAgent.ValidatorGuardian.TestKernel Inner;
        internal GuardianPlan Seen;
        internal RecordingKernel(AiAgent.ValidatorGuardian.TestKernel value) { Inner=value; }
        public void RequireHost(GuardianPlan plan) { Seen=plan; Inner.RequireHost(plan); }
        public object NewJob() { return Inner.NewJob(); }
        public ChildPair CreateSuspended(object job,string root) { return Inner.CreateSuspended(job,root); }
        public bool Member(object process,object job) { return Inner.Member(process,job); }
        public uint Resume(object thread) { return Inner.Resume(thread); }
        public uint Wait(object process,uint ms) { return Inner.Wait(process,ms); }
        public uint ExitCode(object process) { return Inner.ExitCode(process); }
        public uint Active(object job) { return Inner.Active(job); }
        public void Stop(object job) { Inner.Stop(job); }
        public void Pause(int ms) { Inner.Pause(ms); }
        public void Close(object handle) { Inner.Close(handle); }
    }
    internal sealed class CombinedEnv {
        internal readonly AiAgent.ValidatorLaunch.Env F;
        internal readonly AiAgent.ValidatorGuardian.Env K;
        internal readonly RecordingKernel Kernel;
        internal readonly List<string> Events=new List<string>();
        internal Action<string> Hook;
        internal CombinedEnv() {
            SharedModelTime.Time=100; SharedModelTime.Wall=1000;
            F=new AiAgent.ValidatorLaunch.Env(); K=new AiAgent.ValidatorGuardian.Env(); Kernel=new RecordingKernel(K.Api);
            F.Api.Hook=delegate(string at) { Event("F:"+at); };
            K.Api.Hook=delegate(string at) { Event("K:"+at); };
        }
        void Event(string at) { Events.Add(at); if (Hook!=null) Hook(at); }
        internal HeldProvisionGuardian Make(int seconds=10,long until=1900) {
            return new HeldProvisionGuardian(F.Plan(seconds:seconds,until:until),F.Api,Kernel,K.Clock);
        }
        internal void Closed() { F.Api.AllClosed(); K.Api.AllClosed(); }
    }
    public static class HandoffHarness {
        static readonly string Exe=LaunchBoundary.FileNames[0];
        static void Check(bool yes) { if (!yes) throw new Exception("COMPOSITION_ASSERTION"); }
        static void Failure(Action action,bool unknown,string label=null) {
            try { action(); }
            catch (Exception ex) {
                Check((unknown?ex is HeldGuardianUnknown:ex is HeldGuardianRefused) && (label==null || label==ex.Message));
                Check(!ex.Message.Contains("CANARY")); return;
            }
            throw new Exception("COMPOSITION_EXPECTED_FAILURE");
        }
        static int Count(List<string> events,string name) { return events.FindAll(delegate(string s) { return s==name; }).Count; }
        static void CheckNoRetry(CombinedEnv e,HeldProvisionGuardian run) {
            int n=e.Events.Count; Failure(delegate { run.Run(); },false,"one_shot"); Check(e.Events.Count==n);
        }
        static void PlanCase(string name) {
            var e=new CombinedEnv(); Action action=delegate { e.Make(); }; bool unknown=false;
            switch (name) {
                case "null": action=delegate { new HeldProvisionGuardian(null,e.F.Api,e.Kernel,e.K.Clock); }; break;
                case "small_budget": action=delegate { e.Make(seconds:5); }; break;
                case "large_budget": action=delegate { e.Make(seconds:901); }; break;
                case "expired": action=delegate { e.Make(until:1000); }; break;
                case "near_expiry": action=delegate { e.Make(until:1005); }; break;
                case "far_expiry": action=delegate { e.Make(until:87401); }; break;
                case "bad_root": action=delegate { new HeldProvisionGuardian(e.F.Plan(root:"relative"),e.F.Api,e.Kernel,e.K.Clock); }; break;
                case "bad_pin": e.F.Pins[Exe]=new LaunchFilePin(1,new string('B',64)); break;
                case "clock_nan": SharedModelTime.Time=Double.NaN; unknown=true; break;
                case "clock_infinite": SharedModelTime.Time=Double.PositiveInfinity; unknown=true; break;
                default: throw new Exception("UNKNOWN_PLAN_CASE");
            }
            Failure(action,unknown); Check(e.Events.Count==0);
        }
        static void CapCase(string name) {
            var e=new CombinedEnv(); bool launch=name.StartsWith("launch_",StringComparison.Ordinal);
            if (name=="guardian_no_run_window") {
                var guardian=new ProvisionProcessGuardian(e.K.Plan(),e.Kernel,e.K.Clock,103,null);
                try { guardian.Run(); }
                catch (GuardianRefused ex) { Check(ex.Message=="start_window" && e.Events.Count==0 && guardian.LaunchTargetsReleasable); return; }
                throw new Exception("CAP_EXPECTED_NO_START");
            }
            double bound=name.EndsWith("nan",StringComparison.Ordinal)?Double.NaN:
                (name.EndsWith("infinite",StringComparison.Ordinal)?Double.PositiveInfinity:100);
            if (name.EndsWith("cannot_extend",StringComparison.Ordinal) || name.EndsWith("shorter",StringComparison.Ordinal)) {
                bool shorter=name.EndsWith("shorter",StringComparison.Ordinal); bound=shorter?(launch?103:108):1000;
                if (launch) {
                    var gate=new LaunchBoundary(e.F.Plan(),e.F.Api,e.F.Clock,bound); SharedModelTime.Time=shorter?104:111;
                    try { gate.Acquire(); }
                    catch (LaunchRefused ex) { Check(ex.Message=="deadline" && e.Events.Count==0); return; }
                } else {
                    e.K.Api.NeverExit=true;
                    var guardian=new ProvisionProcessGuardian(e.K.Plan(),e.Kernel,e.K.Clock,bound,null);
                    LocalProcessObservation answer=guardian.Run();
                    Check(answer.End==LocalProcessEnd.DeadlineStopped && SharedModelTime.Time<=(shorter?103:105)+0.001);
                    e.Closed(); return;
                }
                throw new Exception("CAP_EXPECTED_FAILURE");
            }
            try {
                if (launch) new LaunchBoundary(e.F.Plan(),e.F.Api,e.F.Clock,bound);
                else new ProvisionProcessGuardian(e.K.Plan(),e.Kernel,e.K.Clock,bound,null);
            } catch (Exception ex) {
                Check((launch?ex is LaunchRefused:ex is GuardianRefused) && ex.Message=="shared_deadline");
                Check(e.Events.Count==0); return;
            }
            throw new Exception("CAP_EXPECTED_REFUSAL");
        }
        static void FaultCase(string name) {
            var e=new CombinedEnv(); var run=e.Make(); bool retained=false,unknown=false; string label=null;
            int rewinds=0;
            switch (name) {
                case "operator": e.F.Api.Operator=false; label="targets_refused"; break;
                case "initial_hash": e.F.Api.Data[Exe][0]^=1; label="targets_refused"; break;
                case "extra_root": e.F.Api.RootNames="extra"; label="targets_refused"; break;
                case "dirty_scratch": e.F.Api.DirtyScratch=true; label="targets_refused"; break;
                case "host": e.K.Api.Host=false; label="process_refused"; break;
                case "host_unknown": e.K.Api.Fault="host"; unknown=true; label="handoff_unknown"; break;
                case "job_unknown": e.K.Api.Fault="job"; unknown=true; label="handoff_unknown"; break;
                case "precreate_hash": e.Hook=delegate(string at) { if (at=="K:host") e.F.Api.Data[Exe][0]^=1; }; label="process_refused"; break;
                case "precreate_window": e.Hook=delegate(string at) { if (at=="K:host") SharedModelTime.Time=105; }; label="process_refused"; break;
                case "precreate_verify_window":
                    e.Hook=delegate(string at) { if (at=="F:rewind:"+Exe && ++rewinds==2) SharedModelTime.Time=105; };
                    label="process_refused"; break;
                case "create_unknown": e.K.Api.Fault="create"; retained=true; break;
                case "created_alias": e.K.Api.PairMode="alias"; retained=true; break;
                case "membership": e.K.Api.MemberValue=false; retained=true; break;
                case "preresume_hash": e.Hook=delegate(string at) { if (at=="K:member") e.F.Api.Data[Exe][0]^=1; }; retained=true; break;
                case "preresume_security": e.Hook=delegate(string at) { if (at=="K:member") e.F.Api.Meta[Exe].Security="CHANGED"; }; retained=true; break;
                case "late_create": e.Hook=delegate(string at) { if (at=="K:create") SharedModelTime.Time=106; }; retained=true; break;
                case "preresume_verify_window":
                    e.Hook=delegate(string at) { if (at=="F:rewind:"+Exe && ++rewinds==3) SharedModelTime.Time=105; };
                    retained=true; break;
                case "resume": e.K.Api.ResumeValue=0; retained=true; break;
                case "wait": e.K.Api.WaitFailure=UInt32.MaxValue; retained=true; break;
                case "accounting": e.K.Api.Fault="active"; retained=true; break;
                case "stop": e.K.Api.NeverExit=true; e.K.Api.StopFails=true; retained=true; break;
                case "never_empty": e.K.Api.NeverExit=true; e.K.Api.StopNeverEmpty=true; retained=true; break;
                case "root_not_signaled": e.K.Api.NeverExit=true; e.K.Api.RootNeverSignaled=true; retained=true; break;
                case "close_thread": e.K.Api.CloseFault="thread"; retained=true; break;
                case "close_process": e.K.Api.CloseFault="process"; retained=true; break;
                case "close_job": e.K.Api.CloseFault="job"; retained=true; break;
                case "late_process_close": e.Hook=delegate(string at) { if (at=="K:close:job") SharedModelTime.Time=111; }; retained=true; break;
                case "target_close": e.F.Api.CloseFault=Exe; unknown=true; label="target_close_unknown"; break;
                case "late_target_close": e.Hook=delegate(string at) { if (at=="F:close:@") SharedModelTime.Time=111; }; unknown=true; label="deadline_outcome_unknown"; break;
                case "late_target_wall": e.Hook=delegate(string at) { if (at=="F:close:@") SharedModelTime.Wall=1900; }; unknown=true; label="deadline_outcome_unknown"; break;
                case "target_clock_unknown": e.Hook=delegate(string at) { if (at=="F:close:@") SharedModelTime.Time=Double.NaN; }; unknown=true; label="clock_unknown"; break;
                case "clock_rollback": e.Hook=delegate(string at) { if (at=="K:member") SharedModelTime.Time=99; }; retained=true; break;
                case "clock_nan": e.Hook=delegate(string at) { if (at=="K:member") SharedModelTime.Time=Double.NaN; }; retained=true; break;
                case "acquire_nan": SharedModelTime.Time=Double.NaN; unknown=true; label="handoff_unknown"; break;
                default: throw new Exception("UNKNOWN_FAULT_CASE");
            }
            if (retained) { unknown=true; label="targets_retained_outcome_unknown"; }
            Failure(delegate { run.Run(); },unknown,label); Check(run.LaunchLeaseRetained==retained);
            e.K.Api.AllClosed(); if (retained) e.F.Api.AllLive(); else e.F.Api.AllClosed();
            if (name.StartsWith("preresume",StringComparison.Ordinal) || name=="late_create") Check(e.K.Api.Resumes==0);
            if (name.StartsWith("precreate",StringComparison.Ordinal)) Check(!e.K.Api.Events.Contains("create"));
            Check(e.K.Api.Stops<=1); CheckNoRetry(e,run);
        }
        static void Scenario(string name) {
            if (name.StartsWith("plan:",StringComparison.Ordinal)) { PlanCase(name.Substring(5)); return; }
            if (name.StartsWith("fault:",StringComparison.Ordinal)) { FaultCase(name.Substring(6)); return; }
            if (name.StartsWith("cap:",StringComparison.Ordinal)) { CapCase(name.Substring(4)); return; }
            var e=new CombinedEnv(); var run=e.Make(); int rewinds=0;
            switch (name) {
                case "construct_no_io": Check(e.Events.Count==0 && !run.LaunchLeaseRetained); return;
                case "nonzero_exit": e.K.Api.Code=7; break;
                case "exit_259": e.K.Api.Code=259; break;
                case "timeout": e.K.Api.NeverExit=true; break;
                case "wall_rollback_no_extension": e.K.Api.NeverExit=true; SharedModelTime.Wall=0; break;
                case "residual": e.K.Api.Residue=true; break;
                case "stop_progress": e.K.Api.Residue=true; e.K.Api.StopPolls=3; break;
                case "maximum_budget": e.K.Api.NeverExit=true; run=e.Make(seconds:900); break;
                case "near_approval_cap": e.K.Api.NeverExit=true; run=e.Make(seconds:900,until:1008); break;
                case "construction_delay_consumes_budget": e.K.Api.NeverExit=true; SharedModelTime.Time=104; break;
                case "acquisition_consumes_budget": case "create_gate_consumes_budget": case "resume_gate_consumes_budget":
                    e.K.Api.NeverExit=true; int target=name=="acquisition_consumes_budget"?1:(name=="create_gate_consumes_budget"?2:3);
                    e.Hook=delegate(string at) { if (at=="F:rewind:"+Exe && ++rewinds==target) SharedModelTime.Time+=3; }; break;
                case "locks_live_through_cleanup":
                    e.K.Api.Residue=true; e.K.Api.StopPolls=2;
                    e.Hook=delegate(string at) { if (at.StartsWith("K:",StringComparison.Ordinal)) e.F.Api.AllLive(); }; break;
                case "one_shot_concurrent":
                    Func<int> attempt=delegate { try { run.Run(); return 1; } catch (HeldGuardianRefused ex) { Check(ex.Message=="one_shot"); return 0; } };
                    Task<int> a=Task.Run(attempt),b=Task.Run(attempt); Task.WaitAll(a,b);
                    Check(a.Result+b.Result==1 && e.K.Api.Resumes==1 && !run.LaunchLeaseRetained); e.Closed(); return;
                case "public_api_fixed":
                    ConstructorInfo[] ctors=typeof(HeldProvisionGuardian).GetConstructors();
                    Check(ctors.Length==1 && ctors[0].GetParameters().Length==1 && ctors[0].GetParameters()[0].ParameterType==typeof(LaunchPlan));
                    Check(!typeof(IDisposable).IsAssignableFrom(typeof(HeldProvisionGuardian)));
                    foreach (MethodInfo method in typeof(HeldProvisionGuardian).GetMethods(BindingFlags.Public|BindingFlags.Instance|BindingFlags.DeclaredOnly))
                        Check(method.Name=="Run" || method.Name=="get_LaunchLeaseRetained");
                    return;
                case "normal_exit": break;
                default: throw new Exception("UNKNOWN_MODEL_CASE");
            }
            LocalProcessObservation answer=run.Run(); e.Closed(); Check(!run.LaunchLeaseRetained && answer.EmptyObserved && answer.Resumed);
            GuardianPlan seen=e.Kernel.Seen; LaunchPlan expected=e.F.Plan();
            Check(seen.Root==expected.Root && seen.OperatorSid==expected.OperatorSid && seen.InstallationId==expected.InstallationId &&
                seen.ApprovalSha256==expected.ApprovalSha256 && seen.ApprovedUntilUnix==(name=="near_approval_cap"?1008:expected.ApprovedUntilUnix) &&
                seen.BudgetSeconds==((name=="maximum_budget" || name=="near_approval_cap")?900:10));
            Check(answer.InstallationId==expected.InstallationId && answer.ApprovalSha256==expected.ApprovalSha256);
            Check(e.K.Api.Resumes==1 && e.K.Api.Stops<=1 && answer.ProcessId==42);
            int host=e.Events.IndexOf("K:host"),create=e.Events.IndexOf("K:create"),resume=e.Events.IndexOf("K:resume");
            Check(host>0 && create>host && resume>create);
            foreach (string file in LaunchBoundary.FileNames) {
                string eventName="F:rewind:"+file; Check(Count(e.Events,eventName)==3);
                Check(e.Events.IndexOf(eventName)<host);
                int precreate=e.Events.FindIndex(host+1,delegate(string s) { return s==eventName; });
                int preresume=e.Events.FindIndex(create+1,delegate(string s) { return s==eventName; });
                Check(precreate>host && precreate<create && preresume>create && preresume<resume);
                Check(Count(e.Events,"F:open:"+file)==1);
            }
            Check(e.F.Api.Handles.Count==7 && e.Events.IndexOf("F:close:"+LaunchBoundary.FileNames[3])>e.Events.IndexOf("K:close:job"));
            for (int i=0;i<e.F.Api.Handles.Count;i++) {
                string expectedClose="F:close:"+e.F.Api.Handles[e.F.Api.Handles.Count-1-i].Name;
                Check(e.Events[e.Events.Count-e.F.Api.Handles.Count+i]==expectedClose);
            }
            if (e.K.Api.NeverExit) {
                double stop=name=="maximum_budget"?995:(name=="near_approval_cap"?103:105);
                Check(answer.End==LocalProcessEnd.DeadlineStopped && SharedModelTime.Time<=stop+0.001 && e.K.Api.Stops==1);
            } else if (e.K.Api.Stops!=0) Check(answer.End==LocalProcessEnd.ResidualTreeStopped);
            else Check(answer.End==LocalProcessEnd.RootExited && answer.ExitCode==e.K.Api.Code);
            Check(LocalProcessObservation.Scope=="local_process_observations_only_not_install_acceptance");
            CheckNoRetry(e,run);
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


def _backend(path: Path) -> str:
    """Read literal model text, without importing/executing the sibling test."""
    tree = ast.parse(path.read_text(encoding='utf-8'))
    values = [
        ast.literal_eval(node.value) for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == 'HARNESS' for target in node.targets)
    ]
    assert len(values) == 1 and isinstance(values[0], str)
    text = values[0]
    old = 'internal double Time=100; internal long Wall=1000;'
    assert text.count(old) == 1
    shared = (
        'internal double Time { get { return AiAgent.ValidatorHandoff.SharedModelTime.Time; } '
        'set { AiAgent.ValidatorHandoff.SharedModelTime.Time=value; } } '
        'internal long Wall { get { return AiAgent.ValidatorHandoff.SharedModelTime.Wall; } '
        'set { AiAgent.ValidatorHandoff.SharedModelTime.Wall=value; } }'
    )
    return text.replace(old, shared).replace('__CASES__', 'new string[0]')


def _quote(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


@pytest.fixture(scope='module')
def models(tmp_path_factory):
    if os.name != 'nt':
        pytest.skip('requires Windows CLR compiler; not native handoff evidence')
    compiler = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    assert compiler.is_file(), 'required Windows model compiler unavailable'
    folder = tmp_path_factory.mktemp('validator-held-guardian-model')
    paths = list(SOURCES)
    for role in ('launch_boundary', 'process_guardian'):
        backend = folder / f'{role}_model.cs'
        backend.write_text(_backend(Path(__file__).with_name(f'test_native_validator_{role}.py')), encoding='utf-8')
        paths.append(backend)
    harness = folder / 'composition_models.cs'
    cases = 'new string[] {' + ','.join(json.dumps(name) for name in SCENARIOS) + '}'
    harness.write_text(HARNESS.replace('__CASES__', cases), encoding='utf-8')
    paths.append(harness)
    script = (
        "$ErrorActionPreference='Stop'; "
        'Add-Type -Path @(' + ','.join(_quote(path) for path in paths) + ') -ErrorAction Stop; '
        '[AiAgent.ValidatorHandoff.HandoffHarness]::RunAll()'
    )
    encoded = base64.b64encode(script.encode('utf-16le')).decode('ascii')
    completed = subprocess.run(
        [str(compiler), '-NoLogo', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
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
def test_held_guardian_clr_models(models, scenario):
    assert models[scenario] == 'PASS'


def test_composition_has_no_second_plan_or_public_unlock_path():
    text = CORE.read_text(encoding='utf-8')
    assert 'public HeldProvisionGuardian(LaunchPlan value)' in text
    assert 'new GuardianPlan(value.Root,value.OperatorSid,value.InstallationId,' in text
    assert 'value.ApprovalSha256,value.ApprovedUntilUnix,value.BudgetSeconds)' in text
    assert 'guardian.LaunchTargetsReleasable' in text
    assert 'HeldLaunchLease current=lease; lease=null;' in text
    assert 'targets_retained_outcome_unknown' in text
    assert not re.search(r'public\s+(?:void\s+Dispose|HeldLaunchLease|GuardianPlan)\b', text)
    assert '~HeldProvisionGuardian' not in text and 'using (lease' not in text


def test_internal_launch_gates_and_shared_caps_precede_process_instructions():
    guardian = GUARDIAN.read_text(encoding='utf-8')
    launch = LAUNCH.read_text(encoding='utf-8')
    composition = CORE.read_text(encoding='utf-8')
    assert guardian.index('launchGate.BeforeCreate()') < guardian.index('creationAttempted=true;') < guardian.index('child=api.CreateSuspended(')
    assert guardian.index('launchGate.BeforeResume()') < guardian.index('api.Resume(child.Thread)')
    assert 'if (!creationAttempted && closeKnown && windowKnown) LaunchTargetsReleasable=true;' in guardian
    for text in (guardian, launch):
        assert 'limit=Math.Min(limit,bound)' in text
        assert 'Double.IsNaN(bound) || Double.IsInfinity(bound) || bound<=now' in text
    assert 'deadline-ProvisionProcessGuardian.StopReserveSeconds' in composition
    assert 'clock.Seconds>=deadline || clock.Unix>=approvedUntil' in composition
    assert 'now<last' in composition


def test_no_starter_approval_claim_python_or_vm_is_added():
    text = CORE.read_text(encoding='utf-8')
    assert 'AiAgent.NativeValidator' not in text and 'night_shifts' not in text
    for forbidden in ('Assembly.Load', 'LoadLibrary', 'DllImport', 'Process.Start', 'CreateProcessW', 'CreateClaim', 'File.Write'):
        assert forbidden not in text
    assert not re.search(r'\b(?:Main|ShellExecute|SetSecurityInfo|DeleteFile)\s*\(', text)
    assert 'authenticated permanent approval MUST precede' in text and 'No Main or tool' in text


def test_composition_source_visible_but_not_deployed_or_wired():
    ignore = (ROOT / '.gitignore').read_text(encoding='utf-8').splitlines()
    exception = '!/' + CORE.relative_to(ROOT).as_posix()
    assert ignore.count(exception) == 1 and ignore.index(exception) > ignore.index('/scripts/*')
    for path in [*(ROOT / 'runtime').glob('*.py'), *(ROOT / 'scripts').glob('*.ps1')]:
        assert 'native_validator_held_guardian' not in path.read_text(encoding='utf-8-sig')
    for name in ('bootstrap_native_deployment.py', 'bootstrap_native_provision.py'):
        assert 'native_validator_held_guardian' not in (ROOT / 'night_shifts' / name).read_text(encoding='utf-8')
