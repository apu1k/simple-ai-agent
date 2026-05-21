"""
tests/core/test_agent_batch.py

Coverage for batched tool-call execution in core/agent.py.
"""

from dataclasses import dataclass

from core.agent import Agent
from tools._base import ToolResult, DisplayItem
from core.tool_registry import ToolRegistry, ToolSpec
from editing.store import EditStore


@dataclass
class FakeModelConfig:
    provider_label: str = "test"
    model: str = "fake-model"


@dataclass
class FakeState:
    cwd: str
    model_config: FakeModelConfig
    edit_store: EditStore


class FakeLLM:
    def __init__(self, replies: list[str]):
        self._replies = replies
        self._idx = 0

    def chat(self, messages: list[dict]) -> str:
        if self._idx >= len(self._replies):
            return "done"
        r = self._replies[self._idx]
        self._idx += 1
        return r


def _make_agent(replies: list[str], tool_registry: ToolRegistry) -> Agent:
    state = FakeState(cwd=".", model_config=FakeModelConfig(), edit_store=EditStore())
    return Agent(system_prompt="sys", state=state, llm=FakeLLM(replies), tool_registry=tool_registry)


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
