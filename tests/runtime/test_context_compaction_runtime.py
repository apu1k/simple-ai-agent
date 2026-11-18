"""Runtime integration of Layer 0 context compaction, entirely offline."""
from types import SimpleNamespace

import pytest

from core.agent import Agent
from core.context_compaction import MASK_MARKER, CompactionSettings
from core.tool_registry import ToolRegistry
from runtime.service import AgentRuntime
from tests.runtime_helpers import make_runtime

BIG = "x" * 4_000


@pytest.fixture
def compaction_runtime(tmp_path):
    fixture, _ = make_runtime(tmp_path)
    state = fixture.state
    fixture.close()
    llm = SimpleNamespace(
        supports_native_tools=False, last_usage=None,
        chat=lambda messages, tools=None, tool_choice=None: "done",
    )
    runtime = AgentRuntime(
        state=state, llm=llm,
        agent_factory=lambda **kwargs: Agent("fixture system", tool_registry=ToolRegistry(), **kwargs),
    )
    runtime.initialize()
    try:
        yield runtime, runtime._agent
    finally:
        runtime.close()


def seed_tool_turns(agent, count):
    for index in range(count):
        agent.messages.extend([
            {"role": "user", "content": f"q{index}"},
            {"role": "user", "content": f"TOOL RESULT (read_file): {BIG}"},
            {"role": "assistant", "content": f"a{index}"},
        ])


def test_manual_compaction_masks_old_output_reports_and_captures_context(compaction_runtime):
    runtime, agent = compaction_runtime
    agent.compaction_settings = None  # manual compaction ignores the automatic switch
    seed_tool_turns(agent, 4)
    cursor = runtime.snapshot().sequence

    runtime.compact_context()

    # Config defaults keep the last 3 turns; only q0's result is elided.
    tool_results = [m["content"] for m in agent.messages if m["content"].startswith("TOOL RESULT")]
    assert [MASK_MARKER in content for content in tool_results] == [True, False, False, False]
    role, text = runtime.snapshot().messages[-1]
    assert role == "System"
    assert text.startswith("Context compaction: elided 1 old tool result(s)")
    assert runtime._context["messages"] == agent.messages[1:]
    kinds = [event.kind for event in runtime.events_since(cursor)]
    assert "tool" in kinds and "message" in kinds


def test_manual_compaction_without_old_output_reports_nothing_to_elide(compaction_runtime):
    runtime, agent = compaction_runtime
    seed_tool_turns(agent, 2)
    before = [dict(m) for m in agent.messages]

    runtime.compact_context()

    assert agent.messages == before
    role, text = runtime.snapshot().messages[-1]
    assert role == "System" and text.startswith("Context compaction: nothing to elide")


def test_automatic_compaction_during_a_run_is_shown_as_system_message(compaction_runtime):
    runtime, agent = compaction_runtime
    agent.compaction_settings = CompactionSettings(
        trigger_tokens=1_000, keep_recent_turns=1, min_result_chars=1_000, min_savings_tokens=500,
    )
    seed_tool_turns(agent, 2)

    runtime.submit("next")
    assert runtime.wait_for_idle(5)

    messages = runtime.snapshot().messages
    assert ("You", "next") in messages and ("AI", "done") in messages
    assert any(role == "System" and text.startswith("Context compaction: elided 1 old tool result(s)")
               for role, text in messages)
    assert MASK_MARKER in agent.messages[2]["content"]
    assert MASK_MARKER not in agent.messages[5]["content"]
