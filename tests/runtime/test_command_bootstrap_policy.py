"""No UAC/install: installed-byte checks, frozen argv and actual ordinary build."""
from __future__ import annotations

import ctypes
import hashlib
import os
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from night_shifts import bootstrap_native_builder as builder
from night_shifts.bootstrap_native_install_request import _CONFIG
from runtime import elevated_commands as client
from runtime import privileged_host as host
from runtime.privileged_turn import ELEVATED_OPERATION, PrivilegedClaim
from tests.night_shifts.test_bootstrap_native_builder import _native_case
from tests.runtime.test_command_bootstrap import candidate, policy


@pytest.mark.parametrize('fault', ['none', 'binary', 'config', 'missing', 'bool', 'pin'])
def test_installed_bootstrap_and_runtime_bytes_are_checked_before_approval(monkeypatch, tmp_path, fault):
    root = tmp_path / 'AiAgentElevatedCommands'
    root.mkdir()
    (root / 'requests').mkdir()
    (root / 'receipts').mkdir()
    helper, binary = b'INERT_HELPER_NEVER_EXECUTE', b'INERT_BINARY_NEVER_EXECUTE'
    p = policy()
    p.update(helper_sha256=hashlib.sha256(helper).hexdigest(), bootstrap_sha256=hashlib.sha256(binary).hexdigest())
    (root / 'helper.ps1').write_bytes(helper)
    (root / 'command-bootstrap.exe').write_bytes(binary + (b'changed' if fault == 'binary' else b''))
    (root / 'command-bootstrap.exe.config').write_bytes(_CONFIG + (b'changed' if fault == 'config' else b''))
    if fault == 'missing':
        (root / 'command-bootstrap.exe.config').unlink()  # exact inert fixture, not installed evidence
    if fault == 'bool':
        p['bootstrap_supervision_protocol'] = True
    if fault == 'pin':
        p['bootstrap_sha256'] = 'D' * 64
    checked = []
    monkeypatch.setattr(client, '_windows_paths', lambda: (tmp_path / 'AiAgentHyperVEvidence', tmp_path / 'powershell.exe'))
    monkeypatch.setattr(client, '_assert_protected', lambda path, **kwargs: checked.append(path))
    monkeypatch.setattr(client, '_bounded_json', lambda path: p)
    monkeypatch.setattr(client, '_current_user_sid', lambda: 'fixture')
    if fault == 'none':
        assert client.load_launcher() == (root, tmp_path / 'powershell.exe', p)
        assert root / 'command-bootstrap.exe' in checked and root / 'command-bootstrap.exe.config' in checked
    else:
        with pytest.raises((host.PrivilegedHostError, FileNotFoundError)):
            client.load_launcher()


@pytest.mark.skipif(os.name != 'nt', reason='client preflight only; no native launch')
@pytest.mark.parametrize('fault', ['pin', 'missing_pin', 'legacy', 'lifetime', 'preparation', 'worker', 'bootstrap'])
def test_independent_bootstrap_pin_cannot_fall_back_even_without_requirement_flags(monkeypatch, tmp_path, fault):
    p = policy()
    if fault == 'pin':
        p['bootstrap_sha256'] = 'e' * 64
    elif fault == 'missing_pin':
        del p['bootstrap_sha256']
    elif fault == 'legacy':
        del p['bootstrap_supervision_protocol'], p['bootstrap_sha256']
    else:
        field = dict(lifetime='lifetime_protocol', preparation='preparation_protocol',
            worker='preparation_supervision_protocol', bootstrap='bootstrap_supervision_protocol')[fault]
        p[field] = True  # bool is not protocol version 1
    monkeypatch.setattr(client, 'local_path', lambda *a, **k: tmp_path)
    monkeypatch.setattr(client, 'load_launcher', lambda: (tmp_path, tmp_path / 'powershell.exe', p))
    monkeypatch.setattr(client, 'await_approval', lambda *a: pytest.fail('must refuse before pending'))
    monkeypatch.setattr(client, '_elevate', lambda *a, **k: pytest.fail('must not request UAC'))
    with pytest.raises(host.PrivilegedHostError, match='Independently reviewed command bootstrap'):
        client.run_approved_script(client.PrivilegedTurn(), PrivilegedClaim('a' * 32, time.time() + 30, ELEVATED_OPERATION),
            'exit 0', 20, 'inert fixture', str(tmp_path), required_bootstrap_sha256='d' * 64)


