"""Unelevated C# guardian models. NEVER call the new native process adapter.

Compile the actual sources with fake jobs/processes/tokens/time. No child from
this guardian, installed worker, provisioning, native job, elevation or VM is
created. Only ordinary CLR compiler/model processes and temporary harness data.
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
CORE = ROOT / 'scripts/native_validator_process_guardian.cs'
WINDOWS = ROOT / 'scripts/native_validator_process_guardian_windows.cs'
SCENARIOS = (
    'construct_no_io', 'normal_exit', 'nonzero_exit', 'exit_259_is_valid',
    'deadline', 'maximum_budget', 'wall_expiry', 'wall_backwards_no_extension',
    'residual_child', 'stop_progress', 'hold_handles_until_empty', 'close_order',
    'one_shot_success', 'one_shot_failure', 'one_shot_concurrent',
    'no_install_acceptance', 'no_wait_deadline_renewal',
    'plan:null', 'plan:relative', 'plan:unc', 'plan:dot', 'plan:ads',
    'plan:trailing', 'plan:device', 'plan:reserved', 'plan:long',
    'plan:sid', 'plan:id', 'plan:approval', 'plan:budget_small', 'plan:budget_large',
    'plan:expired', 'plan:near_expiry', 'plan:window',
    'fault:host', 'fault:job', 'fault:create', 'fault:null_pair',
    'fault:null_process', 'fault:null_thread', 'fault:alias', 'fault:pid_zero',
    'fault:not_member', 'fault:initial_zero', 'fault:initial_two', 'fault:initial_three',
    'fault:resume_zero', 'fault:resume_two', 'fault:resume_failed',
    'fault:wait_failed', 'fault:wait_exception', 'fault:exit_code',
    'fault:no_wait_progress', 'fault:stop', 'fault:stop_never_empty',
    'fault:root_not_signaled', 'fault:close_thread', 'fault:close_process', 'fault:close_job',
    'fault:role_expiry', 'fault:create_expiry', 'fault:late_resume',
    'fault:clock_nan', 'fault:late_close', 'fault:accounting', 'fault:pause',
    'environment:exact', 'environment:terminated', 'environment:system_mismatch',
    'environment:bad_windows', 'environment:fixed_command', 'security:object_descriptor',
    'layout:security', 'layout:basic_limits', 'layout:limits', 'layout:accounting',
    'layout:startup', 'layout:startup_ex', 'layout:process_info',
)

HARNESS = r'''
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Security.AccessControl;
using System.Threading.Tasks;
namespace AiAgent.ValidatorGuardian {
    internal sealed class TestClock : IGuardianClock {
        internal double Time=100; internal long Wall=1000;
        public double Seconds { get { return Time; } }
        public long Unix { get { return Wall; } }
    }
    internal sealed class TestHandle {
        internal string Kind; internal bool Closed; internal int Closes;
    }
    internal sealed class TestKernel : IGuardianKernel {
        internal readonly TestClock Clock;
        internal readonly List<TestHandle> Handles=new List<TestHandle>();
        internal readonly List<string> Events=new List<string>();
        internal readonly List<uint> Waits=new List<uint>();
        internal Action<string> Hook;
        internal string Fault,PairMode,CloseFault;
        internal bool Host=true,MemberValue=true,NeverExit,Residue,NoWaitProgress,StopFails,StopNeverEmpty,RootNeverSignaled;
        internal bool Running,Done,Stopped;
        internal int Stops,Resumes,StopPolls;
        internal uint ResumeValue=1,Code,WaitFailure;
        internal uint? InitialCount;
        internal double ExitAt=100.1;
        internal TestKernel(TestClock clock) { Clock=clock; }
        void Event(string name) {
            Events.Add(name); if (Hook!=null) Hook(name);
            if (name==Fault) throw new InvalidOperationException("SYNTHETIC_NATIVE_CANARY");
        }
        TestHandle Make(string kind) { var h=new TestHandle {Kind=kind}; Handles.Add(h); return h; }
        static void Live(object value,string kind) {
            var h=(TestHandle)value; GuardianHarness.Check(!h.Closed && h.Kind==kind);
        }
        public void RequireHost(GuardianPlan plan) {
            Event("host"); if (!Host) throw new GuardianRefused("protected_host_role");
        }
        public object NewJob() { Event("job"); return Make("job"); }
        public ChildPair CreateSuspended(object job,string root) {
            Live(job,"job"); GuardianHarness.Check(root==@"C:\Private Anchor"); Event("create");
            if (PairMode=="null_pair") return null;
            object process=PairMode=="null_process"?null:Make("process");
            object thread=PairMode=="null_thread"?null:(PairMode=="alias"?process:Make("thread"));
            return new ChildPair {Process=process,Thread=thread,Id=PairMode=="pid_zero"?0u:42u};
        }
        public bool Member(object process,object job) { Live(process,"process"); Live(job,"job"); Event("member"); return MemberValue; }
        public uint Resume(object thread) {
            Live(thread,"thread"); Event("resume"); Resumes++; Running=true; return ResumeValue;
        }
        void NaturalExit() { if (Running && !NeverExit && Clock.Time>=ExitAt) Done=true; }
        public uint Wait(object process,uint ms) {
            Live(process,"process"); Event(ms==0?"wait_zero":"wait"); Waits.Add(ms);
            if (ms==0) return Done && !RootNeverSignaled?0u:258u;
            if (WaitFailure!=0) return WaitFailure;
            if (!NoWaitProgress) {
                double end=Clock.Time+ms/1000.0;
                Clock.Time=!NeverExit && ExitAt<=end?Math.Max(Clock.Time,ExitAt):end;
            }
            NaturalExit(); return Done?0u:258u;
        }
        public uint ExitCode(object process) { Live(process,"process"); Event("exit_code"); GuardianHarness.Check(Done); return Code; }
        public uint Active(object job) {
            Live(job,"job"); Event("active");
            if (!Running && !Stopped && InitialCount.HasValue) return InitialCount.Value;
            if (Stopped && !StopNeverEmpty) {
                if (StopPolls>0) { StopPolls--; return 1; }
                Done=true; Residue=false;
            }
            NaturalExit(); return !Done?1u:(Residue?1u:0u);
        }
        public void Stop(object job) {
            Live(job,"job"); Event("stop"); Stops++;
            if (StopFails) throw new GuardianUnknown("stop_unknown");
            Stopped=true;
        }
        public void Pause(int ms) {
            Event("pause"); GuardianHarness.Check(ms>=1 && ms<=20); Clock.Time+=ms/1000.0;
        }
        public void Close(object handle) {
            var h=(TestHandle)handle; GuardianHarness.Check(!h.Closed); h.Closed=true; h.Closes++;
            Event("close:"+h.Kind);
            if (h.Kind=="job") { Done=true; Residue=false; }
            if (h.Kind==CloseFault) throw new InvalidOperationException("SYNTHETIC_CLOSE_CANARY");
        }
        internal void AllClosed() { foreach (TestHandle h in Handles) GuardianHarness.Check(h.Closed && h.Closes==1); }
    }
    internal sealed class Env {
        internal TestClock Clock=new TestClock(); internal TestKernel Api;
        internal Env() { Api=new TestKernel(Clock); }
        internal GuardianPlan Plan(string root=@"C:\Private Anchor",string sid="S-1-5-21-1-2-3-1001",
            string id="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",string approval="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            long until=1900,int seconds=10) { return new GuardianPlan(root,sid,id,approval,until,seconds); }
        internal ProvisionProcessGuardian Guardian() { return new ProvisionProcessGuardian(Plan(),Api,Clock); }
    }
    public static class GuardianHarness {
        internal static void Check(bool yes) { if (!yes) throw new Exception("MODEL_ASSERTION"); }
        static void Failure(Action action,bool refused,string label=null) {
            try { action(); }
            catch (Exception ex) {
                Check((refused?ex is GuardianRefused:ex is GuardianUnknown) && (label==null || ex.Message==label));
                Check(!ex.Message.Contains("CANARY")); return;
            }
            throw new Exception("MODEL_EXPECTED_FAILURE");
        }
        static void PlanCase(string name) {
            var e=new Env(); Action run=delegate { e.Guardian(); };
            switch (name) {
                case "null": run=delegate { new ProvisionProcessGuardian(null,e.Api,e.Clock); }; break;
                case "relative": run=delegate { new ProvisionProcessGuardian(e.Plan(root:"relative"),e.Api,e.Clock); }; break;
                case "unc": run=delegate { new ProvisionProcessGuardian(e.Plan(root:@"\\host\anchor"),e.Api,e.Clock); }; break;
                case "dot": run=delegate { new ProvisionProcessGuardian(e.Plan(root:@"C:\Anchor\..\x"),e.Api,e.Clock); }; break;
                case "ads": run=delegate { new ProvisionProcessGuardian(e.Plan(root:@"C:\Anchor:ads"),e.Api,e.Clock); }; break;
                case "trailing": run=delegate { new ProvisionProcessGuardian(e.Plan(root:@"C:\Anchor "),e.Api,e.Clock); }; break;
                case "device": run=delegate { new ProvisionProcessGuardian(e.Plan(root:@"\\?\C:\Anchor"),e.Api,e.Clock); }; break;
                case "reserved": run=delegate { new ProvisionProcessGuardian(e.Plan(root:@"C:\NUL.txt"),e.Api,e.Clock); }; break;
                case "long": run=delegate { new ProvisionProcessGuardian(e.Plan(root:@"C:\"+new string('a',200)),e.Api,e.Clock); }; break;
                case "sid": run=delegate { new ProvisionProcessGuardian(e.Plan(sid:"S-1-5-18"),e.Api,e.Clock); }; break;
                case "id": run=delegate { new ProvisionProcessGuardian(e.Plan(id:new string('A',32)),e.Api,e.Clock); }; break;
                case "approval": run=delegate { new ProvisionProcessGuardian(e.Plan(approval:"self-approved"),e.Api,e.Clock); }; break;
                case "budget_small": run=delegate { new ProvisionProcessGuardian(e.Plan(seconds:5),e.Api,e.Clock); }; break;
                case "budget_large": run=delegate { new ProvisionProcessGuardian(e.Plan(seconds:901),e.Api,e.Clock); }; break;
                case "expired": run=delegate { new ProvisionProcessGuardian(e.Plan(until:1000),e.Api,e.Clock); }; break;
                case "near_expiry": run=delegate { new ProvisionProcessGuardian(e.Plan(until:1005),e.Api,e.Clock); }; break;
                case "window": run=delegate { new ProvisionProcessGuardian(e.Plan(until:87401),e.Api,e.Clock); }; break;
                default: throw new Exception("UNKNOWN_MODEL_CASE");
            }
            Failure(run,true); Check(e.Api.Events.Count==0);
        }
        static void FaultCase(string name) {
            var e=new Env(); bool refused=false; string label=null;
            switch (name) {
                case "host": e.Api.Host=false; refused=true; label="protected_host_role"; break;
                case "job": e.Api.Fault="job"; label="guardian_unknown"; break;
                case "create": e.Api.Fault="create"; label="guardian_unknown"; break;
                case "null_pair": e.Api.PairMode=name; label="child_unknown"; break;
                case "null_process": e.Api.PairMode=name; label="child_handles_unknown"; break;
                case "null_thread": e.Api.PairMode=name; label="child_handles_unknown"; break;
                case "alias": e.Api.PairMode=name; label="child_handles_unknown"; break;
                case "pid_zero": e.Api.PairMode=name; label="child_handles_unknown"; break;
                case "not_member": e.Api.MemberValue=false; label="atomic_membership_unknown"; break;
                case "initial_zero": e.Api.InitialCount=0; label="atomic_membership_unknown"; break;
                case "initial_two": e.Api.InitialCount=2; label="atomic_membership_unknown"; break;
                case "initial_three": e.Api.InitialCount=3; label="job_accounting_unknown"; break;
                case "resume_zero": e.Api.ResumeValue=0; label="resume_unknown"; break;
                case "resume_two": e.Api.ResumeValue=2; label="resume_unknown"; break;
                case "resume_failed": e.Api.ResumeValue=UInt32.MaxValue; label="resume_unknown"; break;
                case "wait_failed": e.Api.WaitFailure=UInt32.MaxValue; label="root_wait_unknown"; break;
                case "wait_exception": e.Api.Fault="wait"; label="guardian_unknown"; break;
                case "exit_code": e.Api.Fault="exit_code"; label="guardian_unknown"; break;
                case "no_wait_progress": e.Api.NeverExit=true; e.Api.NoWaitProgress=true; label="wait_progress_unknown"; break;
                case "stop": e.Api.NeverExit=true; e.Api.StopFails=true; break;
                case "stop_never_empty": e.Api.NeverExit=e.Api.StopNeverEmpty=true; break;
                case "root_not_signaled": e.Api.RootNeverSignaled=true; break;
                case "close_thread": e.Api.CloseFault="thread"; label="close_unknown"; break;
                case "close_process": e.Api.CloseFault="process"; label="close_unknown"; break;
                case "close_job": e.Api.CloseFault="job"; label="close_unknown"; break;
                case "role_expiry": e.Api.Hook=delegate(string at) { if (at=="host") e.Clock.Time=105; }; refused=true; label="start_window"; break;
                case "create_expiry": e.Api.Hook=delegate(string at) { if (at=="create") e.Clock.Time=105; }; refused=true; label="start_window"; break;
                case "late_resume": e.Api.Hook=delegate(string at) { if (at=="resume") e.Clock.Time=111; }; label="deadline_outcome_unknown"; break;
                case "clock_nan": e.Api.Hook=delegate(string at) { if (at=="host") e.Clock.Time=Double.NaN; }; label="clock_unknown"; break;
                case "late_close": e.Api.Hook=delegate(string at) { if (at=="close:job") e.Clock.Time=111; }; label="deadline_outcome_unknown"; break;
                case "accounting": e.Api.Fault="active"; label="termination_unknown"; break;
                case "pause": e.Api.NeverExit=true; e.Api.StopPolls=3; e.Api.Fault="pause"; label="termination_unknown"; break;
                default: throw new Exception("UNKNOWN_MODEL_CASE");
            }
            var guardian=e.Guardian(); Failure(delegate { guardian.Run(); },refused,label);
            e.Api.AllClosed(); Failure(delegate { guardian.Run(); },true,"one_shot"); Check(e.Api.Stops<=1);
            if (name=="create_expiry" || name=="not_member") Check(e.Api.Resumes==0);
        }
        static void EnvironmentCase(string name) {
            const string root=@"C:\Private Anchor";
            if (name=="system_mismatch") {
                Failure(delegate { WindowsGuardianKernel.EnvironmentBlock(root,@"C:\Windows",@"C:\Other"); },true,"system_directory"); return;
            }
            if (name=="bad_windows") {
                Failure(delegate { WindowsGuardianKernel.EnvironmentBlock(root,@"C:\Windows:ads",@"C:\Windows:ads\System32"); },true); return;
            }
            if (name=="fixed_command") {
                Check(WindowsGuardianKernel.Command(root)=="\"C:\\Private Anchor\\validator-provision-worker.exe\" --provision-once"); return;
            }
            string block=WindowsGuardianKernel.EnvironmentBlock(root,@"C:\Windows",@"C:\Windows\System32");
            if (name=="terminated") { Check(block.EndsWith("\0\0",StringComparison.Ordinal) && block.Split('\0').Length==7); return; }
            var values=new Dictionary<string,string>(StringComparer.Ordinal);
            foreach (string line in block.Split('\0')) {
                if (line.Length==0) continue; int equal=line.IndexOf('='); values.Add(line.Substring(0,equal),line.Substring(equal+1));
            }
            Check(values.Count==5 && values["PATH"]==@"C:\Windows\System32" && values["SystemRoot"]==@"C:\Windows" &&
                values["WINDIR"]==@"C:\Windows" && values["TEMP"]==root+@"\scratch" && values["TMP"]==root+@"\scratch");
        }
        static void Layout(string name) {
            Check(IntPtr.Size==8);
            switch (name) {
                case "security": Check(Marshal.SizeOf(typeof(WindowsGuardianKernel.SecurityAttributes))==24); break;
                case "basic_limits": Check(Marshal.SizeOf(typeof(WindowsGuardianKernel.JobBasicLimits))==64); break;
                case "limits": Check(Marshal.SizeOf(typeof(WindowsGuardianKernel.JobLimits))==144); break;
                case "accounting": Check(Marshal.SizeOf(typeof(WindowsGuardianKernel.Accounting))==48 && Marshal.OffsetOf(typeof(WindowsGuardianKernel.Accounting),"Active").ToInt32()==40); break;
                case "startup": Check(Marshal.SizeOf(typeof(WindowsGuardianKernel.Startup))==104); break;
                case "startup_ex": Check(Marshal.SizeOf(typeof(WindowsGuardianKernel.StartupEx))==112 && Marshal.OffsetOf(typeof(WindowsGuardianKernel.StartupEx),"Attributes").ToInt32()==104); break;
                case "process_info": Check(Marshal.SizeOf(typeof(WindowsGuardianKernel.ProcessInfo))==24); break;
                default: throw new Exception("UNKNOWN_MODEL_CASE");
            }
        }
        static void Scenario(string name) {
            if (name.StartsWith("plan:",StringComparison.Ordinal)) { PlanCase(name.Substring(5)); return; }
            if (name.StartsWith("fault:",StringComparison.Ordinal)) { FaultCase(name.Substring(6)); return; }
            if (name.StartsWith("environment:",StringComparison.Ordinal)) { EnvironmentCase(name.Substring(12)); return; }
            if (name.StartsWith("layout:",StringComparison.Ordinal)) { Layout(name.Substring(7)); return; }
            if (name=="security:object_descriptor") {
                var d=new RawSecurityDescriptor(WindowsGuardianKernel.ObjectSddl);
                Check(d.Owner.Value=="S-1-5-32-544" && d.Group.Value=="S-1-5-32-544" && d.DiscretionaryAcl.Count==2 &&
                    (d.ControlFlags&ControlFlags.DiscretionaryAclProtected)!=0);
                var sids=new HashSet<string>(StringComparer.Ordinal);
                foreach (GenericAce raw in d.DiscretionaryAcl) {
                    var ace=(CommonAce)raw; Check(ace.AceType==AceType.AccessAllowed && ace.AceFlags==AceFlags.None && ace.AccessMask==0x10000000);
                    sids.Add(ace.SecurityIdentifier.Value);
                }
                Check(sids.SetEquals(new string[] {"S-1-5-18","S-1-5-32-544"})); return;
            }
            var e=new Env(); ProvisionProcessGuardian guardian=e.Guardian();
            switch (name) {
                case "construct_no_io": Check(e.Api.Events.Count==0); return;
                case "nonzero_exit": e.Api.Code=7; break;
                case "exit_259_is_valid": e.Api.Code=259; break;
                case "deadline":
                case "no_wait_deadline_renewal": e.Api.NeverExit=true; break;
                case "maximum_budget": e.Api.NeverExit=true; guardian=new ProvisionProcessGuardian(e.Plan(seconds:900),e.Api,e.Clock); break;
                case "wall_expiry": e.Api.NeverExit=true; e.Api.Hook=delegate(string at) { if (at=="wait") e.Clock.Wall=1900; }; break;
                case "wall_backwards_no_extension": e.Api.NeverExit=true; e.Clock.Wall=0; break;
                case "residual_child": e.Api.Residue=true; break;
                case "stop_progress": e.Api.Residue=true; e.Api.StopPolls=3; break;
                case "hold_handles_until_empty":
                    e.Api.Hook=delegate(string at) { if (at=="active" || at=="wait_zero") foreach (TestHandle h in e.Api.Handles) Check(!h.Closed); }; break;
                case "one_shot_failure": e.Api.Host=false; Failure(delegate { guardian.Run(); },true,"protected_host_role");
                    Failure(delegate { guardian.Run(); },true,"one_shot"); return;
                case "one_shot_concurrent":
                    Func<int> run=delegate { try { guardian.Run(); return 1; } catch (GuardianRefused ex) { Check(ex.Message=="one_shot"); return 0; } };
                    Task<int> a=Task.Run(run),b=Task.Run(run); Task.WaitAll(a,b); Check(a.Result+b.Result==1 && e.Api.Resumes==1); e.Api.AllClosed(); return;
                case "normal_exit":
                case "close_order":
                case "one_shot_success":
                case "no_install_acceptance": break;
                default: throw new Exception("UNKNOWN_MODEL_CASE");
            }
            LocalProcessObservation answer=guardian.Run(); e.Api.AllClosed(); Check(answer.EmptyObserved && answer.Resumed && answer.ProcessId==42);
            Check(answer.InstallationId==e.Plan().InstallationId && answer.ApprovalSha256==e.Plan().ApprovalSha256);
            if (e.Api.NeverExit) {
                Check(answer.End==LocalProcessEnd.DeadlineStopped && e.Api.Stops==1);
                Check(e.Clock.Time<=((name=="maximum_budget")?995:105)+0.001);
                Check(!answer.ExitCode.HasValue);
            } else if (name=="residual_child" || name=="stop_progress") Check(answer.End==LocalProcessEnd.ResidualTreeStopped && e.Api.Stops==1);
            else Check(answer.End==LocalProcessEnd.RootExited && answer.ExitCode==e.Api.Code && e.Api.Stops==0);
            foreach (uint ms in e.Api.Waits) Check(ms<=500);
            Check(e.Api.Resumes==1 && e.Api.Stops<=1);
            if (name=="one_shot_success") Failure(delegate { guardian.Run(); },true,"one_shot");
            if (name=="close_order") {
                int n=e.Api.Events.Count; Check(e.Api.Events[n-3]=="close:thread" && e.Api.Events[n-2]=="close:process" && e.Api.Events[n-1]=="close:job");
            }
            if (name=="no_install_acceptance") Check(LocalProcessObservation.Scope=="local_process_observations_only_not_install_acceptance");
        }
        public static string[] RunAll() {
            string[] cases=__CASES__; var observations=new List<string>();
            foreach (string name in cases) {
                try { Scenario(name); observations.Add(name+"|PASS"); }
                catch (Exception ex) { observations.Add(name+"|FAIL|"+ex.GetType().Name+"|"+ex.Message); }
            }
            return observations.ToArray();
        }
    }
}
'''


def _quote(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


@pytest.fixture(scope='module')
def models(tmp_path_factory):
    if os.name != 'nt':
        pytest.skip('requires Windows CLR compiler; not native guardian evidence')
    exe = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    assert exe.is_file(), 'required Windows model compiler unavailable'
    harness = tmp_path_factory.mktemp('validator-guardian-model') / 'models.cs'
    cases = 'new string[] {' + ','.join(json.dumps(n) for n in SCENARIOS) + '}'
    harness.write_text(HARNESS.replace('__CASES__', cases), encoding='utf-8')
    script = (
        "$ErrorActionPreference='Stop'; "
        f"Add-Type -Path @({_quote(CORE)},{_quote(WINDOWS)},{_quote(harness)}) -ErrorAction Stop; "
        "[AiAgent.ValidatorGuardian.GuardianHarness]::RunAll()"
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
def test_guardian_clr_models(models, scenario):
    assert models[scenario] == 'PASS'


def test_atomic_job_assignment_and_fixed_role_are_not_fallbacks():
    text = WINDOWS.read_text(encoding='utf-8')
    core = CORE.read_text(encoding='utf-8')
    assert 'JobFlags=0x2008, ProcessFlags=0x08080404' in text
    assert 'JobListAttribute=0x0002000d' in text
    assert 'state.JobArray,(IntPtr)job' in text
    assert 'false,ProcessFlags,state.Environment,root,ref startup,out state.Child' in text
    assert 'actual.Basic.Flags!=JobFlags || actual.Basic.ActiveLimit!=2' in text
    assert '(handleFlags&1)!=0' in text
    assert 'AssignProcessToJobObject' not in text
    assert 'TerminateProcess(' not in text and 'OpenProcess(' not in text
    assert 'TerminateJobObject((IntPtr)job,124)' in text
    assert 'path.ToString()!=plan.Root+' in text
    assert 'validator-install-guardian.exe' in core and 'validator-provision-worker.exe' in core
    assert '--provision-once' in core


def test_guardian_does_not_load_acquisition_or_python_closure():
    combined = CORE.read_text(encoding='utf-8') + WINDOWS.read_text(encoding='utf-8')
    assert 'AiAgent.NativeValidator' not in combined
    assert 'native_validator_install_boundary' not in combined
    assert 'night_shifts' not in combined
    assert 'Assembly.Load' not in combined and 'LoadLibrary' not in combined
    assert not re.search(r'\b(?:Main|ShellExecute|SetSecurityInfo|DeleteFile)\s*\(', combined)
    assert 'Process.Start(' not in combined
    assert 'GetEnvironmentVariables' not in combined
    assert 'Inherit=0' in combined
    assert 'No Main' in combined


def test_scratch_cleanup_precedes_native_handle_transfer():
    text = WINDOWS.read_text(encoding='utf-8')
    before = 'state.ReleaseScratch(); answer.Process=state.Child.Process; answer.Thread=state.Child.Thread;'
    transfer = 'state.Child.Process=IntPtr.Zero; state.Child.Thread=IntPtr.Zero; return answer;'
    assert text.index(before) < text.index(transfer)
    assert 'finally { state.CloseAll(); }' in text
    assert 'IntPtr old=value; value=IntPtr.Zero;' in text


def test_guardian_sources_are_visible_but_not_wired():
    ignore = (ROOT / '.gitignore').read_text(encoding='utf-8').splitlines()
    for path in (CORE, WINDOWS):
        exception = '!/' + path.relative_to(ROOT).as_posix()
        assert ignore.count(exception) == 1
        assert ignore.index(exception) > ignore.index('/scripts/*')
    for path in [*(ROOT / 'runtime').glob('*.py'), *(ROOT / 'scripts').glob('*.ps1')]:
        text = path.read_text(encoding='utf-8-sig')
        assert 'native_validator_process_guardian' not in text
    deployment = (ROOT / 'night_shifts/bootstrap_native_deployment.py').read_text(encoding='utf-8')
    assert 'native_validator_process_guardian' not in deployment
