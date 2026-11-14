"""Ordinary, inert FULL helper-attempt fixtures. Never protected execution.

Admission/ACLs are explicit disposable adapters. The actual parent/worker helper,
atomic jobs, inherited lease, original window and result publication execute.
Failures retain fixture trees. Exact duplicated handles, never PID searches.
"""
from __future__ import annotations

import ctypes as c
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from runtime import elevated_commands as client
from runtime.command_lifetime import CommandLifetime
from runtime.privileged_host import PrivilegedHostError, _windows_paths
from runtime.privileged_turn import ELEVATED_OPERATION, PrivilegedClaim, PrivilegedTurn
from tests.runtime.test_command_lifetime import OWNER
from tests.runtime.test_command_watchdog_ownership_windows import OBSERVER, ROOT, once
from tests.runtime.test_elevated_commands import quote
from tests.runtime.test_elevated_receipts import receipt


@pytest.mark.parametrize('capability', [None, True, False, 0, 2, '1'])
def test_fixed_setup_refuses_missing_supervisor_before_pending(monkeypatch, tmp_path, capability):
    policy = dict(operator_sid='fixture', helper_sha256='c' * 64, max_timeout=900,
        lifetime_protocol=1, preparation_protocol=1, setup_preload_protocol=1)
    if capability is not None:
        policy['preparation_supervision_protocol'] = capability
    monkeypatch.setattr(client, 'local_path', lambda *args, **kwargs: tmp_path)
    monkeypatch.setattr(client, 'load_launcher', lambda: (tmp_path, tmp_path / 'powershell.exe', policy))
    monkeypatch.setattr(client, 'await_approval', lambda *args: pytest.fail('must refuse before pending'))
    with pytest.raises(PrivilegedHostError, match='preparation-worker supervision deployment'):
        client.run_approved_script(PrivilegedTurn(), PrivilegedClaim('a' * 32, time.time() + 30, ELEVATED_OPERATION),
            'exit 0', 20, 'fixture', str(tmp_path), require_preparation_supervision=True)


@pytest.mark.parametrize('value', [None, True, False, 1, 'true'])
def test_supervision_evidence_is_typed_and_cannot_replace_inner_observations(value):
    data = receipt()
    data.update(preparation_supervision_observed=value, preparation_observed=True,
        lifetime_observed=True, process_tree_observed=True)
    claim = PrivilegedClaim(data['request_id'], 1000, ELEVATED_OPERATION)
    if type(value) is not bool:
        with pytest.raises(PrivilegedHostError):
            client.validate_receipt(data, claim, 'b' * 64, 'c' * 64)
    else:
        client.validate_receipt(data, claim, 'b' * 64, 'c' * 64)
        if value:
            for field in ('preparation_observed', 'lifetime_observed', 'process_tree_observed'):
                broken = dict(data)
                del broken[field]
                with pytest.raises(PrivilegedHostError):
                    client.validate_receipt(broken, claim, 'b' * 64, 'c' * 64)


