"""Offline guardian entry and generated build DATA; never Main/native execution.

Compile sixteen repository C# sources plus one inert generated profile as a
library. Actual entry/approval/request/held/process/section/frame logic uses
fake policy/input/file/process/counters. No privileged profile is supplied.
"""
from __future__ import annotations

import base64
import copy
import os
import re
import subprocess
from pathlib import Path

import pytest

from night_shifts import bootstrap_native_install_request as profile
from tests.night_shifts import test_native_validator_section_delivery as delivery_models

approval_models = delivery_models.approval_models
request_models = delivery_models.request_models
ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / 'scripts/native_validator_guardian_entry.cs'
SOURCES = (CORE, *delivery_models.SOURCES)
SCENARIOS = (
    'construct', 'normal', 'nonzero', 'child_refusal', 'timeout', 'residual',
    'arrival', 'read_cost', 'policy_cost', 'utc_cap', 'copy_isolation', 'concurrent',
    'bad_payload', 'null_payload', 'existing_claim', 'policy_mismatch', 'host_refused',
    'read_unknown', 'read_late', 'read_rollback',
    'retained_bind', 'retained_create', 'retained_membership', 'retained_stop', 'retained_read_close',
    'frame:null', 'frame:count', 'frame:worker_mode', 'frame:policy_zero', 'frame:policy_large', 'frame:policy_upper',
    'policy:hash', 'policy:bytes', 'policy:request_pin', 'policy:budget',
    'clock:nan', 'clock:post_sample_rollback', 'clock:post_sample_nan', 'clock:post_sample_infinite', 'clock:wide',
    'counter:changed', 'counter:expired', 'counter:short_window',
    'cap:nan', 'cap:infinite', 'cap:past', 'cap:no_run_window', 'cap:shorter', 'cap:cannot_extend',
    'plan:profile', 'plan:files', 'plan:targets', 'plan:kernel', 'plan:clock', 'plan:counter', 'plan:input',
    'native_guards', 'profile_overlap', 'profile_large_identity',
)


def _profile():
    return {'version': 1, 'scope': profile.GUARDIAN_PROFILE_SCOPE,
            'operator_sid': 'S-1-5-21-1-2-3-1001',
            'approval_anchor': {'path': r'C:\Approval', 'identity': {'volume': 88, 'index': 100}},
            'launch_root': r'C:\Private Anchor'}


