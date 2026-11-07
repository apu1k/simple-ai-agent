"""Offline lifetime composition, not native Python launch or protected approval.

Compile the actual codec, import boundary and process guardian with the new
worker owner. All file/process/clock operations are fake. The Python oracle
independently supplies canonical held worker-request bytes; no carried code runs.
"""
from __future__ import annotations

import ast
import base64
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

from night_shifts import bootstrap_native_install_request as profile

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / 'scripts/native_validator_worker_guardian.cs'
SOURCES = (CORE, *(ROOT / 'scripts' / f'native_validator_{name}.cs' for name in (
    'install_boundary', 'install_windows', 'install_request', 'launch_boundary',
    'launch_windows', 'process_guardian', 'process_guardian_windows',
)))
SCENARIOS = (
    'construct_no_io', 'normal_exit', 'nonzero_exit', 'exit_259', 'timeout', 'residual',
    'stop_progress', 'minimum_budget', 'maximum_budget', 'approval_cap',
    'arrival_consumes_budget', 'wall_rollback_no_extension', 'context_isolation',
    'locks_through_stop_and_close', 'one_shot_concurrent', 'claim_cannot_retry',
    'internal_only_no_native_default',
    'reject:null', 'reject:length', 'reject:hash', 'reject:json', 'reject:canonical',
    'reject:budget_mismatch', 'reject:expiry_mismatch',
    'plan:zero_length', 'plan:large_length', 'plan:null_digest', 'plan:upper_digest',
    'plan:small_budget', 'plan:large_budget', 'plan:expired', 'plan:near_expiry',
    'plan:far_expiry', 'plan:large_expiry', 'plan:null_files', 'plan:null_kernel',
    'plan:null_clock', 'plan:clock_nan', 'plan:clock_infinite',
    'cap:nan', 'cap:infinite', 'cap:past', 'cap:equal', 'cap:no_run_window',
    'cap:shorter', 'cap:cannot_extend',
    'window:before_decode', 'window:after_decode', 'window:after_decode_wall',
    'window:after_decode_rollback', 'window:after_decode_nan',
    'window:acquire', 'window:copy', 'window:bind',
    'fault:host', 'fault:host_unknown', 'fault:hash', 'fault:claim_write',
    'fault:job', 'fault:precreate_hash', 'fault:copy_postcheck', 'fault:bind',
    'fault:create', 'fault:membership', 'fault:preresume_hash', 'fault:resume',
    'fault:wait', 'fault:accounting', 'fault:stop', 'fault:never_empty',
    'fault:root_not_signaled', 'fault:process_close', 'fault:late_process_close',
    'fault:import_close', 'fault:late_import_close', 'fault:late_import_wall',
    'fault:rollback_after_create', 'fault:nan_after_create',
)


def _canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode('ascii')


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _candidate():
    """Match the existing inert import backend, never actual deployment bytes."""
    def identity(index, volume=42):
        return {'volume': volume, 'index': index}

    def member(name):
        raw = b'INERT NONRUNNABLE MODEL:' + name.encode('ascii')
        if name in profile._EMPTY:
            raw = b''
        elif name == 'runtime/python314._pth':
            raw = profile._PTH
        elif name.endswith('.exe.config'):
            raw = profile._CONFIG
        return {'name': name, 'bytes': len(raw), 'sha256': _sha(raw)}

    imports = [member(n) for n in profile.IMPORT_NAMES]
    trees = {m['name'][8:]: {k: m[k] for k in ('bytes', 'sha256')}
             for m in imports if m['name'].startswith('payload/')}
    code = {n: p for n, p in trees.items() if n.startswith('night_shifts/')}
    codec = {n: p for n, p in trees.items() if not n.startswith('night_shifts/')}
    return {
        'version': 1, 'scope': profile.SCOPE, 'operation': profile.OPERATION,
        'installation_id': 'a' * 32, 'operator_sid': 'S-1-5-21-1-2-3-1001',
        'budget_seconds': 10, 'expires_unix': 1900,
        'launch_anchor': {'path': r'C:\Private Anchor', 'identity': identity(2, 77),
                          'scratch_identity': identity(3, 77),
                          'files': [member(n) for n in profile.LAUNCH_NAMES]},
        'import_anchor': {'path': r'C:\Anchor', 'identity': identity(2), 'files': imports},
        'provision': {
            'source': {'path': r'C:\Inputs', 'identity': identity(30)},
            'output_parent': {'path': r'C:\Outputs', 'identity': identity(40)},
            'bundle': {'bytes': 100, 'sha256': 'b' * 64},
            'pins': {'code_tree_sha256': _sha(_canonical(code)), 'codec_tree_sha256': _sha(_canonical(codec)),
                     'runtime_sha256': 'c' * 64, 'runtime_bytes': 1000,
                     'recovery_sha256': 'd' * 64, 'recovery_bytes': 40960},
        },
    }


