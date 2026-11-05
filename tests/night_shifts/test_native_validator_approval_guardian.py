"""Unelevated protected-policy/claim composition models, NOT native approval.

Compile ten actual C# sources; substitute token, file, job and clock observations.
Actual codec/plan/claim logic runs on inert synthetic data. No native adapter call,
protected installation, carried runtime, provisioner or VM is invoked.
"""
from __future__ import annotations

import ast
import base64
import hashlib
import json
import os
import re
import struct
import subprocess
from pathlib import Path

import pytest

from night_shifts import bootstrap_native_install_request as profile

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / 'scripts/native_validator_approval_guardian.cs'
REQUEST = ROOT / 'scripts/native_validator_request_guardian.cs'
CODEC = ROOT / 'scripts/native_validator_install_request.cs'
SOURCES = (CORE, *(ROOT / 'scripts' / f'native_validator_{n}.cs' for n in (
    'install_boundary', 'install_windows', 'install_request', 'launch_boundary', 'launch_windows',
    'process_guardian', 'process_guardian_windows', 'held_guardian', 'request_guardian',
)))
SCENARIOS = (
    'construct_no_io', 'normal_exit', 'nonzero_exit', 'timeout', 'residual', 'short_reads',
    'minimum_budget', 'maximum_budget', 'approval_cap', 'arrival_consumes_budget',
    'policy_consumes_budget', 'policy_and_targets_share_budget', 'locks_through_cleanup',
    'one_shot_concurrent', 'new_object_existing_claim', 'different_request_existing_claim',
    'request:null', 'request:pin', 'request:canonical', 'request:late_mutation',
    'overlap:launch', 'overlap:import', 'overlap:source', 'overlap:parent',
    'overlap:ancestor', 'alias:launch', 'alias:scratch', 'alias:import', 'alias:source', 'alias:parent',
    'window:before_run', 'window:before_claim', 'window:after_claim', 'window:wall',
    'window:rollback', 'window:nan',
    'fault:operator', 'fault:root_identity', 'fault:alias', 'fault:path', 'fault:extra_root',
    'fault:existing_claim', 'fault:policy_bytes', 'fault:policy_security', 'fault:read_zero',
    'fault:read_excess', 'fault:read_trailing', 'fault:create', 'fault:write', 'fault:flush',
    'fault:readback', 'fault:claim_identity', 'fault:claim_directory_drift',
    'fault:host', 'fault:create_process', 'fault:preresume', 'fault:stop',
    'fault:post_return_policy', 'fault:close', 'fault:late_close',
    'plan:null', 'plan:index', 'plan:path', 'plan:sid', 'plan:sid_zero', 'plan:policy_pin',
    'plan:policy_size', 'plan:request_size', 'plan:request_pin', 'plan:small_budget',
    'plan:large_budget', 'plan:expired', 'plan:near_expiry', 'plan:far_expiry',
    'plan:clock_nan', 'plan:clock_resolution', 'plan:null_files',
    'cap:nan', 'cap:infinite', 'cap:past', 'cap:shorter', 'cap:cannot_extend', 'public_api_fixed',
)


def _canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode('ascii')


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _request():
    """Extract only the earlier inert fixture function, never execute its tests."""
    path = Path(__file__).with_name('test_native_validator_request_guardian.py')
    tree = ast.parse(path.read_text(encoding='utf-8'))
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_candidate']
    assert len(functions) == 1
    namespace = {'profile': profile, '_sha': _sha, '_canonical': _canonical}
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(path), 'exec'), namespace)
    return namespace['_candidate']()


def _policy(size, digest, seconds, until):
    return _canonical({'version': 1, 'scope': 'protected_native_validator_install_approval_once',
        'operation': profile.OPERATION, 'operator_sid': 'S-1-5-21-1-2-3-1001',
        'request_bytes': size, 'request_sha256': digest, 'budget_seconds': seconds, 'expires_unix': until})


def _binary_string(text):
    raw = text.encode('utf-8')
    size, prefix = len(raw), bytearray()
    while size >= 128:
        prefix.append((size & 127) | 128)
        size >>= 7
    prefix.append(size)
    return bytes(prefix) + raw


