"""Offline agent double shared by runtime and Textual integration tests."""
from pathlib import Path
from types import SimpleNamespace

from core.tool_progress import tool_progress_listener
from core.tool_registry import ToolRegistry
from llm.request_progress import request_progress_listener
from runtime.chat_store import ChatStore
from runtime.service import AgentRuntime
from runtime.state import AgentState, ModelConfig


class StubAgent:
    def __init__(self, state, llm):
        self.state = state
        self.llm = llm
        self.registry = ToolRegistry()
        self.messages = [{"role": "system", "content": "fixture system"}]
        self.on_tool = lambda text: None
        self.behavior = lambda text: f"answer: {text}"

    def bind(self, **kwargs):
        self.on_tool = kwargs["on_tool"]
        return self

    def step(self, text):
        with (self.state.privileged_turn.turn("head"),
              tool_progress_listener(self.on_tool),
              request_progress_listener(self.on_tool)):
            self.messages.append({"role": "user", "content": text})
            reply = self.behavior(text)
            self.messages.append({"role": "assistant", "content": reply})
            return reply

    def reset(self, system_prompt):
        self.state.privileged_turn.revoke()
        self.messages = [{"role": "system", "content": system_prompt}]

    def set_llm(self, llm, system_prompt=None):
        if getattr(llm, "reject_configuration", False):
            raise ValueError("fixture configuration rejected")
        self.llm = llm
        if system_prompt is not None:
            self.messages[0] = {"role": "system", "content": system_prompt}


def make_runtime(tmp_path: Path, **options):
    state = AgentState(
        cwd=tmp_path,
        model_config=ModelConfig(
            provider_key="fixture", provider_label="Fixture", model="fixture-model",
            api_key=None, base_url=None, api_type="chat_completions",
        ),
        chat_store=ChatStore(tmp_path / "history"),
    )
    llm = SimpleNamespace(supports_native_tools=False)
    agent = StubAgent(state, llm)
    runtime = AgentRuntime(state=state, llm=llm, agent_factory=agent.bind, **options)
    runtime.initialize()
    return runtime, agent
