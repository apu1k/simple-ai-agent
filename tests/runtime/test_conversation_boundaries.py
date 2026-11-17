"""Activation failure and late-navigation boundaries; all agents are offline."""
import asyncio
from uuid import uuid4

import httpx
import pytest

from tests.runtime.conversation_helpers import make_manager
from tests.runtime.test_conversation_server import EPOCH, connect_adapter, frame


@pytest.mark.parametrize("phase", ["agent_factory", "history_import"])
def test_failed_activation_does_not_save_an_empty_checkpoint_or_hide_history(tmp_path, phase):
    manager, agents = make_manager(tmp_path, durable=True)
    identity = manager.history.new_session()
    manager.history.append_turn(session_id=identity, user_text="keep question", assistant_text="keep answer")
    original = manager._factory

    def failing_factory(chat_id, store, source):
        runtime = original(chat_id, store, source)
        if phase == "agent_factory":
            def unavailable(**kwargs):
                raise RuntimeError("offline activation failure")
            runtime._agent_factory = unavailable
        else:
            def unavailable_import(session_id):
                runtime.initialize()
                runtime._message("System", "partial import must not become a checkpoint")
                raise RuntimeError("offline activation failure")
            runtime.load_chat = unavailable_import
        return runtime

    try:
        manager._factory = failing_factory
        with pytest.raises(RuntimeError, match="offline activation failure"):
            manager.get(identity)
        assert identity not in manager.activity()
        assert manager.storage.scope(identity).load() is None
        assert manager.history.load_original_turns(identity)[0]["user"] == "keep question"
        manager._factory = original
        runtime = manager.get(identity)
        assert agents[identity].messages[1:] == [
            {"role": "user", "content": "keep question"},
            {"role": "assistant", "content": "keep answer"},
        ]
        assert ("You", "keep question") in runtime.snapshot().messages
        assert not any("partial import" in text for _, text in runtime.snapshot().messages)
    finally:
        manager.close()
    restored, restored_agents = make_manager(tmp_path, durable=True)
    try:
        assert restored_agents[identity].messages[1:][0]["content"] == "keep question"
    finally:
        restored.close()


@pytest.mark.parametrize("superseded_by", ["reselect_current_chat", "new_server_epoch"])
def test_late_new_chat_acknowledgement_cannot_override_newer_navigation_context(tmp_path, superseded_by):
    manager, _ = make_manager(tmp_path)
    identity = manager.default_chat_id
    adapter = connect_adapter(manager)

    async def scenario():
        adapter.new_chat()
        body = adapter._jobs.get_nowait()["body"]
        if superseded_by == "reselect_current_chat":
            adapter.load_chat(identity)
        else:
            replacement = frame(manager, identity)
            replacement["server_id"] = uuid4().hex
            adapter._ingest(replacement)
        created = manager.new_chat(source_id=identity)

        def acknowledge(request):
            return httpx.Response(200, json={"server_id": EPOCH, "session_id": identity, "result": created})

        async with httpx.AsyncClient(transport=httpx.MockTransport(acknowledge)) as client:
            await adapter._post(client, body)
        assert adapter.state.chat_session_id == identity
        assert adapter._selection_ready
        assert len(manager.list_sessions()) == 2

    try:
        asyncio.run(scenario())
    finally:
        manager.close()