def _claim(policy, size, digest, seconds, until):
    # Independent .NET BinaryWriter length-prefixed plan-digest oracle.
    fields = (_binary_string('native-validator-approval-anchor-v1'), _binary_string(r'C:\Approval'),
        struct.pack('<IQ', 88, 100), _binary_string('S-1-5-21-1-2-3-1001'),
        struct.pack('<q', len(policy)), _binary_string(_sha(policy)), struct.pack('<q', size),
        _binary_string(digest), struct.pack('<iq', seconds, until))
    return _canonical({'version': 1, 'scope': 'approval_attempt_consumed_not_acceptance',
        'approval_sha256': _sha(policy), 'request_sha256': digest, 'plan_sha256': _sha(b''.join(fields))})


HARNESS = r'''
using System;
using System.Collections.Generic;
using System.Reflection;
using System.Text;
using System.Threading.Tasks;
using AiAgent.NativeValidator;
using AiAgent.ValidatorAdmission;
using AiAgent.ValidatorGuardian;
using AiAgent.ValidatorHandoff;
namespace AiAgent.ValidatorHandoff {
    internal static class SharedModelTime { internal static double Time; internal static long Wall; }
}
namespace AiAgent.ValidatorApproval {
    internal sealed class ApprovalModelClock : IGuardianClock {
        public double Seconds { get { return SharedModelTime.Time; } }
        public long Unix { get { return SharedModelTime.Wall; } }
    }
    internal sealed class PolicyHandle { internal string Name; internal bool Closed; internal int Position,Closes; }
    internal sealed class PolicyFiles : IBoundaryFiles {
        internal readonly Dictionary<string,Stamp> Meta=new Dictionary<string,Stamp>();
        internal readonly Dictionary<string,byte[]> Data=new Dictionary<string,byte[]>();
        internal readonly List<PolicyHandle> Handles=new List<PolicyHandle>();
        internal Action<string> Hook;
        internal string Fault,ReadMode,WriteMode;
        internal bool Operator=true,ExtraRoot,ShortReads;
        internal int Creates,Writes,Flushes;
        internal PolicyFiles(byte[] policy) {
            Add("@",1,true); Add("",100,true); Add("claims",200,true); Add("approval.json",300,false);
            Data.Add("approval.json",(byte[])policy.Clone()); Meta["approval.json"].Bytes=policy.Length;
        }
        void Add(string name,ulong index,bool directory) {
            string root=@"\\?\Volume{22222222-2222-2222-2222-222222222222}\";
            Meta.Add(name,new Stamp {Volume=88,Index=index,Attributes=directory?16u:32u,Links=1,
                Bytes=0,Private=name!="@",Security=name=="@"?"MODEL_ANCESTOR":"MODEL_PRIVATE",
                FinalName=name=="@"?root:root+"Approval"+(name==""?"":"\\"+name.Replace('/','\\'))});
        }
        void Event(string name) {
            if (Hook!=null) Hook(name);
            if (name==Fault) throw new InvalidOperationException("SYNTHETIC_APPROVAL_CANARY");
        }
        PolicyHandle Make(string name) { var h=new PolicyHandle {Name=name}; Handles.Add(h); return h; }
        static PolicyHandle Live(object handle) {
            var h=(PolicyHandle)handle; ApprovalHarness.Check(!h.Closed); return h;
        }
        public void RequireOperator(string sid) {
            Event("operator"); ApprovalHarness.Check(sid=="S-1-5-21-1-2-3-1001");
            if (!Operator) throw new BoundaryRefused("enabled_operator_required");
        }
        public object Root(string drive) { ApprovalHarness.Check(drive==@"C:\"); Event("root"); return Make("@"); }
        public object Open(object parent,string name,bool directory) {
            PolicyHandle up=Live(parent); Event("open:"+name);
            if (up.Name=="@") { ApprovalHarness.Check(name=="Approval" && directory); return Make(""); }
            ApprovalHarness.Check(up.Name=="" && (name=="claims" || name=="approval.json") && directory==(name=="claims"));
            return Make(name);
        }
        public object CreateClaim(object parent) {
            ApprovalHarness.Check(Live(parent).Name=="claims"); Creates++; Event("create");
            if (Data.ContainsKey("claims/install-attempt.claim")) throw new BoundaryRefused("claim_collision");
            Add("claims/install-attempt.claim",400,false); Data.Add("claims/install-attempt.claim",new byte[0]);
            return Make("claims/install-attempt.claim");
        }
        public Stamp Observe(object handle,bool directory,bool ancestor) {
            var h=Live(handle); Event("observe:"+h.Name); Stamp s=Meta[h.Name];
            ApprovalHarness.Check(directory==((s.Attributes&16)!=0) && ancestor==(h.Name=="@"));
            return new Stamp {Volume=s.Volume,Index=s.Index,Attributes=s.Attributes,Links=s.Links,Bytes=s.Bytes,
                Private=s.Private,Security=s.Security,FinalName=s.FinalName};
        }
        public string[] Names(object directory) {
            string name=Live(directory).Name; Event("names:"+name);
            if (name=="") return ExtraRoot?new string[] {"approval.json","claims","unexpected"}:new string[] {"approval.json","claims"};
            ApprovalHarness.Check(name=="claims");
            return Data.ContainsKey("claims/install-attempt.claim")?new string[] {"install-attempt.claim"}:new string[0];
        }
        public void Rewind(object handle) { var h=Live(handle); Event("rewind:"+h.Name); h.Position=0; }
        public int Read(object handle,byte[] bytes,int count) {
            var h=Live(handle); Event("read:"+h.Name);
            if (ReadMode=="zero") return 0;
            if (ReadMode=="excess") return count+1;
            byte[] raw=Data[h.Name]; int n=Math.Min(count,raw.Length-h.Position);
            if (ReadMode=="trailing" && n==0) return 1;
            if (ShortReads) n=Math.Min(n,7);
            Array.Copy(raw,h.Position,bytes,0,n); h.Position+=n; return n;
        }
        public void WriteClaim(object handle,byte[] bytes) {
            var h=Live(handle); ApprovalHarness.Check(h.Name=="claims/install-attempt.claim"); Writes++; Event("write");
            Data[h.Name]=(byte[])bytes.Clone(); Meta[h.Name].Bytes=bytes.Length;
            if (WriteMode=="short") { Data[h.Name]=new byte[1]; Meta[h.Name].Bytes=1; throw new BoundaryUnknown("short_write"); }
            Flushes++; if (WriteMode=="flush") throw new BoundaryUnknown("flush_unknown");
            if (WriteMode=="readback") Data[h.Name][0]^=1;
            if (WriteMode=="identity") Meta[h.Name].Index++;
        }
        public void Close(object handle) {
            var h=Live(handle); h.Closed=true; h.Closes++; Event("close:"+h.Name);
        }
        internal void Existing() {
            Add("claims/install-attempt.claim",400,false); Data.Add("claims/install-attempt.claim",new byte[] {1});
            Meta["claims/install-attempt.claim"].Bytes=1;
        }
        internal void Closed() { foreach (PolicyHandle h in Handles) ApprovalHarness.Check(h.Closed && h.Closes==1); }
        internal void AllLive() { foreach (PolicyHandle h in Handles) ApprovalHarness.Check(!h.Closed && h.Closes==0); }
    }
    internal sealed class ApprovalEnv {
        internal readonly PolicyFiles A;
        internal readonly AiAgent.ValidatorLaunch.Env F;
        internal readonly AiAgent.ValidatorGuardian.Env K;
        internal readonly ApprovalModelClock Clock=new ApprovalModelClock();
        internal readonly List<string> Events=new List<string>();
        internal Action<string> Hook;
        internal ApprovalEnv(byte[] policy) {
            SharedModelTime.Time=100; SharedModelTime.Wall=1000;
            A=new PolicyFiles(policy); F=new AiAgent.ValidatorLaunch.Env(); K=new AiAgent.ValidatorGuardian.Env();
            A.Hook=delegate(string s) { Event("A:"+s); };
            F.Api.Hook=delegate(string s) { Event("F:"+s); };
            K.Api.Hook=delegate(string s) { Event("K:"+s); };
        }
        void Event(string s) { Events.Add(s); if (Hook!=null) Hook(s); }
        internal ApprovalAnchorPlan Plan(byte[] policy,long size,string digest,int seconds,long until,
            string root=@"C:\Approval",ulong index=100,string sid="S-1-5-21-1-2-3-1001",long? policySize=null,
            string policySha=null,long? requestSize=null,string requestSha=null) {
            return new ApprovalAnchorPlan(root,88,index,sid,policySize??policy.Length,policySha??InstallBoundary.Sha(policy),
                requestSize??size,requestSha??digest,seconds,until);
        }
        internal ApprovalProvisionGuardian Make(ApprovalAnchorPlan plan) {
            return new ApprovalProvisionGuardian(plan,A,F.Api,K.Api,Clock);
        }
        internal void Closed() { A.Closed(); F.Api.AllClosed(); K.Api.AllClosed(); }
    }
    public static class ApprovalHarness {
        internal static void Check(bool yes) { if (!yes) throw new Exception("APPROVAL_ASSERTION"); }
        static void Failure(Action action,bool unknown,string label=null) {
            try { action(); }
            catch (Exception ex) {
                Check((unknown?ex is ApprovalUnknown:ex is ApprovalRefused) && (label==null || ex.Message==label));
                Check(!ex.Message.Contains("CANARY")); return;
            }
            throw new Exception("EXPECTED_APPROVAL_FAILURE");
        }
        static void Equal(byte[] a,byte[] b) {
            Check(a.Length==b.Length); for (int i=0;i<a.Length;i++) Check(a[i]==b[i]);
        }
        static void NoRetry(ApprovalEnv e,ApprovalProvisionGuardian run,byte[] raw) {
            int n=e.Events.Count; Failure(delegate { run.Run(raw); },false,"one_shot"); Check(n==e.Events.Count);
        }
        static void PlanCase(string name,ApprovalEnv e,ApprovalAnchorPlan p,byte[] policy,long size,string digest,int seconds,long until) {
            Action act=delegate { e.Make(p); }; bool unknown=false;
            switch (name) {
                case "null": act=delegate { e.Make(null); }; break;
                case "index": p=e.Plan(policy,size,digest,seconds,until,index:0); break;
                case "path": p=e.Plan(policy,size,digest,seconds,until,root:@"C:\Approval\..\Other"); break;
                case "sid": p=e.Plan(policy,size,digest,seconds,until,sid:"S-1-5-18"); break;
                case "sid_zero": p=e.Plan(policy,size,digest,seconds,until,sid:"S-1-5-21-01-2-3-1001"); break;
                case "policy_pin": p=e.Plan(policy,size,digest,seconds,until,policySha:new string('0',64)); break;
                case "policy_size": p=e.Plan(policy,size,digest,seconds,until,policySize:1025); break;
                case "request_size": p=e.Plan(policy,size,digest,seconds,until,requestSize:32769); break;
                case "request_pin": p=e.Plan(policy,size,digest,seconds,until,requestSha:new string('A',64)); break;
                case "small_budget": case "large_budget": case "expired": case "near_expiry": case "far_expiry": break;
                case "clock_nan": SharedModelTime.Time=Double.NaN; unknown=true; break;
                case "clock_resolution": SharedModelTime.Time=1e30; break;
                case "null_files": act=delegate { new ApprovalProvisionGuardian(p,null,e.F.Api,e.K.Api,e.Clock); }; break;
                default: throw new Exception("UNKNOWN_PLAN");
            }
            Failure(act,unknown); Check(e.Events.Count==0);
        }
        static void Cap(string name,ApprovalEnv e,long size,string digest,int seconds,long until) {
            double bound=name=="nan"?Double.NaN:(name=="infinite"?Double.PositiveInfinity:100);
            if (name=="shorter" || name=="cannot_extend") {
                e.K.Api.NeverExit=true; bound=name=="shorter"?108:1000;
                var run=new RequestProvisionGuardian(size,digest,seconds,until,e.F.Api,e.K.Api,e.Clock,bound);
                LocalProcessObservation result=run.Run(CapRaw); e.Closed();
                Check(result.End==LocalProcessEnd.DeadlineStopped && SharedModelTime.Time<=(name=="shorter"?103:105)+0.001); return;
            }
            try { new RequestProvisionGuardian(size,digest,seconds,until,e.F.Api,e.K.Api,e.Clock,bound); }
            catch (RequestGuardianRefused ex) { Check(ex.Message=="shared_deadline" && e.Events.Count==0); return; }
            throw new Exception("EXPECTED_CAP_REFUSAL");
        }
        static byte[] CapRaw;
        static void Scenario(string name,byte[] raw,long size,string digest,int seconds,long until,byte[] policy,byte[] expectedClaim) {
            var e=new ApprovalEnv(policy); var p=e.Plan(policy,size,digest,seconds,until);
            if (name.StartsWith("plan:",StringComparison.Ordinal)) { PlanCase(name.Substring(5),e,p,policy,size,digest,seconds,until); return; }
            if (name.StartsWith("cap:",StringComparison.Ordinal)) { CapRaw=raw; Cap(name.Substring(4),e,size,digest,seconds,until); return; }
            var run=e.Make(p); bool fail=false,unknown=false,retained=false,launchRetained=false,claimExpected=true;
            double stop=100+Math.Min(seconds,until-1000)-5;
            switch (name) {
                case "construct_no_io": Check(e.Events.Count==0 && !run.ClaimCreationAttempted && !run.ApprovalLeaseRetained); return;
                case "normal_exit": case "minimum_budget": break;
                case "nonzero_exit": e.K.Api.Code=7; break;
                case "residual": e.K.Api.Residue=true; break;
                case "timeout": case "maximum_budget": case "approval_cap": e.K.Api.NeverExit=true; break;
                case "short_reads": e.A.ShortReads=true; break;
                case "arrival_consumes_budget": SharedModelTime.Time=104; e.K.Api.NeverExit=true; break;
                case "policy_consumes_budget": case "policy_and_targets_share_budget":
                    e.K.Api.NeverExit=true; int policyHashes=0,launchHashes=0;
                    e.Hook=delegate(string s) {
                        if (s=="A:rewind:approval.json" && ++policyHashes==1) SharedModelTime.Time+=3;
                        if (name=="policy_and_targets_share_budget" && s=="F:rewind:validator-install-guardian.exe" && ++launchHashes==1)
                            SharedModelTime.Time+=1;
                    }; break;
                case "locks_through_cleanup":
                    e.K.Api.Residue=true; e.K.Api.StopPolls=2;
                    e.Hook=delegate(string s) { if (s.StartsWith("K:",StringComparison.Ordinal)) e.A.AllLive(); }; break;
                case "new_object_existing_claim": case "different_request_existing_claim": break;
                case "one_shot_concurrent":
                    Func<int> attempt=delegate {
                        try { run.Run(raw); return 1; }
                        catch (ApprovalRefused ex) { Check(ex.Message=="one_shot"); return 0; }
                    };
                    Task<int> a=Task.Run(attempt),b=Task.Run(attempt); Task.WaitAll(a,b);
                    Check(a.Result+b.Result==1 && e.A.Creates==1 && e.K.Api.Resumes==1); e.Closed(); return;
                case "public_api_fixed":
                    ConstructorInfo[] ctors=typeof(ApprovalProvisionGuardian).GetConstructors();
                    Check(ctors.Length==1 && ctors[0].GetParameters().Length==1 && ctors[0].GetParameters()[0].ParameterType==typeof(ApprovalAnchorPlan));
                    Check(!typeof(IDisposable).IsAssignableFrom(typeof(ApprovalProvisionGuardian)));
                    foreach (MethodInfo method in typeof(ApprovalProvisionGuardian).GetMethods(BindingFlags.Public|BindingFlags.Instance|BindingFlags.DeclaredOnly))
                        Check(method.Name=="Run" || method.Name=="get_ClaimCreationAttempted" || method.Name=="get_ApprovalLeaseRetained" || method.Name=="get_LaunchLeaseRetained");
                    return;
                case "request:null": case "request:pin": case "request:canonical": fail=true; break;
                case "request:late_mutation":
                    int hashes=0; e.Hook=delegate(string s) { if (s=="A:rewind:approval.json" && ++hashes==3) raw[0]^=1; };
                    fail=true; unknown=true; retained=true; break;
                case "window:before_run": SharedModelTime.Time=105; fail=true; claimExpected=false; break;
                case "window:before_claim":
                    e.Hook=delegate(string s) { if (s=="A:rewind:approval.json") SharedModelTime.Time=105; };
                    fail=true; claimExpected=false; break;
                case "window:after_claim":
                    e.Hook=delegate(string s) { if (s=="A:write") SharedModelTime.Time=105; }; fail=true; break;
                case "window:wall":
                    e.Hook=delegate(string s) { if (s=="A:write") SharedModelTime.Wall=1900; }; fail=true; break;
                case "window:rollback": case "window:nan":
                    e.Hook=delegate(string s) { if (s=="A:write") SharedModelTime.Time=name=="window:nan"?Double.NaN:99; };
                    fail=true; unknown=true; break;
                case "fault:operator": e.A.Operator=false; fail=true; claimExpected=false; break;
                case "fault:root_identity": e.A.Meta[""].Index++; fail=true; claimExpected=false; break;
                case "fault:alias": e.A.Meta["approval.json"].Index=100; fail=true; claimExpected=false; break;
                case "fault:path": e.A.Meta["approval.json"].FinalName+=".changed"; fail=true; claimExpected=false; break;
                case "fault:extra_root": e.A.ExtraRoot=true; fail=true; claimExpected=false; break;
                case "fault:existing_claim": e.A.Existing(); fail=true; claimExpected=false; break;
                case "fault:policy_bytes": e.A.Data["approval.json"][0]^=1; fail=true; claimExpected=false; break;
                case "fault:policy_security":
                    e.Hook=delegate(string s) { if (s=="A:rewind:approval.json") e.A.Meta["approval.json"].Security="CHANGED"; };
                    fail=true; claimExpected=false; break;
                case "fault:read_zero": e.A.ReadMode="zero"; fail=true; claimExpected=false; break;
                case "fault:read_excess": e.A.ReadMode="excess"; fail=true; claimExpected=false; break;
                case "fault:read_trailing": e.A.ReadMode="trailing"; fail=true; claimExpected=false; break;
                case "fault:create": e.A.Fault="create"; fail=true; unknown=true; break;
                case "fault:write": e.A.WriteMode="short"; fail=true; unknown=true; break;
                case "fault:flush": e.A.WriteMode="flush"; fail=true; unknown=true; break;
                case "fault:readback": e.A.WriteMode="readback"; fail=true; break;
                case "fault:claim_identity": e.A.WriteMode="identity"; fail=true; break;
                case "fault:claim_directory_drift":
                    e.Hook=delegate(string s) { if (s=="A:write") e.A.Meta["claims"].Security="CHANGED"; }; fail=true; break;
                case "fault:host": e.K.Api.Host=false; fail=true; unknown=true; retained=true; break;
                case "fault:create_process": e.K.Api.Fault="create"; fail=true; unknown=true; retained=true; launchRetained=true; break;
                case "fault:preresume":
                    e.Hook=delegate(string s) { if (s=="K:member") e.F.Api.Data["validator-install-guardian.exe"][0]^=1; };
                    fail=true; unknown=true; retained=true; launchRetained=true; break;
                case "fault:stop":
                    e.K.Api.NeverExit=true; e.K.Api.StopFails=true; fail=true; unknown=true; retained=true; launchRetained=true; break;
                case "fault:post_return_policy":
                    e.Hook=delegate(string s) { if (s=="K:close:job") e.A.Data["approval.json"][0]^=1; }; fail=true; break;
                case "fault:close": e.A.Fault="close:approval.json"; fail=true; unknown=true; break;
                case "fault:late_close":
                    e.Hook=delegate(string s) { if (s=="A:close:@") SharedModelTime.Time=111; }; fail=true; unknown=true; break;
                default:
                    Check(name.StartsWith("overlap:",StringComparison.Ordinal) || name.StartsWith("alias:",StringComparison.Ordinal));
                    fail=true; break;
            }
            if (fail) {
                Failure(delegate { run.Run(raw); },unknown);
                Check(run.ClaimCreationAttempted==claimExpected && run.ApprovalLeaseRetained==retained && run.LaunchLeaseRetained==launchRetained);
                if (retained) e.A.AllLive(); else e.A.Closed();
                if (launchRetained) e.F.Api.AllLive(); else e.F.Api.AllClosed(); e.K.Api.AllClosed();
                Check(e.A.Creates<=1 && e.A.Writes<=1 && e.A.Flushes<=1);
                if (name.StartsWith("request:",StringComparison.Ordinal) || name.StartsWith("overlap:",StringComparison.Ordinal) || name.StartsWith("alias:",StringComparison.Ordinal)) {
                    Check(e.A.Writes==1 && e.A.Flushes==1 && e.F.Api.Events.Count==0 && e.K.Api.Events.Count==0);
                    Equal(e.A.Data["claims/install-attempt.claim"],expectedClaim);
                }
                NoRetry(e,run,raw); return;
            }
            LocalProcessObservation answer=run.Run(raw); e.Closed();
            Check(run.ClaimCreationAttempted && !run.ApprovalLeaseRetained && !run.LaunchLeaseRetained);
            Check(e.A.Creates==1 && e.A.Writes==1 && e.A.Flushes==1 && e.K.Api.Resumes==1);
            Equal(e.A.Data["claims/install-attempt.claim"],expectedClaim);
            Check(e.Events.IndexOf("A:read:claims/install-attempt.claim")<e.Events.IndexOf("F:operator"));
            Check(e.Events.IndexOf("A:close:approval.json")>e.Events.IndexOf("K:close:job"));
            Check(answer.ApprovalSha256==digest && answer.EmptyObserved && answer.Resumed);
            Check(LocalProcessObservation.Scope=="local_process_observations_only_not_install_acceptance");
            if (e.K.Api.NeverExit) Check(answer.End==LocalProcessEnd.DeadlineStopped && SharedModelTime.Time<=stop+0.001);
            else if (name=="residual" || name=="locks_through_cleanup") Check(answer.End==LocalProcessEnd.ResidualTreeStopped);
            else Check(answer.End==LocalProcessEnd.RootExited && answer.ExitCode==e.K.Api.Code);
            NoRetry(e,run,raw);
            if (name=="new_object_existing_claim" || name=="different_request_existing_claim") {
                if (name=="different_request_existing_claim") { digest=new string('e',64); policy=ApprovalProvisionGuardian.PolicyBytes(e.Plan(policy,size,digest,seconds,until));
                    e.A.Data["approval.json"]=(byte[])policy.Clone(); e.A.Meta["approval.json"].Bytes=policy.Length; }
                var second=e.Make(e.Plan(policy,size,digest,seconds,until)); int creates=e.A.Creates;
                Failure(delegate { second.Run(raw); },false); Check(e.A.Creates==creates && !second.ClaimCreationAttempted); e.A.Closed();
            }
        }
        public static string Run(string name,byte[] raw,long size,string digest,int seconds,long until,byte[] policy,byte[] expectedClaim) {
            try { Scenario(name,raw,size,digest,seconds,until,policy,expectedClaim); return name+"|PASS"; }
            catch (Exception ex) { return name+"|FAIL|"+ex.GetType().Name+"|"+ex.Message; }
        }
    }
}
'''


