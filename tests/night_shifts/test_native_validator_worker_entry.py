"""Offline entry composition; NEVER call Main, section P/Invoke or carried Python.

Compile ten actual C# sources as a library. Reuse inert file/process models to
exercise the actual receiver-frame/clock/owner composition. Native section
rights, handle inheritance, parent authenticity and termination remain unproved.
"""
from __future__ import annotations

import base64
import hashlib
import os
import re
import subprocess
from pathlib import Path

import pytest

from night_shifts import bootstrap_native_install_request as profile
from tests.night_shifts import test_native_validator_worker_guardian as worker_models

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / 'scripts/native_validator_worker_entry.cs'
SOURCES = (CORE, ROOT / 'scripts/native_validator_worker_windows.cs', *worker_models.SOURCES)
SCENARIOS = (
    'construct', 'frame_bounds', 'normal', 'nonzero', 'refused_child', 'unknown_child', 'exit259',
    'timeout', 'residual', 'arrival', 'utc_cap', 'array_mutation', 'concurrent',
    'second_object_claim', 'late_import_close', 'precreate_hash',
    'retained_create', 'retained_membership', 'retained_wait', 'retained_stop', 'retained_process_close',
    'host_failure', 'read_failure', 'read_late', 'read_expired', 'read_rollback', 'read_nan',
    'request_hash', 'request_length', 'request_null', 'request_malformed', 'budget_mismatch', 'expiry_mismatch',
    'parse:null', 'parse:count', 'parse:legacy', 'parse:mode', 'parse:handle_zero',
    'parse:handle_unaligned', 'parse:handle_negative', 'parse:handle_large', 'parse:length_zero',
    'parse:length_large', 'parse:digest_upper', 'parse:digest_newline', 'parse:digest_null',
    'parse:budget_small', 'parse:budget_large', 'parse:leading_zero', 'parse:expiry_large',
    'parse:limit_negative', 'parse:limit_zero', 'parse:frequency_zero', 'parse:frequency_large', 'parse:number_newline',
    'counter:changed', 'counter:frequency', 'counter:zero', 'counter:negative', 'counter:rollback',
    'counter:wide', 'counter:expired', 'counter:large_window', 'counter:short_window',
    'counter:nan', 'counter:infinite', 'counter:negative_clock', 'counter:large_clock',
    'counter:clock_rollback', 'counter:clock_wide', 'counter:clock_throw', 'counter:wall_zero', 'counter:wall_expired',
    'counter:post_sample_rollback', 'counter:post_sample_nan', 'counter:post_sample_infinite',
    'plan:files', 'plan:kernel', 'plan:clock', 'plan:counter', 'plan:input',
)

