"""Real subprocess/network acceptance tests plus client replay/race tests."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, contextmanager, suppress
from pathlib import Path
import socket
import subprocess
import sys
import time
from uuid import uuid4

import httpx
import pytest
from textual.widgets import Input

from adapters.textual.app import AgentTextualApp
from runtime.chat_store import ChatStore
from runtime.remote import RemoteRuntimeClient, validate_server_url
from runtime.server import CommandLedger, CommandRequest
from runtime.wire import public_frame
from tests.runtime.server_fixture import TOKEN
from tests.runtime_helpers import make_runtime

ROOT = Path(__file__).resolve().parents[2]


@contextmanager
def running_server(tmp_path, port=None):
    if port is None:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
    process = subprocess.Popen(
        [sys.executable, "-m", "tests.runtime.server_fixture", "--port", str(port), "--root", str(tmp_path)],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if process.poll() is not None:
                pytest.fail("Offline server exited: " + process.stderr.read().decode(errors="replace"))
            try:
                response = httpx.get(url + "/v1/snapshot", headers={"Authorization": f"Bearer {TOKEN}"},
                                     timeout=0.3, trust_env=False)
                if response.status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.05)
        else:
            pytest.fail("Offline server did not become ready")
        yield url, port
    finally:
        # Only this newly owned, fake-tool subprocess is terminated here.
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        process.stderr.close()


async def eventually(predicate, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.03)
    assert predicate(), "Condition did not become true before the deadline"


def close_adapter(adapter, identity):
    adapter.detach_client(identity)
    if adapter._thread is not None:
        adapter._thread.join(timeout=3)
        assert not adapter._thread.is_alive()


def test_two_remote_textual_clients_approve_after_initiator_closes_and_reconnect(tmp_path):
    with running_server(tmp_path) as (url, port):
        async def scenario():
            second = AgentTextualApp(runtime=RemoteRuntimeClient(url, TOKEN))
            async with second.run_test(size=(120, 40)):
                await eventually(lambda: second.runtime.connection_status == "connected")
                first = AgentTextualApp(runtime=RemoteRuntimeClient(url, TOKEN))
                async with first.run_test(size=(120, 40)):
                    await eventually(lambda: first.runtime.connection_status == "connected")
                    first._start_agent_step("propose")
                    await eventually(lambda: bool(second.runtime.pending()))
                    first._drain_runtime_events()
                    second._drain_runtime_events()
                    assert first._processing and second._processing
                    assert first._messages == second._messages
                    assert not hasattr(second.state, "chat_store")
                    assert not hasattr(second.state.model_config, "api_key")
                # The originating interface process/thread owns no server work.
                assert second.runtime.snapshot().processing
                second._enter_pending_select_mode()
                second._approve_selected_pending()
                await eventually(lambda: (tmp_path / "approved.txt").exists())
                await eventually(lambda: second.runtime.snapshot().run.status == "completed")
                second._drain_runtime_events()
                assert not second._processing
                assert (tmp_path / "approved.txt").read_text(encoding="utf-8") == "approved from another client"
                assert ("AI", "finished after initiating client disconnected") in second._messages
                assert not second._pending_entries()
                reconnected = AgentTextualApp(runtime=RemoteRuntimeClient(url, TOKEN))
                async with reconnected.run_test(size=(120, 40)):
                    await eventually(lambda: reconnected.runtime.connection_status == "connected")
                    reconnected._drain_runtime_events()
                    assert reconnected._messages == second._messages
                    assert not reconnected._processing
        asyncio.run(scenario())


def test_remote_clean_context_reload_is_shared_and_keeps_the_local_chat(tmp_path):
    store = ChatStore(tmp_path / "history")
    session = store.new_session()
    for index in range(1, 41):
        store.append_turn(session_id=session, user_text=f"u{index}", assistant_text=f"a{index}")
    with running_server(tmp_path) as (url, port):
        first = RemoteRuntimeClient(url, TOKEN)
        second = RemoteRuntimeClient(url, TOKEN)
        first_id = first.attach_client()
        second_id = second.attach_client()

        async def scenario():
            await eventually(lambda: first.connection_status == second.connection_status == "connected")
            first.load_chat(session)
            await eventually(lambda: second.state.chat_session_id == session)
            first.reload_context()

            def reloaded(adapter):
                messages = adapter.snapshot().messages
                return bool(messages) and messages[-1][1].startswith("Reloaded clean context: 32 saved turns")

            await eventually(lambda: reloaded(first) and reloaded(second))
            expected = tuple(
                (role, text)
                for index in range(9, 41)
                for role, text in (("You", f"u{index}"), ("AI", f"a{index}"))
            )
            assert first.snapshot().messages[:-1] == second.snapshot().messages[:-1] == expected
            assert first.state.chat_session_id == second.state.chat_session_id == session
            assert store.list_sessions()[0].turn_count == 40
            first.submit("continue clean chat")
            await eventually(lambda: second.snapshot().run is not None and second.snapshot().run.status == "completed")
            assert second.snapshot().messages[-1] == ("AI", "answer: continue clean chat")
            assert store.list_sessions()[0].turn_count == 41

        try:
            asyncio.run(scenario())
        finally:
            close_adapter(first, first_id)
            close_adapter(second, second_id)


def test_remote_reload_context_uses_an_empty_epoch_bound_command_and_rejects_offline():
    adapter = RemoteRuntimeClient("http://127.0.0.1:8765", TOKEN)
    with pytest.raises(RuntimeError, match="disconnected"):
        adapter.reload_context()
    assert adapter._jobs.empty()
    adapter._server_id = uuid4().hex
    adapter._set_connected(True)
    adapter.reload_context()
    job = adapter._jobs.get_nowait()
    assert job["kind"] == "command"
    assert job["body"]["operation"] == "reload_context"
    assert job["body"]["arguments"] == {}
    assert job["body"]["server_id"] == adapter._server_id
    assert len(job["body"]["request_id"]) == 32


def test_remote_compact_context_sends_an_empty_epoch_bound_command():
    adapter = RemoteRuntimeClient("http://127.0.0.1:8765", TOKEN)
    with pytest.raises(RuntimeError, match="disconnected"):
        adapter.compact_context()
    adapter._server_id = uuid4().hex
    adapter._set_connected(True)
    adapter.compact_context()
    job = adapter._jobs.get_nowait()
    assert job["body"]["operation"] == "compact_context"
    assert job["body"]["arguments"] == {}
    assert job["body"]["server_id"] == adapter._server_id


def test_backend_restart_reconnects_but_old_review_token_cannot_approve_reused_id(tmp_path):
    adapter = None
    identity = None

    async def scenario():
        nonlocal adapter, identity
        with running_server(tmp_path) as (url, port):
            adapter = RemoteRuntimeClient(url, TOKEN)
            identity = adapter.attach_client()
            await eventually(lambda: adapter.connection_status == "connected")
            adapter.submit("propose")
            await eventually(lambda: bool(adapter.pending()))
            reviewed = next(iter(adapter.pending().values()))
            old_epoch = adapter._server_id
        await eventually(lambda: adapter.connection_status != "connected")
        with running_server(tmp_path, port) as (url, port):
            await eventually(lambda: adapter.connection_status == "connected" and adapter._server_id != old_epoch)
            adapter.submit("propose")
            await eventually(lambda: bool(adapter.pending()))
            replacement = next(iter(adapter.pending().values()))
            assert replacement.id == reviewed.id
            # Even identical proposal contents cannot reuse a previous epoch's consent.
            with pytest.raises(RuntimeError, match="Server changed"):
                adapter.decide_pending(reviewed.id, accept=True, revision=reviewed.revision)
            assert not (tmp_path / "approved.txt").exists()
            adapter.decide_pending(replacement.id, accept=True, revision=replacement.revision)
            await eventually(lambda: (tmp_path / "approved.txt").exists())
            assert any("Server restarted" in text for _, text in adapter.snapshot().messages)

    try:
        asyncio.run(scenario())
    finally:
        if adapter is not None and identity is not None:
            close_adapter(adapter, identity)


def test_lost_http_reply_reuses_exact_request_id_and_executes_only_once(tmp_path):
    runtime, agent = make_runtime(tmp_path)
    epoch = uuid4().hex
    ledger = CommandLedger(runtime, epoch)
    adapter = RemoteRuntimeClient("http://127.0.0.1:8765", TOKEN)
    calls = []

    async def scenario():
        def dispatch(request):
            import json
            body = json.loads(request.content)
            status, response = ledger.execute(CommandRequest(**body))
            calls.append(body)
            if len(calls) == 1:
                raise httpx.ReadError("Simulated lost response", request=request)
            return httpx.Response(status, json=response)
        body = {"request_id": uuid4().hex, "server_id": epoch, "operation": "new_chat", "arguments": {}}
        async with httpx.AsyncClient(transport=httpx.MockTransport(dispatch)) as http:
            await adapter._post(http, body)
        assert len(calls) == 2
        assert calls[0] == calls[1]
        assert len(runtime.list_sessions()) == 1

    try:
        asyncio.run(scenario())
    finally:
        runtime.close()


def test_same_server_replay_does_not_duplicate_messages_and_snapshot_reset_repairs_cursor(tmp_path):
    runtime, agent = make_runtime(tmp_path)
    epoch = uuid4().hex
    adapter = RemoteRuntimeClient("http://127.0.0.1:8765", TOKEN)
    try:
        adapter._ingest(public_frame(runtime, epoch))
        runtime.submit("replay")
        assert runtime.wait_for_idle(2)
        adapter._ingest(public_frame(runtime, epoch, 0))
        snapshot = adapter.snapshot()
        assert snapshot.messages == (("You", "replay"), ("AI", "answer: replay"))
        adapter._ingest(public_frame(runtime, epoch, runtime.snapshot().sequence))
        assert adapter.snapshot().messages == snapshot.messages
        # A server reset replaces, rather than appends, the conversation.
        adapter._ingest(public_frame(runtime, epoch))
        assert adapter.snapshot().messages == snapshot.messages
    finally:
        runtime.close()


def test_rendered_review_is_not_replaced_by_unrendered_network_cache(tmp_path):
    runtime, agent = make_runtime(tmp_path)
    adapter = RemoteRuntimeClient("http://127.0.0.1:8765", TOKEN)
    old_epoch, new_epoch = uuid4().hex, uuid4().hex
    runtime.state.edit_store.propose_create(tmp_path / "review.txt", "reviewed")

    async def scenario():
        # No transport is started: apply frames explicitly to exercise the
        # exact cache-update/key-press race without scheduler timing assumptions.
        app = AgentTextualApp(runtime=adapter)
        app._connect_runtime = lambda: None
        adapter._ingest(public_frame(runtime, old_epoch))
        adapter._set_connected(True)
        async with app.run_test(size=(120, 40)):
            app._enter_pending_select_mode()
            reviewed_revision = app._reviewed_pending_edit.revision
            adapter._ingest(public_frame(runtime, new_epoch))
            assert app._reviewed_pending_edit.revision == reviewed_revision
            assert next(iter(adapter.pending().values())).revision != reviewed_revision
            app._approve_selected_pending()
            assert any(role == "Error" and "Server changed" in text for role, text in app._messages)
            assert adapter._jobs.empty()
            assert not (tmp_path / "review.txt").exists()
    try:
        asyncio.run(scenario())
    finally:
        runtime.close()


def test_unavailable_server_never_blocks_textual_input_or_queues_offline_commands():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        # Keep the port reserved but not listening throughout this test.
        port = listener.getsockname()[1]
        adapter = RemoteRuntimeClient(f"http://127.0.0.1:{port}", TOKEN)

        async def scenario():
            app = AgentTextualApp(runtime=adapter)
            async with app.run_test() as pilot:
                await pilot.press("a", "b", "c")
                assert app.query_one("#input", Input).value == "abc"
                app._start_agent_step("must not queue")
                assert any(role == "Error" and "disconnected" in text for role, text in app._messages)
                assert adapter._jobs.empty()
        asyncio.run(scenario())


@pytest.mark.parametrize("url", ["http://100.64.0.1:8765", "http://example.com", "ftp://localhost",
                                "https://user:pass@example.com", "https://example.com?token=secret",
                                "https://example.com/path", "https://example.com/#fragment"])
def test_unsafe_remote_origins_are_rejected(url):
    with pytest.raises(ValueError):
        validate_server_url(url)


@pytest.mark.parametrize("url", ["http://127.0.0.1:8765", "http://localhost:8765/",
                                "http://[::1]:8765", "https://agent.example.ts.net"])
def test_loopback_or_https_origins_are_allowed(url):
    assert validate_server_url(url) == url.rstrip("/")


def test_remote_composition_does_not_import_or_construct_provider_clients():
    script = (
        "import os,sys; os.environ['AI_AGENT_MODE']='remote'; os.environ['AI_AGENT_TOKEN']='x'*40; "
        "from runtime.textual_loop import create_textual_app; "
        "app=create_textual_app(); "
        "assert type(app.runtime).__name__=='RemoteRuntimeClient'; "
        "assert 'llm.providers' not in sys.modules; "
        "assert 'runtime.bootstrap' not in sys.modules"
    )
    result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, capture_output=True,
                            text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_slow_catalogue_reads_cannot_delay_commands():
    adapter = RemoteRuntimeClient("http://127.0.0.1:8765", TOKEN)
    adapter._server_id = uuid4().hex
    adapter._set_connected(True)

    async def scenario():
        read_started, release_read, command_received = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def dispatch(request):
            if request.method == "GET":
                read_started.set()
                await release_read.wait()
                return httpx.Response(200, json=[])
            command_received.set()
            return httpx.Response(200, json={"result": "accepted", "server_id": adapter._server_id})

        adapter._read("/v1/sessions")
        async with httpx.AsyncClient(transport=httpx.MockTransport(dispatch)) as http:
            reader = asyncio.create_task(adapter._refresh(http))
            sender = asyncio.create_task(adapter._send(http))
            try:
                await asyncio.wait_for(read_started.wait(), 1)
                adapter.submit("must not wait for history")
                await asyncio.wait_for(command_received.wait(), 1)
                assert not release_read.is_set()
            finally:
                release_read.set()
                reader.cancel()
                sender.cancel()
                await asyncio.gather(reader, sender, return_exceptions=True)
    asyncio.run(scenario())


def test_interrupted_acknowledgement_is_visible_and_not_silently_requeued():
    adapter = RemoteRuntimeClient("http://127.0.0.1:8765", TOKEN)
    adapter._server_id = uuid4().hex
    adapter._set_connected(True)

    async def scenario():
        started = asyncio.Event()
        calls = []

        async def dispatch(request):
            calls.append(request)
            started.set()
            await asyncio.Event().wait()

        adapter.submit("uncertain result")
        async with httpx.AsyncClient(transport=httpx.MockTransport(dispatch)) as http:
            sender = asyncio.create_task(adapter._send(http))
            await asyncio.wait_for(started.wait(), 1)
            sender.cancel()
            with suppress(asyncio.CancelledError):
                await sender
        assert len(calls) == 1
        assert adapter._jobs.empty()
        assert any("Outcome unknown" in text for _, text in adapter.snapshot().messages)
    asyncio.run(scenario())


@pytest.mark.parametrize("status,data", [
    (307, {"detail": "redirect"}), (200, []), (200, {"result": "wrong epoch", "server_id": "other"}),
])
def test_redirect_or_malformed_success_is_not_treated_as_acknowledgement(status, data):
    adapter = RemoteRuntimeClient("http://127.0.0.1:8765", TOKEN)
    calls = []

    async def scenario():
        def dispatch(request):
            calls.append(request)
            return httpx.Response(status, json=data, headers={"Location": "https://untrusted.invalid"})
        body = {"request_id": uuid4().hex, "server_id": uuid4().hex,
                "operation": "new_chat", "arguments": {}}
        async with httpx.AsyncClient(transport=httpx.MockTransport(dispatch)) as http:
            await adapter._post(http, body)
        assert len(calls) == 1
        assert any("Outcome unknown" in text for _, text in adapter.snapshot().messages)
    asyncio.run(scenario())


def test_network_drop_reconnects_to_same_run_without_duplicate_messages(tmp_path, monkeypatch):
    import runtime.remote as remote_module
    real_connect = remote_module.connect
    connections = []

    @asynccontextmanager
    async def recording_connect(*args, **kwargs):
        async with real_connect(*args, **kwargs) as connection:
            connections.append(connection)
            yield connection

    monkeypatch.setattr(remote_module, "connect", recording_connect)
    with running_server(tmp_path) as (url, port):
        adapter = RemoteRuntimeClient(url, TOKEN)
        identity = adapter.attach_client()

        async def scenario():
            await eventually(lambda: adapter.connection_status == "connected")
            adapter.submit("propose")
            await eventually(lambda: bool(adapter.pending()))
            epoch = adapter._server_id
            run_id = adapter.snapshot().run.run_id
            closing = asyncio.run_coroutine_threadsafe(connections[0].close(), adapter._loop)
            await asyncio.wrap_future(closing)
            await eventually(lambda: len(connections) >= 2 and adapter.connection_status == "connected")
            assert adapter._server_id == epoch
            assert adapter.snapshot().run.run_id == run_id
            assert adapter.snapshot().processing
            reviewed = next(iter(adapter.pending().values()))
            adapter.decide_pending(reviewed.id, accept=True, revision=reviewed.revision)
            await eventually(lambda: adapter.snapshot().run.status == "completed")
            messages = [e for e in adapter.events_since(0) if e.kind == "message" and e.role == "You"]
            assert [e.text for e in messages] == ["propose"]
            assert sum(role == "You" for role, _ in adapter.snapshot().messages) == 1
        try:
            asyncio.run(scenario())
        finally:
            close_adapter(adapter, identity)
