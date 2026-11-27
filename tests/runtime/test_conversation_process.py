"""Real network clients and process-death recovery on newly owned offline hosts."""
import asyncio
from uuid import uuid4

from runtime.chat_store import ChatStore
from runtime.remote import RemoteRuntimeClient
from tests.runtime.recovery_fixture import TOKEN
from tests.runtime.test_recovery_process import process_host, until
from tests.runtime.test_remote import close_adapter, eventually

MODULE = "tests.runtime.multi_fixture"


def snapshot(client, identity=None):
    response = client.get("/v1/snapshot", params={"session_id": identity} if identity else {})
    response.raise_for_status()
    return response.json()


def command(client, identity, operation, arguments=None):
    response = client.post("/v1/commands", json={
        "request_id": uuid4().hex, "server_id": snapshot(client)["server_id"],
        "session_id": identity, "operation": operation, "arguments": arguments or {},
    })
    response.raise_for_status()
    return response.json()["result"]


def test_real_two_clients_select_independently_and_switch_without_stopping_runs(tmp_path):
    with process_host(tmp_path, module=MODULE) as http:
        first_chat = snapshot(http)["session_id"]
        first = RemoteRuntimeClient(str(http.base_url).rstrip("/"), TOKEN)
        second = RemoteRuntimeClient(str(http.base_url).rstrip("/"), TOKEN)
        first_id, second_id = first.attach_client(), second.attach_client()

        async def scenario():
            await eventually(lambda: first.connection_status == second.connection_status == "connected")
            second_chat = await asyncio.to_thread(command, http, first_chat, "new_chat")
            second.load_chat(second_chat)
            await eventually(lambda: second._selection_ready and second.state.chat_session_id == second_chat)
            assert first.state.chat_session_id == first_chat
            first.submit("hold")
            second.submit("hold")
            await eventually(lambda: first.snapshot().processing and second.snapshot().processing)
            await eventually(lambda: (tmp_path / f"started-{first_chat}").exists()
                             and (tmp_path / f"started-{second_chat}").exists())
            first.load_chat(second_chat)
            await eventually(lambda: first._selection_ready and first.state.chat_session_id == second_chat)
            assert first.snapshot().run.run_id == second.snapshot().run.run_id
            assert first.snapshot().processing
            assert second.state.chat_session_id == second_chat
            assert snapshot(http, first_chat)["snapshot"]["run"]["status"] == "running"
            first.new_chat()
            await eventually(lambda: first._selection_ready and first.state.chat_session_id not in {first_chat, second_chat})
            first.submit("independent third chat")
            await eventually(lambda: first.snapshot().run is not None and first.snapshot().run.status == "completed")
            assert second.snapshot().processing
            assert first.session_activity(first_chat)["running"]

        try:
            asyncio.run(scenario())
        finally:
            close_adapter(first, first_id)
            close_adapter(second, second_id)


def test_new_textual_instance_resumes_recent_chat_without_manual_setup(tmp_path):
    history = ChatStore(tmp_path / "history")
    older = history.new_session()
    recent = history.new_session()
    history.append_turn(session_id=recent, user_text="prior work", assistant_text="saved reply")

    def connect(http):
        adapter = RemoteRuntimeClient(str(http.base_url).rstrip("/"), TOKEN)
        return adapter, adapter.attach_client()

    async def expect_resume(http, expected):
        adapter, client_id = connect(http)
        try:
            await eventually(lambda: adapter.connection_status == "connected")
            assert adapter.state.chat_session_id == expected
        finally:
            close_adapter(adapter, client_id)

    async def use_chats(http):
        first, first_id = connect(http)
        second, second_id = connect(http)
        try:
            await eventually(lambda: first.connection_status == second.connection_status == "connected")
            assert first.state.chat_session_id == second.state.chat_session_id == recent
            assert ("AI", "saved reply") in first.snapshot().messages
            first.load_chat(older)
            await eventually(lambda: first._selection_ready and first.state.chat_session_id == older)
            await expect_resume(http, older)  # Opening alone counts; no message required.
            assert second.state.chat_session_id == recent
            second.submit("more work in an already-open chat")
            await eventually(lambda: second.snapshot().run is not None
                             and second.snapshot().run.status == "completed")
            await expect_resume(http, recent)
            first.new_chat()
            await eventually(lambda: first._selection_ready and first.state.chat_session_id != older)
            newest = first.state.chat_session_id
            assert newest not in {recent, None}
            await expect_resume(http, newest)
            return newest
        finally:
            close_adapter(first, first_id)
            close_adapter(second, second_id)

    with process_host(tmp_path, module=MODULE) as http:
        assert snapshot(http)["session_id"] not in {older, recent}
        newest = asyncio.run(use_chats(http))
    with process_host(tmp_path, module=MODULE) as http:
        asyncio.run(expect_resume(http, newest))


def test_completed_and_interrupted_chats_recover_separately_without_repeating_effects(tmp_path):
    with process_host(tmp_path, module=MODULE) as http:
        first = snapshot(http)["session_id"]
        second = command(http, first, "new_chat")
        command(http, first, "submit", {"text": "propose"})
        until(lambda: snapshot(http, first)["snapshot"]["run"]["status"] == "completed")
        command(http, second, "submit", {"text": "hold"})
        until(lambda: (tmp_path / f"started-{second}").exists())
        before = {identity: snapshot(http, identity) for identity in (first, second)}
        calls = {identity: (tmp_path / f"calls-{identity}.txt").read_text(encoding="utf-8") for identity in before}
    with process_host(tmp_path, module=MODULE) as http:
        restored = {identity: snapshot(http, identity) for identity in (first, second)}
        assert restored[first]["snapshot"]["run"]["status"] == "completed"
        assert restored[second]["snapshot"]["run"]["status"] == "interrupted"
        assert "Nothing was automatically retried" in restored[second]["snapshot"]["run"]["error"]
        assert (tmp_path / f"effects-{second}.txt").read_text(encoding="utf-8") == "one scratch effect\n"
        for identity in (first, second):
            assert restored[identity]["pending"] == before[identity]["pending"]
            assert (tmp_path / f"calls-{identity}.txt").read_text(encoding="utf-8") == calls[identity]
            assert restored[identity]["session_id"] == identity
        proposal = restored[first]["pending"][0]
        command(http, first, "decide_pending", {"identity": proposal["id"], "accept": True,
                                               "revision": proposal["revision"]})
        assert (tmp_path / f"approved-{first}.txt").read_text(encoding="utf-8") == first
        assert not (tmp_path / f"approved-{second}.txt").exists()
        assert snapshot(http, second)["pending"]
