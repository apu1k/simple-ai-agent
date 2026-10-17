"""Synthetic approvals and unelevated native fixtures; never UAC/install/Hyper-V."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.tool_progress import approval_ui_context, tool_progress_listener
from runtime import elevated_commands as client
from runtime.privileged_turn import ELEVATED_OPERATION, PrivilegedTurn
from runtime.tool_profiles import AgentProfile, profile_tool_names
from tools.system.elevated import run_elevated_shell_command
from tools.system.shell import MAX_TIMEOUT as ORDINARY_MAX_TIMEOUT


def gate():
    permit = PrivilegedTurn()
    permit.arm(ELEVATED_OPERATION)
    return permit


def approve(permit, accept=True):
    def callback(message):
        identity = message.removeprefix('[privileged-approval] ')
        permit.decide(identity, accept=accept)
    return callback


def test_multiple_calls_each_need_a_distinct_single_handoff():
    permit = gate()
    with permit.turn('head'), approval_ui_context(), tool_progress_listener(approve(permit)):
        for _ in range(3):
            claim = permit.claim(ELEVATED_OPERATION)
            request, decision = client.await_approval(permit, claim, {'script': 'Write-Output fixture'})
            assert decision == 'accepted'
            permit.require_accepted(request)
            with pytest.raises(PermissionError):
                permit.require_accepted(request)
        for operation in ('collect_host_evidence', 'inspect_image_copy'):
            permit.claim(operation)
            with pytest.raises(PermissionError):
                permit.claim(operation)
    assert permit.status == 'disabled'
    assert not permit.pending()


def test_reject_forged_changed_and_expired_requests():
    permit = gate()
    with permit.turn('head'), approval_ui_context(), tool_progress_listener(approve(permit, False)):
        claim = permit.claim(ELEVATED_OPERATION)
        request, decision = client.await_approval(permit, claim, {'script': 'exit 0'})
        assert decision == 'rejected'
        with pytest.raises(PermissionError):
            permit.require_accepted(request)
        with pytest.raises(ValueError):
            permit.decide(request.id, accept=True)
        with pytest.raises(PermissionError):
            permit.submit(claim, {'script': 'different'})
        claim = permit.claim(ELEVATED_OPERATION)
        request = permit.submit(claim, {'script': 'exit 0'})
        permit.revoke()
        assert permit.wait(request) == 'expired'
        with pytest.raises(PermissionError):
            permit.require_accepted(request)
    with pytest.raises(PermissionError):
        permit.submit(claim, {})


def test_turn_exit_releases_a_waiting_thread():
    permit = gate()
    with ThreadPoolExecutor(max_workers=1) as pool:
        with permit.turn('head'):
            request = permit.submit(permit.claim(ELEVATED_OPERATION), {'script': 'fixture'})
            future = pool.submit(copy_context().run, permit.wait, request)
            assert not future.done()
        assert future.result(timeout=2) == 'expired'


def test_headless_call_does_not_wait_or_elevate():
    permit = gate()
    with permit.turn('head'), pytest.raises(PermissionError, match='Interactive Textual'):
        client.await_approval(permit, permit.claim(ELEVATED_OPERATION), {'script': 'fixture'})


def test_15_minute_limit_independent_of_ordinary_tool_and_worker_denial():
    assert client.MAX_TIMEOUT == 900
    assert ORDINARY_MAX_TIMEOUT == 30
    client.validate_script('exit 0', 1, 'fixture')
    client.validate_script('exit 0', 900, 'fixture')
    for timeout in (0, 901, True, '900', 1.5):
        with pytest.raises(ValueError):
            client.validate_script('exit 0', timeout, 'fixture')
    permit = gate()
    with permit.turn('coding-worker'), pytest.raises(PermissionError):
        permit.claim(ELEVATED_OPERATION)
    assert 'run_elevated_shell_command' in profile_tool_names(AgentProfile.HEAD)
    assert all('run_elevated_shell_command' not in profile_tool_names(p)
               for p in AgentProfile if p != AgentProfile.HEAD)


@pytest.mark.parametrize('accept,uac', [(False, None), (True, 'uac_cancelled'), (True, 'completed')])
def test_script_snapshot_approval_precedes_uac_and_binds_receipt(monkeypatch, tmp_path, accept, uac):
    permit = gate()
    (tmp_path / 'requests').mkdir()
    (tmp_path / 'receipts').mkdir()
    policy = {'operator_sid': 'fixture', 'helper_sha256': 'f' * 64, 'max_timeout': 900}
    monkeypatch.setattr(client, 'local_path', lambda *args, **kwargs: tmp_path)
    monkeypatch.setattr(client, 'load_launcher', lambda: (tmp_path, tmp_path / 'powershell.exe', copy.deepcopy(policy)))
    elevated = []
    def elevate(exe, helper, claim, *, request_sha256):
        payload = (tmp_path / 'requests' / (claim.request_id + '.json')).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == request_sha256
        assert json.loads(payload)['script'] == 'Write-Output "fixture"'
        elevated.append(claim)
        receipt = dict(version=1, request_id=claim.request_id, operation=ELEVATED_OPERATION,
                       request_sha256=request_sha256, helper_sha256=policy['helper_sha256'],
                       status='completed', executed=True, effects_verified=False,
                       exit_code=0, stdout='fixture\n', stderr='', output_truncated=False, retry_authorized=False)
        (tmp_path / 'receipts' / (claim.request_id + '.result.json')).write_text(json.dumps(receipt))
        return uac
    monkeypatch.setattr(client, '_elevate', elevate)
    monkeypatch.setattr(client, '_bounded_json', lambda p: json.loads(p.read_text()))
    with permit.turn('head'), approval_ui_context(), tool_progress_listener(approve(permit, accept)):
        claim = permit.claim(ELEVATED_OPERATION)
        answer = client.run_approved_script(permit, claim, 'Write-Output "fixture"', 60, 'fixture only', str(tmp_path))
    assert len(elevated) == int(accept)
    assert answer['status'] == ('rejected' if not accept else uac)
    if not accept:
        assert answer['executed'] is False
        assert not list((tmp_path / 'requests').iterdir())
    if uac == 'completed':
        assert answer['effects_verified'] is False


def test_installed_policy_change_after_acceptance_blocks_launch(monkeypatch, tmp_path):
    permit = gate()
    monkeypatch.setattr(client, 'local_path', lambda *args, **kwargs: tmp_path)
    policies = iter(({'operator_sid': 'x', 'helper_sha256': 'f' * 64, 'max_timeout': 900},
                     {'operator_sid': 'x', 'helper_sha256': 'a' * 64, 'max_timeout': 900}))
    monkeypatch.setattr(client, 'load_launcher', lambda: (tmp_path, tmp_path / 'ps.exe', next(policies)))
    monkeypatch.setattr(client, '_elevate', lambda *args, **kwargs: pytest.fail('must not elevate'))
    with permit.turn('head'), approval_ui_context(), tool_progress_listener(approve(permit)):
        with pytest.raises(Exception, match='changed after review'):
            client.run_approved_script(permit, permit.claim(ELEVATED_OPERATION), 'exit 0', 30, 'fixture', str(tmp_path))


def test_tool_disabled_and_bad_timeout_do_not_run(monkeypatch, tmp_path):
    monkeypatch.setattr('tools.system.elevated.run_approved_script', lambda *args: pytest.fail('must not run'))
    state = SimpleNamespace(privileged_turn=PrivilegedTurn(), cwd=tmp_path)
    assert run_elevated_shell_command(state, 'exit 0', 'fixture').startswith('Error: Enable')
    assert run_elevated_shell_command(state, 'exit 0', 'fixture', 901).startswith('Error: Timeout')


def quote(value):
    return "'" + str(value).replace("'", "''") + "'"


@pytest.mark.skipif(os.name != 'nt', reason='native unelevated Windows fixture')
def test_native_command_watchdog_capture_exit_timeout_and_bounded_output(tmp_path):
    from runtime.privileged_host import _windows_paths
    _, exe = _windows_paths()
    scripts = Path(__file__).resolve().parents[2] / 'scripts'
    helper = scripts / 'privileged_command_helper.ps1'
    installer = scripts / 'install_privileged_command_helper.ps1'
    script = f"""
