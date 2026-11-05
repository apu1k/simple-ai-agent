"""Offline request-to-guardian models, not native launch or approval evidence.

Compile nine actual C# sources with fake file/process/time backends. The actual
codec hashes/parses canonical synthetic request bytes; executable inputs are
inert data. No P/Invoke, installation, carried Python or VM is invoked.
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
CORE = ROOT / 'scripts/native_validator_request_guardian.cs'
HELD = ROOT / 'scripts/native_validator_held_guardian.cs'
SOURCES = (CORE, HELD, *(ROOT / 'scripts' / f'native_validator_{name}.cs' for name in (
    'install_boundary', 'install_windows', 'install_request', 'launch_boundary',
    'launch_windows', 'process_guardian', 'process_guardian_windows',
)))
SCENARIOS = (
    'construct_no_io', 'normal_exit', 'nonzero_exit', 'timeout', 'residual',
    'minimum_budget', 'maximum_budget', 'approval_cap', 'wall_rollback_no_renewal',
    'arrival_consumes_budget', 'decode_consumes_budget', 'decode_and_acquire_share_budget',
    'copy_isolation', 'one_shot_concurrent', 'public_api_fixed',
    'reject:null', 'reject:hash', 'reject:length', 'reject:json', 'reject:canonical',
    'reject:budget_mismatch', 'reject:expiry_mismatch',
    'window:before_decode', 'window:after_decode', 'window:after_decode_wall',
    'window:before_decode_nan', 'window:after_decode_nan', 'window:after_decode_rollback',
    'fault:initial_hash', 'fault:host', 'fault:create', 'fault:preresume',
    'fault:stop', 'fault:target_close', 'fault:late_target_close',
    'plan:zero_length', 'plan:large_length', 'plan:null_digest', 'plan:upper_digest',
    'plan:small_budget', 'plan:large_budget', 'plan:expired', 'plan:near_expiry',
    'plan:far_expiry', 'plan:large_expiry', 'plan:clock_nan', 'plan:clock_infinite',
    'plan:clock_resolution', 'plan:null_files', 'plan:null_kernel', 'plan:null_clock',
    'cap:nan', 'cap:infinite', 'cap:past', 'cap:shorter', 'cap:cannot_extend',
)


def _canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode('ascii')


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _candidate():
    """Match the independent fake launch backend, never runnable PE contents."""
    def identity(index, volume=42):
        return {'volume': volume, 'index': index}

    def member(name):
        raw = b'INERT REQUEST MODEL:' + name.encode('ascii')
        if name in profile._EMPTY:
            raw = b''
        elif name == 'runtime/python314._pth':
            raw = profile._PTH
        elif name.endswith('.exe.config'):
            raw = profile._CONFIG
        elif name.endswith('.exe') and '/' not in name:
            raw = bytes(i % 251 for i in range(65537))
        return {'name': name, 'bytes': len(raw), 'sha256': _sha(raw)}

    imports = [member(n) for n in profile.IMPORT_NAMES]
    inventory = {m['name'][8:]: {k: m[k] for k in ('bytes', 'sha256')}
                 for m in imports if m['name'].startswith('payload/')}
    code = {n: p for n, p in inventory.items() if n.startswith('night_shifts/')}
    codec = {n: p for n, p in inventory.items() if not n.startswith('night_shifts/')}
    return {
        'version': 1, 'scope': profile.SCOPE, 'operation': profile.OPERATION,
        'installation_id': 'a' * 32, 'operator_sid': 'S-1-5-21-1-2-3-1001',
        'budget_seconds': 10, 'expires_unix': 1900,
        'launch_anchor': {'path': r'C:\Private Anchor', 'identity': identity(2, 77),
                          'scratch_identity': identity(3, 77),
                          'files': [member(n) for n in profile.LAUNCH_NAMES]},
        'import_anchor': {'path': r'C:\Imports', 'identity': identity(20), 'files': imports},
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
using AiAgent.ValidatorGuardian;
using AiAgent.ValidatorHandoff;
using AiAgent.ValidatorLaunch;
namespace AiAgent.ValidatorHandoff {
    internal static class SharedModelTime { internal static double Time; internal static long Wall; }
}
namespace AiAgent.ValidatorAdmission {
    internal sealed class ProbeClock : IGuardianClock {
        internal int Reads;
        internal Action<int> Hook;
        public double Seconds {
            get { Reads++; if (Hook!=null) Hook(Reads); return SharedModelTime.Time; }
        }
        public long Unix { get { return SharedModelTime.Wall; } }
    }
    internal sealed class ModelEnv {
        internal readonly AiAgent.ValidatorLaunch.Env F;
        internal readonly AiAgent.ValidatorGuardian.Env K;
        internal readonly ProbeClock Clock=new ProbeClock();
        internal readonly List<string> Events=new List<string>();
        internal Action<string> Hook;
        internal ModelEnv() {
            SharedModelTime.Time=100; SharedModelTime.Wall=1000;
            F=new AiAgent.ValidatorLaunch.Env(); K=new AiAgent.ValidatorGuardian.Env();
            F.Api.Hook=delegate(string s) { Event("F:"+s); };
            K.Api.Hook=delegate(string s) { Event("K:"+s); };
        }
        void Event(string s) { Events.Add(s); if (Hook!=null) Hook(s); }
        internal RequestProvisionGuardian Make(long size,string digest,int seconds=10,long until=1900) {
            return new RequestProvisionGuardian(size,digest,seconds,until,F.Api,K.Api,Clock);
        }
        internal void Closed() { F.Api.AllClosed(); K.Api.AllClosed(); }
    }
    public static class RequestGuardianHarness {
        static void Check(bool yes) { if (!yes) throw new Exception("REQUEST_GUARDIAN_ASSERTION"); }
        static void Failure(Action action,bool unknown,string label=null) {
            try { action(); }
            catch (Exception ex) {
                Check((unknown?ex is RequestGuardianUnknown:ex is RequestGuardianRefused) && (label==null || ex.Message==label));
                Check(!ex.Message.Contains("CANARY")); return;
            }
            throw new Exception("REQUEST_GUARDIAN_EXPECTED_FAILURE");
        }
        static void NoRetry(ModelEnv e,RequestProvisionGuardian run,byte[] raw) {
            int events=e.Events.Count,reads=e.Clock.Reads;
            Failure(delegate { run.Run(raw); },false,"one_shot");
            Check(e.Events.Count==events && e.Clock.Reads==reads);
        }
        static void Plan(string name,long size,string digest) {
            var e=new ModelEnv(); Action act=delegate { e.Make(size,digest); }; bool unknown=false;
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
                case "clock_nan": SharedModelTime.Time=Double.NaN; unknown=true; break;
                case "clock_infinite": SharedModelTime.Time=Double.PositiveInfinity; unknown=true; break;
                case "clock_resolution": SharedModelTime.Time=1e30; break;
                case "null_files": act=delegate { new RequestProvisionGuardian(size,digest,10,1900,null,e.K.Api,e.Clock); }; break;
                case "null_kernel": act=delegate { new RequestProvisionGuardian(size,digest,10,1900,e.F.Api,null,e.Clock); }; break;
                case "null_clock": act=delegate { new RequestProvisionGuardian(size,digest,10,1900,e.F.Api,e.K.Api,null); }; break;
                default: throw new Exception("UNKNOWN_PLAN");
            }
            Failure(act,unknown); Check(e.Events.Count==0);
        }
        static void Cap(string name) {
            var e=new ModelEnv(); double bound=name=="nan"?Double.NaN:(name=="infinite"?Double.PositiveInfinity:100);
            if (name=="shorter" || name=="cannot_extend") {
                e.K.Api.NeverExit=true; bound=name=="shorter"?108:1000;
                var run=new HeldProvisionGuardian(e.F.Plan(),e.F.Api,e.K.Api,e.Clock,bound);
                var answer=run.Run(); e.Closed();
                Check(answer.End==LocalProcessEnd.DeadlineStopped && !run.LaunchLeaseRetained);
                Check(SharedModelTime.Time<=(name=="shorter"?103:105)+0.001); return;
            }
            try { new HeldProvisionGuardian(e.F.Plan(),e.F.Api,e.K.Api,e.Clock,bound); }
            catch (HeldGuardianRefused ex) { Check(ex.Message=="shared_deadline" && e.Events.Count==0); return; }
            throw new Exception("EXPECTED_CAP_REFUSAL");
        }
        static void Scenario(string name,byte[] raw,long size,string digest,int seconds,long until) {
            if (name.StartsWith("plan:",StringComparison.Ordinal)) { Plan(name.Substring(5),size,digest); return; }
            if (name.StartsWith("cap:",StringComparison.Ordinal)) { Cap(name.Substring(4)); return; }
            var e=new ModelEnv(); var run=e.Make(size,digest,seconds,until);
            bool fails=false,unknown=false,retained=false; string label=null;
            double stop=100+Math.Min(seconds,until-1000)-5;
            switch (name) {
                case "construct_no_io": Check(e.Events.Count==0 && e.Clock.Reads==1 && !run.LaunchLeaseRetained); return;
                case "normal_exit": case "minimum_budget": break;
                case "nonzero_exit": e.K.Api.Code=7; break;
                case "residual": e.K.Api.Residue=true; break;
                case "timeout": case "maximum_budget": case "approval_cap": e.K.Api.NeverExit=true; break;
                case "wall_rollback_no_renewal": e.K.Api.NeverExit=true; SharedModelTime.Wall=0; break;
                case "arrival_consumes_budget": e.K.Api.NeverExit=true; SharedModelTime.Time=104; break;
                case "decode_consumes_budget": case "decode_and_acquire_share_budget":
                    e.K.Api.NeverExit=true;
                    e.Clock.Hook=delegate(int n) { if (n==3) SharedModelTime.Time+=3; };
                    if (name=="decode_and_acquire_share_budget") {
                        int hashes=0;
                        e.Hook=delegate(string s) { if (s=="F:rewind:"+LaunchBoundary.FileNames[0] && ++hashes==1) SharedModelTime.Time+=1; };
                    }
                    break;
                case "copy_isolation":
                    e.Clock.Hook=delegate(int n) { if (n==3) Array.Clear(raw,0,raw.Length); }; break;
                case "one_shot_concurrent":
                    Func<int> attempt=delegate {
                        try { run.Run(raw); return 1; }
                        catch (RequestGuardianRefused ex) { Check(ex.Message=="one_shot"); return 0; }
                    };
                    Task<int> a=Task.Run(attempt),b=Task.Run(attempt); Task.WaitAll(a,b);
                    Check(a.Result+b.Result==1 && e.K.Api.Resumes==1 && !run.LaunchLeaseRetained); e.Closed(); return;
                case "public_api_fixed":
                    ConstructorInfo[] ctors=typeof(RequestProvisionGuardian).GetConstructors();
                    Check(ctors.Length==1 && ctors[0].GetParameters().Length==4);
                    Check(!typeof(IDisposable).IsAssignableFrom(typeof(RequestProvisionGuardian)));
                    foreach (MethodInfo method in typeof(RequestProvisionGuardian).GetMethods(BindingFlags.Public|BindingFlags.Instance|BindingFlags.DeclaredOnly))
                        Check(method.Name=="Run" || method.Name=="get_LaunchLeaseRetained");
                    Check(e.Events.Count==0); return;
                case "reject:null": case "reject:hash": case "reject:length": case "reject:json": case "reject:canonical":
                    fails=true; label="request_refused"; break;
                case "reject:budget_mismatch": case "reject:expiry_mismatch":
                    fails=true; label="request_window_mismatch"; break;
                case "window:before_decode":
                    SharedModelTime.Time=105; fails=true; label="attempt_window"; break;
                case "window:before_decode_nan":
                    SharedModelTime.Time=Double.NaN; fails=true; unknown=true; label="request_guardian_unknown"; break;
                case "window:after_decode": case "window:after_decode_wall": case "window:after_decode_nan": case "window:after_decode_rollback":
                    fails=true; unknown=name.EndsWith("nan",StringComparison.Ordinal) || name.EndsWith("rollback",StringComparison.Ordinal);
                    label=unknown?"request_guardian_unknown":"attempt_window";
                    e.Clock.Hook=delegate(int n) {
                        if (n!=3) return;
                        if (name.EndsWith("wall",StringComparison.Ordinal)) SharedModelTime.Wall=1900;
                        else SharedModelTime.Time=name.EndsWith("nan",StringComparison.Ordinal)?Double.NaN:
                            (name.EndsWith("rollback",StringComparison.Ordinal)?99:105);
                    }; break;
                case "fault:initial_hash":
                    e.F.Api.Data[LaunchBoundary.FileNames[0]][0]^=1; fails=true; label="held_guardian_refused"; break;
                case "fault:host": e.K.Api.Host=false; fails=true; label="held_guardian_refused"; break;
                case "fault:create": e.K.Api.Fault="create"; fails=true; unknown=true; retained=true; break;
                case "fault:preresume":
                    e.Hook=delegate(string s) { if (s=="K:member") e.F.Api.Data[LaunchBoundary.FileNames[0]][0]^=1; };
                    fails=true; unknown=true; retained=true; break;
                case "fault:stop":
                    e.K.Api.NeverExit=true; e.K.Api.StopFails=true; fails=true; unknown=true; retained=true; break;
                case "fault:target_close": e.F.Api.CloseFault=LaunchBoundary.FileNames[0]; fails=true; unknown=true; break;
                case "fault:late_target_close":
                    e.Hook=delegate(string s) { if (s=="F:close:@") SharedModelTime.Time=111; };
                    fails=true; unknown=true; break;
                default: throw new Exception("UNKNOWN_SCENARIO");
            }
            if (fails) {
                Failure(delegate { run.Run(raw); },unknown,label);
                Check(run.LaunchLeaseRetained==retained); e.K.Api.AllClosed();
                if (retained) e.F.Api.AllLive(); else e.F.Api.AllClosed();
                if (name.StartsWith("reject:",StringComparison.Ordinal) || name.StartsWith("window:",StringComparison.Ordinal))
                    Check(e.Events.Count==0);
                if (name=="fault:preresume") Check(e.K.Api.Resumes==0);
                NoRetry(e,run,raw); return;
            }
            LocalProcessObservation answer=run.Run(raw); e.Closed();
            Check(!run.LaunchLeaseRetained && answer.Resumed && answer.EmptyObserved && answer.ProcessId==42);
            Check(answer.ApprovalSha256==digest && answer.InstallationId==new string('a',32));
            Check(LocalProcessObservation.Scope=="local_process_observations_only_not_install_acceptance");
            if (e.K.Api.NeverExit) {
                Check(answer.End==LocalProcessEnd.DeadlineStopped && e.K.Api.Stops==1 && SharedModelTime.Time<=stop+0.001);
            } else if (name=="residual") Check(answer.End==LocalProcessEnd.ResidualTreeStopped && e.K.Api.Stops==1);
            else Check(answer.End==LocalProcessEnd.RootExited && answer.ExitCode==e.K.Api.Code);
            Check(e.K.Api.Resumes==1); NoRetry(e,run,raw);
        }
        public static string Run(string name,byte[] raw,long size,string digest,int seconds,long until) {
            try { Scenario(name,raw,size,digest,seconds,until); return name+"|PASS"; }
            catch (Exception ex) { return name+"|FAIL|"+ex.GetType().Name+"|"+ex.Message; }
        }
    }
}
'''


def _backend(role):
    """Extract literal fake source without importing/executing sibling tests."""
    path = Path(__file__).with_name(f'test_native_validator_{role}.py')
    tree = ast.parse(path.read_text(encoding='utf-8'))
    values = [ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
              and any(isinstance(t, ast.Name) and t.id == 'HARNESS' for t in node.targets)]
    assert len(values) == 1 and isinstance(values[0], str)
    old = 'internal double Time=100; internal long Wall=1000;'
    assert values[0].count(old) == 1
    shared = (
        'internal double Time { get { return AiAgent.ValidatorHandoff.SharedModelTime.Time; } '
        'set { AiAgent.ValidatorHandoff.SharedModelTime.Time=value; } } '
        'internal long Wall { get { return AiAgent.ValidatorHandoff.SharedModelTime.Wall; } '
        'set { AiAgent.ValidatorHandoff.SharedModelTime.Wall=value; } }'
    )
    return values[0].replace(old, shared).replace('__CASES__', 'new string[0]')


@pytest.fixture(scope='module')
def models(tmp_path_factory):
    if os.name != 'nt':
        pytest.skip('Windows CLR model compiler required; not native launch evidence')
    compiler = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    assert compiler.is_file(), 'required model compiler unavailable'
    folder = tmp_path_factory.mktemp('validator-request-guardian-model')
    paths = list(SOURCES)
    for role in ('launch_boundary', 'process_guardian'):
        path = folder / f'{role}_model.cs'
        path.write_text(_backend(role), encoding='utf-8')
        paths.append(path)
    path = folder / 'request_guardian_models.cs'
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
        raw = _canonical(value)
        if name == 'reject:json':
            raw = b'{'
        if name == 'reject:canonical':
            raw += b' '
        size, digest = len(raw), _sha(raw)
        if name == 'reject:hash':
            digest = '0' * 64
        if name == 'reject:length':
            size += 1
        encoded = '-' if name == 'reject:null' else base64.b64encode(raw).decode('ascii')
        rows.append('|'.join((name, str(size), digest, str(seconds), str(until), encoded)))
    corpus = folder / 'inert_corpus.txt'
    corpus.write_text('\n'.join(rows) + '\n', encoding='ascii')

    def quote(p):
        return "'" + str(p).replace("'", "''") + "'"

    script = (
        "$ErrorActionPreference='Stop'; Add-Type -Path @(" + ','.join(quote(p) for p in paths) + ') '
        "-ReferencedAssemblies @('System.dll','System.Core.dll','System.Xml.dll','System.Runtime.Serialization.dll') -ErrorAction Stop; "
        f'foreach ($line in [IO.File]::ReadAllLines({quote(corpus)})) {{ '
        "$p=$line.Split('|'); $raw=if($p[5] -eq '-'){$null}else{[Convert]::FromBase64String($p[5])}; "
        '[AiAgent.ValidatorAdmission.RequestGuardianHarness]::Run($p[0],$raw,[long]$p[1],$p[2],[int]$p[3],[long]$p[4]) }'
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
def test_request_guardian_clr_models(models, scenario):
    assert models[scenario] == 'PASS'


def test_one_shot_pin_first_metadata_equality_and_original_cap():
    text = CORE.read_text(encoding='utf-8')
    assert text.index('used=true;') < text.index('InstallationRequest.Bind(')
    assert text.index('InstallationRequest.Bind(') < text.index('inputs.CreateLaunchPlan()')
    assert text.index('plan.BudgetSeconds!=budgetSeconds') < text.index('guardian=new HeldProvisionGuardian(')
    assert 'plan.ApprovedUntilUnix!=approvedUntil' in text
    assert 'guardian=new HeldProvisionGuardian(plan,files,kernel,clock,deadline)' in text
    assert 'deadline-ProvisionProcessGuardian.StopReserveSeconds' in text
    assert 'clock.Seconds>=deadline || clock.Unix>=approvedUntil' in text
    assert 'public LocalProcessObservation Run(byte[] request)' in text
    assert 'guardian=null' not in text and 'guardian.Dispose' not in text
    held = HELD.read_text(encoding='utf-8')
    assert 'double? originalDeadline' in held
    assert 'Double.IsNaN(bound) || Double.IsInfinity(bound) || bound<=now' in held
    assert 'limit=Math.Min(limit,bound); // preserve time spent decoding/admitting' in held


def test_no_authorization_transport_entrypoint_or_unsafe_release_added():
    text = CORE.read_text(encoding='utf-8')
    for forbidden in ('DllImport', 'Assembly.Load', 'Process.Start', 'File.Open', 'File.Write',
                      'CreateClaim', 'CreateProcessW', 'WorkerRequestBytes', 'CreateImportPlan'):
        assert forbidden not in text
    assert not re.search(r'\b(?:Main|Dispose|ShellExecute|DeleteFile)\s*\(', text)
    assert '~RequestProvisionGuardian' not in text
    assert 'not authentication' in text and 'permanent authenticated approval MUST precede' in text
    assert 'cross-process cap' in text and 'same monotonic origin' in text


def test_source_is_visible_and_not_deployed_or_wired():
    ignore = (ROOT / '.gitignore').read_text(encoding='utf-8').splitlines()
    exception = '!/' + CORE.relative_to(ROOT).as_posix()
    assert ignore.count(exception) == 1 and ignore.index(exception) > ignore.index('/scripts/*')
    for path in [*(ROOT / 'runtime').glob('*.py'), *(ROOT / 'scripts').glob('*.ps1')]:
        assert 'native_validator_request_guardian' not in path.read_text(encoding='utf-8-sig')
    for name in ('bootstrap_native_deployment.py', 'bootstrap_native_provision.py', 'bootstrap_native_install_request.py'):
        assert 'native_validator_request_guardian' not in (ROOT / 'night_shifts' / name).read_text(encoding='utf-8')