HARNESS = r'''
using System;
using System.Globalization;
using System.Threading.Tasks;
using AiAgent.NativeValidator;
using AiAgent.ValidatorApproval;
using AiAgent.ValidatorDelivery;
using AiAgent.ValidatorGuardian;
using AiAgent.ValidatorHandoff;
using AiAgent.ValidatorWorker;
namespace AiAgent.ValidatorEntry {
    internal sealed class EntryClockModel : IGuardianClock {
        internal int Reads;
        internal Action<int> Hook;
        public double Seconds { get { Reads++; if (Hook!=null) Hook(Reads); return SharedModelTime.Time; } }
        public long Unix { get { return SharedModelTime.Wall; } }
    }
    internal sealed class EntryInputModel : IGuardianEntryInput {
        internal readonly ApprovalEnv Env;
        internal byte[] Raw;
        internal int Hosts,Reads;
        internal bool HostRefused,ReadUnknown;
        internal Action OnRead;
        internal EntryInputModel(ApprovalEnv env,byte[] raw) { Env=env; Raw=(byte[])raw.Clone(); }
        public void RequireHost(GuardianEntryProfile p) {
            Hosts++; Env.Events.Add("I:host");
            EntryHarness.Check(p.ApprovalRoot==@"C:\Approval" && p.ApprovalVolume==88 && p.ApprovalIndex==100 &&
                p.LaunchRoot==@"C:\Private Anchor" && p.OperatorSid=="S-1-5-21-1-2-3-1001");
            if (HostRefused) throw new GuardianEntryRefused("MODEL_HOST");
        }
        public byte[] Read(GuardianEntryFrame frame) {
            Reads++; Env.Events.Add("I:read"); if (OnRead!=null) OnRead();
            if (ReadUnknown) throw new Exception("INPUT_CANARY");
            return Raw==null?null:(byte[])Raw.Clone();
        }
    }
    public static class EntryHarness {
        internal static void Check(bool yes) { if (!yes) throw new Exception("GUARDIAN_ENTRY_ASSERTION"); }
        static string N(long value) { return value.ToString(CultureInfo.InvariantCulture); }
        static string[] Args(byte[] raw,byte[] policy) {
            return new string[] {GuardianEntryFrame.Mode,"256",N(raw.Length),InstallBoundary.Sha(raw),"20","1900","30000","1000",
                N(policy.Length),InstallBoundary.Sha(policy)};
        }
        static void Refused(Action action) {
            bool refused=false;
            try { action(); } catch (Exception ex) { Check(ex is GuardianEntryRefused || ex is WorkerEntryRefused || ex is ApprovalRefused); refused=true; }
            Check(refused);
        }
        static void Cap(string name,byte[] raw,byte[] policy) {
            var e=new ApprovalEnv(policy); var kernel=new DeliveryModel(e);
            ApprovalAnchorPlan plan=e.Plan(policy,raw.Length,InstallBoundary.Sha(raw),20,1900);
            double bound=name=="nan"?Double.NaN:(name=="infinite"?Double.PositiveInfinity:(name=="no_run_window"?105:99));
            if (name=="shorter" || name=="cannot_extend") {
                bound=name=="shorter"?118:1000;
                var owner=new ApprovalProvisionGuardian(plan,e.A,e.F.Api,kernel,e.Clock,bound);
                LocalProcessObservation answer=owner.Run(raw);
                Check(answer.EmptyObserved && answer.Resumed && kernel.Window.Deadline==(name=="shorter"?113:115));
                Check(!owner.ApprovalLeaseRetained && !owner.LaunchLeaseRetained); e.Closed(); kernel.Memory.Closed(); return;
            }
            Refused(delegate { new ApprovalProvisionGuardian(plan,e.A,e.F.Api,kernel,e.Clock,bound); });
            Check(e.Events.Count==0);
        }
        static void Scenario(string name,byte[] raw,byte[] policy,byte[] claim) {
            if (name.StartsWith("cap:",StringComparison.Ordinal)) { Cap(name.Substring(4),raw,policy); return; }
            if (name=="native_guards") {
                Refused(delegate { new WindowsGuardianEntryInput().RequireHost(null); });
                Refused(delegate { new WindowsGuardianEntryInput().Read(null); });
                Refused(delegate { WindowsWorkerEntryInput.ReadSection(null); }); return; // BEFORE P/Invoke
            }
            if (name=="profile_overlap") {
                Refused(delegate { new GuardianEntryProfile(@"C:\Private Anchor\Policy",88,100,"S-1-5-21-1-2-3-1001",@"C:\Private Anchor"); }); return;
            }
            if (name=="profile_large_identity") {
                var p=new GuardianEntryProfile(@"C:\Approval",UInt32.MaxValue,UInt64.MaxValue,"S-1-5-21-4294967295-1-2-4294967295",@"C:\Private Anchor");
                Check(p.ApprovalIndex==UInt64.MaxValue && p.ApprovalVolume==UInt32.MaxValue); return;
            }
            var e=new ApprovalEnv(policy); var kernel=new DeliveryModel(e); var clock=new EntryClockModel();
            var counter=new CounterModel {TrackTime=true}; var input=new EntryInputModel(e,raw);
            GuardianEntryProfile profile=ReviewedGuardianProfile.Create();
            if (name.StartsWith("plan:",StringComparison.Ordinal)) {
                string part=name.Substring(5);
                Refused(delegate { new GuardianEntry(part=="profile"?null:profile,part=="files"?null:e.A,part=="targets"?null:e.F.Api,
                    part=="kernel"?null:kernel,part=="clock"?null:clock,part=="counter"?null:counter,part=="input"?null:input); });
                Check(e.Events.Count==0 && clock.Reads==0 && counter.Reads==0); return;
            }
            var entry=new GuardianEntry(profile,e.A,e.F.Api,kernel,clock,counter,input); string[] args=Args(raw,policy);
            int expected=0; bool park=false;
            if (name=="construct") { Check(e.Events.Count==0 && clock.Reads==0 && input.Hosts==0 && !entry.MustParkForSupervisor); return; }
            if (name.StartsWith("frame:",StringComparison.Ordinal)) {
                expected=126;
                switch (name.Substring(6)) {
                    case "null": args=null; break;
                    case "count": args=new string[11]; break;
                    case "worker_mode": args[0]=WorkerEntryFrame.Mode; break;
                    case "policy_zero": args[8]="0"; break;
                    case "policy_large": args[8]="1025"; break;
                    case "policy_upper": args[9]=new string('A',64); break;
                    default: throw new Exception("UNKNOWN_FRAME_CASE");
                }
            } else if (name.StartsWith("policy:",StringComparison.Ordinal)) {
                expected=126;
                switch (name.Substring(7)) {
                    case "hash": args[9]=new string('0',64); break;
                    case "bytes": args[8]=N(policy.Length+1); break;
                    case "request_pin": args[3]=new string('0',64); break;
                    case "budget": args[4]="19"; break;
                    default: throw new Exception("UNKNOWN_POLICY_CASE");
                }
            } else if (name.StartsWith("clock:",StringComparison.Ordinal)) {
                expected=125;
                switch (name.Substring(6)) {
                    case "nan": SharedModelTime.Time=Double.NaN; break;
                    case "post_sample_rollback": clock.Hook=delegate(int n) { if (n==3) SharedModelTime.Time=99; }; break;
                    case "post_sample_nan": clock.Hook=delegate(int n) { if (n==3) SharedModelTime.Time=Double.NaN; }; break;
                    case "post_sample_infinite": clock.Hook=delegate(int n) { if (n==3) SharedModelTime.Time=Double.PositiveInfinity; }; break;
                    case "wide": clock.Hook=delegate(int n) { if (n==2) SharedModelTime.Time=100.251; }; expected=126; break;
                    default: throw new Exception("UNKNOWN_CLOCK_CASE");
                }
            } else if (name.StartsWith("counter:",StringComparison.Ordinal)) {
                expected=126;
                switch (name.Substring(8)) {
                    case "changed": counter.Again=999; break;
                    case "expired": args[6]="10010"; break;
                    case "short_window": args[6]="15011"; break;
                    default: throw new Exception("UNKNOWN_COUNTER_CASE");
                }
            } else switch (name) {
                case "normal": break;
                case "nonzero": e.K.Api.Code=7; expected=125; break;
                case "child_refusal": e.K.Api.Code=126; expected=126; break;
                case "timeout": e.K.Api.NeverExit=true; expected=125; break;
                case "residual": e.K.Api.Residue=true; expected=125; break;
                case "arrival": SharedModelTime.Time=102; break;
                case "read_cost": input.OnRead=delegate { SharedModelTime.Time+=2; }; break;
                case "policy_cost": int count=0; e.Hook=delegate(string s) { if (s=="A:rewind:approval.json" && ++count==1) SharedModelTime.Time+=2; }; break;
                case "utc_cap": SharedModelTime.Wall=1882; break;
                case "copy_isolation": input.OnRead=delegate { args[9]=new string('0',64); args[6]="999999999"; }; break;
                case "concurrent":
                    Task<int> a=Task.Run(delegate { return entry.Run(args); }),b=Task.Run(delegate { return entry.Run(args); });
                    Task.WaitAll(a,b); Check(a.Result+b.Result==126 && e.K.Api.Resumes==1 && input.Reads==1);
                    Check(!entry.MustParkForSupervisor); e.Closed(); kernel.Memory.Closed(); return;
                case "bad_payload": input.Raw[0]^=1; expected=126; break;
                case "null_payload": input.Raw=null; expected=126; break;
                case "existing_claim": e.A.Existing(); expected=126; break;
                case "policy_mismatch": e.A.Data["approval.json"][0]^=1; expected=126; break;
                case "host_refused": input.HostRefused=true; expected=126; break;
                case "read_unknown": input.ReadUnknown=true; expected=125; break;
                case "read_late": input.OnRead=delegate { SharedModelTime.Time=116; }; expected=126; break;
                case "read_rollback": input.OnRead=delegate { SharedModelTime.Time=99; }; expected=125; break;
                case "retained_bind": kernel.Fault="request"; expected=125; park=true; break;
                case "retained_create": e.K.Api.Fault="create"; expected=125; park=true; break;
                case "retained_membership": e.K.Api.MemberValue=false; expected=125; park=true; break;
                case "retained_stop": e.K.Api.NeverExit=e.K.Api.StopFails=true; expected=125; park=true; break;
                case "retained_read_close": kernel.Memory.Fault="close:r"; expected=125; park=true; break;
                default: throw new Exception("UNKNOWN_GUARDIAN_ENTRY_CASE");
            }
            Check(entry.Run(args)==expected && entry.MustParkForSupervisor==park);
            e.K.Api.AllClosed(); kernel.Memory.Closed();
            if (park) { e.A.AllLive(); if (name=="retained_bind") e.F.Api.AllClosed(); else e.F.Api.AllLive(); }
            else e.Closed();
            if (name.StartsWith("frame:",StringComparison.Ordinal)) Check(input.Hosts==0 && input.Reads==0 && counter.Reads==0 && e.Events.Count==0);
            if (name.StartsWith("clock:",StringComparison.Ordinal) || name.StartsWith("counter:",StringComparison.Ordinal) ||
                name.StartsWith("policy:",StringComparison.Ordinal)) Check(input.Reads==0 && e.A.Creates==0 && kernel.RequestBinds==0);
            if (name=="bad_payload" || name=="null_payload") Check(e.A.Creates==1 && e.A.Writes==1 && kernel.RequestBinds==0);
            if (name=="read_unknown" || name=="read_late" || name=="read_rollback") Check(e.A.Creates==0 && kernel.RequestBinds==0);
            if (name=="retained_create") Check(e.K.Api.Events.Contains("create"));
            if (name=="retained_stop") Check(e.K.Api.Stops==1);
            if (name=="retained_read_close") Check(kernel.Memory.Events.Contains("close:r"));
            if (expected==0 || name=="nonzero" || name=="child_refusal" || name=="timeout" || name=="residual") {
                Check(e.A.Creates==1 && e.A.Writes==1 && e.A.Flushes==1 && e.K.Api.Resumes==1);
                double cap=kernel.Window.Deadline;
                if (name=="utc_cap") Check(cap>112.998 && cap<113); else Check(cap>114.988 && cap<114.99);
                Check(kernel.Frame.Limit<24998 && kernel.Frame.Limit>22970);
                Check(Convert.ToBase64String(e.A.Data["claims/install-attempt.claim"])==Convert.ToBase64String(claim));
            }
            int events=e.Events.Count,reads=input.Reads,counters=counter.Reads;
            Check(entry.Run(Args(raw,policy))==126 && entry.MustParkForSupervisor==park);
            Check(events==e.Events.Count && reads==input.Reads && counters==counter.Reads);
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
        pytest.skip('requires Windows CLR compiler; NOT installed guardian/native execution evidence')
    folder = tmp_path_factory.mktemp('guardian-entry-models')
    paths = list(SOURCES)
    generated = folder / 'ReviewedGuardianProfile.g.cs'
    generated.write_bytes(profile.build_validation_guardian_profile(_profile()))
    paths.append(generated)
    for name, text in (
        ('launch_models', request_models._backend('launch_boundary')),
        ('process_models', request_models._backend('process_guardian')),
        ('approval_models', approval_models.HARNESS),
        ('section_models', delivery_models.HARNESS),
        ('entry_models', HARNESS),
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
        '[AiAgent.ValidatorEntry.EntryHarness]::Run($name,$raw,$policy,$claim) }'
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
def test_guardian_entry_clr_models(models, scenario):
    assert models[scenario] == 'PASS', models[scenario]


BAD_PROFILES = (
    ('version_bool', ('version',), True),
    ('scope', ('scope',), 'authorized'),
    ('extra', ('reset',), True),
    ('request_pin', ('request_sha256',), 'a' * 64),
    ('policy_pin', ('policy_sha256',), 'a' * 64),
    ('budget', ('budget_seconds',), 20),
    ('source', ('source_code',), 'unreviewed'),
    ('sid', ('operator_sid',), 'S-1-5-18'),
    ('sid_zero', ('operator_sid',), 'S-1-5-21-01-2-3-1001'),
    ('sid_large', ('operator_sid',), 'S-1-5-21-4294967296-2-3-1001'),
    ('anchor_extra', ('approval_anchor', 'sha256'), 'a' * 64),
    ('volume_bool', ('approval_anchor', 'identity', 'volume'), True),
    ('volume_large', ('approval_anchor', 'identity', 'volume'), 2**32),
    ('index_zero', ('approval_anchor', 'identity', 'index'), 0),
    ('index_large', ('approval_anchor', 'identity', 'index'), 2**64),
    ('relative', ('approval_anchor', 'path'), 'relative'),
    ('quote', ('approval_anchor', 'path'), 'C:\\Policy"Injected'),
    ('newline', ('approval_anchor', 'path'), 'C:\\Policy\nInjected'),
    ('device', ('approval_anchor', 'path'), r'C:\NUL'),
    ('launch_long', ('launch_root',), 'C:\\' + 'a' * 198),
    ('same_root', ('approval_anchor', 'path'), r'C:\PRIVATE ANCHOR'),
    ('ancestor', ('approval_anchor', 'path'), r'C:\Private Anchor\Policy'),
    ('descendant', ('launch_root',), r'C:\Approval\Host'),
)


@pytest.mark.parametrize('_case,keys,bad', BAD_PROFILES, ids=[row[0] for row in BAD_PROFILES])
def test_profile_emitter_rejects_unreviewable_or_self_referential_data(_case, keys, bad):
    value = copy.deepcopy(_profile())
    target = value
    for key in keys[:-1]:
        target = target[key]
    target[keys[-1]] = bad
    with pytest.raises(profile.InstallRequestRefused):
        profile.build_validation_guardian_profile(value)


def test_profile_emitter_is_bounded_deterministic_and_has_no_request_hash_cycle(monkeypatch):
    import builtins
    monkeypatch.setattr(builtins, 'open', lambda *_a, **_k: pytest.fail('profile emitter accessed files'))
    raw = profile.build_validation_guardian_profile(_profile())
    assert profile.build_validation_guardian_profile(dict(reversed(tuple(_profile().items())))) == raw
    text = raw.decode('ascii')
    assert len(raw) <= profile.MAX_GUARDIAN_PROFILE_BYTES and raw.endswith(b'\n')
    assert '@"C:\\Approval",88u,100UL,"S-1-5-21-1-2-3-1001",@"C:\\Private Anchor"' in text
    assert not any(name in text for name in ('request_sha256', 'policy_sha256', 'expires_unix', 'budget_seconds'))
    assert 'ReviewedGuardianProfile' in text and 'not authorization or pre-load trust' in text


def test_fixed_entry_binds_profile_and_earlier_cap_before_reception_without_auth_claims():
    text = CORE.read_text(encoding='utf-8')
    assert text.index('used=true;') < text.index('GuardianEntryFrame.Parse(args)')
    assert text.index('WorkerEntryDeadline.Translate(') < text.index('owner=new ApprovalProvisionGuardian(') < text.index('byte[] raw=input.Read(frame)')
    assert 'kernel,clock,earlier)' in text and 'clock=new WorkerClock(time)' in text
    assert 'new WindowsSectionGuardianKernel()' in text and 'ReviewedGuardianProfile.Create()' in text
    assert r'profile.LaunchRoot+"\\"+ProvisionProcessGuardian.GuardianExe' in text
    assert 'identity.User.Value!=profile.OperatorSid' in text
    assert 'owner.ApprovalLeaseRetained || owner.LaunchLeaseRetained' in text
    assert 'for (;;) { Sleep(UInt32.MaxValue); GC.KeepAlive(entry); }' in text
    assert 'owner=null' not in text and 'Console.Write' not in text
    for forbidden in ('Assembly.Load', 'File.Open', 'File.Read', 'Process.Start', 'ShellExecute', 'SetSecurityInfo', 'DeleteFile'):
        assert forbidden not in text


def test_shared_native_section_reader_preserves_worker_gates_and_read_only_policy():
    text = (ROOT / 'scripts/native_validator_worker_entry.cs').read_text(encoding='utf-8')
    entry = CORE.read_text(encoding='utf-8')
    assert 'return ReadSection(frame);' in text and 'internal static byte[] ReadSection(WorkerEntryFrame frame)' in text
    assert text.index('if (!host || frame==null)') < text.index('return ReadSection(frame);')
    assert 'return WindowsWorkerEntryInput.ReadSection(frame.Request)' in entry
    assert 'actual.GrantedAccess!=SectionMapRead' in text and 'SetHandleInformation(handle,HandleInherit,0)' in text
    assert 'adopted=true;' in text and 'if (adopted && !CloseHandle(oldHandle))' in text
    approval = (ROOT / 'scripts/native_validator_approval_guardian.cs').read_text(encoding='utf-8')
    assert 'double? originalDeadline' in approval and 'limit=Math.Min(limit,bound)' in approval
    assert 'Acquire(); // permanent claim' in approval and 'clock,deadline)' in approval


def test_no_production_profile_installation_tool_or_carried_payload_wiring():
    ignore = (ROOT / '.gitignore').read_text(encoding='utf-8').splitlines()
    exception = '!/' + CORE.relative_to(ROOT).as_posix()
    assert ignore.count(exception) == 1 and ignore.index(exception) > ignore.index('/scripts/*')
    assert not (ROOT / 'scripts/ReviewedGuardianProfile.g.cs').exists()
    for path in [*(ROOT / 'runtime').glob('*.py'), *(ROOT / 'scripts').glob('*.ps1')]:
        assert 'native_validator_guardian_entry' not in path.read_text(encoding='utf-8-sig')
    for name in ('bootstrap_native_deployment.py', 'bootstrap_native_provision.py'):
        assert 'native_validator_guardian_entry' not in (ROOT / 'night_shifts' / name).read_text(encoding='utf-8')
    assert not re.search(r'\b(?:CreateProcessW|CreateFileMappingW|CreateClaim|WriteFile|CreateNamedPipeW)\s*\(', CORE.read_text(encoding='utf-8'))
