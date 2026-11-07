"""Offline fixed-launch/entry models; NEVER invoke P/Invoke or carried Python.

Compile nine actual C# sources with synthetic counter samples. Feed real CLR
command-frame output into the real Python entry/handoff using fake provisioning.
No installed process, native launch, protected claim or VM operation occurs.
"""
from __future__ import annotations

import ast
import base64
import hashlib
import os
import re
import shlex
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from night_shifts import bootstrap_native_install_request as profile
from night_shifts import bootstrap_native_provision as m
from tests.night_shifts import test_bootstrap_native_worker_handoff as handoff_models

wire = handoff_models.wire
probe = handoff_models.probe
ROOT = Path(__file__).resolve().parents[2]
NATIVE = ROOT / 'scripts/native_validator_worker_windows.cs'
SOURCES = (NATIVE, *(ROOT / 'scripts' / f'native_validator_{name}.cs' for name in (
    'worker_guardian', 'install_boundary', 'install_windows', 'install_request',
    'launch_boundary', 'launch_windows', 'process_guardian', 'process_guardian_windows',
)))
SCENARIOS = (
    'capture', 'capture_delay', 'wall_cap', 'command', 'command_max', 'context_copy',
    'frequency_zero', 'frequency_negative', 'frequency_large', 'frequency_changed',
    'counter_zero', 'counter_negative', 'counter_rollback', 'sample_wide',
    'clock_nan', 'clock_infinite', 'expired', 'remaining_large', 'counter_overflow',
    'near_deadline', 'null_counter', 'bind_without_host', 'create_without_binding',
    'job_without_host', 'frame_zero', 'frame_frequency',
)

