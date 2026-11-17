"""Offline, independently constructed agents for multi-chat tests."""
from dataclasses import replace
from types import SimpleNamespace

from runtime.chat_store import ChatStore
from runtime.conversations import ConversationManager
from runtime.service import AgentRuntime
from runtime.state import AgentState, ModelConfig, ModelSettings
from tests.runtime_helpers import StubAgent


def make_manager(root, *, durable=False, max_parallel_runs=4):
    history = ChatStore(root / "history")
    agents = {}

    def factory(identity, store, source):
        state = AgentState(
            cwd=source.cwd if source else root,
            model_config=replace(source.model_config) if source else ModelConfig(
                provider_key="fixture", provider_label="Fixture", model="fixture-model",
                api_key=None, base_url=None, api_type="chat_completions",
            ),
            model_settings=replace(source.model_settings) if source else ModelSettings(),
            chat_store=history, chat_session_id=identity,
        )
        llm = SimpleNamespace(supports_native_tools=False)
        agent = StubAgent(state, llm)
        agents[identity] = agent
        return AgentRuntime(state=state, llm=llm, agent_factory=agent.bind, persistence_store=store)

    manager = ConversationManager(
        history=history, runtime_factory=factory, max_parallel_runs=max_parallel_runs,
        persistence_path=root / "state.sqlite3" if durable else None,
    )
    return manager, agents
