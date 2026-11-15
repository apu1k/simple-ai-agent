"""Clean transcript replay and fresh provider continuation, entirely offline."""
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core.agent import Agent
from core.tool_registry import ToolRegistry
from llm.base import NativeToolOutput
from llm.openai_responses import OpenAIResponsesClient
from llm.providers import ProviderConfig
from runtime.service import AgentRuntime
from tests.runtime_helpers import make_runtime


@pytest.fixture
def real_runtime(tmp_path):
    fixture, _ = make_runtime(tmp_path)
    state = fixture.state
    fixture.close()
    llm = SimpleNamespace(supports_native_tools=False, reset_conversation=Mock())
    runtime = AgentRuntime(
        state=state, llm=llm,
        agent_factory=lambda **kwargs: Agent("fixture system", tool_registry=ToolRegistry(), **kwargs),
    )
    runtime.initialize()
    try:
        yield runtime, runtime._agent, llm
    finally:
        runtime.close()


def seed_turns(runtime, count):
    session = runtime.state.chat_store.new_session(runtime.state)
    runtime.state.chat_session_id = session
    for index in range(1, count + 1):
        runtime.state.chat_store.append_turn(
            session_id=session, user_text=f"u{index}", assistant_text=f"a{index}",
            state=runtime.state,
        )
    return session


@pytest.mark.parametrize("turn_count", [0, 3, 40])
def test_reload_rebuilds_only_saved_final_turns_and_preserves_local_state(real_runtime, tmp_path, turn_count):
    runtime, agent, llm = real_runtime
    session = seed_turns(runtime, turn_count)
    history = runtime.state.chat_store.load_original_turns(session, limit=0)
    config = runtime.state.model_config
    runtime.set_model_setting("include_diff", "model")
    runtime.set_model_setting("openai_reasoning_effort", "high")
    approver = runtime.attach_client(can_approve=True)
    runtime.set_model_setting("elevated_commands", True, client_id=approver)
    proposal, _ = runtime.state.edit_store.propose_create(tmp_path / "pending.txt", "pending")
    agent.messages.extend([
        {"role": "assistant", "content": "", "tool_calls": [{"id": "old-call"}]},
        {"role": "tool", "tool_call_id": "old-call", "content": "old tool output"},
        {"role": "user", "content": "unsaved interrupted input"},
    ])
    agent._pending_native_tool_calls = ["old-call"]
    runtime._message("System", "old progress")
    cursor = runtime.snapshot().sequence

    runtime.reload_context()

    expected = [
        {"role": role, "content": text}
        for index in range(max(1, turn_count - 31), turn_count + 1)
        for role, text in (("user", f"u{index}"), ("assistant", f"a{index}"))
    ]
    assert agent.messages[0]["role"] == "system"
    assert agent.messages[1:] == expected
    assert agent._pending_native_tool_calls is None
    llm.reset_conversation.assert_called_once_with()
    assert runtime.state.chat_session_id == session
    assert runtime.state.model_config is config
    assert runtime.state.cwd == tmp_path
    assert runtime.state.model_settings.include_diff == "model"
    assert runtime.state.model_settings.openai_reasoning_effort == "high"
    assert runtime.state.privileged_turn.status == "disabled"
    assert list(runtime.pending()) == [proposal.id]
    assert not (tmp_path / "pending.txt").exists()
    assert runtime.state.chat_store.load_original_turns(session, limit=0) == history
    assert len(runtime.list_sessions()) == 1
    snapshot = runtime.snapshot()
    assert snapshot.run is None and snapshot.progress == ""
    assert snapshot.messages[:-1] == tuple(
        ("You" if message["role"] == "user" else "AI", message["content"])
        for message in expected
    )
    assert snapshot.messages[-1][0] == "System"
    assert f"{min(32, turn_count)} saved turns" in snapshot.messages[-1][1]
    events = runtime.events_since(cursor)
    assert [event.kind for event in events] == ["conversation_changed", "message"]
    assert events[0].messages == snapshot.messages[:-1]


def test_reload_without_active_chat_is_rejected_without_erasing_context(real_runtime):
    runtime, agent, llm = real_runtime
    before = list(agent.messages)
    snapshot = runtime.snapshot()
    with pytest.raises(ValueError, match="No active chat session"):
        runtime.reload_context()
    assert agent.messages == before
    assert runtime.snapshot() == snapshot
    llm.reset_conversation.assert_not_called()
    assert runtime.list_sessions() == []


def test_reload_history_read_failure_does_not_erase_live_context(real_runtime, monkeypatch):
    runtime, agent, llm = real_runtime
    seed_turns(runtime, 1)
    agent.messages.append({"role": "user", "content": "live context"})
    before = list(agent.messages)
    snapshot = runtime.snapshot()
    monkeypatch.setattr(runtime.state.chat_store, "load_original_turns", Mock(side_effect=OSError("offline disk error")))
    with pytest.raises(OSError, match="offline disk error"):
        runtime.reload_context()
    assert agent.messages == before
    assert runtime.snapshot() == snapshot
    llm.reset_conversation.assert_not_called()


def test_reload_responses_starts_fresh_chain_then_continues_only_the_new_chain(tmp_path):
    fixture, _ = make_runtime(tmp_path)
    state = fixture.state
    fixture.close()
    state.model_config = replace(state.model_config, api_type="responses", model="offline-model")
    llm = OpenAIResponsesClient(ProviderConfig(
        key="fixture", label="Fixture", api_key="offline-test-key", base_url=None,
        api_type="responses", default_model="offline-model", supports_model_listing=False,
    ))
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(id=f"resp_{len(calls)}", output=[], output_text="offline answer")

    llm._client = SimpleNamespace(responses=SimpleNamespace(create=create))
    runtime = AgentRuntime(
        state=state, llm=llm,
        agent_factory=lambda **kwargs: Agent("fixture system", tool_registry=ToolRegistry(), **kwargs),
    )
    runtime.initialize()
    session = seed_turns(runtime, 40)
    try:
        llm.chat([{"role": "user", "content": "old provider conversation"}], tools=[], tool_choice="auto")
        llm.submit_tool_outputs([NativeToolOutput(call_id="old-call", output="old tool output")])
        assert llm._last_response_id == "resp_2"
        old_calls = list(calls)

        runtime.reload_context()

        assert calls == old_calls  # Reload itself is local and sends no paid request.
        assert llm._last_response_id is None
        assert llm._last_tools is None and llm._last_tool_choice is None
        runtime.submit("after reload")
        assert runtime.wait_for_idle(2)
        assert runtime.snapshot().run.status == "completed"
        assert runtime.snapshot().run.reply == "offline answer"
        request = calls[2]
        assert "previous_response_id" not in request
        assert "prompt_cache_key" not in request
        assert request["input"] == [
            {"role": role, "content": text}
            for index in range(9, 41)
            for role, text in (("user", f"u{index}"), ("assistant", f"a{index}"))
        ] + [{"role": "user", "content": "after reload"}]
        runtime.submit("continue new chain")
        assert runtime.wait_for_idle(2)
        assert runtime.snapshot().run.status == "completed"
        assert runtime.snapshot().run.reply == "offline answer"
        assert calls[3]["previous_response_id"] == "resp_3"
        assert calls[3]["input"] == [{"role": "user", "content": "continue new chain"}]
        assert calls[:2] == old_calls
        assert state.chat_session_id == session
        assert len(runtime.list_sessions()) == 1
        assert len(state.chat_store.load_original_turns(session, limit=0)) == 42
    finally:
        runtime.close()
