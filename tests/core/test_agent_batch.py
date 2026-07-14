"""
tests/core/test_agent_batch.py

Coverage for batched tool-call execution in core/agent.py.
"""

import json
from dataclasses import dataclass

from core.agent import Agent
from core.tool_registry import ToolRegistry, ToolSpec
from editing.store import EditStore
from llm.base import LLMResponse, NativeToolCall
from dataclasses import field


@dataclass
class _DummyModelConfig:
    provider_label: str = "OpenAI"
    provider_key: str = "openai"
    model: str = "gpt-4o-mini"
    api_type: str = "chat_completions"


@dataclass
class _DummyState:
    cwd: str = "."
    model_config: _DummyModelConfig = field(default_factory=_DummyModelConfig)


class _FakeLLMNativeOnce:
    """
    First call returns native tool call.
    Second call returns final text.
    """

    supports_native_tools = True
    supports_native_tool_outputs = False
    api_type = "chat_completions"

    def __init__(self, args):
        self._args = args
        self._n = 0

    def chat(self, messages, tools=None, tool_choice=None):
        self._n += 1
        if self._n == 1:
            return LLMResponse(
                content="",
                tool_calls=[
                    NativeToolCall(
                        id="call_1",
                        name="t_capture",
                        arguments=self._args,
                    )
                ],
            )
        return "done"

    def submit_tool_outputs(self, tool_outputs):
        raise NotImplementedError


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


class _FakeLLMResponses:
    supports_native_tools = True
    supports_native_tool_outputs = True
    api_type = "responses"

    def __init__(self):
        self.chat_calls = 0
        self.submit_calls = 0
        self.reset_calls = 0
        self.submitted_tool_outputs = []

    def chat(self, messages, tools=None, tool_choice=None):
        self.chat_calls += 1
        if self.chat_calls == 1:
            return LLMResponse(
                content=None,
                tool_calls=[NativeToolCall(id="call_resp_1", name="t_ok_native", arguments={})],
            )
        return "final-after-submit"

    def submit_tool_outputs(self, tool_outputs):
        self.submit_calls += 1
        self.submitted_tool_outputs.append(list(tool_outputs))
        return "final-after-submit"

    def reset_conversation(self):
        self.reset_calls += 1


class _FakeLLMResponsesOversizedBatch(_FakeLLMResponses):
    def chat(self, messages, tools=None, tool_choice=None):
        self.chat_calls += 1
        return LLMResponse(
            content=None,
            tool_calls=[
                NativeToolCall(id=f"call_resp_{i}", name="t_ok_native", arguments={})
                for i in range(11)
            ],
        )


class _FakeLLMChatNoNative:
    supports_native_tools = False
    supports_native_tool_outputs = False
    api_type = "chat_completions"

    def chat(self, messages, tools=None, tool_choice=None):
        return "done"


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


def _build_registry_capture(captured):
    from core.tool_registry import ToolRegistry, ToolSpec

    reg = ToolRegistry()

    def t_capture(state, **kwargs):
        captured.append(kwargs)
        return "ok"

    reg.register(
        ToolSpec(
            name="t_capture",
            description="capture kwargs",
            function=t_capture,
            parameters={"type": "object", "properties": {}, "required": []},
            requires_state=True,
        )
    )
    return reg


def test_agent_normalizes_native_tool_args_dict():
    captured = []
    reg = _build_registry_capture(captured)
    llm = _FakeLLMNativeOnce({"path": "x.py", "edits": [{"find": "a", "replace": "b"}]})

    agent = Agent(
        system_prompt="test",
        state=_DummyState(),
        llm=llm,
        tool_registry=reg,
    )

    out = agent.step("go")
    assert out == "done"
    assert len(captured) == 1
    assert captured[0]["path"] == "x.py"
    assert captured[0]["edits"] == [{"find": "a", "replace": "b"}]


def test_agent_normalizes_native_tool_args_json_string():
    captured = []
    reg = _build_registry_capture(captured)
    llm = _FakeLLMNativeOnce(json.dumps({"path": "x.py", "edits": [{"find": "a", "replace": "b"}]}))

    agent = Agent(
        system_prompt="test",
        state=_DummyState(),
        llm=llm,
        tool_registry=reg,
    )

    out = agent.step("go")
    assert out == "done"
    assert len(captured) == 1
    assert captured[0]["path"] == "x.py"
    assert captured[0]["edits"] == [{"find": "a", "replace": "b"}]


def test_agent_normalizes_native_tool_args_none_to_empty_dict():
    captured = []
    reg = _build_registry_capture(captured)
    llm = _FakeLLMNativeOnce(None)

    agent = Agent(
        system_prompt="test",
        state=_DummyState(),
        llm=llm,
        tool_registry=reg,
    )

    out = agent.step("go")
    assert out == "done"
    assert len(captured) == 1
    assert captured[0] == {}


def test_agent_rejects_native_tool_args_non_object_json():
    captured = []
    reg = _build_registry_capture(captured)
    llm = _FakeLLMNativeOnce("[1,2,3]")

    agent = Agent(
        system_prompt="test",
        state=_DummyState(),
        llm=llm,
        tool_registry=reg,
    )

    import pytest

    with pytest.raises(TypeError, match="must be a JSON object"):
        agent.step("go")

    assert captured == []


