"""Ordinary native supervision, not protected installation or native setup.

Fixture roles/files/actions are explicit test doubles. Only the private kernel
object descriptor is user-adapted in a disposable copy. The controller holds an
exact duplicated child handle; it never searches for child PIDs/names.
"""
from __future__ import annotations

import ctypes as c
import hashlib
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

from night_shifts import bootstrap_native_build as build
from night_shifts import bootstrap_native_install_request as request
from night_shifts import bootstrap_native_setup_build as setup_build
from tests.night_shifts.test_bootstrap_native_setup_build import profile
from tests.night_shifts.test_native_validator_setup import ROOT, powershell

FIXTURE = r'''
using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.Principal;
using System.Text;
using System.Threading;
using AiAgent.NativeValidator;
using AiAgent.ValidatorGuardian;
namespace AiAgent.ValidatorSetup {
    internal sealed class FixtureRole : ISetupRole {
        public void Require(SetupHostProfile p,bool watchdog) {
            using (WindowsIdentity id=WindowsIdentity.GetCurrent()) {
                if (id.User.Value!=p.Parent.OperatorSid || new WindowsPrincipal(id).IsInRole(WindowsBuiltInRole.Administrator))
                    throw new Exception("ORDINARY_FIXTURE_ROLE_REQUIRED");
            }
        }
    }
    internal sealed class DiskFiles : ISetupAttemptFiles {
        readonly SetupSupervisorProfile p;
        readonly bool watchdog;
        FileStream reader; byte[] pinned;
        internal DiskFiles(SetupSupervisorProfile value,bool owner) { p=value; watchdog=owner; }
        string PathOf(string n) { return Path.Combine(p.Host.Location.Root,n); }
        static void New(string path,byte[] raw) {
            using (var s=new FileStream(path,FileMode.CreateNew,FileAccess.Write,FileShare.None)) { s.Write(raw,0,raw.Length); s.Flush(true); }
        }
        public void Acquire() {
            if (watchdog) New(PathOf("fixture-attempt.claim"),p.Claim());
            else if (!File.Exists(PathOf("fixture-attempt.claim"))) throw new Exception("MISSING_FIXTURE_CLAIM");
            reader=new FileStream(PathOf(SetupHostProfile.HostExe),FileMode.Open,FileAccess.Read,FileShare.Read);
            pinned=new byte[checked((int)reader.Length)]; int offset=0;
            while (offset<pinned.Length) { int n=reader.Read(pinned,offset,pinned.Length-offset); if (n<1) throw new Exception("FIXTURE_READ"); offset+=n; }
            if (pinned.Length!=p.HostBytes || InstallBoundary.Sha(pinned)!=p.HostSha256) throw new Exception("FIXTURE_HOST_PIN"); Reverify();
        }
        public void Reverify() {
            reader.Position=0; byte[] raw=new byte[pinned.Length]; int offset=0;
            while (offset<raw.Length) { int n=reader.Read(raw,offset,raw.Length-offset); if (n<1) throw new Exception("FIXTURE_REVERIFY"); offset+=n; }
            if (reader.ReadByte()!=-1) throw new Exception("FIXTURE_EOF"); SetupPayload.Exact(raw,pinned);
        }
        public void BeforeCreate() { Reverify(); } public void BeforeResume() { Reverify(); }
        public byte[] Packet() { throw new Exception("NO_PACKET_IN_FIXTURE"); }
        public void WriteResult(byte[] raw) { New(PathOf("operation-result.bin"),raw); }
        public byte[] ReadResult() {
            string path=PathOf("operation-result.bin"); if (!File.Exists(path)) return null;
            if (new FileInfo(path).Length>SetupResult.Bytes) throw new Exception("FIXTURE_RESULT_BOUND"); return File.ReadAllBytes(path);
        }
        public void WriteReceipt(byte[] raw) { New(PathOf("supervisor-receipt.json"),raw); }
        public void Close() { FileStream old=reader; reader=null; if (old!=null) old.Dispose(); }
    }
    internal sealed class DiskFactory : ISetupFilesFactory,ISetupSupervisorFilesFactory {
        public ISetupAttemptFiles Host(SetupSupervisorProfile p,SetupClock c,double cap) { return new DiskFiles(p,false); }
        public ISetupAttemptFiles Create(SetupSupervisorProfile p,SetupClock c,double cap) { return new DiskFiles(p,true); }
    }
    internal sealed class InertAction : ISetupOperation {
        public SetupReferences Run(SetupHostProfile p,SetupClock c,double cap,byte[] raw) {
            using (var f=new FileStream(Path.Combine(p.Location.Root,"resumed.marker"),FileMode.CreateNew,FileAccess.Write,FileShare.Read)) {
                byte[] marker=Encoding.ASCII.GetBytes("INERT FIXTURE RESUMED\n"); f.Write(marker,0,marker.Length); f.Flush(true);
            }
            string mode="__MODE__"; if (mode!="normal") Thread.Sleep(Timeout.Infinite);
            var indices=new Dictionary<string,ulong>(StringComparer.Ordinal); ulong index=100;
            foreach (string name in SetupTransaction.Anchors) indices.Add(name,index++); return new SetupReferences(p.Parent,indices);
        }
    }
    // The only PID here is this test's known controller, embedded at compilation.
    // The CHILD capability comes from CreateProcess's ACTUAL returned handle.
    internal sealed class ObservedKernel : IGuardianKernel,IGuardianWindowKernel {
        readonly WindowsSetupSupervisorKernel inner;
        readonly SetupHostProfile p;
        [DllImport("kernel32.dll",ExactSpelling=true)] static extern IntPtr GetCurrentProcess();
        [DllImport("kernel32.dll",ExactSpelling=true)] static extern IntPtr OpenProcess(uint access,bool inherit,uint pid);
        [DllImport("kernel32.dll",ExactSpelling=true)] static extern bool DuplicateHandle(IntPtr source,IntPtr handle,IntPtr target,out IntPtr result,uint access,bool inherit,uint options);
        [DllImport("kernel32.dll",ExactSpelling=true)] static extern bool CloseHandle(IntPtr h);
        [DllImport("kernel32.dll",ExactSpelling=true)] static extern bool QueryInformationJobObject(IntPtr h,int kind,out WindowsGuardianKernel.JobLimits info,uint bytes,IntPtr returned);
        internal ObservedKernel(SetupSupervisorProfile profile,ISetupRole role) { p=profile.Host; inner=new WindowsSetupSupervisorKernel(profile,role,new SetupCounter()); }
        public void RequireHost(GuardianPlan plan) { inner.RequireHost(plan); }
        public object NewJob() {
            object job=inner.NewJob(); WindowsGuardianKernel.JobLimits info;
            if (!QueryInformationJobObject((IntPtr)job,9,out info,(uint)Marshal.SizeOf(typeof(WindowsGuardianKernel.JobLimits)),IntPtr.Zero) ||
                info.Basic.ActiveLimit!=1 || info.Basic.Flags!=0x2008) throw new Exception("FIXTURE_LIMIT_NOT_ONE");
            File.WriteAllText(Path.Combine(p.Location.Root,"limit.marker"),"1"); return job;
        }
        public void BindWindow(GuardianPlan plan,IGuardianClock c,double cap) { inner.BindWindow(plan,c,cap); }
        public ChildPair CreateSuspended(object job,string root) {
            ChildPair child=inner.CreateSuspended(job,root);
            IntPtr controller=OpenProcess(0x40,false,__CONTROLLER_PID__u),copy=IntPtr.Zero;
            if (controller==IntPtr.Zero) throw new Exception("FIXTURE_CONTROLLER_OPEN");
            try {
                if (!DuplicateHandle(GetCurrentProcess(),(IntPtr)child.Process,controller,out copy,0x101001,false,0)) throw new Exception("FIXTURE_CHILD_DUPLICATE");
                // Publish the complete capability text, never a visible partial
                // decimal handle. Only the exact controller owns this duplicate.
                string pending=Path.Combine(root,"child-handle.pending");
                using (var file=new FileStream(pending,FileMode.CreateNew,FileAccess.Write,FileShare.None)) {
                    byte[] bytes=Encoding.ASCII.GetBytes(copy.ToInt64().ToString(System.Globalization.CultureInfo.InvariantCulture));
                    file.Write(bytes,0,bytes.Length); file.Flush(true);
                }
                File.Move(pending,Path.Combine(root,"child-handle.txt"));
            } finally { if (!CloseHandle(controller)) throw new Exception("FIXTURE_CONTROLLER_CLOSE"); }
            return child;
        }
        public bool Member(object process,object job) { return inner.Member(process,job); }
        public uint Resume(object thread) { return inner.Resume(thread); } public uint Wait(object process,uint ms) { return inner.Wait(process,ms); }
        public uint ExitCode(object process) { return inner.ExitCode(process); } public uint Active(object job) { return inner.Active(job); }
        public void Stop(object job) { inner.Stop(job); } public void Pause(int ms) { inner.Pause(ms); } public void Close(object h) { inner.Close(h); }
    }
    internal static class FixtureHostProgram {
        static int Main(string[] args) { return new SetupHostEntry(ReviewedSetupHost.Create(),new GuardianClock(),new SetupCounter(),new FixtureRole(),new DiskFactory(),new InertAction()).Run(args); }
    }
    internal static class FixtureWatchdogProgram {
        static int Main(string[] args) {
            var p=ReviewedSetupSupervisor.Create(); var role=new FixtureRole();
            var entry=new SetupSupervisorEntry(p,new GuardianClock(),role,new DiskFactory(),new ObservedKernel(p,role));
            int code=args.Length==0?entry.Run(args):entry.RunDelivered(args,new SetupCounter());
            if (entry.MustParkForSupervisor) for (;;) { Thread.Sleep(1000); GC.KeepAlive(entry); }
            return code;
        }
    }
}
'''


