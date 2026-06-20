"""
tests/core/test_agent_batch.py

Coverage for batched tool-call execution in core/agent.py.
"""

from dataclasses import dataclass

from core.agent import Agent
from tools._base import ToolResult, DisplayItem
from core.tool_registry import ToolRegistry, ToolSpec
from editing.store import EditStore
from llm.base import LLMResponse, NativeToolCall


@dataclass
class FakeModelConfig:
    provider_key: str = "test"
    provider_label: str = "test"
    model: str = "fake-model"
    api_type: str = "chat_completions"


@dataclass
class FakeState:
    cwd: str
    model_config: FakeModelConfig
    edit_store: EditStore


class FakeLLM:
    # Keep fake LLM behavior explicit for tests that rely on JSON-string parsing
    # rather than native tool-calling payloads.
    supports_native_tools = False

    def __init__(self, replies: list[str]):
        self._replies = replies
        self._idx = 0

    def chat(self, messages: list[dict], tools=None, tool_choice=None) -> str:
        if self._idx >= len(self._replies):
            return "done"
        r = self._replies[self._idx]
        self._idx += 1
        return r


class FakeNativeLLM:
    supports_native_tools = True
    supports_native_tool_outputs = False
    api_type = "chat_completions"

    def __init__(self, replies: list[str | LLMResponse]):
        self._replies = replies
        self._idx = 0

    def chat(self, messages: list[dict], tools=None, tool_choice=None) -> str | LLMResponse:
        if self._idx >= len(self._replies):
            return "done"
        r = self._replies[self._idx]
        self._idx += 1
        return r


def _make_agent(replies: list[str], tool_registry: ToolRegistry) -> Agent:
    state = FakeState(cwd=".", model_config=FakeModelConfig(), edit_store=EditStore())
    return Agent(system_prompt="sys", state=state, llm=FakeLLM(replies), tool_registry=tool_registry)


def _make_native_agent(replies: list[str | LLMResponse], tool_registry: ToolRegistry) -> Agent:
    state = FakeState(cwd=".", model_config=FakeModelConfig(api_type="chat_completions"), edit_store=EditStore())
    return Agent(system_prompt="sys", state=state, llm=FakeNativeLLM(replies), tool_registry=tool_registry)


def _register_tool(tool_registry: ToolRegistry, name: str, fn, requires_state: bool = False) -> None:
    tool_registry.register(
        ToolSpec(
            name=name,
            function=fn,
            description="test tool",
            parameters={},
            requires_state=requires_state,
            example=None,
        )
    )


def test_single_tool_call_keeps_legacy_tool_result_shape():
    local_registry = ToolRegistry()

    def t_ok():
        return "ok-single"

    _register_tool(local_registry, "t_ok_single", t_ok)

    agent = _make_agent([
        '{"action": "t_ok_single", "input": {}}',
        'final answer',
    ], tool_registry=local_registry)

    out = agent.step("go")
    assert out == "final answer"

    tool_results = [m for m in agent.messages if m["role"] == "user" and m["content"].startswith("TOOL RESULT")]
    assert any(m["content"].startswith("TOOL RESULT (t_ok_single):") for m in tool_results)
    assert not any(m["content"].startswith("TOOL RESULT (batch):") for m in tool_results)


def test_batch_fail_fast_stops_remaining_and_reports_skipped():
    local_registry = ToolRegistry()

    def t_ok():
        return "ok"

    def t_fail():
        raise RuntimeError("boom")

    def t_never():
        return "should-not-run"

    _register_tool(local_registry, "t_ok_batch", t_ok)
    _register_tool(local_registry, "t_fail_batch", t_fail)
    _register_tool(local_registry, "t_never_batch", t_never)

    agent = _make_agent([
        '{"tool_calls": ['
        '{"action": "t_ok_batch", "input": {}}, '
        '{"action": "t_fail_batch", "input": {}}, '
        '{"action": "t_never_batch", "input": {}}'
        ']}',
        'done',
    ], tool_registry=local_registry)

    out = agent.step("go")
    assert out == "done"

    batch_results = [
        m["content"]
        for m in agent.messages
        if m["role"] == "user" and m["content"].startswith("TOOL RESULT (batch):")
    ]
    assert len(batch_results) == 1
    report = batch_results[0]
    assert "t_ok_batch" in report
    assert "t_fail_batch" in report
    assert "FAILED" in report
    assert "t_never_batch" in report
    assert "SKIPPED" in report


def test_single_tool_failure_keeps_legacy_tool_result_shape():
    local_registry = ToolRegistry()

    def t_fail_single():
        raise RuntimeError("single boom")

    _register_tool(local_registry, "t_fail_single", t_fail_single)

    agent = _make_agent([
        '{"action": "t_fail_single", "input": {}}',
        'done',
    ], tool_registry=local_registry)

    out = agent.step("go")
    assert out == "done"

    tool_results = [
        m["content"]
        for m in agent.messages
        if m["role"] == "user" and m["content"].startswith("TOOL RESULT")
    ]
    assert any(s.startswith("TOOL RESULT (t_fail_single):") for s in tool_results)
    assert not any(s.startswith("TOOL RESULT (batch):") for s in tool_results)
    assert any("Tool execution failed" in s for s in tool_results)