HARNESS = r'''
using System;
using System.Collections.Generic;
using System.Reflection;
using System.Threading.Tasks;
using AiAgent.NativeValidator;
using AiAgent.ValidatorGuardian;
namespace AiAgent.ValidatorWorker {
    internal static class ModelTime { internal static double Time; internal static long Wall; }
    internal sealed class ProbeClock : IGuardianClock {
        internal int Reads;
        internal Action<int> Hook;
        public double Seconds {
            get { Reads++; if (Hook!=null) Hook(Reads); return ModelTime.Time; }
        }
        public long Unix { get { return ModelTime.Wall; } }
    }
    internal sealed class PythonModel : IWorkerPythonKernel {
        internal readonly AiAgent.ValidatorGuardian.TestKernel Inner;
        internal WorkerLaunchContext Context;
        internal GuardianPlan HostPlan;
        internal Action OnBind;
        internal PythonModel(AiAgent.ValidatorGuardian.TestKernel value) { Inner=value; }
        public void Bind(WorkerLaunchContext context) {
            if (Context!=null) throw new Exception("MODEL_BIND_TWICE");
            Context=context; if (OnBind!=null) OnBind();
        }
        public void RequireHost(GuardianPlan plan) { HostPlan=plan; Inner.RequireHost(plan); }
        public object NewJob() { return Inner.NewJob(); }
        public ChildPair CreateSuspended(object job,string root) {
            WorkerHarness.Check(Context!=null && Context.LaunchRoot==root);
            return Inner.CreateSuspended(job,root);
        }
        public bool Member(object process,object job) { return Inner.Member(process,job); }
        public uint Resume(object thread) { return Inner.Resume(thread); }
        public uint Wait(object process,uint ms) { return Inner.Wait(process,ms); }
        public uint ExitCode(object process) { return Inner.ExitCode(process); }
        public uint Active(object job) { return Inner.Active(job); }
        public void Stop(object job) { Inner.Stop(job); }
        public void Pause(int ms) { Inner.Pause(ms); }
        public void Close(object handle) { Inner.Close(handle); }
    }
    internal sealed class ModelEnv {
        internal readonly AiAgent.NativeValidator.Env F;
        internal readonly AiAgent.ValidatorGuardian.Env K;
        internal readonly PythonModel Python;
        internal readonly ProbeClock Clock=new ProbeClock();
        internal readonly List<string> Events=new List<string>();
        internal Action<string> Hook;
        internal ModelEnv(byte[] worker) {
            ModelTime.Time=100; ModelTime.Wall=1000;
            F=new AiAgent.NativeValidator.Env(); K=new AiAgent.ValidatorGuardian.Env();
            F.Api.Data["provision-request.json"]=(byte[])worker.Clone();
            F.Api.Meta["provision-request.json"].Bytes=worker.Length;
            Python=new PythonModel(K.Api);
            F.Api.Hook=delegate(string at) { Event("F:"+at); };
            K.Api.Hook=delegate(string at) { Event("K:"+at); };
            Python.OnBind=delegate { Event("P:bind"); };
        }
        void Event(string at) { Events.Add(at); if (Hook!=null) Hook(at); }
        internal WorkerProvisionGuardian Make(long size,string digest,int seconds=10,long until=1900,double cap=110) {
            return new WorkerProvisionGuardian(size,digest,seconds,until,cap,F.Api,Python,Clock);
        }
        internal void Live() {
            foreach (AiAgent.NativeValidator.TestHandle h in F.Api.Handles) WorkerHarness.Check(!h.Closed);
        }
        internal void Closed() { F.Api.AllClosed(); K.Api.AllClosed(); }
    }
    public static class WorkerHarness {
        const string File="payload/night_shifts/bootstrap_native_provision.py";
        internal static void Check(bool yes) { if (!yes) throw new Exception("WORKER_ASSERTION"); }
        static void Failure(Action action,bool unknown,string label=null) {
            try { action(); }
            catch (Exception ex) {
                Check((unknown?ex is WorkerGuardianUnknown:ex is WorkerGuardianRefused) && (label==null || ex.Message==label));
                Check(!ex.Message.Contains("CANARY")); return;
            }
            throw new Exception("WORKER_EXPECTED_FAILURE");
        }
        static void NoRetry(ModelEnv e,WorkerProvisionGuardian run,byte[] raw) {
            int events=e.Events.Count,reads=e.Clock.Reads;
            Failure(delegate { run.Run(raw); },false,"one_shot");
            Check(e.Events.Count==events && e.Clock.Reads==reads);
        }
        static void Plan(string name,ModelEnv e,long size,string digest) {
            Action act=delegate { e.Make(size,digest); }; bool unknown=false;
            switch (name) {
                case "zero_length": act=delegate { e.Make(0,digest); }; break;
                case "large_length": act=delegate { e.Make(32769,digest); }; break;
                case "null_digest": act=delegate { e.Make(size,null); }; break;
                case "upper_digest": act=delegate { e.Make(size,new string('A',64)); }; break;
                case "small_budget": act=delegate { e.Make(size,digest,5); }; break;
                case "large_budget": act=delegate { e.Make(size,digest,901); }; break;
                case "expired": act=delegate { e.Make(size,digest,until:1000); }; break;
                case "near_expiry": act=delegate { e.Make(size,digest,until:1005); }; break;
                case "far_expiry": act=delegate { e.Make(size,digest,until:87401); }; break;
                case "large_expiry": act=delegate { e.Make(size,digest,until:253402300800L); }; break;
                case "null_files": act=delegate { new WorkerProvisionGuardian(size,digest,10,1900,110,null,e.Python,e.Clock); }; break;
                case "null_kernel": act=delegate { new WorkerProvisionGuardian(size,digest,10,1900,110,e.F.Api,null,e.Clock); }; break;
                case "null_clock": act=delegate { new WorkerProvisionGuardian(size,digest,10,1900,110,e.F.Api,e.Python,null); }; break;
                case "clock_nan": ModelTime.Time=Double.NaN; unknown=true; break;
                case "clock_infinite": ModelTime.Time=Double.PositiveInfinity; unknown=true; break;
                default: throw new Exception("UNKNOWN_PLAN_CASE");
            }
            Failure(act,unknown); Check(e.Events.Count==0);
        }
        static void Fault(string name,ModelEnv e,WorkerProvisionGuardian run,byte[] raw) {
            bool retained=false,unknown=false; string label=null; int requestPass=0;
            switch (name) {
                case "host": e.K.Api.Host=false; label="process_refused"; break;
                case "host_unknown": e.K.Api.Fault="host"; unknown=true; label="worker_unknown"; break;
                case "hash": e.F.Api.Data[File][0]^=1; label="imports_refused"; break;
                case "claim_write": e.F.Api.WriteMode="short"; unknown=true; label="worker_unknown"; break;
                case "job": e.K.Api.Fault="job"; unknown=true; label="worker_unknown"; break;
                case "precreate_hash": e.Hook=delegate(string at) { if (at=="K:job") e.F.Api.Data[File][0]^=1; }; unknown=true; break;
                case "copy_postcheck":
                    e.Hook=delegate(string at) {
                        if (at=="F:rewind:provision-request.json" && ++requestPass==3) e.F.Api.Data[File][0]^=1;
                    }; unknown=true; break;
                case "bind": e.Hook=delegate(string at) { if (at=="P:bind") throw new Exception("BIND_CANARY"); }; unknown=true; break;
                case "create": e.K.Api.Fault="create"; retained=true; break;
                case "membership": e.K.Api.MemberValue=false; retained=true; break;
                case "preresume_hash": e.Hook=delegate(string at) { if (at=="K:member") e.F.Api.Data[File][0]^=1; }; retained=true; break;
                case "resume": e.K.Api.ResumeValue=0; retained=true; break;
                case "wait": e.K.Api.WaitFailure=UInt32.MaxValue; retained=true; break;
                case "accounting": e.K.Api.Fault="active"; retained=true; break;
                case "stop": e.K.Api.NeverExit=e.K.Api.StopFails=true; retained=true; break;
                case "never_empty": e.K.Api.NeverExit=e.K.Api.StopNeverEmpty=true; retained=true; break;
                case "root_not_signaled": e.K.Api.NeverExit=e.K.Api.RootNeverSignaled=true; retained=true; break;
                case "process_close": e.K.Api.CloseFault="process"; retained=true; break;
                case "late_process_close": e.Hook=delegate(string at) { if (at=="K:close:job") ModelTime.Time=111; }; retained=true; break;
                case "import_close": e.F.Api.CloseFault=File; unknown=true; label="import_close_unknown"; break;
                case "late_import_close": e.Hook=delegate(string at) { if (at=="F:close:@volume") ModelTime.Time=111; }; unknown=true; label="deadline_outcome_unknown"; break;
                case "late_import_wall": e.Hook=delegate(string at) { if (at=="F:close:@volume") ModelTime.Wall=1900; }; unknown=true; label="deadline_outcome_unknown"; break;
                case "rollback_after_create": e.Hook=delegate(string at) { if (at=="K:member") ModelTime.Time=99; }; retained=true; break;
                case "nan_after_create": e.Hook=delegate(string at) { if (at=="K:member") ModelTime.Time=Double.NaN; }; retained=true; break;
                default: throw new Exception("UNKNOWN_FAULT_CASE");
            }
            if (retained) { unknown=true; label="imports_retained_outcome_unknown"; }
            Failure(delegate { run.Run(raw); },unknown,label);
            Check(run.ImportLeaseRetained==retained); e.K.Api.AllClosed();
            if (retained) e.Live(); else e.F.Api.AllClosed();
            if (name=="preresume_hash") Check(e.K.Api.Resumes==0);
            if (name=="precreate_hash" || name=="copy_postcheck" || name=="bind") Check(!e.K.Api.Events.Contains("create"));
            if (name=="host" || name=="host_unknown") Check(e.F.Api.Writes==0);
            Check(e.K.Api.Stops<=1); NoRetry(e,run,raw);
        }
        static void Scenario(string name,byte[] raw,long size,string digest,int seconds,long until,byte[] worker) {
            var e=new ModelEnv(worker);
            if (name.StartsWith("plan:",StringComparison.Ordinal)) { Plan(name.Substring(5),e,size,digest); return; }
            if (name.StartsWith("cap:",StringComparison.Ordinal) && name!="cap:shorter" && name!="cap:cannot_extend") {
                double cap=name=="cap:nan"?Double.NaN:(name=="cap:infinite"?Double.PositiveInfinity:(name=="cap:past"?99:(name=="cap:no_run_window"?105:100)));
                Failure(delegate { e.Make(size,digest,cap:cap); },false); Check(e.Events.Count==0); return;
            }
            double bound=name=="cap:shorter"?108:(name=="cap:cannot_extend"?1000:100+seconds);
            var run=e.Make(size,digest,seconds,until,bound);
            if (name.StartsWith("fault:",StringComparison.Ordinal)) { Fault(name.Substring(6),e,run,raw); return; }
            if (name.StartsWith("reject:",StringComparison.Ordinal)) {
                byte[] incoming=name=="reject:null"?null:raw;
                if (name=="reject:hash") { incoming=(byte[])raw.Clone(); incoming[0]^=1; }
                if (name=="reject:length") incoming=new byte[raw.Length+1];
                Failure(delegate { run.Run(incoming); },false); Check(e.Events.Count==0); NoRetry(e,run,raw); return;
            }
            if (name.StartsWith("window:",StringComparison.Ordinal)) {
                if (name=="window:before_decode") ModelTime.Time=105;
                else if (name.StartsWith("window:after_decode",StringComparison.Ordinal)) {
                    e.Clock.Hook=delegate(int read) {
                        if (read!=3) return;
                        if (name.EndsWith("wall",StringComparison.Ordinal)) ModelTime.Wall=until;
                        else ModelTime.Time=name.EndsWith("rollback",StringComparison.Ordinal)?99:
                            (name.EndsWith("nan",StringComparison.Ordinal)?Double.NaN:105);
                    };
                } else {
                    int passes=0;
                    e.Hook=delegate(string at) {
                        if (name=="window:bind" && at=="P:bind") ModelTime.Time=105;
                        if (name!="window:bind" && at=="F:rewind:"+File && ++passes==(name=="window:acquire"?1:2)) ModelTime.Time=105;
                    };
                }
                bool unknown=name.EndsWith("rollback",StringComparison.Ordinal) || name.EndsWith("nan",StringComparison.Ordinal) || name=="window:copy" || name=="window:bind";
                Failure(delegate { run.Run(raw); },unknown);
                Check(!run.ImportLeaseRetained && !e.K.Api.Events.Contains("create"));
                if (name=="window:bind") Check(e.Events.Contains("P:bind"));
                e.Closed(); NoRetry(e,run,raw); return;
            }
            switch (name) {
                case "construct_no_io": Check(e.Events.Count==0 && !run.ImportLeaseRetained); return;
                case "nonzero_exit": e.K.Api.Code=7; break;
                case "exit_259": e.K.Api.Code=259; break;
                case "timeout": case "maximum_budget": case "approval_cap": case "cap:shorter": case "cap:cannot_extend": e.K.Api.NeverExit=true; break;
                case "arrival_consumes_budget": ModelTime.Time=104; e.K.Api.NeverExit=true; break;
                case "wall_rollback_no_extension": ModelTime.Wall=0; e.K.Api.NeverExit=true; break;
                case "residual": e.K.Api.Residue=true; break;
                case "stop_progress": e.K.Api.Residue=true; e.K.Api.StopPolls=3; break;
                case "locks_through_stop_and_close":
                    e.K.Api.Residue=true; e.K.Api.StopPolls=3;
                    e.Hook=delegate(string at) { if (at.StartsWith("K:",StringComparison.Ordinal) && at!="K:host") e.Live(); }; break;
                case "one_shot_concurrent":
                    Func<int> attempt=delegate { try { run.Run(raw); return 1; } catch (WorkerGuardianRefused ex) { Check(ex.Message=="one_shot"); return 0; } };
                    Task<int> a=Task.Run(attempt),b=Task.Run(attempt); Task.WaitAll(a,b);
                    Check(a.Result+b.Result==1 && e.K.Api.Resumes==1 && e.F.Api.Writes==1); e.Closed(); return;
                case "internal_only_no_native_default":
                    Check(!typeof(WorkerProvisionGuardian).IsPublic && typeof(WorkerProvisionGuardian).GetConstructors().Length==0);
                    Check(!typeof(IWorkerPythonKernel).IsAssignableFrom(typeof(WindowsGuardianKernel)));
                    Check(typeof(WorkerProvisionGuardian).GetMethods(BindingFlags.Public|BindingFlags.Instance|BindingFlags.DeclaredOnly).Length==0); return;
            }
            LocalProcessObservation answer=run.Run(raw);
            Check(!run.ImportLeaseRetained && answer.EmptyObserved && answer.Resumed && e.F.Api.Writes==1);
            e.Closed(); Check(e.Python.Context!=null);
            WorkerLaunchContext c=e.Python.Context;
            Check(c.WorkerBytes==worker.Length && c.WorkerSha256==InstallBoundary.Sha(worker) && c.RequestSha256==digest);
            Check(c.BudgetSeconds==seconds && c.ApprovedUntilUnix==until && c.ImportRoot==@"C:\Anchor");
            Check(c.LaunchRoot==@"C:\Private Anchor" && c.InstallationId==new string('a',32) && c.OperatorSid=="S-1-5-21-1-2-3-1001");
            double expected=Math.Min(bound,100+Math.Min(seconds,until-1000))-5;
            Check(c.RunDeadline==expected && e.K.Api.Resumes==1);
            Check(Convert.ToBase64String(c.CopyRequest())==Convert.ToBase64String(worker));
            if (name=="context_isolation") {
                byte[] first=c.CopyRequest(),second=c.CopyRequest(); first[0]^=1;
                Check(!Object.ReferenceEquals(first,second) && Convert.ToBase64String(second)==Convert.ToBase64String(c.CopyRequest()));
                e.F.Api.Data["provision-request.json"][0]^=1;
                Check(Convert.ToBase64String(second)==Convert.ToBase64String(c.CopyRequest()));
            }
            int claim=e.Events.IndexOf("F:claim"),bind=e.Events.IndexOf("P:bind"),create=e.Events.IndexOf("K:create"),resume=e.Events.IndexOf("K:resume");
            Check(claim>=0 && claim<bind && bind<create && create<resume);
            Check(e.Events.IndexOf("F:close:"+File)>e.Events.IndexOf("K:close:job"));
            Check(e.Events.FindAll(delegate(string s) { return s=="F:open:"+File; }).Count==1);
            int preResume=e.Events.FindIndex(create+1,delegate(string s) { return s=="F:rewind:"+File; });
            Check(preResume>create && preResume<resume);
            if (e.K.Api.NeverExit) Check(answer.End==LocalProcessEnd.DeadlineStopped && ModelTime.Time<=expected+0.001);
            else if (e.K.Api.Stops!=0) Check(answer.End==LocalProcessEnd.ResidualTreeStopped);
            else Check(answer.End==LocalProcessEnd.RootExited && answer.ExitCode==e.K.Api.Code);
            if (name=="claim_cannot_retry") {
                int creates=e.K.Api.Resumes;
                var again=e.Make(size,digest,seconds,until,bound);
                Failure(delegate { again.Run(raw); },false,"imports_refused");
                Check(e.K.Api.Resumes==creates && e.F.Api.Writes==1); e.Closed();
            }
            NoRetry(e,run,raw);
        }
        public static string Run(string name,byte[] raw,long size,string digest,int seconds,long until,byte[] worker) {
            try { Scenario(name,raw,size,digest,seconds,until,worker); return name+"|PASS"; }
            catch (Exception ex) { return name+"|FAIL|"+ex.GetType().Name+"|"+ex.Message; }
        }
    }
}
'''


