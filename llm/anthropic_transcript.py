"""Claude-native tool-loop entries kept in the agent's local history.

Claude's prompt cache matches exact request prefixes. A tool loop sends the
provider's native blocks (signed thinking, tool_use, tool_result). If local
history kept only a text rewrite of them, the next user message would resend a
different prefix and pay cache writes for everything after the system prompt.
Storing the exact blocks keeps the next turn's prefix byte-identical.

Native entries are tagged with NATIVE_KEY (the producing model). They are
replayed only to that same model and only as complete tool_use/tool_result
pairs. Anything else is degraded to the legacy text form every provider accepts.
This module has no SDK dependency so non-Anthropic code paths can import it.
"""
from __future__ import annotations

import json
from typing import Any, Protocol, Sequence

NATIVE_KEY = "anthropic_native"


class _ToolOutput(Protocol):
    call_id: str
    output: str
    is_error: bool


def tool_result_blocks(call_ids: Sequence[str], outputs: Sequence[_ToolOutput]) -> list[dict]:
    """The single tool_result content used both on the wire and in history."""
    by_id = {output.call_id: output for output in outputs}
    if len(by_id) != len(outputs) or by_id.keys() != set(call_ids):
        raise ValueError("Anthropic requires exactly one result per pending tool call.")
    return [
        {"type": "tool_result", "tool_use_id": call_id,
         "content": by_id[call_id].output, "is_error": by_id[call_id].is_error}
        for call_id in call_ids
    ]


def is_native(message: Any) -> bool:
    return isinstance(message, dict) and NATIVE_KEY in message


def _blocks(message: Any, role: str, model: str) -> list[dict] | None:
    if not (is_native(message) and message.get("role") == role and message[NATIVE_KEY] == model):
        return None
    content = message.get("content")
    if not isinstance(content, list) or not all(isinstance(block, dict) for block in content):
        return None
    return content


def replayable_native_indices(messages: Sequence[dict], model: str | None) -> set[int]:
    """Indices of native entries that may be sent unchanged to ``model``.

    Claude rejects a tool_use without its tool_result (and vice versa), and
    signed thinking is only valid for the model that produced it.
    """
    valid: set[int] = set()
    if not model:
        return valid
    for index in range(len(messages) - 1):
        calls = _blocks(messages[index], "assistant", model)
        results = _blocks(messages[index + 1], "user", model)
        if calls is None or results is None:
            continue
        use_ids = [block.get("id") for block in calls if block.get("type") == "tool_use"]
        if not results or any(block.get("type") != "tool_result" for block in results):
            continue
        result_ids = [block.get("tool_use_id") for block in results]
        if use_ids and len(set(use_ids)) == len(use_ids) and use_ids == result_ids:
            valid.update((index, index + 1))
    return valid


def as_text(message: dict) -> dict:
    """Legacy text form of a native entry, without signed or hidden blocks."""
    role, content = message.get("role"), message.get("content")
    if not isinstance(content, list):
        return {"role": role, "content": content}
    blocks = [block for block in content if isinstance(block, dict)]
    if role == "assistant":
        text = "".join(block.get("text", "") for block in blocks if block.get("type") == "text")
        calls = [
            f"- id={block.get('id')} name={block.get('name')} arguments="
            + json.dumps(block.get("input"), ensure_ascii=False, sort_keys=True, default=str)
            for block in blocks if block.get("type") == "tool_use"
        ]
        if calls:
            text = f"{text}\n\nNATIVE TOOL CALL REQUEST:\n" + "\n".join(calls)
        return {"role": "assistant", "content": text.strip()}
    parts = []
    for block in blocks:
        if block.get("type") == "tool_result":
            body = block.get("content")
            if not isinstance(body, str):
                body = json.dumps(body, ensure_ascii=False, default=str)
            status = " [error]" if block.get("is_error") else ""
            parts.append(f"TOOL RESULT ({block.get('tool_use_id')}){status}: {body}")
        elif block.get("type") == "text":
            parts.append(str(block.get("text", "")))
    return {"role": role, "content": "\n\n".join(parts)}


def plain_messages(messages: list[dict]) -> list[dict]:
    """Degrade native entries for providers that cannot replay Claude blocks."""
    if not any(is_native(message) for message in messages):
        return messages
    return [as_text(message) if is_native(message) else message for message in messages]
