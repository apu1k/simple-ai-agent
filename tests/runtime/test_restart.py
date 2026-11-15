"""Local maintenance drain is authenticated, reviewed and atomic with submit."""
from concurrent.futures import ThreadPoolExecutor
import os
from threading import Barrier, Event
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from runtime.server import create_server
from runtime.service import RuntimeBusyError
from tests.runtime_helpers import make_runtime

TOKEN = "offline-maintenance-token-" + "x" * 32
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


def client_for(runtime, peer="127.0.0.1"):
    return TestClient(create_server(runtime, token=TOKEN), base_url="http://127.0.0.1",
                      headers=HEADERS, client=(peer, 50123))


@pytest.mark.parametrize("peer", ["127.0.0.1", "::1"])
def test_maintenance_status_is_minimal_and_never_returns_chat_or_credentials(tmp_path, peer):
    runtime, _ = make_runtime(tmp_path)
    runtime._message("You", "PRIVATE_CHAT_SENTINEL")
    runtime.state.edit_store.propose_create(tmp_path / "pending.txt", "PRIVATE_FILE_SENTINEL")
    with client_for(runtime, peer) as client:
        response = client.get("/v1/maintenance")
        assert response.status_code == 200
        assert response.json() == {
            "version": 1, "server_id": client.app.state.server_id, "process_id": os.getpid(),
            "sequence": runtime.snapshot().sequence, "processing": False,
            "pending_count": 1, "closed": False,
        }
        assert response.headers["Cache-Control"] == "no-store"
        for forbidden in ("PRIVATE_CHAT_SENTINEL", "PRIVATE_FILE_SENTINEL", TOKEN, "api_key", "model_config"):
            assert forbidden not in response.text
        assert client.get("/v1/maintenance", headers={"Authorization": "wrong"}).status_code == 401
        assert client.post("/v1/maintenance/drain", json={}, headers={"Authorization": "wrong"}).status_code == 401
        assert client.get("/v1/maintenance", headers={"Origin": "https://untrusted.invalid"}).status_code == 401


def test_remote_peer_cannot_drain_even_with_token_and_spoofed_forwarded_headers(tmp_path):
    runtime, _ = make_runtime(tmp_path)
    with client_for(runtime, "100.64.0.8") as client:
        body = {"server_id": client.app.state.server_id, "sequence": runtime.snapshot().sequence}
        headers = {"X-Forwarded-For": "127.0.0.1", "Forwarded": "for=127.0.0.1"}
        assert client.get("/v1/maintenance", headers=headers).status_code == 403
        assert client.post("/v1/maintenance/drain", json=body, headers=headers).status_code == 403
        assert not runtime.snapshot().closed


def test_drain_checks_epoch_and_reviewed_sequence_then_closes_without_deleting_state(tmp_path):
    runtime, agent = make_runtime(tmp_path)
    runtime.submit("saved message")
    assert runtime.wait_for_idle(2)
    proposal, _ = runtime.state.edit_store.propose_create(tmp_path / "pending.txt", "not applied")
    with client_for(runtime) as client:
        status = client.get("/v1/maintenance").json()
        body = {"server_id": status["server_id"], "sequence": status["sequence"]}
        assert client.post("/v1/maintenance/drain", json=dict(body, server_id=uuid4().hex)).status_code == 409
        assert client.post("/v1/maintenance/drain", json=dict(body, force=True)).status_code == 422
        assert not runtime.snapshot().closed
        runtime._message("System", "state changed after review")
        assert client.post("/v1/maintenance/drain", json=body).status_code == 409
        assert not runtime.snapshot().closed
        body["sequence"] = runtime.snapshot().sequence
        messages, context = runtime.snapshot().messages, list(agent.messages)
        result = client.post("/v1/maintenance/drain", json=body)
        assert result.status_code == 200
        assert result.json() == {"server_id": status["server_id"], "closed": True}
        assert runtime.snapshot().closed
        assert runtime.snapshot().messages == messages
        assert agent.messages == context
        assert proposal.id in runtime.pending()
        assert not (tmp_path / "pending.txt").exists()
        assert client.post("/v1/maintenance/drain", json=body).json() == result.json()
        with pytest.raises(RuntimeError, match="closed"):
            runtime.submit("must not start")
        with pytest.raises(RuntimeError, match="closed"):
            runtime.decide_pending(proposal.id, accept=True)
        assert client.get("/v1/maintenance").json()["closed"] is True
        # It is deliberately not exposed as a normal agent/client command.
        assert client.post("/v1/commands", json={
            "request_id": uuid4().hex, "server_id": status["server_id"],
            "operation": "prepare_restart", "arguments": {},
        }).status_code == 422


def test_active_run_cannot_be_drained(tmp_path):
    runtime, agent = make_runtime(tmp_path)
    started, release = Event(), Event()

    def step(text):
        started.set()
        assert release.wait(5)
        return "finished normally"

    agent.behavior = step
    with client_for(runtime) as client:
        try:
            runtime.submit("working")
            assert started.wait(2)
            status = client.get("/v1/maintenance").json()
            assert status["processing"] is True
            response = client.post("/v1/maintenance/drain", json={
                "server_id": status["server_id"], "sequence": status["sequence"],
            })
            assert response.status_code == 409
            assert not runtime.snapshot().closed
        finally:
            release.set()
            assert runtime.wait_for_idle(2)


def test_concurrent_submit_and_drain_cannot_close_an_active_run(tmp_path):
    runtime, agent = make_runtime(tmp_path)
    barrier, release = Barrier(2), Event()
    agent.behavior = lambda text: "done" if release.wait(5) else "fixture timed out"
    sequence = runtime.snapshot().sequence

    def submit():
        barrier.wait(timeout=2)
        try:
            runtime.submit("racing submit")
            return "submitted"
        except RuntimeError:
            return "closed"

    def drain():
        barrier.wait(timeout=2)
        try:
            runtime.prepare_restart(sequence)
            return "drained"
        except RuntimeBusyError:
            return "busy"

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = pool.submit(submit), pool.submit(drain)
            outcomes = first.result(), second.result()
        assert outcomes in {("submitted", "busy"), ("closed", "drained")}
        assert not (runtime.snapshot().processing and runtime.snapshot().closed)
    finally:
        release.set()
        runtime.close()