def _backend(role):
    """Reuse inert fake text only; never import/execute sibling test modules."""
    path = Path(__file__).with_name(f'test_native_validator_{role}.py')
    tree = ast.parse(path.read_text(encoding='utf-8'))
    values = [ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
              and any(isinstance(t, ast.Name) and t.id == 'HARNESS' for t in node.targets)]
    assert len(values) == 1 and isinstance(values[0], str)
    old = 'internal double Time=100; internal long Wall=1000;'
    assert values[0].count(old) == 1
    shared = (
        'internal double Time { get { return AiAgent.ValidatorWorker.ModelTime.Time; } '
        'set { AiAgent.ValidatorWorker.ModelTime.Time=value; } } '
        'internal long Wall { get { return AiAgent.ValidatorWorker.ModelTime.Wall; } '
        'set { AiAgent.ValidatorWorker.ModelTime.Wall=value; } }'
    )
    text = values[0].replace(old, shared).replace('__CASES__', 'new string[0]')
    if role == 'install_boundary':
        # The original fake logs closes locally without forwarding its hook.
        # This composition needs the SAME close event in the merged trace and
        # late-close fault injection. Change only extracted disposable fake text.
        old_close = 'h.Closes++; Events.Add("close:"+h.Name);'
        assert text.count(old_close) == 1
        text = text.replace(old_close, 'h.Closes++; Event("close:"+h.Name);')
    return text