def test_assert_tools_shape_accepts_chat_completions_nested_shape():
    local_registry = ToolRegistry()

    state = FakeState(cwd=".", model_config=FakeModelConfig(api_type="chat_completions"), edit_store=EditStore())
    agent = Agent(system_prompt="sys", state=state, llm=FakeLLM([]), tool_registry=local_registry)

    nested_tools = [
        {
            "type": "function",
            "function": {
                "name": "x",
                "description": "d",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]

    agent._assert_tools_shape("chat_completions", nested_tools)


def test_assert_tools_shape_accepts_responses_flat_shape():
    local_registry = ToolRegistry()

    state = FakeState(cwd=".", model_config=FakeModelConfig(api_type="responses"), edit_store=EditStore())
    agent = Agent(system_prompt="sys", state=state, llm=FakeLLM([]), tool_registry=local_registry)

    flat_tools = [
        {
            "type": "function",
            "name": "x",
            "description": "d",
            "parameters": {"type": "object", "properties": {}},
        }
    ]

    agent._assert_tools_shape("responses", flat_tools)


def test_assert_tools_shape_rejects_wrong_shape_for_chat_completions():
    local_registry = ToolRegistry()

    state = FakeState(cwd=".", model_config=FakeModelConfig(api_type="chat_completions"), edit_store=EditStore())
    agent = Agent(system_prompt="sys", state=state, llm=FakeLLM([]), tool_registry=local_registry)

    flat_tools = [
        {
            "type": "function",
            "name": "x",
            "description": "d",
            "parameters": {"type": "object", "properties": {}},
        }
    ]

    try:
        agent._assert_tools_shape("chat_completions", flat_tools)
        assert False, "Expected ValueError for wrong tool shape"
    except ValueError as e:
        assert "chat_completions" in str(e)


def test_step_returns_error_on_state_llm_api_type_mismatch():
    local_registry = ToolRegistry()

    state = FakeState(cwd=".", model_config=FakeModelConfig(api_type="chat_completions"), edit_store=EditStore())
    agent = Agent(system_prompt="sys", state=state, llm=FakeLLM(["final"]), tool_registry=local_registry)
    agent._api_type = "responses"

    out = agent.step("go")
    assert out.startswith("Error: Configuration mismatch:")

def test_native_tool_call_with_empty_content_is_not_treated_as_empty_response():
    local_registry = ToolRegistry()

    def t_ok_native():
        return "ok-native"

    _register_tool(local_registry, "t_ok_native", t_ok_native)

    native_tool_reply = LLMResponse(
        content=None,
        tool_calls=[NativeToolCall(id="call_1", name="t_ok_native", arguments={})],
    )

    agent = _make_native_agent([
        native_tool_reply,
        "final-native",
    ], tool_registry=local_registry)

    out = agent.step("go")
    assert out == "final-native"

    # Ensure no empty-response retry prompt was injected.
    assert not any(
        m["role"] == "user" and "Your previous response was empty." in m["content"]
        for m in agent.messages
    )


def test_empty_final_response_retries_then_errors():
    local_registry = ToolRegistry()

    agent = _make_agent([
        "",
        "",
        "",
    ], tool_registry=local_registry)

    out = agent.step("go")
    assert out == "Error: Empty response from model."

    empty_retry_prompts = [
        m for m in agent.messages
        if m["role"] == "user" and "Your previous response was empty." in m["content"]
    ]
    assert len(empty_retry_prompts) == 2


def test_batch_report_includes_display_summary_for_toolresult():
    local_registry = ToolRegistry()

    def t_show_like():
        return ToolResult(
            observation="displayed something",
            display_items=[
                DisplayItem(
                    kind="file",
                    title="x",
                    content="y",
                    path="x.py",
                    display_path="x.py",
                    language="python",
                )
            ],
        )

    _register_tool(local_registry, "t_show_like", t_show_like)

    agent = _make_agent([
        '{"tool_calls": ['
        '{"action": "t_show_like", "input": {}}, '
        '{"action": "t_show_like", "input": {}}'
        ']}',
        'done',
    ], tool_registry=local_registry)

    out = agent.step("go")
    assert out == "done"

    batch_results = [
        m["content"]
        for m in agent.messages
        if m["role"] == "user" and m["content"].startswith("TOOL RESULT (batch):")
    ]
    assert len(batch_results) == 1
    report = batch_results[0]
    assert "displayed_calls=2" in report
    assert "displayed_items=2" in report
    assert "showed to user" in report
