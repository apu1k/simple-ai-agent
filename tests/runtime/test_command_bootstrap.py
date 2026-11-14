"""Closed builds and full ORDINARY bootstrap/helper/worker compositions.

Explicit admission adapters and inert bodies only. No UAC, installation or VM.
Observed fixture pins are NOT independent production approval. Failed trees stay.
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

from core.tool_progress import approval_ui_context, tool_progress_listener
from night_shifts import bootstrap_native_build as build
from night_shifts import bootstrap_native_builder as builder
from night_shifts import bootstrap_native_command_build as recipe
from runtime import elevated_commands as client
from runtime.command_lifetime import CommandLifetime
from runtime.privileged_host import PrivilegedHostError
from runtime.privileged_turn import ELEVATED_OPERATION, PrivilegedClaim, PrivilegedTurn
from tests.night_shifts.test_bootstrap_native_build import _pins
from tests.night_shifts.test_bootstrap_native_builder import ROOT, _native_case
from tests.runtime.test_command_attempt_supervision import ordinary_helper
from tests.runtime.test_command_lifetime import OWNER
from tests.runtime.test_command_watchdog_ownership_windows import OBSERVER, once
from tests.runtime.test_elevated_commands import approve, gate
from tests.runtime.test_elevated_receipts import receipt


def candidate(windows=r'C:\Windows', stage=r'C:\CommandBuild', sources=None, tools=None, aliases=None):
    sources = {n: (ROOT / 'scripts' / n).read_bytes() for n in recipe.SOURCES} if sources is None else sources
    tools = {n: b'inert ' + n.encode('ascii') for n in build.TOOLCHAIN_NAMES} if tools is None else tools
    framework = windows + '\\Microsoft.NET\\Framework64\\v4.0.30319'
    return dict(version=1, scope=recipe.SCOPE, windows_root=windows, staging_root=stage, source_pins=_pins(sources),
        toolchain_pins=_pins(tools), toolchain_aliases=aliases or {n: [framework + '\\' + n] for n in tools}), sources, tools


def policy():
    return dict(version=1, operator_sid='fixture', helper_sha256='c' * 64, max_timeout=900, lifetime_protocol=1,
        preparation_protocol=1, setup_preload_protocol=1, preparation_supervision_protocol=1,
        bootstrap_supervision_protocol=1, bootstrap_sha256='d' * 64)


def test_recipe_reuses_exact_helper_core_and_fixed_compiler_contract():
    review, sources, tools = candidate()
    plan = recipe.plan_command_bootstrap_build(review, source_files=sources, toolchain_files=tools)
    staged = dict(plan.staging_files)
    helper = sources[recipe.SOURCES[0]].decode('utf-8-sig').replace('\r\n', '\n')
    assert staged[recipe.CORE].decode('utf-8') == helper.split("    Add-Type -TypeDefinition @'\n", 1)[1].split("\n'@\n", 1)[0]
    assert plan.entry_points == (build.COMMAND_ENTRY_POINT,) and len(plan.commands) == 1
    assert set(build.COMMON_OPTIONS).issubset(plan.commands[0])
    assert plan.expected_outputs == ('command-bootstrap.exe', 'command-bootstrap.exe.config')
    assert dict(plan.environment).keys() == {'SystemRoot', 'WINDIR', 'TEMP', 'TMP'}
    assert build.MANIFEST_BYTES in staged.values()  # asInvoker; no installation


@pytest.mark.parametrize('fault', ['extra', 'pin', 'scope', 'overlap', 'bool', 'core'])
def test_invalid_recipe_refuses_before_native_loading(fault):
    review, sources, tools = candidate()
    if fault == 'extra':
        review['command'] = 'injected.exe'
    elif fault == 'pin':
        review['source_pins'][recipe.SOURCES[1]]['sha256'] = '0' * 64
    elif fault == 'scope':
        review['scope'] = 'trusted'
    elif fault == 'overlap':
        review['staging_root'] = r'C:\Windows\Build'
    elif fault == 'bool':
        review['version'] = True
    else:
        sources[recipe.SOURCES[0]] = b'no embedded core'
        review['source_pins'] = _pins(sources)
    with pytest.raises(build.ValidatorBuildRefused):
        recipe.plan_command_bootstrap_build(review, source_files=sources, toolchain_files=tools)


@pytest.mark.parametrize('capability', [None, False, True, 0, 2, '1'])
def test_fixed_setup_requires_complete_helper_supervision_before_pending(monkeypatch, tmp_path, capability):
    p = policy()
    if capability is None:
        del p['bootstrap_supervision_protocol']
    else:
        p['bootstrap_supervision_protocol'] = capability
    monkeypatch.setattr(client, 'local_path', lambda *a, **k: tmp_path)
    monkeypatch.setattr(client, 'load_launcher', lambda: (tmp_path, tmp_path / 'powershell.exe', p))
    monkeypatch.setattr(client, 'await_approval', lambda *a: pytest.fail('must refuse before pending'))
    with pytest.raises(PrivilegedHostError, match='complete-helper bootstrap supervision'):
        client.run_approved_script(PrivilegedTurn(), PrivilegedClaim('a' * 32, time.time() + 30, ELEVATED_OPERATION),
            'exit 0', 20, 'fixture', str(tmp_path), require_bootstrap_supervision=True)


@pytest.mark.parametrize('state,frame,pin', [('completed', True, 'd'), ('helper_failed', True, 'd'),
    ('completed', False, 'd'), ('completed', True, 'e'), ('deadline_outcome_unknown', True, 'd')])
def test_parent_exit_and_receipt_are_jointly_required(monkeypatch, tmp_path, state, frame, pin):
    p = policy()
    class Lease:
        binding = dict(version=1, pipe='FIXTURE_ONLY', owner_pid=1, owner_created='1')
        def __init__(self, *args):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
    monkeypatch.setattr(client, 'CommandLifetime', Lease)
    monkeypatch.setattr(client, 'local_path', lambda *a, **k: tmp_path)
    monkeypatch.setattr(client, 'load_launcher', lambda: (tmp_path, tmp_path / 'powershell.exe', p))
    (tmp_path / 'requests').mkdir()
    observed = receipt()
    def elevate(exe, helper, claim, *, request_sha256, command_bootstrap):
        assert command_bootstrap == (20, 'FIXTURE_ONLY', 1, '1')
        raw = (tmp_path / 'requests' / (claim.request_id + '.json')).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == request_sha256
        assert json.loads(raw)['bootstrap_sha256'] == 'd' * 64
        observed.update(request_id=claim.request_id, request_sha256=request_sha256,
            process_tree_observed=True, lifetime_observed=True, preparation_observed=True,
            preparation_supervision_observed=True, bootstrap_frame_observed=frame, bootstrap_sha256=pin * 64)
        return state
    monkeypatch.setattr(client, '_elevate', elevate)
    monkeypatch.setattr(client, '_bounded_json', lambda path: observed)
    permit = gate()
    with permit.turn('head'), approval_ui_context(), tool_progress_listener(approve(permit)):
        result = client.run_approved_script(permit, permit.claim(ELEVATED_OPERATION), 'exit 0', 20, 'fixture', str(tmp_path),
            require_bootstrap_supervision=True)
    success = state == 'completed' and frame and pin == 'd'
    assert result['status'] == ('completed' if success else 'outcome_unknown')
    assert result['effects_verified'] is False
    assert result.get('bootstrap_supervision_observed', False) is success
    assert 'bootstrap_supervision_observed' not in observed  # never fake protected bytes


@pytest.fixture(scope='module')
def ordinary_bootstrap():
    with _native_case() as case:
        sources = {n: (ROOT / 'scripts' / n).read_bytes() for n in recipe.SOURCES}
        entry = sources[recipe.SOURCES[1]].decode('utf-8-sig')
        # Explicit disposable adapters: permit ONLY an ordinary token and take
        # fixture location from this test assembly. No production defaults change.
        entry = once(entry, 'return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), "AiAgentElevatedCommands");',
            'return Path.GetDirectoryName(typeof(ApprovedCommandBootstrap).Assembly.Location);')
        entry = once(entry, 'if (!new WindowsPrincipal(identity).IsInRole(WindowsBuiltInRole.Administrator))',
            'if (new WindowsPrincipal(identity).IsInRole(WindowsBuiltInRole.Administrator))')
        entry = once(entry, 'Admission(root); EnvironmentForWorker(root,system);',
            'Admission(root); EnvironmentForWorker(root,system); CommandFixture.Root=Path.Combine(root,"outer"); CommandFixture.Mode=File.Exists(Path.Combine(root,"final-close.marker"))?"finalclose":"normal";')
        # Exact held child handle supplied by the actual atomic CreateProcess,
        # duplicated into this controller BEFORE child resume. Never PID searches.
        helper = sources[recipe.SOURCES[0]].decode('utf-8-sig').replace('\r\n', '\n')
        helper = once(helper, '            bool member;', '            if (deliver) CommandFixture.Published(p.Process);\n            bool member;')
        helper = once(helper, 'old!=IntPtr.Zero && !CloseHandle(old)', 'old!=IntPtr.Zero && (!CloseHandle(old) || CommandFixture.TerminalFault(old))')
        helper = once(helper, '            Close(ref p.Process); Close(ref job); return answer;',
            '            if (deliver && CommandFixture.Mode=="finalclose") CommandFixture.FailHandle(p.Process); Close(ref p.Process); Close(ref job); return answer;')
        entry += '\n' + OBSERVER.replace('__CONTROLLER_PID__', str(os.getpid()))
        sources = {recipe.SOURCES[0]: helper.encode('utf-8'), recipe.SOURCES[1]: entry.encode('utf-8')}
        review, sources, tools = candidate(case.review['windows_root'], str(case.stage), sources, case.tools, case.review['toolchain_aliases'])
        product = builder.build_command_bootstrap_candidate(review, source_files=sources, toolchain_files=tools, deadline=time.monotonic() + 40)
        assert tuple(a.name for a in product.artifacts) == ('command-bootstrap.exe', 'command-bootstrap.exe.config')
        yield product
        case.clean = True


@pytest.mark.skipif(os.name != 'nt', reason='ordinary precompiled owner/helper/native jobs')
@pytest.mark.parametrize('mode', ['normal', 'deadline_load', 'cancel_compile', 'cancel_claim', 'cancel_result',
    'owner_death', 'watchdog_death', 'wrong_timeout', 'claim_collision', 'outer_final_close', 'normal_crlf'])
def test_precompiled_owner_supervises_complete_helper(ordinary_bootstrap, mode):
    from night_shifts.ubuntu_preparation_control import _current_user_sid

    sid = _current_user_sid()
    folder = Path(tempfile.mkdtemp(prefix='bootstrap-ordinary-'))
    for name in ('requests', 'receipts', 'outer'):
        (folder / name).mkdir()
    for artifact in ordinary_bootstrap.artifacts:
        (folder / artifact.name).write_bytes(artifact.raw)
    helper = folder / 'helper.ps1'
    text = ordinary_helper(folder, sid, 'normal')
    marker = folder / 'blocked.marker'
    block = "[IO.File]::WriteAllText('" + str(marker).replace("'", "''") + "','ordinary blocked call'); [Threading.Thread]::Sleep(30000)\n"
    if mode in ('deadline_load', 'owner_death', 'watchdog_death'):
        text = once(text, '# GENERAL ADMINISTRATOR EXECUTION.', block + '# GENERAL ADMINISTRATOR EXECUTION.')
    elif mode == 'cancel_compile':
        text = once(text, '    # Kill-on-close process containment.', '    if ($bootstrapWorker) { ' + block + '}\n    # Kill-on-close process containment.')
    elif mode in ('cancel_claim', 'cancel_result'):
        suffix = '.supervision-start.json' if mode == 'cancel_claim' else '.result.json'
        text = once(text, '    $path = [IO.Path]::Combine($receipts,$Name)',
            "    if ($bootstrapWorker -and $Name.EndsWith('" + suffix + "')) { " + block + '}\n    $path = [IO.Path]::Combine($receipts,$Name)')
    helper.write_bytes(b'\xef\xbb\xbf' + text.replace('\n', '\r\n' if mode == 'normal_crlf' else '\n').encode('utf-8'))
    if mode == 'outer_final_close':
        (folder / 'final-close.marker').write_bytes(b'EXPLICIT_TEST_FAULT')
    digest = hashlib.sha256(helper.read_bytes()).hexdigest()
    p = policy()
    p.update(operator_sid=sid, helper_sha256=digest,
        bootstrap_sha256=hashlib.sha256((folder / 'command-bootstrap.exe').read_bytes()).hexdigest())
    (folder / 'policy.json').write_text(json.dumps(p), encoding='utf-8')
    request_id, revoked = 'b' * 32, Event()
    claim = PrivilegedClaim(request_id, time.time() + 60, ELEVATED_OPERATION)
    lifetime = CommandLifetime(SimpleNamespace(execution_cancelled=lambda claim: revoked.is_set()), claim, sid)
    k = c.WinDLL('kernel32', use_last_error=True)
    k.WaitForSingleObject.argtypes, k.WaitForSingleObject.restype = [c.c_void_p, c.c_uint32], c.c_uint32
    k.CloseHandle.argtypes, k.CloseHandle.restype = [c.c_void_p], c.c_int
    proc = owner = None
    handles = []
    try:
        with lifetime:
            binding = lifetime.binding
            if mode == 'owner_death':
                owner_script, owner_record = folder / 'owner.py', folder / 'owner.json'
                owner_script.write_text(OWNER, encoding='utf-8')
                owner = subprocess.Popen([sys.executable, '-I', '-B', str(owner_script), str(ROOT), str(owner_record), sid, request_id],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                until = time.monotonic() + 8
                while not owner_record.exists():
                    assert owner.poll() is None and time.monotonic() < until, str(folder)
                    time.sleep(0.01)
                binding = json.loads(owner_record.read_text(encoding='utf-8'))
            timeout = 4 if mode == 'deadline_load' else 20
            payload = dict(version=1, request_id=request_id, operation=ELEVATED_OPERATION, deadline_unix=int(claim.deadline_unix),
                timeout=timeout, script="Write-Output 'WHOLE_HELPER_INERT'", cwd=str(folder), reason='ordinary inert bootstrap',
                operator_sid=sid, helper_sha256=digest, lifetime=binding, bootstrap_sha256=p['bootstrap_sha256'])
            raw = json.dumps(payload, separators=(',', ':')).encode('utf-8')
            (folder / 'requests' / (request_id + '.json')).write_bytes(raw)
            if mode == 'claim_collision':
                (folder / 'receipts' / (request_id + '.supervision-start.json')).write_bytes(b'KEEP_CLAIM')
            started = time.monotonic()
            proc = subprocess.Popen([str(folder / 'command-bootstrap.exe'), '--approved-command-bootstrap-v1', request_id,
                str(int(claim.deadline_unix)), hashlib.sha256(raw).hexdigest(), str(timeout + int(mode == 'wrong_timeout')),
                binding['pipe'], str(binding['owner_pid']), binding['owner_created']], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if mode.startswith('cancel') or mode in ('owner_death', 'watchdog_death'):
                until = time.monotonic() + 12
                while not marker.exists():
                    assert proc.poll() is None and time.monotonic() < until, str(folder)
                    time.sleep(0.01)
                if mode == 'watchdog_death':
                    proc.kill()  # exact retained outer handle; job must kill helper
                elif owner is not None:
                    owner.kill()
                    owner.communicate(timeout=5)
                else:
                    # Closing the actual caller channel, not polling an identifier.
                    revoked.set()
                    lifetime._thread.join(2)
                    assert not lifetime._thread.is_alive(), str(folder)
            out, err = proc.communicate(timeout=22)
            assert not out and not err, (str(folder), out, err)
            for path in (folder / 'outer/root.handle', folder / 'root.handle'):
                if path.exists():
                    handle = int(path.read_text(encoding='ascii'))
                    handles.append(handle)
                    assert k.WaitForSingleObject(handle, 5000) == 0, 'Exact child stop UNKNOWN: ' + str(folder)
            assert handles, str(folder)
            result_path = folder / 'receipts' / (request_id + '.result.json')
            if mode in ('normal', 'normal_crlf'):
                assert proc.returncode == 0, str(folder)
                data = json.loads(result_path.read_text(encoding='utf-8'))
                client.validate_receipt(data, claim, hashlib.sha256(raw).hexdigest(), digest)
                assert data['bootstrap_frame_observed'] is data['preparation_supervision_observed'] is True
                assert data['bootstrap_sha256'] == p['bootstrap_sha256'] and data['stdout'] == 'WHOLE_HELPER_INERT\r\n'
                assert 'bootstrap_supervision_observed' not in data  # child cannot claim parent's future exit
                start = json.loads((folder / 'receipts' / (request_id + '.supervision-start.json')).read_text(encoding='utf-8'))
                inner = json.loads((folder / 'receipts' / (request_id + '.start.json')).read_text(encoding='utf-8'))
                assert inner['execution_qpc_limit'] <= start['execution_qpc_limit']
                assert inner['execution_qpc_frequency'] == start['execution_qpc_frequency']
            else:
                assert proc.returncode != 0 and time.monotonic() - started < 18, str(folder)
                if result_path.exists():
                    data = json.loads(result_path.read_text(encoding='utf-8'))
                    assert data['status'] == ('completed' if mode == 'outer_final_close' else 'outcome_unknown')
                    assert data['retry_authorized'] is data['effects_verified'] is False
                    if mode == 'outer_final_close':
                        assert data['bootstrap_frame_observed'] is True  # parent still failed; cannot accept
                if mode == 'claim_collision':
                    assert (folder / 'receipts' / (request_id + '.supervision-start.json')).read_bytes() == b'KEEP_CLAIM'
            if mode in ('deadline_load', 'cancel_compile', 'cancel_claim', 'wrong_timeout', 'claim_collision', 'owner_death', 'watchdog_death'):
                assert not (folder / 'receipts' / (request_id + '.payload.ps1')).exists(), str(folder)
    finally:
        for process in (owner, proc):
            if process is not None and process.poll() is None:
                process.kill()
                process.communicate(timeout=5)
        for handle in handles:
            assert k.CloseHandle(handle), 'Fixture observation close UNKNOWN: ' + str(folder)
    shutil.rmtree(folder)  # only exact successful fixture observations reach removal
