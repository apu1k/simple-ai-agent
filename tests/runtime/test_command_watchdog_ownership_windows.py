"""Ordinary atomic-job/handle fixtures. No helper entry point, UAC or install.

Only compiler input is extracted. Exact CreateProcess handles are duplicated to
this known controller; there are no child PID/name searches. Faults affect only
disposable compiler copies. Failed fixture trees are retained, never retried.
"""
from __future__ import annotations

import ctypes as c
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

from runtime.privileged_host import _windows_paths
from tests.runtime.test_elevated_commands import quote

ROOT = Path(__file__).resolve().parents[2]

OBSERVER = r'''
public static class CommandFixture {
    [System.Runtime.InteropServices.StructLayout(System.Runtime.InteropServices.LayoutKind.Sequential)]
    struct Security { public int Size; public System.IntPtr Descriptor; public int Inherit; }
    [System.Runtime.InteropServices.DllImport("kernel32.dll")] static extern System.IntPtr GetCurrentProcess();
    [System.Runtime.InteropServices.DllImport("kernel32.dll")] static extern System.IntPtr OpenProcess(uint access,bool inherit,uint pid);
    [System.Runtime.InteropServices.DllImport("kernel32.dll")] static extern bool DuplicateHandle(System.IntPtr source,System.IntPtr handle,System.IntPtr target,out System.IntPtr result,uint access,bool inherit,uint options);
    [System.Runtime.InteropServices.DllImport("kernel32.dll")] static extern bool CloseHandle(System.IntPtr h);
    [System.Runtime.InteropServices.DllImport("kernel32.dll")] static extern bool GetHandleInformation(System.IntPtr h,out uint flags);
    [System.Runtime.InteropServices.DllImport("kernel32.dll")] static extern System.IntPtr CreateEvent(ref Security s,bool manual,bool initial,string name);
    [System.Runtime.InteropServices.DllImport("kernel32.dll")] static extern uint WaitForSingleObject(System.IntPtr h,uint ms);
    public static string Root,Mode;
    static int closeFault;
    static System.IntPtr failHandle;
    public static bool Refuse() { return true; }
    public static void FailHandle(System.IntPtr h) { failHandle=h; }
    public static bool CloseFault() { return System.Threading.Interlocked.Exchange(ref closeFault,1)==0; }
    public static bool TerminalFault(System.IntPtr h) { return h==failHandle; }
    public static System.IntPtr Sentinel() {
        var s=new Security {Size=System.Runtime.InteropServices.Marshal.SizeOf(typeof(Security)),Inherit=1};
        System.IntPtr h=CreateEvent(ref s,true,false,null); uint flags;
        if (h==System.IntPtr.Zero || !GetHandleInformation(h,out flags) || flags!=1) throw new System.Exception("FIXTURE_SENTINEL"); return h;
    }
    public static void EndSentinel(System.IntPtr h) {
        uint wait=WaitForSingleObject(h,0); bool closed=CloseHandle(h);
        if (wait!=258 || !closed) throw new System.Exception("FIXTURE_UNRELATED_HANDLE_INHERITED_OR_CLOSE_UNKNOWN");
    }
    public static void Published(System.IntPtr child) {
        System.IntPtr controller=OpenProcess(0x40,false,__CONTROLLER_PID__u),copy=System.IntPtr.Zero;
        if (controller==System.IntPtr.Zero) throw new System.Exception("FIXTURE_CONTROLLER_OPEN");
        try {
            if (!DuplicateHandle(GetCurrentProcess(),child,controller,out copy,0x101000,false,0)) throw new System.Exception("FIXTURE_ROOT_DUPLICATE");
            string pending=System.IO.Path.Combine(Root,"root-handle.pending");
            using (var file=new System.IO.FileStream(pending,System.IO.FileMode.CreateNew,System.IO.FileAccess.Write,System.IO.FileShare.None)) {
                byte[] raw=System.Text.Encoding.ASCII.GetBytes(copy.ToInt64().ToString(System.Globalization.CultureInfo.InvariantCulture));
                file.Write(raw,0,raw.Length); file.Flush(true);
            }
            System.IO.File.Move(pending,System.IO.Path.Combine(Root,"root.handle"));
        } finally { if (!CloseHandle(controller)) throw new System.Exception("FIXTURE_CONTROLLER_CLOSE"); }
        if (Mode=="death_before_resume") System.Threading.Thread.Sleep(System.Threading.Timeout.Infinite);
    }
}
'''

