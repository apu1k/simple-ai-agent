"""Windows launcher checks using scratch credentials and fake backends only."""
from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
from threading import Thread
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
POWERSHELL = shutil.which("powershell.exe")
pytestmark = pytest.mark.skipif(os.name != "nt" or not POWERSHELL, reason="Windows PowerShell required")
TOKEN = "offline-startup-token-" + "x" * 32


def powershell(script, *, env=None, timeout=12):
    child_env = os.environ.copy()
    for name in ("AI_AGENT_TOKEN", "AI_AGENT_MODE", "AI_AGENT_SERVER"):
        child_env.pop(name, None)
    child_env.update(env or {})
    return subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", "$ErrorActionPreference='Stop'; " + script],
        env=child_env, capture_output=True, text=True, timeout=timeout,
    )


def helper_env(tmp_path):
    return {"AI_TEST_PROJECT": str(tmp_path), "AI_TEST_HELPER": str(SCRIPTS / "agent_startup.ps1")}


@pytest.mark.parametrize("name", ["agent_startup.ps1", "start_backend.ps1"])
def test_tracked_startup_scripts_parse_in_windows_powershell(name):
    result = powershell(r"""
$tokens = $null; $problems = $null
[Management.Automation.Language.Parser]::ParseFile($env:AI_TEST_SCRIPT, [ref]$tokens, [ref]$problems) | Out-Null
if ($problems.Count) { throw ($problems.Message -join '; ') }
""", env={"AI_TEST_SCRIPT": str(SCRIPTS / name)})
    assert result.returncode == 0, result.stderr


def test_generated_token_is_dpapi_protected_reused_and_not_logged(tmp_path):
    result = powershell(r"""
. $env:AI_TEST_HELPER
$first = Get-AgentStartupToken -Project $env:AI_TEST_PROJECT
Assert-AgentStartupToken -Token $first
$file = Join-Path $env:AI_TEST_PROJECT '.agent_runtime\startup-token.dpapi'
$cipher = [IO.File]::ReadAllText($file)
if ($cipher.Contains($first)) { throw 'Credential file is not encrypted' }
$second = Get-AgentStartupToken -Project $env:AI_TEST_PROJECT
if ($first -cne $second) { throw 'Credential changed between independent loads' }
Write-Output 'protected-and-reused'
""", env=helper_env(tmp_path))
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "protected-and-reused"
    assert not result.stderr


def test_explicit_environment_token_wins_without_writing_a_file(tmp_path):
    env = dict(helper_env(tmp_path), AI_AGENT_TOKEN=TOKEN)
    result = powershell(r"""
. $env:AI_TEST_HELPER
$value = Get-AgentStartupToken -Project $env:AI_TEST_PROJECT
if ($value -cne $env:AI_AGENT_TOKEN) { throw 'Explicit credential was not retained' }
if (Test-Path (Join-Path $env:AI_TEST_PROJECT '.agent_runtime')) { throw 'Unexpected credential write' }
Write-Output 'explicit-token-retained'
""", env=env)
    assert result.returncode == 0, result.stderr
    assert TOKEN not in result.stdout + result.stderr
    assert result.stdout.strip() == "explicit-token-retained"


@pytest.mark.parametrize("token", ["short", " " + "x" * 40, "x" * 20 + "\n" + "x" * 20])
def test_invalid_configured_token_fails_closed(tmp_path, token):
    result = powershell(r"""
. $env:AI_TEST_HELPER
$value = Get-AgentStartupToken -Project $env:AI_TEST_PROJECT
""", env=dict(helper_env(tmp_path), AI_AGENT_TOKEN=token))
    assert result.returncode != 0
    assert "printable ASCII" in result.stderr
    assert not (tmp_path / ".agent_runtime").exists()


def test_broken_credential_is_not_silently_rotated(tmp_path):
    token_path = tmp_path / ".agent_runtime" / "startup-token.dpapi"
    token_path.parent.mkdir()
    token_path.write_text("not-valid-dpapi", encoding="ascii")
    result = powershell(r"""
. $env:AI_TEST_HELPER
$value = Get-AgentStartupToken -Project $env:AI_TEST_PROJECT
""", env=helper_env(tmp_path))
    assert result.returncode != 0
    assert "Cannot decrypt" in result.stderr
    assert token_path.read_text(encoding="ascii") == "not-valid-dpapi"


@contextmanager
def fake_backend(status, payload):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append((self.path, self.headers.get("Authorization")))
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            if status == 302:
                self.send_header("Location", "/must-not-follow")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            yield server.server_port, requests
        finally:
            server.shutdown()
            worker.join(timeout=3)


