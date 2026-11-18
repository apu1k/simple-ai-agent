"""Chat-bound commands, client-local subscriptions and cross-chat approval guards."""
import asyncio
from threading import Event
from uuid import uuid4

from fastapi.testclient import TestClient
import httpx
import pytest
from textual.widgets import Input

from adapters.textual.app import AgentTextualApp
from runtime.events import RunInfo
from runtime.remote import RemoteRuntimeClient
from runtime.server import CommandLedger, CommandRequest, create_server
from runtime.wire import public_frame
from tests.runtime.conversation_helpers import make_manager

TOKEN = "offline-multi-chat-" + "x" * 32
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
EPOCH = "a" * 32


def frame(manager, identity, generation=0):
    result = public_frame(manager.get(identity), EPOCH)
    result.update(multi_chat=True, session_id=identity, selection=generation, activity=manager.activity())
    return result


def connect_adapter(manager):
    adapter = RemoteRuntimeClient("http://127.0.0.1:8765", TOKEN)
    adapter._ingest(frame(manager, manager.default_chat_id))
    adapter._set_connected(True)
    return adapter


def command(client, epoch, identity, operation, arguments=None, request_id=None):
    return client.post("/v1/commands", json={
        "request_id": request_id or uuid4().hex, "server_id": epoch,
        "session_id": identity, "operation": operation, "arguments": arguments or {},
    })


def receive_until(websocket, predicate):
    for _ in range(30):
        result = websocket.receive_json()
        if predicate(result):
            return result
    pytest.fail("Did not receive the expected chat frame")


def test_explicit_chat_required_and_deduplication_includes_chat_identity(tmp_path):
    manager, _ = make_manager(tmp_path)
    first, second = manager.default_chat_id, manager.new_chat()
    ledger = CommandLedger(manager, EPOCH)
    try:
        request = CommandRequest(request_id=uuid4().hex, server_id=EPOCH, session_id=first,
                                 operation="set_model_setting", arguments={"key": "openai_flex", "value": True})
        assert ledger.execute(request)[0] == 200
        assert ledger.execute(request)[0] == 200
        assert ledger.execute(request.model_copy(update={"session_id": second}))[0] == 409
        assert manager.get(first).state.model_settings.openai_flex is True
        assert manager.get(second).state.model_settings.openai_flex is False
        missing = request.model_copy(update={"request_id": uuid4().hex, "session_id": None})
        assert ledger.execute(missing)[0] == 409
    finally:
        manager.close()


def test_remote_anthropic_effort_is_validated_and_projected(tmp_path):
    manager, _ = make_manager(tmp_path)
    identity = manager.default_chat_id
    ledger = CommandLedger(manager, EPOCH)

    def set_effort(value):
        return ledger.execute(CommandRequest(
            request_id=uuid4().hex, server_id=EPOCH, session_id=identity,
            operation="set_model_setting", arguments={"key": "anthropic_reasoning_effort", "value": value},
        ))[0]

    try:
        assert set_effort("xhigh") == 200
        assert set_effort("none") == 409
        adapter = connect_adapter(manager)
        assert adapter.state.model_settings.anthropic_reasoning_effort == "xhigh"
        assert adapter.state.model_settings.openai_reasoning_effort is None
        assert set_effort(None) == 200
        assert manager.get(identity).state.model_settings.anthropic_reasoning_effort is None
    finally:
        manager.close()


