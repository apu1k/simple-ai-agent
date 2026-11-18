"""Replace large old tool results with short factual records between turns.

Never infer a tool result from the text of a user message. Keep the message
roles, order and tool IDs unchanged. The recovery journal is not modified.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from llm.anthropic_transcript import NATIVE_KEY
from llm.responses_transcript import EXECUTION_REFS_KEY, SEQUENCE_KEY

TOOL_RESULT_PREFIX = "TOOL RESULT ("
TOOL_RESULT_SUMMARY_KEY = "_tool_result_summary"
INTERNAL_USER_KEY = "_internal_user"
_LOCAL_KEYS = {TOOL_RESULT_SUMMARY_KEY, INTERNAL_USER_KEY, EXECUTION_REFS_KEY, SEQUENCE_KEY}
CONTEXT_COMPACTION_PREFIX = "CONTEXT COMPACTION: "
CHARS_PER_TOKEN = 4

# Only use path-like inputs for known file tools. Never copy command lines,
# search queries, replacement text, or arbitrary inputs/output into a summary.
_PATH_FIELDS = {
    "read_file": ("path",), "file_info": ("path",), "ls": ("path",),
    "find_files": ("path",), "search_text": ("path",),
    "analyze_python_file": ("path",), "analyze_python_files": ("path",),
    "propose_file_edit": ("path",), "propose_file_replace": ("path",),
    "create_file": ("path",), "delete_path": ("path",),
    "create_folder": ("path",), "cd": ("path",),
    "move_file": ("source", "destination"), "copy_file": ("source", "destination"),
}


@dataclass(frozen=True)
class CompactionSettings:
    """Keep recent turns intact and compact only when the saving warrants it."""

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


def tool_result_summary(name: Any, arguments: Any, status: str) -> str:
    """Describe the call and recorded status, not inferred filesystem effects."""
    if not isinstance(name, str) or not name or len(name) > 80 or not all(
        c.isascii() and (c.isalnum() or c in "_-") for c in name
    ):
        name = "tool"
    fields = []
    if isinstance(arguments, dict):
        for field in _PATH_FIELDS.get(name, ()):
            value = arguments.get(field)
            if isinstance(value, str) and 0 < len(value) <= 160:
                fields.append(f"{field}={json.dumps(value, ensure_ascii=True)}")
    status = {"success": "returned", "failed": "failed", "skipped": "skipped"}.get(status, "result")
    return " ".join([name, *fields, f"({status})"])


def provider_messages(messages: list[dict]) -> list[dict]:
    """Remove local compaction metadata without changing provider content."""
    return [
        {key: value for key, value in message.items() if key not in _LOCAL_KEYS}
        if _LOCAL_KEYS.intersection(message) else message
        for message in messages
    ]


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
    return value if type(value) is int else None


def usage_input_tokens(usage: Any) -> int | None:
    """Count both cached and uncached provider input, when known."""
    prompt = _int_field(usage, "prompt_tokens")
    if prompt is not None:
        return prompt
    base = _int_field(usage, "input_tokens")
    if base is None:
        return None
    return base + (_int_field(usage, "cache_read_input_tokens") or 0) + (
        _int_field(usage, "cache_creation_input_tokens") or 0
    )


def is_user_input(message: dict) -> bool:
    """Unmarked legacy user text is conservatively treated as user input."""
    return (
        message.get("role") == "user" and isinstance(message.get("content"), str)
        and message.get(INTERNAL_USER_KEY) is not True and TOOL_RESULT_SUMMARY_KEY not in message
    )


def find_cut_index(messages: list[dict], keep_recent_turns: int) -> int:
    """Return the start of the protected recent turns, or 0 if too few exist."""
    if keep_recent_turns <= 0:
        return len(messages)
    starts = [i for i, m in enumerate(messages) if is_user_input(m)]
    return starts[-keep_recent_turns] if len(starts) >= keep_recent_turns else 0


def _shorter(body: Any, replacement: str, minimum: int) -> bool:
    return isinstance(body, str) and len(body) >= minimum and len(replacement) < len(body)


def _native_replacement(previous: dict, message: dict, minimum: int) -> list[dict] | None:
    model = message.get(NATIVE_KEY)
    calls, results = previous.get("content"), message.get("content")
    if (not model or previous.get(NATIVE_KEY) != model or previous.get("role") != "assistant"
            or message.get("role") != "user" or not isinstance(calls, list)
            or not isinstance(results, list)):
        return None
    by_id = {
        block["id"]: block for block in calls if isinstance(block, dict)
        and block.get("type") == "tool_use" and isinstance(block.get("id"), str)
    }
    if not results or not all(
        isinstance(block, dict) and block.get("type") == "tool_result"
        and isinstance(block.get("tool_use_id"), str) and block["tool_use_id"] in by_id
        for block in results
    ):
        return None
    replacement = []
    for block in results:
        call = by_id[block["tool_use_id"]]
        summary = tool_result_summary(
            call.get("name"), call.get("input"), "failed" if block.get("is_error") else "success",
        )
        replacement.append(
            {**block, "content": summary} if _shorter(block.get("content"), summary, minimum) else block
        )
    return replacement if any(a is not b for a, b in zip(results, replacement, strict=True)) else None


def mask_tool_results(messages: list[dict], end: int, min_result_chars: int) -> CompactionResult:
    """Shorten only explicitly marked or structurally native results."""
    result: list[dict] = []
    masked = saved = 0
    for index, message in enumerate(messages):
        replacement: str | list[dict] | None = None
        # Durable Responses originals are immutable. A replay projection for
        # them is a separate feature; never modify the resolved row in place.
        if index < end and SEQUENCE_KEY not in message:
            summary = message.get(TOOL_RESULT_SUMMARY_KEY)
            role = message.get("role")
            if role == "tool" and not isinstance(summary, str):
                # Legacy Chat Completions results carry a trusted structural role.
                summary = tool_result_summary(message.get("name"), None, "unknown")
            if role in {"tool", "user"} and isinstance(summary, str):
                if _shorter(message.get("content"), summary, min_result_chars):
                    replacement = summary
            elif index:
                replacement = _native_replacement(messages[index - 1], message, min_result_chars)
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
    """Manual compaction skips the thresholds, but still protects recent turns."""
    current = max(estimate_tokens(messages), reported_tokens or 0)
    if not force and current < settings.trigger_tokens:
        return None
    cut = find_cut_index(messages, settings.keep_recent_turns)
    if cut <= 0:
        return None
    result = mask_tool_results(messages, cut, settings.min_result_chars)
    if result.masked_count == 0 or (not force and result.saved_tokens < settings.min_savings_tokens):
        return None
    return result
