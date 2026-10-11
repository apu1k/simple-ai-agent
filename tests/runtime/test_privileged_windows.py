"""Mocked Windows consent/handle API; never request UAC or query Hyper-V."""
import ctypes
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime import privileged_host as module
from runtime.privileged_turn import PrivilegedClaim


class Function:
    def __init__(self, fn):
        self.fn = fn
    def __call__(self, *args):
        return self.fn(*args)


@pytest.mark.parametrize('scenario', ['success', 'exit_error', 'cancel', 'refused',
                                     'no_handle', 'timeout', 'wait_error', 'exit_unknown'])
def test_uac_native_paths_and_handle_cleanup(monkeypatch, scenario):
    seen = []
    closed = []
    def execute(pointer):
        info = pointer._obj
        seen.append((info.lpVerb, info.lpFile, info.lpParameters, info.lpDirectory))
        info.hProcess = None if scenario == 'no_handle' else 42
        return scenario not in ('cancel', 'refused')
    def get_exit(handle, pointer):
        pointer._obj.value = 2 if scenario == 'exit_error' else 0
        return scenario != 'exit_unknown'
    shell = SimpleNamespace(ShellExecuteExW=Function(execute))
    kernel = SimpleNamespace(
        WaitForSingleObject=Function(lambda handle, timeout: 258 if scenario == 'timeout'
                                     else (0xffffffff if scenario == 'wait_error' else 0)),
        GetExitCodeProcess=Function(get_exit),
        CloseHandle=Function(lambda handle: closed.append(handle) or True),
    )
    monkeypatch.setattr(ctypes, 'WinDLL', lambda name, **kw: shell if name == 'shell32' else kernel, raising=False)
    monkeypatch.setattr(ctypes, 'get_last_error', lambda: 1223 if scenario == 'cancel' else 5, raising=False)
    executable = Path('C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe')
    helper = Path('C:/Program Files/AiAgentHyperVEvidence/helper.ps1')
    claim = PrivilegedClaim('a' * 32, time.time() + 30)
    expected = {'success': 'completed', 'exit_error': 'helper_failed',
                'cancel': 'uac_cancelled', 'timeout': 'deadline_outcome_unknown'}
    if scenario in expected:
        assert module._elevate(executable, helper, claim) == expected[scenario]
    else:
        with pytest.raises(module.PrivilegedHostError):
            module._elevate(executable, helper, claim)
    assert seen[0][0] == 'runas' and seen[0][1] == str(executable)
    assert '-NoProfile -NonInteractive' in seen[0][2]
    assert '-EncodedCommand' not in seen[0][2]
    assert '-RequestId ' + claim.request_id in seen[0][2]
    assert closed == ([] if scenario in ('cancel', 'refused', 'no_handle') else [42])


@pytest.mark.parametrize('identity,seconds', [('bad', 30), ('a' * 32, -1), ('a' * 32, 1900)])
def test_stale_excessive_or_malformed_claim_never_requests_uac(monkeypatch, identity, seconds):
    monkeypatch.setattr(ctypes, 'WinDLL', lambda *a, **kw: pytest.fail('must not request elevation'), raising=False)
    with pytest.raises(module.PrivilegedHostError):
        module._elevate(Path('powershell.exe'), Path('helper.ps1'),
                        PrivilegedClaim(identity, time.time() + seconds))