def test_websocket_selection_is_local_and_background_work_continues(tmp_path):
    manager, agents = make_manager(tmp_path)
    first, second = manager.default_chat_id, manager.new_chat()
    release, started_a, started_b = Event(), Event(), Event()

    def behavior(started):
        def step(text):
            started.set()
            assert release.wait(5)
            return text + " finished"
        return step

    agents[first].behavior = behavior(started_a)
    agents[second].behavior = behavior(started_b)
    try:
        app = create_server(manager, token=TOKEN)
        with TestClient(app, base_url="http://127.0.0.1", headers=HEADERS,
                        client=("127.0.0.1", 50123)) as client:
            epoch = app.state.server_id
            with client.websocket_connect("ws://127.0.0.1/v1/events") as b:
                assert b.receive_json()["session_id"] == first
                b.send_json({"session_id": second, "selection": 1})
                assert receive_until(b, lambda f: f.get("selection") == 1)["session_id"] == second
                with client.websocket_connect("ws://127.0.0.1/v1/events") as a:
                    assert a.receive_json()["session_id"] == first
                    assert command(client, epoch, first, "submit", {"text": "task A"}).status_code == 200
                    assert command(client, epoch, second, "submit", {"text": "task B"}).status_code == 200
                    assert started_a.wait(2) and started_b.wait(2)
                    busy = receive_until(b, lambda f: f["snapshot"]["run"] is not None)
                    assert busy["session_id"] == second
                    assert busy["activity"][first]["running"]
                    assert ["You", "task A"] not in busy["snapshot"]["messages"]
                    status = client.get("/v1/maintenance").json()
                    assert status["processing"] is True
                    assert client.post("/v1/maintenance/drain", json={
                        "server_id": epoch, "sequence": status["sequence"],
                    }).status_code == 409
                assert manager.get(first).snapshot().processing
                release.set()
                assert manager.get(first).wait_for_idle(2) and manager.get(second).wait_for_idle(2)
                done = receive_until(b, lambda f: f["snapshot"]["run"]["status"] == "completed")
                assert done["snapshot"]["messages"][-1] == ["AI", "task B finished"]
                assert client.get("/v1/snapshot", params={"session_id": first}).json()["snapshot"]["messages"][-1] == ["AI", "task A finished"]
    finally:
        release.set()
        manager.close()


def test_malformed_subscription_does_not_destroy_the_connection(tmp_path):
    manager, _ = make_manager(tmp_path)
    second = manager.new_chat()
    with TestClient(create_server(manager, token=TOKEN), base_url="http://127.0.0.1", headers=HEADERS) as client:
        with client.websocket_connect("ws://127.0.0.1/v1/events") as ws:
            ws.receive_json()
            ws.send_text("not-json")
            assert "selection_error" in ws.receive_json()
            ws.send_json({"session_id": second, "selection": 1})
            selected = receive_until(ws, lambda f: f.get("selection") == 1)
            assert selected["session_id"] == second and selected["reset"]


def test_switch_clears_display_blocks_commands_and_ignores_in_flight_old_frames(tmp_path):
    manager, _ = make_manager(tmp_path)
    first, second = manager.default_chat_id, manager.new_chat()
    adapter = connect_adapter(manager)
    try:
        adapter.submit("bound to A")
        queued = adapter._jobs.get_nowait()["body"]
        adapter.load_chat(second)
        assert queued["session_id"] == first
        assert adapter.state.chat_session_id == second
        assert adapter.snapshot().messages == ()
        with pytest.raises(RuntimeError, match="loading"):
            adapter.submit("not ready")
        adapter._ingest(frame(manager, first))
        assert adapter.state.chat_session_id == second
        assert not adapter._selection_ready
        adapter._ingest(frame(manager, second, 1))
        adapter.submit("bound to B")
        assert adapter._jobs.get_nowait()["body"]["session_id"] == second
        manager.execute(first, "submit", {"text": queued["arguments"]["text"]})
        assert manager.get(first).wait_for_idle(2)
        assert manager.get(second).snapshot().run is None
    finally:
        manager.close()


def test_old_review_cannot_decide_same_numeric_id_in_a_different_chat(tmp_path):
    manager, _ = make_manager(tmp_path)
    first, second = manager.default_chat_id, manager.new_chat()
    for identity in (first, second):
        manager.get(identity).state.edit_store.propose_create(tmp_path / f"{identity}.txt", identity)
    adapter = connect_adapter(manager)
    try:
        reviewed = adapter.pending()[1]
        adapter.load_chat(second)
        adapter._ingest(frame(manager, second, 1))
        with pytest.raises(RuntimeError, match="Chat changed"):
            adapter.decide_pending(1, accept=True, revision=reviewed.revision)
        assert adapter._jobs.empty()
        current = adapter.pending()[1]
        adapter.decide_pending(1, accept=True, revision=current.revision)
        queued = adapter._jobs.get_nowait()["body"]
        assert queued["session_id"] == second
        assert CommandLedger(manager, EPOCH).execute(CommandRequest(**queued))[0] == 200
        assert not (tmp_path / f"{first}.txt").exists()
        assert (tmp_path / f"{second}.txt").read_text(encoding="utf-8") == second
    finally:
        manager.close()


