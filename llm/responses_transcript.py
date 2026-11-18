"""Ordered Responses items and their portable model-context representation."""
from __future__ import annotations

from hashlib import sha256
import json
from typing import Any, Sequence

REPLAY_KEY = "_responses_replay"
SEQUENCE_KEY = "_transcript_sequence"
EXECUTION_REFS_KEY = "_execution_refs"
RESULT_STATUSES_KEY = "_responses_result_statuses"
RESULT_OVERRIDES_KEY = "_responses_result_overrides"


def replay_scope(endpoint: str, provider: str, model: str) -> str:
    return sha256(json.dumps([endpoint, provider, model]).encode()).hexdigest()


def entry(kind: str, scope: str, content: Any) -> dict:
    return {"role": "assistant" if kind == "output" else "user",
            "content": content, REPLAY_KEY: {"kind": kind, "scope": scope}}


def execution_output(status: str, observation: str | None, error: str | None) -> str:
    """Render exact results for v3 journal references; keep this decoding stable."""
    if status == "success":
        return observation or ""
    if status == "failed":
        return error or observation or "Tool failed."
    return observation or "Skipped due to earlier failure in fail-fast batch."


def output_items(response: Any) -> list[dict]:
    # The SDK's public wire-format serializer preserves assistant phase, call
    # IDs, encrypted reasoning, and ordering. Do not rebuild these from text.
    return [item.copy() if isinstance(item, dict) else item.to_dict() for item in response.output]


def _function_ids(items: list[dict]) -> list[str]:
    calls: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item.get("type") != "function_call":
            continue
        call = item.get("call_id")
        if not isinstance(call, str) or not call or call in seen:
            raise ValueError("Responses returned an invalid function call ID")
        calls.append(call)
        seen.add(call)
    return calls


def validate_output(items: list[dict], status: str | None) -> None:
    if status != "completed":
        raise ValueError("Responses did not complete; the incomplete turn was not carried forward")
    if any(item.get("type") not in {"message", "reasoning", "function_call"} for item in items):
        raise ValueError("Responses returned an item this runtime cannot replay safely")
    _function_ids(items)


def is_entry(message: dict) -> bool:
    return REPLAY_KEY in message


def project_result_bodies(message: dict) -> dict:
    """Apply replay-only overrides; the original result items stay untouched."""
    overrides = message.get(RESULT_OVERRIDES_KEY)
    if not overrides:
        return message
    return {**message, "content": [
        {**item, "output": overrides[item["call_id"]]}
        if item.get("type") == "function_call_output" and item.get("call_id") in overrides else item
        for item in message["content"]
    ]}


def directive_text(messages: Sequence[dict], scope: str) -> str | None:
    for message in reversed(messages):
        if message.get(REPLAY_KEY) == {"kind": "directive", "scope": scope}:
            return message["content"]
    return None


def as_text(message: dict) -> list[dict]:
    """Project tool facts and visible messages, never provider-native reasoning."""
    kind = message[REPLAY_KEY]["kind"]
    if kind == "directive":
        return []
    parts: list[str] = []
    for item in message["content"]:
        item_type = item.get("type")
        if item_type == "message":
            parts.extend(block["text"] for block in item.get("content", [])
                         if block.get("type") == "output_text" and block.get("text"))
            parts.extend(block["refusal"] for block in item.get("content", [])
                         if block.get("type") == "refusal" and block.get("refusal"))
        elif item_type == "function_call":
            parts.append(f"NATIVE TOOL CALL: {item['name']} (id={item['call_id']}) {item['arguments']}")
        elif item_type == "function_call_output":
            parts.append(f"TOOL RESULT ({item['call_id']}): {item['output']}")
    return [{"role": message["role"], "content": "\n\n".join(parts)}] if parts else []


def portable_messages(messages: list[dict]) -> list[dict]:
    return [item for message in messages for item in (as_text(message) if is_entry(message) else (message,))]


def for_responses(messages: list[dict], scope: str) -> list[dict]:
    items: list[dict] = []
    pending: list[str] = []
    for message in messages:
        if not is_entry(message):
            role, text = message.get("role"), message.get("content")
            if pending:
                raise ValueError("Responses transcript has an incomplete tool exchange")
            if role in {"assistant", "user"} and isinstance(text, str) and text:
                items.append({"role": role, "content": text})
            elif role == "tool":
                items.append({"role": "user", "content": f"TOOL RESULT ({message.get('name', 'tool')}): {text}"})
            continue
        kind, source = message[REPLAY_KEY]["kind"], message[REPLAY_KEY]["scope"]
        if pending and (kind != "results" or source != scope):
            raise ValueError("Responses transcript has an incomplete tool exchange")
        if source != scope:
            items.extend(as_text(message))
        elif kind == "directive":
            items.append({"role": "developer", "content": message["content"]})
        elif kind == "output":
            items.extend(message["content"])
            pending = _function_ids(message["content"])
        elif kind == "results":
            results = message["content"]
            if not pending or [result.get("call_id") for result in results] != pending:
                raise ValueError("Responses transcript has unmatched tool results")
            items.extend(results)
            pending = []
        else:
            raise ValueError("Unknown Responses transcript entry")
    if pending:
        raise ValueError("Responses transcript has an incomplete tool exchange")
    return items