@pytest.fixture(scope='module')
def models(tmp_path_factory):
    if os.name != 'nt':
        pytest.skip('Windows CLR model compiler required; not native Python execution')
    compiler = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    assert compiler.is_file(), 'required model compiler unavailable'
    folder = tmp_path_factory.mktemp('validator-worker-guardian-model')
    paths = list(SOURCES)
    for role in ('install_boundary', 'process_guardian'):
        path = folder / f'{role}_model.cs'
        path.write_text(_backend(role), encoding='utf-8')
        paths.append(path)
    path = folder / 'worker_models.cs'
    path.write_text(HARNESS, encoding='utf-8')
    paths.append(path)
    rows = []
    for name in SCENARIOS:
        value = _candidate()
        seconds = 6 if name == 'minimum_budget' else (900 if name in ('maximum_budget', 'approval_cap') else 10)
        until = 1008 if name == 'approval_cap' else 1900
        value.update(budget_seconds=seconds, expires_unix=until)
        if name == 'reject:budget_mismatch':
            value['budget_seconds'] = 9
        if name == 'reject:expiry_mismatch':
            value['expires_unix'] = 1901
        raw = profile.build_validation_install_request(value)
        worker = profile.bind_validation_install_request(raw, expected_bytes=len(raw), expected_sha256=_sha(raw)).worker_request
        if name == 'reject:json':
            raw = b'{'
        if name == 'reject:canonical':
            raw += b' '
        rows.append('|'.join((name, str(len(raw)), _sha(raw), str(seconds), str(until),
                              base64.b64encode(raw).decode('ascii'), base64.b64encode(worker).decode('ascii'))))
    corpus = folder / 'inert_corpus.txt'
    corpus.write_text('\n'.join(rows) + '\n', encoding='ascii')

    def quote(path):
        return "'" + str(path).replace("'", "''") + "'"

    script = (
        "$ErrorActionPreference='Stop'; Add-Type -Path @(" + ','.join(quote(p) for p in paths) + ') '
        "-ReferencedAssemblies @('System.dll','System.Core.dll','System.Xml.dll','System.Runtime.Serialization.dll') -ErrorAction Stop; "
        f'foreach ($line in [IO.File]::ReadAllLines({quote(corpus)})) {{ '
        "$p=$line.Split('|'); "
        '[AiAgent.ValidatorWorker.WorkerHarness]::Run($p[0],[Convert]::FromBase64String($p[5]),'
        '[long]$p[1],$p[2],[int]$p[3],[long]$p[4],[Convert]::FromBase64String($p[6])) }'
    )
    completed = subprocess.run([
        str(compiler), '-NoLogo', '-NoProfile', '-NonInteractive', '-EncodedCommand',
        base64.b64encode(script.encode('utf-16le')).decode('ascii'),
    ], capture_output=True, text=True, timeout=25, check=False)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    answers = {}
    for line in completed.stdout.splitlines():
        name, separator, result = line.partition('|')
        assert separator and name not in answers, line
        answers[name] = result
    assert set(answers) == set(SCENARIOS)
    return answers