WORKER = r'''
import ctypes as c
import os
import subprocess
import sys
import time
from pathlib import Path

root, mode, controller, sentinel = Path(sys.argv[1]), sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
k = c.WinDLL('kernel32', use_last_error=True)
k.SetEvent.argtypes = [c.c_void_p]
k.SetEvent.restype = c.c_int
if k.SetEvent(sentinel):
    raise RuntimeError('UNRELATED_INHERITABLE_EVENT_LEAKED')
(root / 'resumed.marker').write_text('ordinary fixture', encoding='ascii')
if mode in ('residual', 'timeout', 'death_after_resume'):
    child = subprocess.Popen([sys.executable, '-I', '-S', '-B', '-c', 'import time;time.sleep(30)'])
    k.OpenProcess.argtypes = [c.c_uint32, c.c_int, c.c_uint32]
    k.OpenProcess.restype = c.c_void_p
    k.GetCurrentProcess.restype = c.c_void_p
    k.DuplicateHandle.argtypes = [c.c_void_p, c.c_void_p, c.c_void_p, c.POINTER(c.c_void_p), c.c_uint32, c.c_int, c.c_uint32]
    k.DuplicateHandle.restype = c.c_int
    k.CloseHandle.argtypes = [c.c_void_p]
    k.CloseHandle.restype = c.c_int
    owner, copy = k.OpenProcess(0x40, 0, controller), c.c_void_p()
    if not owner:
        raise RuntimeError('FIXTURE_CONTROLLER_OPEN')
    try:
        if not k.DuplicateHandle(k.GetCurrentProcess(), int(child._handle), owner, c.byref(copy), 0x101000, 0, 0):
            raise RuntimeError('FIXTURE_DESCENDANT_DUPLICATE')
        pending = root / 'descendant-handle.pending'
        with pending.open('xb') as stream:
            stream.write(str(copy.value).encode('ascii'))
            stream.flush()
            os.fsync(stream.fileno())
        pending.rename(root / 'descendant.handle')
    finally:
        if not k.CloseHandle(owner):
            raise RuntimeError('FIXTURE_CONTROLLER_CLOSE')
    # The enclosing exact-owned job, not Popen/PID cleanup, owns termination.
    child._child_created = False
if mode in ('timeout', 'death_after_resume'):
    time.sleep(30)
print('INERT_COMMAND_COMPLETED')
'''


def once(text, old, new):
    assert text.count(old) == 1, 'Native fixture seam changed'
    return text.replace(old, new)


def source(mode):
    helper = (ROOT / 'scripts/privileged_command_helper.ps1').read_text(encoding='utf-8')
    start = helper.index('using System;')
    text = helper[start:helper.index("'@", start)]
    text = once(text, '            bool member;', '            CommandFixture.Published(p.Process);\n            bool member;')
    faults = {
        'job_readback': ('actual.Basic.Flags!=0x2000 ||', 'actual.Basic.Flags!=0x2000 || CommandFixture.Refuse() ||'),
        'job_attribute': ('if (!UpdateProcThreadAttribute(attrs,0,new UIntPtr(0x2000d)',
                          'if (CommandFixture.Refuse() || !UpdateProcThreadAttribute(attrs,0,new UIntPtr(0x2000d)'),
        'handle_attribute': ('if (!UpdateProcThreadAttribute(attrs,0,new UIntPtr(0x20002)',
                             'if (CommandFixture.Refuse() || !UpdateProcThreadAttribute(attrs,0,new UIntPtr(0x20002)'),
        'membership': ('|| !member ||', '|| !member || CommandFixture.Refuse() ||'),
        'close': ('old!=IntPtr.Zero && !CloseHandle(old)', 'old!=IntPtr.Zero && (!CloseHandle(old) || CommandFixture.CloseFault())'),
        'wait': ('uint wait=WaitForSingleObject(p.Process,Remaining(ms,limit,frequency));', 'uint wait=0xffffffff;'),
        'stop': ('!TerminateJobObject(job,code)', '(CommandFixture.Refuse() || !TerminateJobObject(job,code))'),
        'accounting': ('if (!QueryAccounting(job,1,', 'if (CommandFixture.Refuse() || !QueryAccounting(job,1,'),
        'drain': ('if (!Task.WaitAll(new Task[]{stdout,stderr},5000))',
                  'if (CommandFixture.Refuse() || !Task.WaitAll(new Task[]{stdout,stderr},5000))'),
    }
    if mode in faults:
        text = once(text, *faults[mode])
    if mode in ('final_process_close', 'final_job_close'):
        text = once(text, 'old!=IntPtr.Zero && !CloseHandle(old)',
            'old!=IntPtr.Zero && (!CloseHandle(old) || CommandFixture.TerminalFault(old))')
        target = 'p.Process' if mode == 'final_process_close' else 'job'
        text = once(text, '            Close(ref p.Process); Close(ref job); return answer;',
            f'            CommandFixture.FailHandle({target}); Close(ref p.Process); Close(ref job); return answer;')
    if mode == 'preparation_expired':
        text = once(text, '            if (Remaining(ms,limit,frequency)==0) throw new Exception("Original window expired before creation");',
            '            System.Threading.Thread.Sleep(300);\n            if (Remaining(ms,limit,frequency)==0) throw new Exception("Original window expired before creation");')
    return text + OBSERVER.replace('__CONTROLLER_PID__', str(os.getpid()))