def test_set_llm_refreshes_runtime_caches_and_api_type():
    reg = ToolRegistry()

    def t_ok_native():
        return "ok"

    _register_tool(reg, "t_ok_native", t_ok_native)

    state = _DummyState()
    llm_initial = _FakeLLMChatNoNative()
    agent = Agent(system_prompt="test", state=state, llm=llm_initial, tool_registry=reg)

    assert agent._use_native_tools is False
    assert agent._api_type == "chat_completions"

    # Simulate model/provider switch to responses native-tool client
    state.model_config.api_type = "responses"
    llm_next = _FakeLLMResponses()
    agent.set_llm(llm_next)

    assert agent._use_native_tools is True
    assert agent._api_type == "responses"
    assert "responses" in agent._tools_by_api_type
    assert "chat_completions" in agent._tools_by_api_type


def test_pending_native_tool_outputs_persist_across_steps():
    reg = ToolRegistry()

    def t_ok_native():
        return "ok-native"

    _register_tool(reg, "t_ok_native", t_ok_native)

    state = _DummyState()
    state.model_config.api_type = "responses"
    llm = _FakeLLMResponses()
    agent = Agent(system_prompt="test", state=state, llm=llm, tool_registry=reg)

    # First step should execute tool call and finalize via submit_tool_outputs.
    out1 = agent.step("go")
    assert out1 == "final-after-submit"
    assert llm.submit_calls == 1
    assert agent._pending_native_tool_calls is None

    # Manually seed pending calls and ensure next step resumes via submit path.
    call = NativeToolCall(id="call_resp_1", name="t_ok_native", arguments={})
    from core.agent import BatchToolRecord
    rec = BatchToolRecord(
        index=1,
        total=1,
        action="t_ok_native",
        tool_input={},
        status="success",
        observation="ok-native",
    )
    agent._pending_native_tool_calls = [(rec, call)]

    out2 = agent.step("continue")
    assert out2 == "final-after-submit"
    assert llm.submit_calls == 2
    assert agent._pending_native_tool_calls is None


def test_oversized_native_responses_batch_executes_limit_and_reports_excess_calls():
    reg = ToolRegistry()
    executed = 0

    def t_ok_native():
        nonlocal executed
        executed += 1
        return "ok-native"

    _register_tool(reg, "t_ok_native", t_ok_native)

    state = _DummyState()
    state.model_config.api_type = "responses"
    llm = _FakeLLMResponsesOversizedBatch()
    agent = Agent(system_prompt="test", state=state, llm=llm, tool_registry=reg)

    out = agent.step("go")

    assert out == "final-after-submit"
    assert executed == 10
    assert llm.submit_calls == 1
    assert len(llm.submitted_tool_outputs) == 1
    submitted = llm.submitted_tool_outputs[0]
    assert [item.call_id for item in submitted] == [f"call_resp_{i}" for i in range(11)]
    assert [item.output for item in submitted[:10]] == ["ok-native"] * 10
    assert "batch limit exceeded" in submitted[10].output
    assert "do not assume it ran" in submitted[10].output
    assert agent._pending_native_tool_calls is None


def test_native_responses_tool_outputs_use_structured_continuation_without_text_memory_pollution():
    reg = ToolRegistry()

    def t_ok_native():
        return "ok-native"

    _register_tool(reg, "t_ok_native", t_ok_native)

    state = _DummyState()
    state.model_config.api_type = "responses"
    llm = _FakeLLMResponses()
    agent = Agent(system_prompt="test", state=state, llm=llm, tool_registry=reg)

    out = agent.step("go")

    assert out == "final-after-submit"
    assert llm.submit_calls == 1
    assert len(llm.submitted_tool_outputs) == 1
    submitted = llm.submitted_tool_outputs[0]
    assert len(submitted) == 1
    assert submitted[0].call_id == "call_resp_1"
    assert submitted[0].output == "ok-native"

    contents = [m["content"] for m in agent.messages]
    assert "go" in contents
    assert "final-after-submit" in contents
    assert not any("NATIVE TOOL CALL REQUEST:" in c for c in contents)
    assert not any("TOOL RESULT" in c for c in contents)


def test_set_llm_can_refresh_system_prompt():
    reg = ToolRegistry()
    state = _DummyState()
    agent = Agent(system_prompt="old prompt", state=state, llm=_FakeLLMChatNoNative(), tool_registry=reg)

    state.model_config.api_type = "responses"
    agent.set_llm(_FakeLLMResponses(), system_prompt="new prompt")

    assert agent.messages[0] == {"role": "system", "content": "new prompt"}
    assert agent._api_type == "responses"


def test_reset_clears_pending_native_calls_and_resets_llm_conversation():
    reg = ToolRegistry()
    state = _DummyState()
    state.model_config.api_type = "responses"
    llm = _FakeLLMResponses()
    agent = Agent(system_prompt="old", state=state, llm=llm, tool_registry=reg)
    agent._pending_native_tool_calls = [(object(), object())]

    agent.reset("new")

    assert agent.messages == [{"role": "system", "content": "new"}]
    assert agent._pending_native_tool_calls is None
    assert llm.reset_calls == 1