class Function:
    def __init__(self, call):
        self.call = call
    def __call__(self, *args):
        return self.call(*args)


@pytest.mark.skipif(os.name != 'nt', reason='ctypes ShellExecute FRAME only; native call replaced')
@pytest.mark.parametrize('fault', ['none', 'timeout', 'pipe', 'pid', 'created', 'close'])
def test_fixed_bootstrap_argv_and_checked_client_release(monkeypatch, fault):
    request_id = 'a' * 32
    claim = PrivilegedClaim(request_id, time.time() + 30, ELEVATED_OPERATION)
    binding = [20, r'\\.\pipe\AiAgentCommandLease-v1-' + request_id + '-' + 'b' * 32, 42, '134000000000000000']
    if fault == 'timeout':
        binding[0] = True
    elif fault == 'pipe':
        binding[1] += ' -Injected'
    elif fault == 'pid':
        binding[2] = True
    elif fault == 'created':
        binding[3] = '0'
    calls = []
    def execute(pointer):
        info = pointer._obj
        calls.append((info.lpFile, info.lpParameters))
        info.hProcess = 123
        return True
    def code(handle, pointer):
        pointer._obj.value = 0
        return True
    kernel = SimpleNamespace(WaitForSingleObject=Function(lambda *args: 0), GetExitCodeProcess=Function(code),
        CloseHandle=Function(lambda handle: fault != 'close'))
    shell = SimpleNamespace(ShellExecuteExW=Function(execute))
    monkeypatch.setattr(ctypes, 'WinDLL', lambda name, **kwargs: shell if name == 'shell32' else kernel)
    monkeypatch.setattr(host, '_observed_phase', lambda *args: 'inert frame')
    helper = Path(r'C:\Program Files\AiAgentElevatedCommands\helper.ps1')
    if fault in ('none', 'close'):
        if fault == 'close':
            with pytest.raises(host.PrivilegedHostError, match='close'):
                host._elevate(Path(r'C:\Windows\powershell.exe'), helper, claim,
                    request_sha256='c' * 64, command_bootstrap=tuple(binding))
        else:
            assert host._elevate(Path(r'C:\Windows\powershell.exe'), helper, claim,
                request_sha256='c' * 64, command_bootstrap=tuple(binding)) == 'completed'
        assert calls[0][0] == str(helper.parent / 'command-bootstrap.exe')
        assert calls[0][1].split()[0] == '--approved-command-bootstrap-v1'
        assert '-File' not in calls[0][1] and 'EncodedCommand' not in calls[0][1]
    else:
        with pytest.raises(host.PrivilegedHostError, match='bootstrap frame'):
            host._elevate(Path(r'C:\Windows\powershell.exe'), helper, claim,
                request_sha256='c' * 64, command_bootstrap=tuple(binding))
        assert not calls


@pytest.mark.skipif(os.name != 'nt', reason='real UNELEVATED fixed production build; refusal launch only')
def test_real_production_bootstrap_build_and_ordinary_refusal():
    with _native_case() as case:
        review, sources, tools = candidate(case.review['windows_root'], str(case.stage), tools=case.tools,
            aliases=case.review['toolchain_aliases'])
        result = builder.build_command_bootstrap_candidate(review, source_files=sources, toolchain_files=tools,
            deadline=time.monotonic() + 40)
        assert result.artifacts[1].raw == _CONFIG
        # This is ONLY the fixed unelevated refusal. No Administrator token,
        # admitted production execution, helper body, install, UAC or VM call.
        exe = case.stage / 'out' / result.artifacts[0].name
        proc = subprocess.run([str(exe), '--approved-command-bootstrap-v1', 'a' * 32, str(int(time.time()) + 30),
            'b' * 64, '20', r'\\.\pipe\AiAgentCommandLease-v1-' + 'a' * 32 + '-' + 'c' * 32, '1', '1'],
            capture_output=True, timeout=5, check=False)
        assert proc.returncode == 2 and not proc.stdout and not proc.stderr
        assert not list((case.stage / 'out').glob('*.json'))
        case.clean = True