HARNESS = r'''
using System;
using AiAgent.NativeValidator;
using AiAgent.ValidatorGuardian;
using AiAgent.ValidatorRequest;
namespace AiAgent.ValidatorWorker {
    internal sealed class FixedClock : IGuardianClock {
        internal double Time=100; internal long Wall=1000;
        public double Seconds { get { return Time; } }
        public long Unix { get { return Wall; } }
    }
    internal sealed class FixedCounter : IWorkerCounter {
        internal long First=10000,Second=10010,Rate=1000,Again=1000;
        internal int Reads,FrequencyReads;
        internal Action OnFirst;
        public long Frequency() { return ++FrequencyReads==1?Rate:Again; }
        public long Read() { if (++Reads==1) { if (OnFirst!=null) OnFirst(); return First; } return Second; }
    }
    public static class FixedPythonHarness {
        static void Check(bool value) { if (!value) throw new Exception("FIXED_ASSERTION"); }
        static void Refused(Action action) {
            try { action(); } catch (GuardianRefused) { return; }
            throw new Exception("FIXED_EXPECTED_REFUSAL");
        }
        public static string Run(string name,byte[] raw,long size,string digest) {
            try {
                BoundInstallationInputs inputs=InstallationRequest.Bind(raw,size,digest);
                var launch=inputs.CreateLaunchPlan(); var imports=inputs.CreateImportPlan();
                var plan=new GuardianPlan(launch.Root,launch.OperatorSid,launch.InstallationId,
                    launch.ApprovalSha256,launch.ApprovedUntilUnix,launch.BudgetSeconds);
                var time=new FixedClock(); var counter=new FixedCounter(); double stop=108;
                switch (name) {
                    case "capture_delay": counter.OnFirst=delegate { time.Time=102; }; break;
                    case "wall_cap": time.Wall=1897; break;
                    case "frequency_zero": counter.Rate=counter.Again=0; break;
                    case "frequency_negative": counter.Rate=counter.Again=-1; break;
                    case "frequency_large": counter.Rate=counter.Again=1000000001; break;
                    case "frequency_changed": counter.Again=999; break;
                    case "counter_zero": counter.First=0; break;
                    case "counter_negative": counter.First=-1; break;
                    case "counter_rollback": counter.Second=9999; break;
                    case "sample_wide": counter.Second=10251; break;
                    case "clock_nan": time.Time=Double.NaN; break;
                    case "clock_infinite": time.Time=Double.PositiveInfinity; break;
                    case "expired": time.Time=108; break;
                    case "remaining_large": stop=1001; time.Wall=999; break;
                    case "counter_overflow": counter.First=counter.Second=Int64.MaxValue-1; break;
                    case "near_deadline": stop=100.001; break;
                }
                byte[] worker=inputs.WorkerRequestBytes();
                if (name=="command_max") {
                    worker=new byte[8192]; for (int i=0;i<worker.Length;i++) worker[i]=65;
                    imports.Files["provision-request.json"]=new FilePin(worker.Length,InstallBoundary.Sha(worker));
                }
                var context=new WorkerLaunchContext(plan,imports,worker,stop,time);
                if (name=="null_counter") { Refused(delegate { new WindowsWorkerPythonKernel(null); }); return name+"|PASS"; }
                if (name=="bind_without_host") {
                    var kernel=new WindowsWorkerPythonKernel(counter);
                    Refused(delegate { kernel.Bind(context); }); Refused(delegate { kernel.Bind(context); });
                    Check(counter.Reads==0); return name+"|PASS";
                }
                if (name=="create_without_binding") {
                    var kernel=new WindowsWorkerPythonKernel(counter);
                    Refused(delegate { kernel.CreateSuspended(null,plan.Root); });
                    Refused(delegate { kernel.CreateSuspended(null,plan.Root); }); Check(counter.Reads==0); return name+"|PASS";
                }
                if (name=="job_without_host") {
                    var kernel=new WindowsWorkerPythonKernel(counter);
                    Refused(delegate { kernel.NewJob(); }); Check(counter.Reads==0); return name+"|PASS";
                }
                if (name=="frame_zero" || name=="frame_frequency") {
                    var invalid=new WorkerCounterFrame(name=="frame_zero"?0:17998,name=="frame_frequency"?0:1000);
                    Refused(delegate { WindowsWorkerPythonKernel.Command(context,invalid); }); return name+"|PASS";
                }
                bool invalidClock=name.StartsWith("frequency_",StringComparison.Ordinal) || name.StartsWith("counter_",StringComparison.Ordinal) ||
                    name.StartsWith("clock_",StringComparison.Ordinal) || name=="sample_wide" || name=="expired" ||
                    name=="remaining_large" || name=="near_deadline";
                if (invalidClock) { Refused(delegate { WorkerCounterFrame.Capture(context,counter); }); return name+"|PASS"; }
                WorkerCounterFrame frame=WorkerCounterFrame.Capture(context,counter);
                long expected=name=="capture_delay"?15998:(name=="wall_cap"?12998:17998);
                Check(frame.Limit==expected && frame.Frequency==1000 && counter.Reads==2 && counter.FrequencyReads==2);
                if (name=="context_copy") { byte[] copy=context.CopyRequest(); copy[0]^=1; Check(InstallBoundary.Sha(context.CopyRequest())==context.WorkerSha256); }
                string command=WindowsWorkerPythonKernel.Command(context,frame);
                Check(command.Length<WindowsWorkerPythonKernel.MaxCommandChars && command.IndexOf('\n')<0);
                return name+"|PASS|"+Convert.ToBase64String(System.Text.Encoding.UTF8.GetBytes(command));
            } catch (Exception ex) { return name+"|FAIL|"+ex.GetType().Name+"|"+ex.Message; }
        }
    }
}
'''


def _quote(value):
    return "'" + str(value).replace("'", "''") + "'"