def ordinary_helper(folder, sid, mode):
    text = (ROOT / 'scripts/privileged_command_helper.ps1').read_text(encoding='utf-8')
    text = once(text, "$root = [IO.Path]::Combine([Environment]::GetFolderPath('ProgramFiles'), 'AiAgentElevatedCommands')",
        '$root = ' + quote(folder))
    text = once(text, 'if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator))',
        'if ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator))')
    start, end = text.index('function Check-Local('), text.index('$exe = ')
    text = text[:start] + (
        'function Check-Local([string]$Path) { if ($Path -cne $root -and -not $Path.StartsWith($root+[IO.Path]::DirectorySeparatorChar,[StringComparison]::Ordinal)) { throw "OUTSIDE_ORDINARY_FIXTURE" }; '
        'if ((Get-Item -LiteralPath $Path -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "FIXTURE_REPARSE" } }\n'
        'function Check-Protected([string]$Path) { if ($Path -cne $exe) { Check-Local $Path } }\n') + text[end:]
    text = once(text, "('O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;FRFX;;;' + $OperatorSid + ')')",
        "('O:' + $OperatorSid + 'G:' + $OperatorSid + 'D:P(A;;FA;;;' + $OperatorSid + ')')")
    text = once(text, '            bool member;',
        '            if (deliver) CommandFixture.Published(p.Process);\n            bool member;')
    start = text.index('using System;')
    end = text.index("'@", start)
    text = text[:end] + OBSERVER.replace('__CONTROLLER_PID__', str(os.getpid())) + '\n' + text[end:]
    text = once(text, "'@\n    if (-not $preparationWorker)",
        "'@\n    [CommandFixture]::Root=" + quote(folder) + "; [CommandFixture]::Mode='normal'\n    if (-not $preparationWorker)")
    if mode.startswith(('deadline', 'cancel', 'caller_death', 'watchdog_death')):
        seam = '        $out.Write($Data,0,$Data.Length); $out.Flush($true)' if mode.endswith('write') else '    # Kill-on-close process containment.'
        block = ("    if ($preparationWorker) { [IO.File]::WriteAllText(" + quote(folder / 'blocked.marker') +
            ",'ordinary blocking call'); [Threading.Thread]::Sleep(30000) }\n")
        text = once(text, seam, block + seam)
    if mode == 'wrong_inherited_identity':
        text = once(text, '$PreparationPipe,$PreparationOwner,[uint32]$request.lifetime.owner_pid,$request.lifetime.owner_created,$RequestId)',
            "$PreparationPipe,$PreparationOwner,[uint32]$request.lifetime.owner_pid,'0',$RequestId)")
    if mode == 'outer_final_close':
        text = once(text, 'old!=IntPtr.Zero && !CloseHandle(old)',
            'old!=IntPtr.Zero && (!CloseHandle(old) || CommandFixture.TerminalFault(old))')
        text = once(text, '            Close(ref p.Process); Close(ref job); return answer;',
            '            if (deliver) CommandFixture.FailHandle(p.Process); Close(ref p.Process); Close(ref job); return answer;')
    if mode == 'delivery_failure':
        text = once(text, '            IntPtr self=GetCurrentProcess();',
            '            if (CommandFixture.Refuse()) throw new Exception("Caller handle delivery unknown");\n            IntPtr self=GetCurrentProcess();')
    if mode == 'missing_worker_result':
        text = once(text, '    Write-Receipt ($RequestId + $suffix) $result $false',
            '    if (-not $preparationWorker) { Write-Receipt ($RequestId + $suffix) $result $false }')
    if mode == 'bad_worker_result':
        text = once(text, '    Write-Receipt ($RequestId + $suffix) $result $false',
            "    if ($preparationWorker) { $result.request_sha256 = '" + '0' * 64 + "' }\n    Write-Receipt ($RequestId + $suffix) $result $false")
    return text


@pytest.mark.skipif(os.name != 'nt', reason='ordinary full helper/job/inherited-lease fixture')
@pytest.mark.parametrize('mode', ['normal', 'deadline_early', 'deadline_write', 'cancel_early', 'cancel_write',
    'caller_death_early', 'watchdog_death_write', 'wrong_inherited_identity', 'outer_final_close',
    'delivery_failure', 'missing_worker_result', 'bad_worker_result', 'claim_collision', 'worker_failure'])
