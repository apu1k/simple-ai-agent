"""
tests/core/test_context_compaction.py

Coverage for Layer 0 context compaction (core/context_compaction.py) and its
between-turn hook in core/agent.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace

from core.agent import Agent
from core.context_compaction import (
    CONTEXT_COMPACTION_PREFIX,
    MASK_MARKER,
    CompactionSettings,
    estimate_tokens,
    find_cut_index,
    is_user_input,
    mask_tool_results,
    plan_compaction,
    usage_input_tokens,
)
from core.tool_registry import ToolRegistry

BIG = "x" * 4_000  # ~1,000 estimated tokens

SETTINGS = CompactionSettings(
    trigger_tokens=2_000,
    keep_recent_turns=1,
    min_result_chars=1_000,
    min_savings_tokens=500,
)


def _turn(text: str, tool: str = "read_file", body: str = BIG) -> list[dict]:
    return [
        {"role": "user", "content": text},
        {"role": "assistant", "content": f"NATIVE TOOL CALL REQUEST:\n- name={tool}"},
        {"role": "user", "content": f"TOOL RESULT ({tool}): {body}"},
        {"role": "assistant", "content": f"answer to {text}"},
    ]


def _history() -> list[dict]:
    return [
        {"role": "system", "content": "sys"},
        *_turn("first"),
        *_turn("second", tool="batch"),
        *_turn("third"),
    ]


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_is_user_input_ignores_runtime_injected_messages():
    assert is_user_input({"role": "user", "content": "hello"})
    assert not is_user_input({"role": "user", "content": "TOOL RESULT (ls): ..."})
    assert not is_user_input({"role": "user", "content": "IMPORTANT: You are on step 31 out of 32."})
    assert not is_user_input({"role": "user", "content": "Your previous response was empty."})
    assert not is_user_input({"role": "user", "content": "RECOVERY NOTICE (evidence only)"})
    assert not is_user_input({"role": "assistant", "content": "hello"})
    assert not is_user_input({"role": "user", "content": [{"type": "text", "text": "x"}]})


def test_find_cut_index_keeps_recent_user_turns():
    messages = _history()
    assert find_cut_index(messages, 1) == 9  # start of "third"
    assert find_cut_index(messages, 2) == 5  # start of "second"
    assert find_cut_index(messages, 3) == 1
    assert find_cut_index(messages, 4) == 0  # not enough turns: compact nothing
    assert find_cut_index(messages, 0) == len(messages)


def test_mask_tool_results_masks_only_old_large_results_and_keeps_structure():
    messages = _history()
    original = [dict(m) for m in messages]
    result = mask_tool_results(messages, end=9, min_result_chars=1_000)

    assert messages == original  # input untouched
    assert result.masked_count == 2
    assert len(result.messages) == len(messages)
    assert [m["role"] for m in result.messages] == [m["role"] for m in messages]

    first, second, third = (result.messages[i]["content"] for i in (3, 7, 11))
    assert first.startswith("TOOL RESULT (read_file): " + MASK_MARKER)
    assert second.startswith("TOOL RESULT (batch): " + MASK_MARKER)
    assert "4,0" in first  # original size is reported
    assert third == messages[11]["content"]  # recent turn untouched
    assert result.saved_chars > 7_000


def test_mask_tool_results_skips_small_results_and_is_idempotent():
    messages = [
        {"role": "user", "content": "q"},
        {"role": "user", "content": "TOOL RESULT (pwd): C:\\data"},
        {"role": "user", "content": f"TOOL RESULT (read_file): {BIG}"},
    ]
    once = mask_tool_results(messages, end=3, min_result_chars=1_000)
    assert once.masked_count == 1
    assert once.messages[1] is messages[1]

    twice = mask_tool_results(once.messages, end=3, min_result_chars=50)
    assert twice.masked_count == 0
    assert twice.messages == once.messages


def test_mask_tool_results_handles_chat_completions_tool_messages():
    tool_calls = [{"id": "call_1", "type": "function",
                   "function": {"name": "read_file", "arguments": "{}"}}]
    messages = [
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": None, "tool_calls": tool_calls},
        {"role": "tool", "tool_call_id": "call_1", "name": "read_file", "content": BIG},
    ]
    result = mask_tool_results(messages, end=3, min_result_chars=1_000)

    masked = result.messages[2]
    assert masked["content"].startswith(MASK_MARKER)
    assert masked["tool_call_id"] == "call_1" and masked["name"] == "read_file"
    assert result.messages[1] == messages[1]


def test_plan_compaction_respects_trigger_and_min_savings():
    messages = _history()
    assert estimate_tokens(messages) > SETTINGS.trigger_tokens

    planned = plan_compaction(messages, SETTINGS)
    assert planned is not None and planned.masked_count == 2

    high_trigger = CompactionSettings(trigger_tokens=10_000, keep_recent_turns=1,
                                      min_result_chars=1_000, min_savings_tokens=500)
    assert plan_compaction(messages, high_trigger) is None
    # Provider-reported size (includes tool schemas) can trigger compaction too.
    assert plan_compaction(messages, high_trigger, reported_tokens=50_000) is not None

    greedy = CompactionSettings(trigger_tokens=2_000, keep_recent_turns=1,
                                min_result_chars=1_000, min_savings_tokens=50_000)
    assert plan_compaction(messages, greedy) is None


def test_plan_compaction_force_ignores_trigger_and_min_savings_but_keeps_recent_turns():
    messages = _history()
    strict = CompactionSettings(trigger_tokens=10_000_000, keep_recent_turns=1,
                                min_result_chars=1_000, min_savings_tokens=10_000_000)
    assert plan_compaction(messages, strict) is None

    forced = plan_compaction(messages, strict, force=True)
    assert forced is not None and forced.masked_count == 2
    assert MASK_MARKER not in forced.messages[11]["content"]  # last turn kept

    # Nothing left to elide: force still reports no compaction.
    assert plan_compaction(forced.messages, strict, force=True) is None
    assert plan_compaction(messages[:5], strict, force=True) is None  # only one turn


def test_usage_input_tokens_supports_provider_shapes():
    anthropic = SimpleNamespace(input_tokens=10, cache_read_input_tokens=1_000,
                                cache_creation_input_tokens=50, output_tokens=5)
    assert usage_input_tokens(anthropic) == 1_060
    assert usage_input_tokens(SimpleNamespace(input_tokens=10, cache_read_input_tokens=None,
                                              cache_creation_input_tokens=None)) == 10
    assert usage_input_tokens({"prompt_tokens": 42, "completion_tokens": 1}) == 42
    assert usage_input_tokens(SimpleNamespace(input_tokens=77, output_tokens=3)) == 77
    assert usage_input_tokens(None) is None
    assert usage_input_tokens(object()) is None


# ---------------------------------------------------------------------------
# Agent integration
# ---------------------------------------------------------------------------


@dataclass
class _ModelConfig:
    provider_key: str = "test"
    provider_label: str = "test"
    model: str = "fake-model"
    api_type: str = "chat_completions"


@dataclass
class _State:
    cwd: str = "."
    model_config: _ModelConfig = field(default_factory=_ModelConfig)


class _RecordingLLM:
    supports_native_tools = False

    def __init__(self) -> None:
        self.requests: list[list[dict]] = []
        self.last_usage: object | None = None

    def chat(self, messages, tools=None, tool_choice=None):
        self.requests.append([dict(m) for m in messages])
        return "done"


def _agent(llm: _RecordingLLM, settings: CompactionSettings | None, tool_log: list[str]) -> Agent:
    agent = Agent(
        system_prompt="sys", state=_State(), llm=llm,  # type: ignore[arg-type]
        tool_registry=ToolRegistry(), compaction_settings=settings,
        on_tool=tool_log.append,
    )
    agent.messages.extend(_history()[1:])
    return agent


def test_agent_compacts_between_turns_before_the_request():
    llm, log = _RecordingLLM(), []
    agent = _agent(llm, SETTINGS, log)
    messages_ref = agent.messages

    assert agent.step("fourth") == "done"

    assert agent.messages is messages_ref  # mutated in place
    sent = llm.requests[0]
    tool_results = [m["content"] for m in sent if str(m["content"]).startswith("TOOL RESULT")]
    # keep_recent_turns=1 counted before "fourth" is appended: "third" survives.
    assert sum(MASK_MARKER in c for c in tool_results) == 2
    assert MASK_MARKER not in tool_results[-1]
    assert any(line.startswith(CONTEXT_COMPACTION_PREFIX) for line in log)


def test_agent_manual_compaction_works_when_automatic_compaction_is_disabled():
    llm, log = _RecordingLLM(), []
    agent = _agent(llm, None, log)
    agent.messages.extend(_turn("fourth"))
    assert agent.compact_context() is None

    result = agent.compact_context(force=True)
    # Config defaults keep the last 3 turns: only "first" is elided.
    assert result is not None and result.masked_count == 1
    assert agent.messages[3]["content"].startswith("TOOL RESULT (read_file): " + MASK_MARKER)
    assert MASK_MARKER not in agent.messages[7]["content"]
    assert sum(line.startswith(CONTEXT_COMPACTION_PREFIX) for line in log) == 1
    assert agent.compact_context(force=True) is None


def test_agent_compaction_can_be_disabled():
    llm, log = _RecordingLLM(), []
    agent = _agent(llm, None, log)
    agent.step("fourth")
    assert not any(MASK_MARKER in str(m["content"]) for m in agent.messages)
    assert not any(line.startswith("CONTEXT COMPACTION:") for line in log)


def test_agent_does_not_retrigger_on_stale_provider_usage():
    llm, log = _RecordingLLM(), []
    settings = CompactionSettings(trigger_tokens=100_000, keep_recent_turns=1,
                                  min_result_chars=1_000, min_savings_tokens=500)
    agent = _agent(llm, settings, log)
    stale = SimpleNamespace(input_tokens=150_000)
    llm.last_usage = stale  # the fake never refreshes usage

    agent.step("fourth")
    assert sum(line.startswith("CONTEXT COMPACTION:") for line in log) == 1

    # "third" is now old, but the only large-context signal is the same
    # pre-compaction usage object; the local estimate is below the trigger.
    agent.step("fifth")
    assert sum(line.startswith("CONTEXT COMPACTION:") for line in log) == 1


def test_agent_reset_clears_compaction_usage_marker():
    llm, log = _RecordingLLM(), []
    agent = _agent(llm, SETTINGS, log)
    agent._compacted_usage = object()
    agent.reset("sys")
    assert agent._compacted_usage is None