HARNESS = r'''
using System;
using System.Globalization;
using System.Threading.Tasks;
using AiAgent.NativeValidator;
using AiAgent.ValidatorGuardian;
namespace AiAgent.ValidatorWorker {
    internal sealed class EntryCounterModel : IWorkerCounter {
        internal long First=10000,Second=10010,Rate=1000,Again=1000;
        internal int Reads,Rates;
        public long Frequency() { return ++Rates==1?Rate:Again; }
        public long Read() { return ++Reads==1?First:Second; }
    }
    internal sealed class EntryInputModel : IWorkerEntryInput {
        internal byte[] Raw;
        internal int Hosts,Reads;
        internal bool HostFails,ReadFails;
        internal Action OnRead;
        internal EntryInputModel(byte[] raw) { Raw=(byte[])raw.Clone(); }
        public void RequireHost() { Hosts++; if (HostFails) throw new WorkerEntryRefused("MODEL_HOST"); }
        public byte[] Read(WorkerEntryFrame frame) {
            Reads++; if (OnRead!=null) OnRead();
            if (ReadFails) throw new Exception("INPUT_CANARY");
            return Raw==null?null:(byte[])Raw.Clone();
        }
    }
    public static class EntryHarness {
        static void Check(bool yes) { if (!yes) throw new Exception("ENTRY_ASSERTION"); }
        static string N(long value) { return value.ToString(CultureInfo.InvariantCulture); }
        static string[] Args(byte[] raw) {
            return new string[] {WorkerEntryFrame.Mode,"256",N(raw.Length),InstallBoundary.Sha(raw),"10","1900","20000","1000"};
        }
        static string[] Bad(string name,string[] args) {
            switch (name) {
                case "null": return null;
                case "count": return new string[9];
                case "legacy": return new string[] {"--provision-once"};
                case "mode": args[0]="--run-anything"; break;
                case "handle_zero": args[1]="0"; break;
                case "handle_unaligned": args[1]="257"; break;
                case "handle_negative": args[1]="-4"; break;
                case "handle_large": args[1]="9223372036854775808"; break;
                case "length_zero": args[2]="0"; break;
                case "length_large": args[2]="32769"; break;
                case "digest_upper": args[3]=new string('A',64); break;
                case "digest_newline": args[3]+="\n"; break;
                case "digest_null": args[3]=null; break;
                case "budget_small": args[4]="5"; break;
                case "budget_large": args[4]="901"; break;
                case "leading_zero": args[4]="010"; break;
                case "expiry_large": args[5]="253402300800"; break;
                case "limit_negative": args[6]="-1"; break;
                case "limit_zero": args[6]="0"; break;
                case "frequency_zero": args[7]="0"; break;
                case "frequency_large": args[7]="1000000001"; break;
                case "number_newline": args[2]+="\n"; break;
                default: throw new Exception("UNKNOWN_PARSE_CASE");
            }
            return args;
        }
        static void Plan(string name,ModelEnv e,EntryCounterModel counter,EntryInputModel input) {
            try {
                new WorkerEntry(name=="files"?null:e.F.Api,name=="kernel"?null:e.Python,
                    name=="clock"?null:e.Clock,name=="counter"?null:counter,name=="input"?null:input);
            } catch (WorkerEntryRefused) { Check(e.Events.Count==0 && input.Hosts==0 && counter.Reads==0); return; }
            throw new Exception("EXPECTED_PLAN_REFUSAL");
        }
        static void Scenario(string name,byte[] raw,byte[] worker) {
            var e=new ModelEnv(worker); var counter=new EntryCounterModel(); var input=new EntryInputModel(raw);
            if (name.StartsWith("plan:",StringComparison.Ordinal)) { Plan(name.Substring(5),e,counter,input); return; }
            var entry=new WorkerEntry(e.F.Api,e.Python,e.Clock,counter,input); string[] args=Args(raw);
            int expected=0; bool park=false;
            if (name=="construct") { Check(e.Events.Count==0 && input.Hosts==0 && counter.Reads==0 && !entry.MustParkForSupervisor); return; }
            if (name=="frame_bounds") {
                args[1]=N(Int64.MaxValue-3); args[2]="32768"; args[4]="900";
                args[5]="253402300799"; args[6]=N(Int64.MaxValue); args[7]="1000000000";
                WorkerEntryFrame frame=WorkerEntryFrame.Parse(args); args[2]="1";
                Check(frame.Handle==Int64.MaxValue-3 && frame.RequestBytes==32768 && frame.BudgetSeconds==900 &&
                    frame.ExpiresUnix==253402300799L && frame.CounterLimit==Int64.MaxValue && frame.Frequency==1000000000);
                Check(e.Events.Count==0 && input.Hosts==0 && counter.Reads==0); return;
            }
            if (name.StartsWith("parse:",StringComparison.Ordinal)) { args=Bad(name.Substring(6),args); expected=126; }
            else if (name.StartsWith("counter:",StringComparison.Ordinal)) {
                expected=126;
                switch (name.Substring(8)) {
                    case "changed": counter.Again=999; break;
                    case "frequency": counter.Rate=counter.Again=999; break;
                    case "zero": counter.First=0; break;
                    case "negative": counter.First=-1; break;
                    case "rollback": counter.Second=9999; break;
                    case "wide": counter.Second=10251; break;
                    case "expired": args[6]="10010"; break;
                    // Keep UTC from shortening the deliberately oversized QPC window to 900.
                    case "large_window": args[6]="911011"; ModelTime.Wall=999; break;
                    case "short_window": args[6]="15011"; break;
                    case "nan": ModelTime.Time=Double.NaN; expected=125; break;
                    case "infinite": ModelTime.Time=Double.PositiveInfinity; expected=125; break;
                    case "negative_clock": ModelTime.Time=-1; break;
                    case "large_clock": ModelTime.Time=1000000001; break;
                    case "clock_rollback": e.Clock.Hook=delegate(int n) { if (n==2) ModelTime.Time=99; }; expected=125; break;
                    case "clock_wide": e.Clock.Hook=delegate(int n) { if (n==2) ModelTime.Time=100.251; }; break;
                    case "post_sample_rollback": e.Clock.Hook=delegate(int n) { if (n==3) ModelTime.Time=99; }; expected=125; break;
                    case "post_sample_nan": e.Clock.Hook=delegate(int n) { if (n==3) ModelTime.Time=Double.NaN; }; expected=125; break;
                    case "post_sample_infinite": e.Clock.Hook=delegate(int n) { if (n==3) ModelTime.Time=Double.PositiveInfinity; }; expected=125; break;
                    case "clock_throw": e.Clock.Hook=delegate(int n) { throw new Exception("CLOCK_CANARY"); }; expected=125; break;
                    case "wall_zero": ModelTime.Wall=0; break;
                    case "wall_expired": ModelTime.Wall=1900; break;
                    default: throw new Exception("UNKNOWN_COUNTER_CASE");
                }
            } else {
                switch (name) {
                    case "normal": case "second_object_claim": break;
                    case "nonzero": e.K.Api.Code=7; expected=125; break;
                    case "refused_child": e.K.Api.Code=126; expected=126; break;
                    case "unknown_child": e.K.Api.Code=125; expected=125; break;
                    case "exit259": e.K.Api.Code=259; expected=125; break;
                    case "timeout": e.K.Api.NeverExit=true; expected=125; break;
                    case "residual": e.K.Api.Residue=true; expected=125; break;
                    case "arrival": input.OnRead=delegate { ModelTime.Time=102; }; break;
                    case "utc_cap": ModelTime.Wall=1892; break;
                    case "array_mutation": input.OnRead=delegate { args[3]=new string('0',64); args[4]="900"; args[6]="999999999"; }; break;
                    case "concurrent":
                        Task<int> a=Task.Run(delegate { return entry.Run(args); }),b=Task.Run(delegate { return entry.Run(args); });
                        Task.WaitAll(a,b); Check(a.Result+b.Result==126 && input.Reads==1 && e.K.Api.Resumes==1 && e.F.Api.Writes==1);
                        Check(!entry.MustParkForSupervisor); e.Closed(); return;
                    case "late_import_close":
                        e.Hook=delegate(string at) { if (at=="F:close:@volume") ModelTime.Time=111; }; expected=125; break;
                    case "precreate_hash":
                        e.Hook=delegate(string at) { if (at=="K:job") e.F.Api.Data["payload/night_shifts/bootstrap_native_provision.py"][0]^=1; }; expected=125; break;
                    case "retained_create": e.K.Api.Fault="create"; park=true; expected=125; break;
                    case "retained_membership": e.K.Api.MemberValue=false; park=true; expected=125; break;
                    case "retained_wait": e.K.Api.WaitFailure=UInt32.MaxValue; park=true; expected=125; break;
                    case "retained_stop": e.K.Api.NeverExit=e.K.Api.StopFails=true; park=true; expected=125; break;
                    case "retained_process_close": e.K.Api.CloseFault="process"; park=true; expected=125; break;
                    case "host_failure": input.HostFails=true; expected=126; break;
                    case "read_failure": input.ReadFails=true; expected=125; break;
                    case "read_late": input.OnRead=delegate { ModelTime.Time=105; }; expected=126; break;
                    case "read_expired": input.OnRead=delegate { ModelTime.Wall=1900; }; expected=126; break;
                    case "read_rollback": input.OnRead=delegate { ModelTime.Time=99; }; expected=125; break;
                    case "read_nan": input.OnRead=delegate { ModelTime.Time=Double.NaN; }; expected=125; break;
                    case "request_hash": args[3]=new string('0',64); expected=126; break;
                    case "request_length": args[2]=N(raw.Length+1); expected=126; break;
                    case "request_null": input.Raw=null; expected=126; break;
                    case "request_malformed": input.Raw=new byte[] {123}; args=Args(input.Raw); expected=126; break;
                    case "budget_mismatch": args[4]="9"; expected=126; break;
                    case "expiry_mismatch": args[5]="1901"; expected=126; break;
                    default: throw new Exception("UNKNOWN_ENTRY_CASE");
                }
            }
            int code=entry.Run(args); Check(code==expected && entry.MustParkForSupervisor==park);
            if (park) { e.Live(); e.K.Api.AllClosed(); } else e.Closed();
            if (name.StartsWith("parse:",StringComparison.Ordinal)) Check(input.Hosts==0 && input.Reads==0 && counter.Reads==0 && e.Events.Count==0);
            if (name.StartsWith("counter:",StringComparison.Ordinal) || name=="host_failure") Check(input.Reads==0 && e.Events.Count==0);
            if (name.StartsWith("read_",StringComparison.Ordinal) || name.StartsWith("request_",StringComparison.Ordinal) ||
                name=="budget_mismatch" || name=="expiry_mismatch") Check(e.F.Api.Writes==0 && e.K.Api.Resumes==0);
            if (expected==0) {
                Check(input.Hosts==1 && input.Reads==1 && e.F.Api.Writes==1 && e.K.Api.Resumes==1);
                double cap=e.Python.Context.RunDeadline;
                if (name=="utc_cap") Check(cap>102.998 && cap<103);
                else Check(cap>104.988 && cap<104.99); // arrival never grants a new full budget
            }
            if (name=="second_object_claim") {
                var again=new WorkerEntry(e.F.Api,e.Python,e.Clock,new EntryCounterModel(),new EntryInputModel(raw));
                Check(again.Run(Args(raw))==126 && !again.MustParkForSupervisor && e.F.Api.Writes==1 && e.K.Api.Resumes==1); e.Closed();
            }
            int events=e.Events.Count,reads=input.Reads,hosts=input.Hosts,counters=counter.Reads;
            Check(entry.Run(Args(raw))==126 && entry.MustParkForSupervisor==park);
            Check(events==e.Events.Count && input.Reads==reads && input.Hosts==hosts && counter.Reads==counters);
        }
        public static string Run(string name,byte[] raw,byte[] worker) {
            try { Scenario(name,raw,worker); return name+"|PASS"; }
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
        pytest.skip('requires Windows CLR model compiler; NOT native worker entry evidence')
    folder = tmp_path_factory.mktemp('worker-entry-models')
    paths = list(SOURCES)
    for name, text in (
        ('install_models', worker_models._backend('install_boundary')),
        ('process_models', worker_models._backend('process_guardian')),
        ('worker_models', worker_models.HARNESS),
        ('entry_models', HARNESS),
    ):
        path = folder / f'{name}.cs'
        path.write_text(text, encoding='utf-8')
        paths.append(path)
    raw = profile.build_validation_install_request(worker_models._candidate())
    worker = profile.bind_validation_install_request(
        raw, expected_bytes=len(raw), expected_sha256=hashlib.sha256(raw).hexdigest(),
    ).worker_request
    corpus = folder / 'inert_outer_request.json'
    projected = folder / 'inert_worker_request.json'
    corpus.write_bytes(raw)
    projected.write_bytes(worker)
    compiler = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    assert compiler.is_file()
    script = (
        "$ErrorActionPreference='Stop'; Add-Type -Path @(" + ','.join(_quote(p) for p in paths) + ') '
        "-ReferencedAssemblies @('System.dll','System.Core.dll','System.Xml.dll','System.Runtime.Serialization.dll') -ErrorAction Stop; "
        f'$raw=[IO.File]::ReadAllBytes({_quote(corpus)}); $worker=[IO.File]::ReadAllBytes({_quote(projected)}); '
        'foreach($name in @(' + ','.join(_quote(n) for n in SCENARIOS) + ')) { '
        '[AiAgent.ValidatorWorker.EntryHarness]::Run($name,$raw,$worker) }'
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
def test_entry_clr_composition(models, scenario):
    assert models[scenario] == 'PASS', models[scenario]


def test_receiver_is_read_only_bounded_and_disarms_native_ownership():
    text = CORE.read_text(encoding='utf-8')
    assert 'actual.GrantedAccess!=SectionMapRead' in text
    assert 'flags!=HandleInherit' in text and 'SectionMapRead=4,HandleInherit=1' in text
    assert 'MapViewOfFile(handle,SectionMapRead,0,0,new UIntPtr((uint)frame.RequestBytes))' in text
    assert 'SetHandleInformation(handle,HandleInherit,0)' in text
    assert text.index('adopted=true;') > text.index('if (view==IntPtr.Zero)')
    assert 'IntPtr oldView=view; view=IntPtr.Zero;' in text
    assert 'IntPtr oldHandle=handle; handle=IntPtr.Zero;' in text
    assert text.count('UnmapViewOfFile(oldView)') == text.count('CloseHandle(oldHandle)') == 1
    assert 'entry_section_close_unknown' in text
    assert not re.search(r'\b(?:CreateFileMappingW|OpenFileMappingW|WriteFile|CreateProcessW|CreateNamedPipeW|ReadFile)\s*\(', text)
    assert not re.search(r'\b(?:File|Environment)\.(?:Open|Read|GetEnvironment)', text)


def test_fixed_entry_keeps_the_actual_owner_and_cannot_exit_on_retained_imports():
    text = CORE.read_text(encoding='utf-8')
    assert text.index('used=true;') < text.index('WorkerEntryFrame.Parse(args)')
    assert text.index('owner=new WorkerProvisionGuardian(') < text.index('byte[] raw=input.Read(frame)')
    assert 'LocalProcessObservation answer=owner.Run(raw)' in text
    assert 'owner.ImportLeaseRetained' in text and 'owner=null' not in text
    assert 'if (entry.MustParkForSupervisor)' in text
    assert 'for (;;) { Sleep(UInt32.MaxValue); GC.KeepAlive(entry); }' in text
    assert 'return answer.ExitCode.Value==0?0:(answer.ExitCode.Value==126?126:125)' in text
    assert not re.search(r'\b(?:Dispose|Reset|DeleteFile|TerminateProcess|OpenProcess|Console\.WriteLine)\s*\(', text)
    assert 'static int Main(string[] args)' in text


def test_original_deadline_precedes_reception_and_has_no_fresh_window():
    text = CORE.read_text(encoding='utf-8')
    assert text.index('double first=clock.Seconds;') < text.index('counter.Read()')
    assert 'frame.CounterLimit-end' in text and 'first+(double)remaining-0.001-0.000001' in text
    assert 'last<first || last-first>0.25' in text
    assert 'remaining>900' in text and 'deadline-ProvisionProcessGuardian.StopReserveSeconds<=last' in text
    assert 'new GuardianClock()' in text  # local origin only, never serialized as the earlier cap
    assert 'clock=new WorkerClock(time)' in text and 'clock=time;' not in text
    assert 'Double.Parse' not in text and 'DateTime.Parse' not in text


def test_entry_is_not_installed_published_or_wired():
    ignore = (ROOT / '.gitignore').read_text(encoding='utf-8').splitlines()
    exception = '!/' + CORE.relative_to(ROOT).as_posix()
    assert ignore.count(exception) == 1 and ignore.index(exception) > ignore.index('/scripts/*')
    for path in [*(ROOT / 'runtime').glob('*.py'), *(ROOT / 'scripts').glob('*.ps1')]:
        assert 'native_validator_worker_entry' not in path.read_text(encoding='utf-8-sig')
    # The historical guardian intentionally cannot supply the new section frame.
    outer = (ROOT / 'scripts/native_validator_process_guardian_windows.cs').read_text(encoding='utf-8')
    assert 'false,ProcessFlags,state.Environment,root,ref startup,out state.Child' in outer
    assert 'WorkerEntryFrame' not in outer and 'HANDLE_LIST' not in outer
