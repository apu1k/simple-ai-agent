"""
core/context_compaction.py

Layer 0 context compaction: deterministic masking of old tool output.

Tool observations (file reads, searches, command output) dominate the local
transcript in Agent.messages. Once the context grows past a threshold, the
bodies of tool results older than the most recent user turns are replaced by
a short placeholder. Message structure (roles, order, tool_call ids) is never
changed, so no tool call is ever separated from its result.

Design notes:
  - Pure functions, no I/O and no LLM calls.
  - Compaction happens rarely and in large chunks (min_savings_tokens), because
    every edit to older messages invalidates the provider prompt cache once.
    A sliding per-turn window would invalidate it on every turn.
  - Full tool output is not lost: it remains in the tool-call audit store and
    logs. The placeholder tells the model to re-run the tool when needed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

TOOL_RESULT_PREFIX = "TOOL RESULT ("
MASK_MARKER = "[output elided by context compaction"
# Progress-callback prefix; the runtime turns these lines into System messages.
CONTEXT_COMPACTION_PREFIX = "CONTEXT COMPACTION: "
CHARS_PER_TOKEN = 4

# User-role messages that the runtime injects itself; they do not start a turn.
_INTERNAL_USER_PREFIXES = (
    TOOL_RESULT_PREFIX,
    "IMPORTANT: You are on step",
    "Your previous response was",
    "RECOVERY NOTICE",
)


@dataclass(frozen=True)
class CompactionSettings:
    """Thresholds for Layer 0 masking.

    trigger_tokens:      Start compacting once the context reaches this size.
    keep_recent_turns:   Tool results of the last N user turns stay untouched.
    min_result_chars:    Smaller tool results are not worth masking.
    min_savings_tokens:  Skip compaction unless it frees at least this much,
                         so the prompt cache is invalidated only rarely.
    """

    trigger_tokens: int = 100_000
    keep_recent_turns: int = 3
    min_result_chars: int = 1_000
    min_savings_tokens: int = 20_000


@dataclass(frozen=True)
class CompactionResult:
    messages: list[dict]
    masked_count: int
    saved_chars: int
    context_tokens: int

    @property
    def saved_tokens(self) -> int:
        return self.saved_chars // CHARS_PER_TOKEN


def _content_chars(message: dict) -> int:
    content = message.get("content")
    if isinstance(content, str):
        size = len(content)
    elif content is None:
        size = 0
    else:
        size = len(json.dumps(content, ensure_ascii=False, default=str))
    tool_calls = message.get("tool_calls")
    if tool_calls:
        size += len(json.dumps(tool_calls, ensure_ascii=False, default=str))
    return size


def estimate_tokens(messages: list[dict]) -> int:
    """Rough local token estimate (chars / 4) of a message list."""
    return sum(_content_chars(m) for m in messages) // CHARS_PER_TOKEN


def _int_field(usage: Any, name: str) -> int | None:
    value = usage.get(name) if isinstance(usage, dict) else getattr(usage, name, None)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def usage_input_tokens(usage: Any) -> int | None:
    """Return the prompt size reported by a provider usage object, if known.

    Supports Chat Completions (prompt_tokens), Responses (input_tokens, which
    already includes cached tokens) and Anthropic (input_tokens plus the
    separately reported cache read/creation tokens).
    """
    if usage is None:
        return None
    prompt = _int_field(usage, "prompt_tokens")
    if prompt is not None:
        return prompt
    base = _int_field(usage, "input_tokens")
    if base is None:
        return None
    cache_read = _int_field(usage, "cache_read_input_tokens") or 0
    cache_creation = _int_field(usage, "cache_creation_input_tokens") or 0
    return base + cache_read + cache_creation


def is_user_input(message: dict) -> bool:
    """True for a genuine user turn, not a runtime-injected user message."""
    if message.get("role") != "user":
        return False
    content = message.get("content")
    if not isinstance(content, str):
        return False
    return not content.startswith(_INTERNAL_USER_PREFIXES)


def find_cut_index(messages: list[dict], keep_recent_turns: int) -> int:
    """Index of the first message belonging to the last N user turns.

    Messages before the returned index may be compacted. Returns 0 when there
    are not enough user turns, so nothing is compacted.
    """
    if keep_recent_turns <= 0:
        return len(messages)
    starts = [i for i, m in enumerate(messages) if is_user_input(m)]
    if len(starts) < keep_recent_turns:
        return 0
    return starts[-keep_recent_turns]


def _masked_content(message: dict, min_result_chars: int) -> str | None:
    """Return placeholder content for a large tool result, else None."""
    content = message.get("content")
    if not isinstance(content, str) or len(content) < min_result_chars:
        return None
    if MASK_MARKER in content:
        return None

    role = message.get("role")
    placeholder = (
        f"{MASK_MARKER}: {len(content):,} chars. "
        "Re-run the tool if the details are needed.]"
    )
    if role == "tool":
        replacement = placeholder
    elif role == "user" and content.startswith(TOOL_RESULT_PREFIX):
        end = content.find("):", len(TOOL_RESULT_PREFIX))
        label = content[len(TOOL_RESULT_PREFIX):end] if end != -1 else "tool"
        replacement = f"{TOOL_RESULT_PREFIX}{label}): {placeholder}"
    else:
        return None
    # Never replace a result with something that is not shorter.
    return replacement if len(replacement) < len(content) else None


def _masked_native_results(message: dict, min_result_chars: int) -> list[dict] | None:
    """Mask large bodies in a Claude-native tool_result message, else None."""
    content = message.get("content")
    if message.get("role") != "user" or not isinstance(content, list) or not content:
        return None
    if not all(isinstance(block, dict) and block.get("type") == "tool_result" for block in content):
        return None
    blocks: list[dict] = []
    changed = False
    for block in content:
        body = block.get("content")
        if isinstance(body, str) and len(body) >= min_result_chars and MASK_MARKER not in body:
            placeholder = (
                f"{MASK_MARKER}: {len(body):,} chars. "
                "Re-run the tool if the details are needed.]"
            )
            if len(placeholder) < len(body):
                blocks.append({**block, "content": placeholder})
                changed = True
                continue
        blocks.append(block)
    return blocks if changed else None


def mask_tool_results(
    messages: list[dict],
    end: int,
    min_result_chars: int,
) -> CompactionResult:
    """Mask large tool results in messages[:end]. The input is not modified."""
    result: list[dict] = []
    masked = 0
    saved = 0
    for index, message in enumerate(messages):
        replacement: str | list[dict] | None = None
        if index < end:
            replacement = _masked_content(message, min_result_chars)
            if replacement is None:
                replacement = _masked_native_results(message, min_result_chars)
        if replacement is None:
            result.append(message)
            continue
        updated = {**message, "content": replacement}
        saved += _content_chars(message) - _content_chars(updated)
        masked += 1
        result.append(updated)
    return CompactionResult(result, masked, saved, estimate_tokens(result))


def plan_compaction(
    messages: list[dict],
    settings: CompactionSettings,
    reported_tokens: int | None = None,
    *,
    force: bool = False,
) -> CompactionResult | None:
    """Return a compacted message list, or None when compaction is not worth it.

    The context size is the larger of the local estimate and the size the
    provider reported for the latest request (which also counts tool schemas).
    force (manual compaction) ignores trigger_tokens and min_savings_tokens,
    but still keeps the recent turns and skips small results.
    """
    current = max(estimate_tokens(messages), reported_tokens or 0)
    if not force and current < settings.trigger_tokens:
        return None
    cut = find_cut_index(messages, settings.keep_recent_turns)
    if cut <= 0:
        return None
    result = mask_tool_results(messages, cut, settings.min_result_chars)
    if result.masked_count == 0:
        return None
    if not force and result.saved_tokens < settings.min_savings_tokens:
        return None
    return result