def probe_backend(tmp_path, port):
    # Substitute ONLY the loopback port inside a scratch copy of the helper.
    # Never probe the real backend or read the operator's actual credential.
    helper = tmp_path / "probe.ps1"
    helper.write_text(
        (SCRIPTS / "agent_startup.ps1").read_text(encoding="utf-8").replace(
            "http://127.0.0.1:8765/v1/health", f"http://127.0.0.1:{port}/v1/health",
        ), encoding="utf-8",
    )
    return powershell(r"""
. $env:AI_TEST_HELPER
if (-not (Test-AgentBackendReady)) { throw 'Unexpected not-ready result' }
Write-Output 'ready'
""", env={"AI_TEST_HELPER": str(helper), "AI_AGENT_TOKEN": TOKEN})


def test_ready_probe_authenticates_without_requesting_chat_history(tmp_path):
    with fake_backend(200, {"version": 1, "server_id": "a" * 32, "closed": False}) as (port, requests):
        result = probe_backend(tmp_path, port)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ready"
    assert requests == [("/v1/health", f"Bearer {TOKEN}")]
    assert TOKEN not in result.stdout + result.stderr


@pytest.mark.parametrize("status,payload", [
    (401, {"detail": "Authentication required"}),
    (302, {"detail": "Redirect"}),
    (200, {"version": 2, "server_id": "a" * 32, "closed": False}),
    (200, {"version": 1, "server_id": "invalid", "closed": False}),
    (200, {"version": 1, "server_id": "a" * 32, "closed": True}),
    (200, {"padding": "x" * 5000}),
])
def test_unready_or_wrong_backend_is_not_accepted_or_redirected(tmp_path, status, payload):
    with fake_backend(status, payload) as (port, requests):
        result = probe_backend(tmp_path, port)
    assert result.returncode != 0
    assert len(requests) == 1
    assert TOKEN not in result.stdout + result.stderr


def test_wait_uses_readiness_not_a_fixed_startup_sleep(tmp_path):
    result = powershell(r"""
. $env:AI_TEST_HELPER
$script:attempts = 0
function Test-AgentBackendReady { $script:attempts++; return ($script:attempts -eq 2) }
Wait-AgentBackendReady -TimeoutSeconds 3
if ($script:attempts -ne 2) { throw 'Readiness was not checked' }
Write-Output 'waited-for-ready'
""", env=helper_env(tmp_path))
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "waited-for-ready"


@pytest.mark.parametrize("already_ready,occupied", [(True, False), (False, True)])
def test_launcher_leaves_existing_backends_and_port_owners_untouched(tmp_path, already_ready, occupied):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    launcher = scripts / "start_backend.ps1"
    launcher.write_text((SCRIPTS / "start_backend.ps1").read_text(encoding="utf-8"), encoding="utf-8")
    # These stub functions make launching a real interpreter impossible. There
    # is no .venv or real backend executable anywhere in this scratch project.
    helper = scripts / "agent_startup.ps1"
    helper.write_text(
        "function Initialize-AgentStartupEnvironment { param($Project) }\n"
        f"function Get-AgentStartupMutexName {{ param($Project,$Purpose) return 'Local\\test-agent-{uuid4().hex}' }}\n"
        f"function Test-AgentBackendReady {{ return ${str(already_ready).lower()} }}\n"
        + ("function Get-NetTCPConnection { return [pscustomobject]@{ OwningProcess = 123 } }\n"
           if occupied else "function Get-NetTCPConnection { throw 'Port scan should not be reached' }\n"),
        encoding="utf-8",
    )
    result = powershell("& $env:AI_TEST_LAUNCHER", env={"AI_TEST_LAUNCHER": str(launcher)})
    if already_ready:
        assert result.returncode == 0, result.stderr
        assert "Leaving it untouched" in result.stdout
    else:
        assert result.returncode != 0
        assert "will not be stopped or replaced" in result.stderr
    assert not (tmp_path / ".agent_runtime").exists()


def test_local_startup_task_scripts_launch_backend_before_textual_and_wait():
    names = ("start_all_silent.ps1", "start_all_visible.ps1", "start_textual.ps1")
    if not all((SCRIPTS / name).exists() for name in names):
        pytest.skip("Operator-specific ignored startup stack is not installed in this checkout")
    for name in names[:2]:
        text = (SCRIPTS / name).read_text(encoding="utf-8")
        assert text.index("start_backend.ps1") < text.index("start_textual.ps1")
    text = (SCRIPTS / "start_textual.ps1").read_text(encoding="utf-8")
    assert text.index("Initialize-AgentStartupEnvironment") < text.index("Wait-AgentBackendReady")
    assert text.index("Wait-AgentBackendReady") < text.index('textual.exe" serve')