def _compile(folder, paths, output, entry):
    compiler = Path(os.environ['SystemRoot']) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    manifest = folder / build.MANIFEST_NAME
    manifest.write_bytes(build.MANIFEST_BYTES)
    command = [str(compiler), *build.COMMON_OPTIONS, '/main:' + entry, '/out:' + str(output),
        '/win32manifest:' + str(manifest), *('/reference:' + str(compiler.parent / n) for n in build.REFERENCE_NAMES), *map(str, paths)]
    result = subprocess.run(command, capture_output=True, timeout=20, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    Path(str(output) + '.config').write_bytes(request._CONFIG)


@pytest.mark.parametrize('mode', ['normal', 'deadline', 'owner_death', 'incoming_deadline'])
def test_native_setup_job_window_termination_and_exact_child_handle(mode):
    if os.name != 'nt':
        pytest.skip('requires ordinary x64 Windows job/QPC characterization')
    identity = powershell("$ErrorActionPreference='Stop'; $i=[Security.Principal.WindowsIdentity]::GetCurrent(); "
        "if((New-Object Security.Principal.WindowsPrincipal($i)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'UNELEVATED tests required'}; $i.User.Value")
    assert identity.returncode == 0, identity.stdout + identity.stderr
    sid = identity.stdout.strip()
    assert sid.startswith('S-1-5-21-') and all(ch in 'S-0123456789' for ch in sid)
    folder = Path(tempfile.mkdtemp(prefix='setup-supervision-ordinary-'))
    p = profile()
    p['operator_sid'] = sid
    p['expires_unix'] = int(time.time()) + 600
    p['budget_seconds'] = 20 if mode == 'incoming_deadline' else 8
    p['host_anchor']['path'] = str(folder)
    paths = []
    for name in setup_build.WATCHDOG_SOURCES:
        path = ROOT / 'scripts' / name
        if name == 'native_validator_setup_supervisor_windows.cs':
            source = path.read_text(encoding='utf-8')
            assert source.count('O:BAG:BAD:P(A;;GA;;;SY)(A;;GA;;;BA)') == 1
            source = source.replace('O:BAG:BAD:P(A;;GA;;;SY)(A;;GA;;;BA)', f'O:{sid}G:{sid}D:P(A;;GA;;;SY)(A;;GA;;;{sid})')
            path = folder / name
            path.write_text(source, encoding='utf-8')
        paths.append(path)
    hp = folder / setup_build.HOST_PROFILE_NAME
    hp.write_bytes(setup_build.emit_setup_host_profile(p))
    paths.append(hp)
    wp = folder / setup_build.WATCHDOG_PROFILE_NAME
    # INERT placeholder for the unused watchdog Main in the HOST fixture build.
    # It is not a production profile or a default in any product source.
    wp.write_bytes(setup_build.emit_setup_watchdog_profile({'bytes': 123, 'sha256': 'a' * 64}))
    paths.append(wp)
    driver = folder / 'inert-fixture.cs'
    driver.write_text(FIXTURE.replace('__MODE__', mode).replace('__CONTROLLER_PID__', str(os.getpid())), encoding='utf-8')
    paths.append(driver)
    host = folder / build.SETUP_ENTRY_POINTS[0][0]
    watchdog = folder / build.SETUP_ENTRY_POINTS[1][0]
    _compile(folder, paths, host, 'AiAgent.ValidatorSetup.FixtureHostProgram')
    raw = host.read_bytes()
    wp.write_bytes(setup_build.emit_setup_watchdog_profile({'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}))
    _compile(folder, paths, watchdog, 'AiAgent.ValidatorSetup.FixtureWatchdogProgram')
    k = c.WinDLL('kernel32', use_last_error=True)
    k.WaitForSingleObject.argtypes = [c.c_void_p, c.c_uint32]
    k.WaitForSingleObject.restype = c.c_uint32
    k.CloseHandle.argtypes = [c.c_void_p]
    k.CloseHandle.restype = c.c_int
    child_handle = None
    argv = [str(watchdog)]
    if mode == 'incoming_deadline':
        k.QueryPerformanceCounter.argtypes = [c.POINTER(c.c_int64)]
        k.QueryPerformanceCounter.restype = c.c_int
        k.QueryPerformanceFrequency.argtypes = [c.POINTER(c.c_int64)]
        k.QueryPerformanceFrequency.restype = c.c_int
        counter, frequency = c.c_int64(), c.c_int64()
        assert k.QueryPerformanceFrequency(c.byref(frequency)) and k.QueryPerformanceCounter(c.byref(counter))
        argv += ['--setup-supervise-qpc-v1', str(counter.value + 8 * frequency.value), str(frequency.value)]
    began = time.monotonic()
    proc = subprocess.Popen(argv, cwd=folder, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        limit = time.monotonic() + 7
        while not ((folder / 'resumed.marker').exists() and (folder / 'child-handle.txt').exists()):
            assert proc.poll() is None and time.monotonic() < limit, 'Fixture did not resume; retained: ' + str(folder)
            time.sleep(0.01)
        child_handle = int((folder / 'child-handle.txt').read_text(encoding='ascii'))
        assert child_handle > 0 and (folder / 'limit.marker').read_text(encoding='ascii') == '1'
        if mode == 'owner_death':
            proc.terminate()  # ONLY this exact controller-owned watchdog handle
        stdout, stderr = proc.communicate(timeout=12)
        assert not stdout and not stderr, (stdout, stderr)
        assert k.WaitForSingleObject(child_handle, 5000) == 0, 'Termination UNKNOWN; retain fixture: ' + str(folder)
        if mode != 'owner_death':
            import json
            receipt = json.loads((folder / 'supervisor-receipt.json').read_bytes())
            assert receipt['scope'] == 'local_setup_process_observations_not_acceptance'
            assert receipt['empty_job_observed'] is True and receipt['result_valid'] == (mode == 'normal')
            assert receipt['end'] == ('RootExited' if mode == 'normal' else 'DeadlineStopped')
            assert proc.returncode == (0 if mode == 'normal' else 124)
            if mode == 'incoming_deadline':
                assert time.monotonic() - began < 10, 'Incoming original cap renewed to profile budget'
        else:
            assert not (folder / 'supervisor-receipt.json').exists()
    finally:
        if child_handle is not None:
            assert k.CloseHandle(child_handle), 'Handle close UNKNOWN; retain fixture: ' + str(folder)
        # No PID/name search, broad cleanup or transaction retry after uncertainty.
        if proc.poll() is None:
            proc.kill()  # original exact watchdog handle only
            proc.wait(timeout=5)
    # Failures, timeouts and unknown closes never reach this exact-tree removal.
    shutil.rmtree(folder)