@pytest.mark.parametrize('scenario', SCENARIOS)
def test_worker_guardian_clr_models(models, scenario):
    assert models[scenario] == 'PASS'


def test_composition_uses_actual_held_bytes_and_one_derived_plan():
    text = CORE.read_text(encoding='utf-8')
    assert text.index('used=true;') < text.index('InstallationRequest.Bind(')
    assert text.index('InstallationRequest.Bind(') < text.index('inputs.CreateImportPlan()')
    assert 'launch.BudgetSeconds!=budgetSeconds || launch.ApprovedUntilUnix!=approvedUntil' in text
    assert 'lease.CopyWorkerRequest()' in text and 'inputs.WorkerRequestBytes' not in text
    assert 'owner.lease.Reverify()' in text
    assert 'new ProvisionProcessGuardian(processPlan,kernel,clock,deadline,new ImportGate(this))' in text
    assert text.index('kernel.RequireHost(processPlan);') < text.index('lease=boundary.Acquire();')


def test_only_terminal_process_fact_allows_import_release():
    text = CORE.read_text(encoding='utf-8')
    assert 'guardian.LaunchTargetsReleasable' in text
    assert 'ImportClosureLease current=lease; lease=null;' in text
    assert 'imports_retained_outcome_unknown' in text
    assert not re.search(r'\bpublic\s+(?:WorkerProvisionGuardian|.*\bDispose)\b', text)
    assert '~WorkerProvisionGuardian' not in text and 'using (lease' not in text
    assert text.count('current.Dispose()') == 1 and 'guardian=null' not in text


