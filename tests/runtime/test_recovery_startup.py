"""Recovery-aware restart messages; scratch HTTP servers only."""
import os
from pathlib import Path
import shutil

import pytest

from tests.runtime.test_windows_startup import TOKEN, fake_backend, powershell

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
pytestmark = pytest.mark.skipif(os.name != "nt" or not shutil.which("powershell.exe"), reason="Windows PowerShell required")


@pytest.mark.parametrize("durable", [False, True])
def test_probe_and_confirmation_distinguish_first_upgrade_from_durable_restart(tmp_path, durable):
    payload = {"version": 1, "server_id": "a" * 32, "process_id": 321,
               "sequence": 7, "processing": False, "pending_count": 2, "closed": False}
    if durable:
        payload["durable_state"] = True
    with fake_backend(200, payload) as (port, requests):
        helper = tmp_path / "probe.ps1"
        helper.write_text((SCRIPTS / "agent_restart.ps1").read_text(encoding="utf-8").replace(
            "http://127.0.0.1:8765", f"http://127.0.0.1:{port}",
        ), encoding="utf-8")
        result = powershell(r"""
. $env:AI_TEST_HELPER
function Read-Host { param($Prompt) return 'RESTART' }
$status = Get-AgentRestartStatus
if ($status.Durable -ne ($env:AI_TEST_DURABLE -eq 'yes')) { throw 'Incorrect recovery capability' }
if (-not (Confirm-AgentRestart -Status $status)) { throw 'Confirmation refused' }
""", env={"AI_TEST_HELPER": str(helper), "AI_TEST_DURABLE": "yes" if durable else "no", "AI_AGENT_TOKEN": TOKEN})
    assert result.returncode == 0, result.stderr
    assert requests == [("/v1/maintenance", f"Bearer {TOKEN}")]
    assert TOKEN not in result.stdout + result.stderr
    if durable:
        assert "preserves saved context and ordinary pending proposals" in result.stdout
        assert "not automatically retried" in result.stdout
        assert "discards live model context" not in result.stdout
    else:
        assert "first upgrade cannot recover its volatile state" in result.stdout
        assert "discards live model context" in result.stdout
