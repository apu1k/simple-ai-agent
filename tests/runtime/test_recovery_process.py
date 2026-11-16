"""Real process death/restart tests. Only newly owned offline fixtures are killed."""
from contextlib import contextmanager
import os
from pathlib import Path
import socket
import subprocess
import sys
import sysconfig
import time
from uuid import uuid4

import httpx
import pytest

from tests.runtime.recovery_fixture import TOKEN

ROOT = Path(__file__).resolve().parents[2]
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


def until(predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.04)
    pytest.fail("Offline recovery fixture did not reach the expected state")


@contextmanager
def process_host(root):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    # Windows venv python.exe is a redirector: killing that shim could leave its
    # child alive. Invoke the base interpreter directly with only this venv's
    # package paths, so the retained Popen handle owns the actual fixture host.
    executable = getattr(sys, "_base_executable", sys.executable)
    env = os.environ.copy()
    env.pop("__PYVENV_LAUNCHER__", None)
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT), sysconfig.get_path("purelib"), sysconfig.get_path("platlib")])
    process = subprocess.Popen(
        [executable, "-m", "tests.runtime.recovery_fixture", "--root", str(root), "--port", str(port)],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    client = httpx.Client(base_url=f"http://127.0.0.1:{port}", headers=HEADERS, timeout=2, trust_env=False)

    def ready():
        if process.poll() is not None:
            pytest.fail(process.stderr.read().decode(errors="replace"))
        try:
            return client.get("/v1/health").status_code == 200
        except httpx.HTTPError:
            return False

    try:
        until(ready)
        yield client
    finally:
        client.close()
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        process.stderr.close()


def frame(client):
    response = client.get("/v1/snapshot")
    response.raise_for_status()
    return response.json()


def command(client, operation, arguments=None, server_id=None):
    return client.post("/v1/commands", json={
        "request_id": uuid4().hex, "server_id": server_id or frame(client)["server_id"],
        "operation": operation, "arguments": arguments or {},
    })


def test_completed_conversation_and_pending_approval_survive_real_process_restarts(tmp_path):
    with process_host(tmp_path) as client:
        assert command(client, "submit", {"text": "propose"}).status_code == 200
        until(lambda: frame(client)["snapshot"]["run"]["status"] == "completed")
        before = frame(client)
        assert before["pending"]
        calls = (tmp_path / "provider_calls.txt").read_text(encoding="utf-8")
        old_id = before["server_id"]
    with process_host(tmp_path) as client:
        restored = frame(client)
        assert restored["server_id"] != old_id
        assert restored["state"]["chat_session_id"] == before["state"]["chat_session_id"]
        assert restored["snapshot"]["run"]["status"] == "completed"
        assert restored["pending"] == before["pending"]
        assert client.get("/v1/maintenance").json()["durable_state"] is True
        assert (tmp_path / "provider_calls.txt").read_text(encoding="utf-8") == calls
        proposal = restored["pending"][0]
        args = {"identity": proposal["id"], "revision": proposal["revision"], "accept": True}
        assert command(client, "decide_pending", args, server_id=old_id).status_code == 409
        assert not (tmp_path / "approved.txt").exists()
        assert command(client, "decide_pending", args).status_code == 200
        assert (tmp_path / "approved.txt").read_text(encoding="utf-8") == "approved after restart"
    with process_host(tmp_path) as client:
        assert frame(client)["pending"] == []
        assert (tmp_path / "provider_calls.txt").read_text(encoding="utf-8") == calls


def test_crash_during_tool_keeps_evidence_and_does_not_repeat_side_effect(tmp_path):
    with process_host(tmp_path) as client:
        assert command(client, "submit", {"text": "interrupt"}).status_code == 200
        until(lambda: (tmp_path / "started").exists())
        before = frame(client)
        assert before["snapshot"]["run"]["status"] == "running"
        assert before["pending"]
    with process_host(tmp_path) as client:
        restored = frame(client)
        assert restored["snapshot"]["run"]["status"] == "interrupted"
        assert restored["pending"] == before["pending"]
        assert (tmp_path / "effects.txt").read_text(encoding="utf-8") == "one scratch effect\n"
        assert len((tmp_path / "provider_calls.txt").read_text(encoding="utf-8").splitlines()) == 1
        messages = "\n".join(text for role, text in restored["snapshot"]["messages"])
        assert "outcome_unknown" in messages and "Nothing was automatically retried" in messages
        assert "external processes may still be running" in messages
        assert command(client, "submit", {"text": "do not retry; just reply"}).status_code == 200
        until(lambda: frame(client)["snapshot"]["run"]["status"] == "completed")
        assert (tmp_path / "effects.txt").read_text(encoding="utf-8") == "one scratch effect\n"