def test_delayed_new_chat_acknowledgement_does_not_steal_a_later_selection(tmp_path):
    manager, _ = make_manager(tmp_path)
    first, second = manager.default_chat_id, manager.new_chat()
    adapter = connect_adapter(manager)
    ledger = CommandLedger(manager, EPOCH)

    async def scenario():
        adapter.new_chat()
        queued = adapter._jobs.get_nowait()["body"]
        adapter.load_chat(second)
        adapter._ingest(frame(manager, second, 1))

        def dispatch(request):
            status, body = ledger.execute(CommandRequest(**queued))
            return httpx.Response(status, json=body)

        async with httpx.AsyncClient(transport=httpx.MockTransport(dispatch)) as http:
            await adapter._post(http, queued)
        assert adapter.state.chat_session_id == second
        assert manager.get(first).state.chat_session_id == first
        assert len(manager.list_sessions()) == 3

    try:
        asyncio.run(scenario())
    finally:
        manager.close()


def test_new_chat_ack_selects_the_created_chat_and_not_a_global_active_chat(tmp_path):
    manager, _ = make_manager(tmp_path)
    adapter = connect_adapter(manager)
    other = connect_adapter(manager)
    ledger = CommandLedger(manager, EPOCH)

    async def scenario():
        adapter.new_chat()
        queued = adapter._jobs.get_nowait()["body"]
        accepted = None

        def dispatch(request):
            nonlocal accepted
            status, accepted = ledger.execute(CommandRequest(**queued))
            return httpx.Response(status, json=accepted)

        async with httpx.AsyncClient(transport=httpx.MockTransport(dispatch)) as http:
            await adapter._post(http, queued)
        assert adapter.state.chat_session_id == accepted["result"]
        assert other.state.chat_session_id == manager.default_chat_id
        assert not adapter._selection_ready

    try:
        asyncio.run(scenario())
    finally:
        manager.close()


def test_late_request_errors_stay_with_their_original_chat_and_background_is_unread(tmp_path):
    manager, _ = make_manager(tmp_path)
    first, second = manager.default_chat_id, manager.new_chat()
    adapter = connect_adapter(manager)
    try:
        adapter.load_chat(second)
        adapter._ingest(frame(manager, second, 1))
        manager.get(first)._message("AI", "background result")
        adapter._ingest(frame(manager, second, 1))
        assert adapter.session_activity(first)["unread"] is True
        adapter._notice("late failure for A", session_id=first)
        assert not any(text == "late failure for A" for _, text in adapter.snapshot().messages)
        adapter.load_chat(first)
        adapter._ingest(frame(manager, first, 2))
        assert adapter.session_activity(first)["unread"] is False
        assert any(text == "late failure for A" for _, text in adapter.snapshot().messages)
        assert any(text == "background result" for _, text in adapter.snapshot().messages)
    finally:
        manager.close()


def test_textual_can_switch_from_a_running_chat_and_resets_processing_to_target(tmp_path):
    manager, _ = make_manager(tmp_path)
    first, second = manager.default_chat_id, manager.new_chat()
    manager.get(first)._run = RunInfo(uuid4().hex, "running in A")
    manager.get(first)._message("You", "running in A")
    adapter = connect_adapter(manager)
    adapter._sessions = manager.list_sessions()

    async def scenario():
        app = AgentTextualApp(runtime=adapter)

        def attach_without_network():
            app._runtime_client_id = "offline-adapter"
            app._apply_runtime_snapshot()

        app._connect_runtime = attach_without_network
        async with app.run_test(size=(140, 40)) as pilot:
            assert app._processing
            await pilot.press("f3")
            assert app._mode == "chat_select"
            app._selected_chat_session_id = second
            app._submit_chat_selection()
            assert app._mode == "chat"
            assert not app._processing
            adapter._ingest(frame(manager, second, 1))
            app._drain_runtime_events()
            assert app.state.chat_session_id == second
            assert not app._processing
            assert "running in A" not in str(app._messages)
            assert not app.query_one("#input", Input).disabled
            assert manager.get(first).snapshot().processing

    try:
        asyncio.run(scenario())
    finally:
        manager.close()