@pytest.fixture(scope='module')
def models(tmp_path_factory):
    if os.name != 'nt':
        pytest.skip('requires Windows CLR compiler; NOT native worker evidence')
    path = Path(__file__).with_name('test_native_validator_worker_guardian.py')
    functions = [n for n in ast.parse(path.read_text(encoding='utf-8')).body
                 if isinstance(n, ast.FunctionDef) and n.name == '_candidate']
    assert len(functions) == 1
    namespace = {'profile': profile, '_sha': handoff_models.sha, '_canonical': handoff_models.canonical}
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(path), 'exec'), namespace)
    value = namespace['_candidate']()
    value['import_anchor']['path'] = r'C:\Import Anchor (Model)'
    raw = profile.build_validation_install_request(value)
    digest = hashlib.sha256(raw).hexdigest()
    folder = tmp_path_factory.mktemp('fixed-python-models')
    harness = folder / 'fixed_models.cs'
    harness.write_text(HARNESS, encoding='utf-8')
    # The OUTER request is much larger than the worker projection. Keep inert
    # model input off PowerShell's UTF-16/Base64-expanded compiler command line.
    corpus = folder / 'inert_outer_request.json'
    corpus.write_bytes(raw)
    paths = (*SOURCES, harness)
    compiler = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    assert compiler.is_file()
    script = (
        "$ErrorActionPreference='Stop'; Add-Type -Path @(" + ','.join(_quote(p) for p in paths) + ') '
        "-ReferencedAssemblies @('System.dll','System.Core.dll','System.Xml.dll','System.Runtime.Serialization.dll') -ErrorAction Stop; "
        f"$raw=[IO.File]::ReadAllBytes({_quote(corpus)}); "
        'foreach($name in @(' + ','.join(_quote(n) for n in SCENARIOS) + ')) { '
        f"[AiAgent.ValidatorWorker.FixedPythonHarness]::Run($name,$raw,[long]{len(raw)},'{digest}') }}"
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
def test_fixed_python_clr_models(models, scenario):
    assert models[scenario].split('|')[0] == 'PASS', models[scenario]


@pytest.fixture
def counter(monkeypatch):
    state = SimpleNamespace(samples=[(10000, 1000), (10010, 1000)], calls=0)

    class FakeCounter:
        def sample(self):
            value = state.samples[state.calls]
            state.calls += 1
            return value

    monkeypatch.setattr(m, '_WindowsWorkerCounter', FakeCounter)
    return state


@pytest.fixture
def fixed(monkeypatch, counter, probe):
    monkeypatch.setattr(m, '_fixed_worker_host', lambda _root: None)
    return probe


def arguments(wire):
    return (wire.document['import_anchor']['path'], base64.b64encode(wire.raw).decode('ascii'),
            str(len(wire.raw)), hashlib.sha256(wire.raw).hexdigest(), wire.outer, '10', '1900', '17998', '1000')


def test_fixed_entry_maps_to_actual_handoff_and_fake_provisioner(wire, fixed):
    assert m._run_fixed_worker(arguments(wire)) == 0
    assert [e[0] for e in fixed.events] == ['construct', 'run']
    assert fixed.events[0][1:3] == (r'C:\Inputs', r'C:\Outputs')
    assert 107.9969 < fixed.events[0][-1] < 107.997


def test_actual_clr_command_frame_reaches_actual_python_entry(models, fixed):
    text = base64.b64decode(models['command'].split('|', 1)[1]).decode('utf-8')
    # Restricted alphabet/path grammar has no embedded quotes/trailing slashes.
    # This is textual codec composition, NOT native Windows CRT parsing evidence.
    tokens = shlex.split(text, posix=False)
    assert tokens[1:5] == ['-I', '-S', '-B', '-c']
    bootstrap = tokens[5][1:-1]
    ast.parse(bootstrap, feature_version=(3, 12))
    assert '_run_fixed_worker(tuple(sys.argv[1:]))' in bootstrap
    frame = tuple(t.strip('"') for t in tokens[6:])
    assert len(frame) == 9 and frame[0] == r'C:\Import Anchor (Model)'
    assert tokens[0] == '"' + frame[0] + '\\runtime\\python.exe"'
    assert m._run_fixed_worker(frame) == 0
    assert [event[0] for event in fixed.events] == ['construct', 'run']
    assert fixed.events[0][-1] < 107.997


@pytest.mark.parametrize('index,value', [
    (0, 'relative'), (0, r'C:\Anchor\..\Other'), (1, ''),
    (2, '0'), (2, '01'), (2, '8193'), (2, '9' * 1000),
    (3, 'A' * 64), (4, 'no'), (5, '5'), (5, '901'), (5, '+10'),
    (6, '0'), (6, '253402300800'), (7, '0'), (7, '9223372036854775808'),
    (8, '0'), (8, '1000000001'),
])
def test_frame_refuses_before_counter_or_provisioning(wire, fixed, counter, index, value):
    frame = list(arguments(wire))
    frame[index] = value
    assert m._run_fixed_worker(tuple(frame)) == 126
    assert fixed.events == [] and counter.calls == 0


@pytest.mark.parametrize('bad', [None, [], (), ('x',) * 8, ('x',) * 10, (None,) * 9])
def test_entry_rejects_wrong_frame_container_without_native(wire, fixed, counter, bad):
    assert m._run_fixed_worker(bad) == 126
    assert fixed.events == [] and counter.calls == 0


@pytest.mark.parametrize('mode', ['alphabet', 'nonascii', 'padding_bits', 'hash', 'json'])
def test_base64_and_pin_checks_precede_json_or_provisioning(wire, fixed, monkeypatch, mode):
    frame = list(arguments(wire))
    if mode in ('alphabet', 'nonascii'):
        frame[1] = ('!' if mode == 'alphabet' else '\u00e9') + frame[1][1:]
    elif mode == 'padding_bits':
        frame[1:4] = ['eB==', '1', hashlib.sha256(b'x').hexdigest()]
    elif mode == 'hash':
        frame[3] = '0' * 64
    else:
        frame[1:4] = [base64.b64encode(b'{').decode('ascii'), '1', hashlib.sha256(b'{').hexdigest()]
    if mode != 'json':
        monkeypatch.setattr(m.json, 'loads', lambda *_a, **_k: pytest.fail('parser before transport/pin check'))
    assert m._run_fixed_worker(tuple(frame)) == 126
    assert fixed.events == []


@pytest.mark.parametrize('samples', [
    [(10000, 999), (10010, 999)], [(10000, 1000), (10010, 999)],
    [(10000, 1000), (9999, 1000)], [(10000, 1000), (10251, 1000)],
    [(17998, 1000), (17998, 1000)],
])
def test_counter_mismatch_expiry_rollback_and_wide_sample(wire, fixed, counter, samples):
    counter.samples = samples
    assert m._run_fixed_worker(arguments(wire)) == 126
    assert fixed.events == []


@pytest.mark.parametrize('times', [(100, 100.251), (100, 99), (float('nan'), 100),
    (100, float('inf')), (-1, 0), (2**40, 2**40)])
def test_local_clock_invalid_window_has_no_provisioning(wire, fixed, monkeypatch, times):
    sequence = iter(times)
    monkeypatch.setattr(m, '_now', lambda: next(sequence))
    assert m._run_fixed_worker(arguments(wire)) == 126
    assert fixed.events == []


def test_transport_work_does_not_renew_deadline(wire, fixed, monkeypatch):
    original = m.base64.b64decode

    def decode(*args, **kw):
        fixed.now = 105
        return original(*args, **kw)

    monkeypatch.setattr(m.base64, 'b64decode', decode)
    assert m._run_fixed_worker(arguments(wire)) == 0
    assert fixed.events[0][-1] < 107.997


@pytest.mark.parametrize('outcome', ['refused', 'unknown', 'exception', 'late'])
def test_post_provisioning_entry_never_reports_success_or_leaks_text(wire, fixed, outcome, capsys):
    def hook(at):
        if at != 'run':
            return
        if outcome == 'late':
            fixed.now = 108
        elif outcome == 'refused':
            raise m.ProvisionRefused('CANARY_PATH')
        elif outcome == 'unknown':
            raise m.ProvisionUnknown('CANARY_NATIVE')
        else:
            raise RuntimeError('CANARY_EXCEPTION')

    fixed.hook = hook
    assert m._run_fixed_worker(arguments(wire)) == 125
    assert capsys.readouterr() == ('', '')


def test_actual_host_guard_cannot_treat_checkout_as_fixed_carried_runtime(wire, probe, counter):
    assert m._run_fixed_worker(arguments(wire)) == 126
    assert probe.events == [] and counter.calls == 0


def test_native_source_fixed_worker_role_private_single_process_atomic_job():
    text = NATIVE.read_text(encoding='utf-8')
    assert 'value.Root+"\\\\"+ProvisionProcessGuardian.WorkerExe' in text
    assert 'limits.Basic.ActiveLimit=1' in text and 'actual.Basic.ActiveLimit!=1' in text
    assert 'limits.Basic.Flags=WG.JobFlags' in text
    assert 'new UIntPtr(WG.JobListAttribute)' in text
    assert 'false,WG.ProcessFlags' in text
    assert 'CreateProcessW(Executable(context),new StringBuilder(command)' in text
    assert 'state.Environment,root,ref startup' in text
    assert 'WG.EnvironmentBlock(root,windows.ToString(),system.ToString())' in text
    for forbidden in ('AssignProcessToJobObject', 'ShellExecute', 'Process.Start', 'File.Open',
                      'SetSecurityInfo', 'DeleteFile', 'Assembly.Load', 'GetProcessById'):
        assert forbidden not in text
    assert not re.search(r'\bMain\s*\(', text)
    assert 'state.Scratch(); answer.Process=' in text
    assert 'finally { state.Close(); }' in text


def test_new_adapter_visible_but_not_installed_or_wired():
    exception = '!/' + NATIVE.relative_to(ROOT).as_posix()
    assert (ROOT / '.gitignore').read_text(encoding='utf-8').splitlines().count(exception) == 1
    for path in [*(ROOT / 'runtime').glob('*.py'), *(ROOT / 'scripts').glob('*.ps1')]:
        assert 'native_validator_worker_windows' not in path.read_text(encoding='utf-8-sig')
    source = (ROOT / 'scripts/native_validator_worker_guardian.cs').read_text(encoding='utf-8')
    assert 'new WindowsWorkerPythonKernel' not in source
