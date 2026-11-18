"""Offline API, authorization, epoch, replay and idempotency contracts."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from starlette.websockets import WebSocketDisconnect

from runtime.server import CommandLedger, CommandRequest, create_server
from tests.runtime_helpers import make_runtime

TOKEN = "offline-test-token-" + "x" * 32
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def host(tmp_path, monkeypatch):
    runtime, agent = make_runtime(tmp_path)
    runtime.state.model_config = replace(runtime.state.model_config, api_key="PROVIDER_SECRET_SENTINEL",
                                         base_url="https://private-provider.invalid")
    provider = SimpleNamespace(key="fixture", label="Fixture", default_model="fixture-model",
                               supports_model_listing=True, api_key="PROVIDER_SECRET_SENTINEL")
    monkeypatch.setattr(type(runtime), "providers", property(lambda self: {"fixture": provider}))
    monkeypatch.setattr(runtime, "provider_models", lambda key: ["fixture-model", "other-model"])
    app = create_server(runtime, token=TOKEN)
    with TestClient(app, base_url="http://127.0.0.1", headers=HEADERS) as client:
        yield client, runtime, agent, app.state.server_id


def command(client, server_id, operation, arguments=None, request_id=None):
    return client.post("/v1/commands", json={
        "request_id": request_id or uuid4().hex, "server_id": server_id,
        "operation": operation, "arguments": arguments or {},
    })


def test_authentication_origin_and_host_are_enforced(host):
    client, runtime, agent, epoch = host
    for path in ("/v1/snapshot", "/v1/providers", "/v1/sessions"):
        assert client.get(path, headers={"Authorization": ""}).status_code == 401
        assert client.get(path, headers={"Origin": "https://untrusted.invalid"}).status_code == 401
        assert client.get(path, headers={"Host": "untrusted.invalid"}).status_code == 400
    assert client.post("/v1/commands", headers={"Authorization": "wrong"}, json={}).status_code == 401
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("ws://127.0.0.1/v1/events", headers={"Authorization": "wrong"}):
            pass
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("ws://127.0.0.1/v1/events", headers={"Origin": "https://untrusted.invalid"}):
            pass
    assert runtime.snapshot().run is None


def test_public_views_never_serialize_provider_credentials_or_internal_context(host, tmp_path):
    client, runtime, agent, epoch = host
    session = runtime.state.chat_store.new_session(runtime.state)
    runtime.state.chat_store.append_turn(session_id=session, user_text="question", assistant_text="answer",
                                         state=runtime.state)
    responses = [client.get(path) for path in (
        "/v1/snapshot", "/v1/providers", "/v1/providers/fixture/models", "/v1/sessions",
        f"/v1/sessions/{session}/turns",
    )]
    assert all(r.status_code == 200 for r in responses)
    encoded = "\n".join(r.text for r in responses)
    for forbidden in ("PROVIDER_SECRET_SENTINEL", "private-provider.invalid", "api_key", TOKEN):
        assert forbidden not in encoded
    assert all(r.headers["Cache-Control"] == "no-store" for r in responses)
    assert responses[-1].json() == [{"user": "question", "assistant_final": "answer"}]
    assert client.get("/v1/sessions/not-a-session/turns").status_code == 404


def test_health_requires_authentication_and_never_returns_chat_or_provider_state(host):
    client, runtime, agent, epoch = host
    runtime._message("You", "private conversation must not enter health responses")
    assert client.get("/v1/health", headers={"Authorization": ""}).status_code == 401
    response = client.get("/v1/health")
    assert response.status_code == 200
    assert response.json() == {"version": 1, "server_id": epoch, "closed": False}
    assert response.headers["Cache-Control"] == "no-store"


def test_duplicate_message_and_concurrent_retries_execute_once(host):
    client, runtime, agent, epoch = host
    release, started = Event(), Event()
    calls = []

    def step(text):
        calls.append(text)
        started.set()
        assert release.wait(5)
        return "done"

    agent.behavior = step
    request_id = uuid4().hex
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            responses = list(pool.map(lambda _: command(client, epoch, "submit", {"text": "once"}, request_id), range(4)))
        assert all(r.status_code == 200 for r in responses)
        assert len({r.json()["result"] for r in responses}) == 1
        assert started.wait(2)
        assert command(client, epoch, "submit", {"text": "different"}, request_id).status_code == 409
        assert command(client, epoch, "submit", {"text": "busy"}).status_code == 409
        assert calls == ["once"]
    finally:
        release.set()
        assert runtime.wait_for_idle(2)


def test_stale_epoch_and_unknown_operations_never_execute(host):
    client, runtime, agent, epoch = host
    assert command(client, uuid4().hex, "submit", {"text": "stale"}).status_code == 409
    assert command(client, epoch, "close").status_code == 422
    assert command(client, epoch, "submit", {"text": "test", "unexpected": True}).status_code == 422
    assert command(client, epoch, "submit", {"text": 42}).status_code == 422
    assert runtime.snapshot().run is None


def test_network_host_cannot_arm_or_decide_privileged_requests(host):
    client, runtime, agent, epoch = host
    assert command(client, epoch, "set_model_setting", {"key": "elevated_commands", "value": True}).status_code == 422
    assert command(client, epoch, "decide_pending", {"identity": "Efixture", "accept": True, "revision": "a" * 64}).status_code == 422
    with pytest.raises(PermissionError):
        runtime.attach_client(can_approve=True)
    with pytest.raises(PermissionError):
        runtime.set_model_setting("elevated_commands", True)
    assert runtime.state.privileged_turn.status == "disabled"


def test_review_revision_and_retried_file_decision_are_checked(host, tmp_path):
    client, runtime, agent, epoch = host
    target = tmp_path / "approved.txt"
    edit, _ = runtime.state.edit_store.propose_create(target, "approved once")
    view = client.get("/v1/snapshot").json()["pending"][0]
    assert view["id"] == edit.id
    bad = {"identity": edit.id, "accept": True, "revision": "0" * 64}
    assert command(client, epoch, "decide_pending", bad).status_code == 409
    assert not target.exists()
    arguments = dict(bad, revision=view["revision"])
    request_id = uuid4().hex
    first = command(client, epoch, "decide_pending", arguments, request_id)
    second = command(client, epoch, "decide_pending", arguments, request_id)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert target.read_text(encoding="utf-8") == "approved once"
    assert command(client, epoch, "decide_pending", arguments).status_code == 409


def test_websocket_disconnect_does_not_stop_work_and_replay_is_ordered(host):
    client, runtime, agent, epoch = host
    started, release = Event(), Event()

    def step(text):
        started.set()
        assert release.wait(5)
        return "finished while disconnected"

    agent.behavior = step
    try:
        with client.websocket_connect("ws://127.0.0.1/v1/events") as websocket:
            initial = websocket.receive_json()
            assert initial["reset"]
            cursor = initial["snapshot"]["sequence"]
            assert command(client, epoch, "submit", {"text": "background"}).status_code == 200
            assert started.wait(2)
        assert runtime.snapshot().processing
        release.set()
        assert runtime.wait_for_idle(2)
        with client.websocket_connect(f"ws://127.0.0.1/v1/events?server_id={epoch}&after={cursor}") as websocket:
            replay = websocket.receive_json()
            assert not replay["reset"]
            sequences = [e["sequence"] for e in replay["events"]]
            assert sequences == list(range(cursor + 1, replay["snapshot"]["sequence"] + 1))
            assert replay["snapshot"]["messages"][-1] == ["AI", "finished while disconnected"]
    finally:
        release.set()
        runtime.wait_for_idle(2)


def test_expired_or_previous_server_cursor_resets_instead_of_losing_state(tmp_path):
    runtime, agent = make_runtime(tmp_path, event_limit=2)
    app = create_server(runtime, token=TOKEN)
    runtime.submit("overflow")
    assert runtime.wait_for_idle(2)
    with TestClient(app, base_url="http://127.0.0.1", headers=HEADERS) as client:
        for epoch in (app.state.server_id, uuid4().hex):
            with client.websocket_connect(f"ws://127.0.0.1/v1/events?server_id={epoch}&after=0") as websocket:
                frame = websocket.receive_json()
                assert frame["reset"]
                assert frame["snapshot"]["messages"][-1] == ["AI", "answer: overflow"]
                assert TOKEN not in json.dumps(frame)


def test_full_ledger_refuses_new_ids_without_forgetting_previous_decisions(tmp_path):
    runtime, agent = make_runtime(tmp_path)
    epoch = uuid4().hex
    ledger = CommandLedger(runtime, epoch, capacity=1)
    request = CommandRequest(request_id=uuid4().hex, server_id=epoch, operation="new_chat")
    try:
        first = ledger.execute(request)
        assert first[0] == 200
        assert ledger.execute(request) == first
        other = request.model_copy(update={"request_id": uuid4().hex})
        assert ledger.execute(other)[0] == 503
        assert ledger.execute(request) == first
        assert len(runtime.list_sessions()) == 1
    finally:
        runtime.close()


def test_compact_context_command_is_strict_and_reports_through_the_runtime(host):
    client, runtime, agent, epoch = host
    before = runtime.snapshot()
    assert command(client, epoch, "compact_context", {"limit": 1}).status_code == 422
    assert runtime.snapshot() == before
    response = command(client, epoch, "compact_context")
    assert response.status_code == 200
    role, text = runtime.snapshot().messages[-1]
    assert role == "System" and text.startswith("Context compaction: nothing to elide")


def test_clean_context_reload_command_is_strict_shared_and_deduplicated(host):
    client, runtime, agent, epoch = host
    assert command(client, epoch, "reload_context").status_code == 409
    runtime.submit("saved question")
    assert runtime.wait_for_idle(2)
    session = runtime.state.chat_session_id
    agent.messages.append({"role": "tool", "content": "discard old tool output"})
    runtime._message("System", "discard old progress")
    before = runtime.snapshot()
    assert command(client, epoch, "reload_context", {"limit": 64}).status_code == 422
    assert runtime.snapshot() == before
    assert command(client, uuid4().hex, "reload_context").status_code == 409
    assert runtime.snapshot() == before
    request_id = uuid4().hex
    response = command(client, epoch, "reload_context", request_id=request_id)
    assert response.status_code == 200
    snapshot = runtime.snapshot()
    assert snapshot.run is None
    assert snapshot.messages[:2] == (("You", "saved question"), ("AI", "answer: saved question"))
    assert snapshot.messages[-1][1].startswith("Reloaded clean context: 1 saved turns")
    assert agent.messages[1:] == [
        {"role": "user", "content": "saved question"},
        {"role": "assistant", "content": "answer: saved question"},
    ]
    retried = command(client, epoch, "reload_context", request_id=request_id)
    assert retried.status_code == 200 and retried.json() == response.json()
    assert runtime.snapshot() == snapshot
    public = client.get("/v1/snapshot").json()
    assert public["snapshot"]["messages"] == [list(message) for message in snapshot.messages]
    assert runtime.state.chat_session_id == session
    assert len(runtime.list_sessions()) == 1
    assert len(runtime.load_original_turns(session)) == 1


@pytest.mark.parametrize("token", ["", "short", " x" + "a" * 32, "é" * 32])
def test_weak_or_malformed_tokens_are_rejected(tmp_path, token):
    runtime, agent = make_runtime(tmp_path)
    try:
        with pytest.raises(ValueError):
            create_server(runtime, token=token)
    finally:
        runtime.close()