$ErrorActionPreference='Stop'
foreach ($path in @({quote(helper)},{quote(installer)})) {{
    $tokens=$null; $errors=$null
    $ast=[Management.Automation.Language.Parser]::ParseFile($path,[ref]$tokens,[ref]$errors)
    if ($errors.Count) {{ throw ($errors | Out-String) }}
}}
$text=[IO.File]::ReadAllText({quote(helper)})
$start=$text.IndexOf('using System;'); $end=$text.IndexOf("'@",$start)
Add-Type -TypeDefinition $text.Substring($start,$end-$start)
$exe={quote(exe)}; $cwd={quote(tmp_path)}
$a=[CommandWatchdog]::Run($exe,'-NoProfile -NonInteractive -Command "[Console]::Out.WriteLine(\''fixture\''); [Console]::Error.WriteLine(\''error\''); exit 7"',$cwd,10000)
if ($a.Code -ne 7 -or $a.Timeout -or $a.Stdout -notmatch 'fixture' -or $a.Stderr -notmatch 'error') {{ throw 'Capture/exit mismatch' }}
$a=[CommandWatchdog]::Run($exe,'-NoProfile -NonInteractive -Command "Start-Sleep -Seconds 30"',$cwd,200)
if (-not $a.Timeout -or $a.Code -ne 124) {{ throw 'Timeout mismatch' }}
$a=[CommandWatchdog]::Run($exe,'-NoProfile -NonInteractive -Command "[Console]::Write((\''x\'' * 100000)); exit 0"',$cwd,10000)
if ($a.Code -ne 0 -or -not $a.Truncated -or $a.Stdout.Length -gt 4000) {{ throw 'Output bound mismatch' }}
Write-Output 'COMMAND_FIXTURES_PASSED'
"""
    result = subprocess.run([str(exe), '-NoProfile', '-NonInteractive', '-Command', script],
                            capture_output=True, text=True, timeout=25)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'COMMAND_FIXTURES_PASSED' in result.stdout