@pytest.mark.skipif(os.name != 'nt', reason='ordinary Windows atomic-job/handle fixture')
@pytest.mark.parametrize('mode', ['normal', 'residual', 'timeout', 'death_before_resume', 'death_after_resume',
    'job_readback', 'job_attribute', 'handle_attribute', 'membership', 'close', 'wait', 'stop', 'accounting', 'drain',
    'final_process_close', 'final_job_close', 'preparation_expired'])
def test_atomic_outer_ownership_and_strict_terminal_observations(mode):
    folder = Path(tempfile.mkdtemp(prefix='command-ownership-ordinary-'))
    compiler = folder / 'ordinary-compiler-input.cs'
    compiler.write_text(source(mode), encoding='utf-8')
    worker = folder / 'inert-worker.py'
    worker.write_text(WORKER, encoding='utf-8')
    worker_mode = mode if mode in ('residual', 'timeout', 'death_after_resume') else 'normal'
    args = f'-I -S -B "{worker}" "{folder}" {worker_mode} {os.getpid()}'
    script = f"""
$ErrorActionPreference='Stop'
$i=[Security.Principal.WindowsIdentity]::GetCurrent()
if ((New-Object Security.Principal.WindowsPrincipal($i)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {{ throw 'UNELEVATED fixture required' }}
$i.Dispose()
Add-Type -Path {quote(compiler)}
[CommandFixture]::Root={quote(folder)}; [CommandFixture]::Mode={quote(mode)}
$sentinel=[CommandFixture]::Sentinel()
try {{
    $watch=[Diagnostics.Stopwatch]::StartNew()
    $ms=if ({quote(mode)} -ceq 'timeout') {{ 1500 }} elseif ({quote(mode)} -ceq 'preparation_expired') {{ 100 }} else {{ 10000 }}
    $limit=[Diagnostics.Stopwatch]::GetTimestamp()+[long]($ms*[Diagnostics.Stopwatch]::Frequency/1000)
    try {{
        $answer=[CommandWatchdog]::RunWithin({quote(sys.executable)},({quote(args)}+' '+$sentinel.ToInt64()),{quote(folder)},$ms,$limit,[Diagnostics.Stopwatch]::Frequency)
        @{{status='returned';answer=$answer;elapsed=$watch.ElapsedMilliseconds}} | ConvertTo-Json -Depth 4 -Compress
    }} catch {{
        $cause=$_.Exception
        while ($cause.InnerException) {{ $cause=$cause.InnerException }}
        @{{status='unknown';cause=$cause.Message;process_tree_observed=$false}} | ConvertTo-Json -Compress
    }}
}} finally {{ [CommandFixture]::EndSentinel($sentinel) }}
"""
    path = folder / 'ordinary-controller.ps1'
    path.write_text(script, encoding='utf-8-sig')
    _, exe = _windows_paths()
    k = c.WinDLL('kernel32', use_last_error=True)
    k.WaitForSingleObject.argtypes = [c.c_void_p, c.c_uint32]
    k.WaitForSingleObject.restype = c.c_uint32
    k.CloseHandle.argtypes = [c.c_void_p]
    k.CloseHandle.restype = c.c_int
    handles = {}
    proc = subprocess.Popen([str(exe), '-NoProfile', '-NonInteractive', '-File', str(path)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        if mode.startswith('death_'):
            stop = time.monotonic() + 10
            required = ['root.handle'] if mode == 'death_before_resume' else ['root.handle', 'descendant.handle']
            while not all((folder / name).exists() for name in required):
                assert proc.poll() is None and time.monotonic() < stop, 'Fixture did not reach death seam: ' + str(folder)
                time.sleep(0.01)
            if mode == 'death_before_resume':
                assert not (folder / 'resumed.marker').exists(), str(folder)
            proc.kill()  # ONLY the exact original controller-owned watchdog handle
        stdout, stderr = proc.communicate(timeout=16)
        assert not stderr, (str(folder), stdout, stderr)
        if mode.startswith('death_'):
            assert proc.returncode != 0 and not stdout, (str(folder), stdout)
        else:
            assert proc.returncode == 0, (str(folder), stdout)
            result = json.loads(stdout)
            causes = {'job_readback': 'Job readback unknown', 'job_attribute': 'Atomic job attribute refused',
                'handle_attribute': 'Explicit handle attribute refused', 'membership': 'Atomic child membership unknown',
                'close': 'Handle close unknown', 'wait': 'Completion unknown', 'stop': 'Termination unknown',
                'accounting': 'Job accounting unknown', 'drain': 'Output completion unknown',
                'final_process_close': 'Handle close unknown', 'final_job_close': 'Handle close unknown',
                'preparation_expired': 'Original window expired before creation'}
            if mode in causes:
                assert result == dict(status='unknown', cause=causes[mode], process_tree_observed=False), (str(folder), result)
            else:
                assert result['status'] == 'returned', (str(folder), result)
                answer = result['answer']
                assert answer['ProcessTreeObserved'] is True and answer['Truncated'] is False, (str(folder), answer)
                assert answer['Timeout'] == (mode == 'timeout')
                assert answer['Code'] == (124 if mode == 'timeout' else 0) and not answer['Stderr'], (str(folder), answer)
                if mode == 'timeout':
                    assert result['elapsed'] < 6000, (str(folder), result)
                else:
                    assert answer['Stdout'].strip() == 'INERT_COMMAND_COMPLETED', (str(folder), answer)
        for leaf in ('root', 'descendant'):
            capability = folder / (leaf + '.handle')
            if capability.exists():
                handle = int(capability.read_text(encoding='ascii'))
                handles[leaf] = handle
                assert k.WaitForSingleObject(handle, 5000) == 0, 'Process termination UNKNOWN; retain: ' + str(folder)
        before_create = mode in ('job_readback', 'job_attribute', 'handle_attribute', 'preparation_expired')
        assert ('root' in handles) != before_create, str(folder)
        if mode in ('residual', 'timeout', 'death_after_resume'):
            assert 'descendant' in handles and (folder / 'resumed.marker').exists(), str(folder)
        if before_create or mode in ('death_before_resume', 'membership', 'close'):
            assert not (folder / 'resumed.marker').exists(), str(folder)
    finally:
        # Recover any already-published exact capability even after an assertion.
        for leaf in ('root', 'descendant'):
            capability = folder / (leaf + '.handle')
            if leaf not in handles and capability.exists():
                handles[leaf] = int(capability.read_text(encoding='ascii'))
        for handle in handles.values():
            assert k.CloseHandle(handle), 'Capability close UNKNOWN; retain: ' + str(folder)
        if proc.poll() is None:
            proc.kill()
            proc.communicate(timeout=5)
    # Only verified cases reach removal. Failed/unknown fixture trees stay put.
    shutil.rmtree(folder)


def test_outer_helper_has_no_post_create_assignment_or_implicit_handle_inheritance():
    text = (ROOT / 'scripts/privileged_command_helper.ps1').read_text(encoding='utf-8')
    assert 'AssignProcessToJobObject' not in text and 'TerminateProcess(' not in text
    assert 'new UIntPtr(0x2000d)' in text and 'new UIntPtr(0x20002)' in text
    assert '0x08080004' in text and 'ResumeThread(p.Thread)!=1' in text
    assert text.index('Empty(job,p.Process,timeout?124u:2u)') < text.index('Close(ref p.Process); Close(ref job); return answer;')
    assert '$result.process_tree_observed = $answer.ProcessTreeObserved' in text