def _backend(role):
    path = Path(__file__).with_name(f'test_native_validator_{role}.py')
    tree = ast.parse(path.read_text(encoding='utf-8'))
    sources = [ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
               and any(isinstance(t, ast.Name) and t.id == 'HARNESS' for t in n.targets)]
    assert len(sources) == 1
    old = 'internal double Time=100; internal long Wall=1000;'
    assert sources[0].count(old) == 1
    shared = ('internal double Time { get { return AiAgent.ValidatorHandoff.SharedModelTime.Time; } '
        'set { AiAgent.ValidatorHandoff.SharedModelTime.Time=value; } } '
        'internal long Wall { get { return AiAgent.ValidatorHandoff.SharedModelTime.Wall; } '
        'set { AiAgent.ValidatorHandoff.SharedModelTime.Wall=value; } }')
    return sources[0].replace(old, shared).replace('__CASES__', 'new string[0]')


@pytest.fixture(scope='module')
def models(tmp_path_factory):
    if os.name != 'nt':
        pytest.skip('requires Windows CLR model compiler, not native approval evidence')
    compiler = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    assert compiler.is_file()
    folder = tmp_path_factory.mktemp('validator-approval-model')
    paths = list(SOURCES)
    for role in ('launch_boundary', 'process_guardian'):
        path = folder / f'{role}_model.cs'
        path.write_text(_backend(role), encoding='utf-8')
        paths.append(path)
    harness = folder / 'approval_models.cs'
    harness.write_text(HARNESS, encoding='utf-8')
    paths.append(harness)
    rows = []
    for name in SCENARIOS:
        value = _request()
        seconds = 6 if name == 'minimum_budget' else (900 if name in ('maximum_budget', 'approval_cap') else 10)
        until = 1008 if name == 'approval_cap' else 1900
        if name == 'plan:small_budget':
            seconds = 5
        if name == 'plan:large_budget':
            seconds = 901
        until = {'plan:expired': 1000, 'plan:near_expiry': 1005, 'plan:far_expiry': 87401}.get(name, until)
        value.update(budget_seconds=seconds, expires_unix=until)
        place = name.partition(':')[2]
        if name.startswith('overlap:'):
            if place in ('launch', 'import'):
                value[place + '_anchor']['path'] = r'C:\Approval'
            else:
                value['provision']['source' if place == 'ancestor' else ('output_parent' if place == 'parent' else place)]['path'] = (
                    r'C:\Approval\Inside' if place == 'ancestor' else r'C:\Approval')
        if name.startswith('alias:'):
            target = (value[place + '_anchor'] if place in ('launch', 'import') else
                      value['launch_anchor'] if place == 'scratch' else value['provision']['output_parent' if place == 'parent' else place])
            target['scratch_identity' if place == 'scratch' else 'identity'] = {'volume': 88, 'index': 100}
            if place in ('launch', 'scratch'):
                value['launch_anchor']['identity']['volume'] = 88
                value['launch_anchor']['scratch_identity']['volume'] = 88
        raw = _canonical(value)
        if name == 'request:canonical':
            raw += b' '
        size, digest = len(raw), _sha(raw)
        policy = _policy(size, digest, seconds, until)
        expected_claim = _claim(policy, size, digest, seconds, until)
        if name == 'request:pin':
            raw = b'!' + raw[1:]
        encoded = '-' if name == 'request:null' else base64.b64encode(raw).decode('ascii')
        rows.append('|'.join((name, str(size), digest, str(seconds), str(until), encoded,
            base64.b64encode(policy).decode('ascii'), base64.b64encode(expected_claim).decode('ascii'))))
    corpus = folder / 'inert_corpus.txt'
    corpus.write_text('\n'.join(rows) + '\n', encoding='ascii')

    def quote(p):
        return "'" + str(p).replace("'", "''") + "'"

    script = (
        "$ErrorActionPreference='Stop'; Add-Type -Path @(" + ','.join(quote(p) for p in paths) + ') '
        "-ReferencedAssemblies @('System.dll','System.Core.dll','System.Xml.dll','System.Runtime.Serialization.dll') -ErrorAction Stop; "
        f'foreach ($line in [IO.File]::ReadAllLines({quote(corpus)})) {{ '
        "$p=$line.Split('|'); $raw=if($p[5] -eq '-'){$null}else{[Convert]::FromBase64String($p[5])}; "
        '[AiAgent.ValidatorApproval.ApprovalHarness]::Run($p[0],$raw,[long]$p[1],$p[2],[int]$p[3],[long]$p[4],'
        '[Convert]::FromBase64String($p[6]),[Convert]::FromBase64String($p[7])) }'
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
def test_approval_claim_and_guardian_models(models, scenario):
    assert models[scenario] == 'PASS'


def test_permanent_claim_precedes_request_decode_and_preserves_original_cap():
    text = CORE.read_text(encoding='utf-8')
    assert text.index('used=true;') < text.index('Acquire(); // permanent claim') < text.index('InstallationRequest.Bind(request,')
    assert text.index('Exact(policy,policyBytes,true)') < text.index('claimAttempted=true;') < text.index('api.CreateClaim(')
    assert text.index('api.WriteClaim(') < text.index('claim.Before=after; Exact(claim,claimBytes,true)')
    assert 'clock,deadline)' in text and 'inputs.RequireSeparateApprovalAnchor(plan.Root,plan.Volume,plan.Index)' in text
    assert 'if (!entered || returned)' in text and 'approval_retained_outcome_unknown' in text
    assert 'guardian=null' not in text and 'guardian.Dispose' not in text
    request = REQUEST.read_text(encoding='utf-8')
    assert 'double? originalDeadline' in request and 'limit=Math.Min(limit,bound)' in request
    assert 'Double.IsNaN(bound) || Double.IsInfinity(bound) || bound<=now' in request


def test_approval_cannot_select_code_reset_claim_or_become_a_starter():
    text = CORE.read_text(encoding='utf-8')
    for forbidden in ('DllImport', 'Assembly.Load', 'Process.Start', 'File.Open', 'File.Write',
                      'CreateProcessW', 'CreateDirectory', 'JsonReader', 'WorkerRequestBytes'):
        assert forbidden not in text
    assert not re.search(r'\b(?:Main|Dispose|ShellExecute|DeleteFile|SetSecurityInfo)\s*\(', text)
    assert '~ApprovalProvisionGuardian' not in text
    assert 'new WindowsBoundaryFiles()' in text and 'InstallBoundary.ClaimName' in text
    assert 'Fixed leaf across ALL request IDs/digests' in text
    assert 'protected_native_validator_install_approval_once' in text
    assert 'approval_attempt_consumed_not_acceptance' in text
    codec = CODEC.read_text(encoding='utf-8')
    assert 'internal void RequireSeparateApprovalAnchor(' in codec
    assert 'root.StartsWith(path+' in codec and 'path.StartsWith(root+' in codec
    assert 'id.Volume==volume && id.Index==index' in codec


def test_source_visible_without_tool_or_carried_payload_wiring():
    ignore = (ROOT / '.gitignore').read_text(encoding='utf-8').splitlines()
    exception = '!/' + CORE.relative_to(ROOT).as_posix()
    assert ignore.count(exception) == 1 and ignore.index(exception) > ignore.index('/scripts/*')
    for path in [*(ROOT / 'runtime').glob('*.py'), *(ROOT / 'scripts').glob('*.ps1')]:
        assert 'native_validator_approval_guardian' not in path.read_text(encoding='utf-8-sig')
    for name in ('bootstrap_native_deployment.py', 'bootstrap_native_provision.py', 'bootstrap_native_install_request.py'):
        assert 'native_validator_approval_guardian' not in (ROOT / 'night_shifts' / name).read_text(encoding='utf-8')