def test_no_fresh_deadline_and_no_production_launcher_fallback():
    text = CORE.read_text(encoding='utf-8')
    assert 'double originalDeadline,IBoundaryFiles importFiles,IWorkerPythonKernel python,IGuardianClock time)' in text
    assert 'deadline=Math.Min(originalDeadline,now+Math.Min(seconds,remaining))' in text
    assert 'deadline-ProvisionProcessGuardian.StopReserveSeconds' in text
    assert 'clock.Seconds>=deadline || clock.Unix>=approvedUntil' in text
    assert 'now<last' in text
    assert 'new WindowsGuardianKernel' not in text and 'new GuardianClock' not in text
    for forbidden in ('DllImport', 'Assembly.Load', 'Process.Start', 'CreateProcessW', 'File.Open', 'CreateClaim'):
        assert forbidden not in text
    assert not re.search(r'\b(?:Main|ShellExecute|DeleteFile|SetSecurityInfo)\s*\(', text)


def test_composed_fake_forwards_close_events_after_disarming_handle():
    text = _backend('install_boundary')
    assert 'h.Closed=true; h.Closes++; Event("close:"+h.Name);' in text
    assert 'h.Closes++; Events.Add("close:"+h.Name);' not in text
    original = Path(__file__).with_name('test_native_validator_install_boundary.py').read_text(encoding='utf-8')
    assert 'h.Closes++; Events.Add("close:"+h.Name);' in original


def test_worker_source_visible_but_not_installed_deployed_or_wired():
    ignore = (ROOT / '.gitignore').read_text(encoding='utf-8').splitlines()
    exception = '!/' + CORE.relative_to(ROOT).as_posix()
    assert ignore.count(exception) == 1 and ignore.index(exception) > ignore.index('/scripts/*')
    for path in [*(ROOT / 'runtime').glob('*.py'), *(ROOT / 'scripts').glob('*.ps1')]:
        assert 'native_validator_worker_guardian' not in path.read_text(encoding='utf-8-sig')
    for name in ('bootstrap_native_deployment.py', 'bootstrap_native_provision.py', 'bootstrap_native_install_request.py'):
        assert 'native_validator_worker_guardian' not in (ROOT / 'night_shifts' / name).read_text(encoding='utf-8')
