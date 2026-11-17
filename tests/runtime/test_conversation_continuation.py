"""Real Responses client logic with an offline provider: chains stay chat-local."""
from collections import defaultdict
from types import SimpleNamespace

from core.agent import Agent
from core.tool_registry import ToolRegistry
from llm.openai_responses import OpenAIResponsesClient
from llm.providers import ProviderConfig
from runtime.chat_store import ChatStore
from runtime.conversations import ConversationManager
from runtime.service import AgentRuntime
from runtime.state import AgentState, ModelConfig


def test_provider_continuations_switch_reload_and_recover_independently(tmp_path):
    calls = defaultdict(list)
    clients = {}
    history = ChatStore(tmp_path / "history")

    def factory(identity, store, source):
        state = AgentState(
            cwd=tmp_path, chat_store=history, chat_session_id=identity,
            model_config=ModelConfig("fixture", "Fixture", "offline-model", "offline-key", None, "responses"),
        )
        llm = OpenAIResponsesClient(ProviderConfig(
            key="fixture", label="Fixture", api_key="offline-key", base_url=None,
            api_type="responses", default_model="offline-model", supports_model_listing=False,
        ))

        def create(**kwargs):
            calls[identity].append(kwargs)
            return SimpleNamespace(id=f"resp_{identity}_{len(calls[identity])}", output=[], output_text="offline reply")

        llm._client.responses.create = create
        clients[identity] = llm
        registry = ToolRegistry()
        return AgentRuntime(
            state=state, llm=llm, persistence_store=store,
            agent_factory=lambda **kwargs: Agent("offline", tool_registry=registry, **kwargs),
        )

    def start_host():
        return ConversationManager(history=history, runtime_factory=factory,
                                   persistence_path=tmp_path / "state.sqlite3")

    def turn(manager, identity, text):
        manager.execute(identity, "submit", {"text": text})
        assert manager.get(identity).wait_for_idle(3)
        assert manager.get(identity).snapshot().run.status == "completed"

    manager = start_host()
    first, second = manager.default_chat_id, manager.new_chat()
    try:
        assert clients[first] is not clients[second]
        turn(manager, first, "first A")
        turn(manager, second, "first B")
        assert not calls[first][0].get("previous_response_id")
        assert not calls[second][0].get("previous_response_id")
        manager.execute(second, "load_chat", {"session_id": first})
        turn(manager, first, "second A")
        assert calls[first][-1]["previous_response_id"] == f"resp_{first}_1"
        before_b = clients[second].export_conversation()
        manager.execute(first, "reload_context", {})
        assert len(calls[first]) == 2  # Reload itself never contacts the provider.
        assert clients[second].export_conversation() == before_b
        turn(manager, first, "fresh A")
        assert not calls[first][-1].get("previous_response_id")
        clean_input = str(calls[first][-1]["input"])
        assert "first A" in clean_input and "second A" in clean_input
        assert "first B" not in clean_input
    finally:
        manager.close()
    restored = start_host()
    try:
        turn(restored, first, "resumed A")
        turn(restored, second, "resumed B")
        assert calls[first][-1]["previous_response_id"] == f"resp_{first}_3"
        assert calls[second][-1]["previous_response_id"] == f"resp_{second}_1"
    finally:
        restored.close()
        for llm in clients.values():
            llm._client.close()