def test_complete_attempt_independently_stops_blocked_preparation(mode):
    from night_shifts.ubuntu_preparation_control import _current_user_sid

    sid = _current_user_sid()
    folder = Path(tempfile.mkdtemp(prefix='attempt-ordinary-'))
    for leaf in ('requests', 'receipts'):
        (folder / leaf).mkdir()
    helper = folder / 'helper.ps1'
    helper.write_text(ordinary_helper(folder, sid, mode), encoding='utf-8-sig')
    digest = hashlib.sha256(helper.read_bytes()).hexdigest()
    (folder / 'policy.json').write_text(json.dumps(dict(version=1, helper_sha256=digest, operator_sid=sid,
        max_timeout=900, lifetime_protocol=1, preparation_protocol=1, setup_preload_protocol=1,
        preparation_supervision_protocol=1)), encoding='utf-8')
    request_id, revoked = 'f' * 32, Event()
    claim = PrivilegedClaim(request_id, time.time() + 60, ELEVATED_OPERATION)
    lifetime = CommandLifetime(SimpleNamespace(execution_cancelled=lambda claim: revoked.is_set()), claim, sid)
    blocking = mode.startswith(('deadline', 'cancel', 'caller_death', 'watchdog_death'))
    supervisor_claim = folder / 'receipts' / (request_id + '.supervision-start.json')
    if mode == 'claim_collision':
        supervisor_claim.write_bytes(b'EXISTING_CLAIM_MUST_STAY')
    owner = proc = None
    handle = None
    k = c.WinDLL('kernel32', use_last_error=True)
    k.WaitForSingleObject.argtypes, k.WaitForSingleObject.restype = [c.c_void_p, c.c_uint32], c.c_uint32
    k.CloseHandle.argtypes, k.CloseHandle.restype = [c.c_void_p], c.c_int
    try:
        with lifetime:
            binding = lifetime.binding
            if mode.startswith('caller_death'):
                owner_script, owner_record = folder / 'owner.py', folder / 'owner.json'
                owner_script.write_text(OWNER, encoding='utf-8')
                owner = subprocess.Popen([sys.executable, '-I', '-B', str(owner_script), str(ROOT), str(owner_record), sid, request_id],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                until = time.monotonic() + 8
                while not owner_record.exists():
                    assert owner.poll() is None and time.monotonic() < until, str(folder)
                    time.sleep(0.01)
                binding = json.loads(owner_record.read_text(encoding='utf-8'))
            payload = dict(version=1, request_id=request_id, operation=ELEVATED_OPERATION, deadline_unix=int(claim.deadline_unix),
                timeout=6 if mode.startswith('deadline') else 20,
                script="exit 7" if mode == 'worker_failure' else "Write-Output 'INERT_ATTEMPT_COMPLETED'",
                cwd=str(folder), reason='ordinary inert fixture', operator_sid=sid, helper_sha256=digest, lifetime=binding)
            raw = json.dumps(payload, separators=(',', ':')).encode('utf-8')
            (folder / 'requests' / (request_id + '.json')).write_bytes(raw)
            request_digest = hashlib.sha256(raw).hexdigest()
            _, exe = _windows_paths()
            started = time.monotonic()
            proc = subprocess.Popen([str(exe), '-NoProfile', '-NonInteractive', '-File', str(helper),
                '-RequestId', request_id, '-DeadlineUnix', str(int(claim.deadline_unix)), '-RequestSha256', request_digest],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if blocking:
                until = time.monotonic() + 10
                while not (folder / 'blocked.marker').exists():
                    assert proc.poll() is None and time.monotonic() < until, str(folder)
                    time.sleep(0.01)
                if mode.startswith('cancel'):
                    revoked.set()
                    lifetime._thread.join(2)
                    assert not lifetime._thread.is_alive(), str(folder)
                elif owner is not None:
                    owner.kill()  # only the exact original lease-owner handle
                    owner.communicate(timeout=5)
                elif mode.startswith('watchdog_death'):
                    proc.kill()  # exact outer owner; job closure must kill worker
            out, err = proc.communicate(timeout=18)
            if not mode.startswith('watchdog_death'):
                assert not out and not err, (str(folder), out, err)
            if mode in ('delivery_failure', 'claim_collision'):
                assert not (folder / 'root.handle').exists(), str(folder)
            else:
                handle = int((folder / 'root.handle').read_text(encoding='ascii'))
                assert k.WaitForSingleObject(handle, 5000) == 0, 'Worker stop UNKNOWN: ' + str(folder)
            assert supervisor_claim.exists(), str(folder)
            path = folder / 'receipts' / (request_id + '.result.json')
            worker_path = folder / 'receipts' / (request_id + '.worker-result.json')
            if mode == 'normal':
                assert proc.returncode == 0, str(folder)
                data = json.loads(path.read_text(encoding='utf-8'))
                client.validate_receipt(data, claim, request_digest, digest)
                assert data['status'] == 'completed' and data['preparation_supervision_observed'] is True
                assert data['stdout'] == 'INERT_ATTEMPT_COMPLETED\r\n' and data['stderr'] == ''
                assert json.loads(worker_path.read_text(encoding='utf-8'))['preparation_supervision_observed'] is False
                start = json.loads((folder / 'receipts' / (request_id + '.start.json')).read_text(encoding='utf-8'))
                supervisor_start = json.loads(supervisor_claim.read_text(encoding='utf-8'))
                assert start['execution_qpc_limit'] <= supervisor_start['execution_qpc_limit']
                assert start['execution_qpc_frequency'] == supervisor_start['execution_qpc_frequency']
            else:
                assert proc.returncode != 0 and time.monotonic() - started < 16, str(folder)
                if blocking or mode in ('delivery_failure', 'claim_collision', 'missing_worker_result'):
                    assert not worker_path.exists(), str(folder)
                if blocking or mode in ('delivery_failure', 'claim_collision', 'wrong_inherited_identity'):
                    assert not (folder / 'receipts' / (request_id + '.payload.ps1')).exists(), str(folder)
                if mode in ('outer_final_close', 'worker_failure', 'bad_worker_result'):
                    inner = json.loads(worker_path.read_text(encoding='utf-8'))
                    assert inner['status'] == ('failed' if mode == 'worker_failure' else 'completed')
                    assert inner['exit_code'] == (7 if mode == 'worker_failure' else 0)
                if mode == 'claim_collision':
                    assert supervisor_claim.read_bytes() == b'EXISTING_CLAIM_MUST_STAY'
                if blocking and mode.endswith('write'):
                    assert (folder / 'receipts' / (request_id + '.start.json')).exists(), str(folder)
                if path.exists():
                    data = json.loads(path.read_text(encoding='utf-8'))
                    client.validate_receipt(data, claim, request_digest, digest)
                    assert data['status'] == 'outcome_unknown'
                    assert data['preparation_supervision_observed'] is data['effects_verified'] is data['retry_authorized'] is False
                else:
                    assert mode.startswith('watchdog_death'), str(folder)
    finally:
        for process in (owner, proc):
            if process is not None and process.poll() is None:
                process.kill()
                process.communicate(timeout=5)
        if handle is None and (folder / 'root.handle').exists():
            handle = int((folder / 'root.handle').read_text(encoding='ascii'))
        if handle is not None:
            assert k.CloseHandle(handle), 'Fixture capability close UNKNOWN: ' + str(folder)
    shutil.rmtree(folder)  # only verified exact fixtures reach removal


@pytest.mark.parametrize('observed', ['missing', False, True])
def test_new_deployment_requires_positive_outer_evidence_at_client(monkeypatch, tmp_path, observed):
    from tests.runtime.test_elevated_commands import approve, gate
    from core.tool_progress import approval_ui_context, tool_progress_listener

    policy = dict(operator_sid='fixture', helper_sha256='c' * 64, max_timeout=900,
        lifetime_protocol=1, preparation_protocol=1, setup_preload_protocol=1, preparation_supervision_protocol=1)
    class Lease:
        binding = dict(version=1, pipe='TEST_ONLY', owner_pid=1, owner_created='1')
        def __init__(self, *args):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
    monkeypatch.setattr(client, 'CommandLifetime', Lease)
    monkeypatch.setattr(client, 'local_path', lambda *args, **kwargs: tmp_path)
    monkeypatch.setattr(client, 'load_launcher', lambda: (tmp_path, tmp_path / 'powershell.exe', policy))
    (tmp_path / 'requests').mkdir()
    def elevate(exe, helper, claim, *, request_sha256):
        data = receipt()
        data.update(request_id=claim.request_id, request_sha256=request_sha256,
            process_tree_observed=True, lifetime_observed=True, preparation_observed=True)
        if observed != 'missing':
            data['preparation_supervision_observed'] = observed
        monkeypatch.setattr(client, '_bounded_json', lambda path: data)
        return 'completed'
    monkeypatch.setattr(client, '_elevate', elevate)
    permit = gate()
    with permit.turn('head'), approval_ui_context(), tool_progress_listener(approve(permit)):
        claim = permit.claim(ELEVATED_OPERATION)
        if observed is True:
            data = client.run_approved_script(permit, claim, 'exit 0', 20, 'fixture', str(tmp_path),
                require_preparation_supervision=True)
            assert data['status'] == 'completed' and data['effects_verified'] is False
        else:
            with pytest.raises(PrivilegedHostError, match='Missing protected preparation-worker supervision'):
                client.run_approved_script(permit, claim, 'exit 0', 20, 'fixture', str(tmp_path),
                    require_preparation_supervision=True)
