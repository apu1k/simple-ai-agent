"""
core/protocol.py

Parses raw LLM response strings into structured ParsedResponse objects.

This is the agent's tool-call protocol:
  - Tool call:    entire response is {"action": "name", "input": {...}}
  - Final answer: any other text
  - Invalid:      looks like a tool call but is malformed or embedded in prose

No I/O, no imports from this project.
"""

import json
import re
from dataclasses import dataclass
from typing import Literal


# ---------------------------------------------------------------------------
# Response types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ParsedResponse:
    kind: Literal["tool", "final", "invalid"]
    action: str | None = None
    tool_input: dict | None = None
    final: str | None = None
    error: str | None = None

    @property
    def is_valid(self) -> bool:
        return self.kind != "invalid"


def _tool(action: str, tool_input: dict) -> ParsedResponse:
    return ParsedResponse(kind="tool", action=action, tool_input=tool_input)


def _final(text: str) -> ParsedResponse:
    return ParsedResponse(kind="final", final=text)


def _invalid(message: str) -> ParsedResponse:
    return ParsedResponse(kind="invalid", error=message)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _validate_tool_call(data: dict) -> ParsedResponse:
    if not isinstance(data, dict):
        return _invalid("Tool call JSON root must be an object.")

    keys = set(data.keys())
    allowed = {"action", "input"}

    extra = keys - allowed
    if extra:
        return _invalid(f"Tool call contains unsupported key(s): {sorted(extra)}.")

    missing = allowed - keys
    if missing:
        return _invalid(f"Tool call is missing required key(s): {sorted(missing)}.")

    action = data["action"]
    tool_input = data["input"]

    if not isinstance(action, str):
        return _invalid("'action' must be a string.")

    action = action.strip()
    if not action:
        return _invalid("'action' must not be empty.")

    if not isinstance(tool_input, dict):
        return _invalid("'input' must be a JSON object.")

    return _tool(action, tool_input)


def _contains_embedded_tool_call(text: str) -> bool:
    """
    Detects a tool call JSON embedded inside prose, e.g.:
      "I would use: {"action": "pwd", "input": {}}"
    Tool calls must be the entire response — not embedded.
    """
    if not isinstance(text, str):
        return False
    if '"action"' not in text or '"input"' not in text:
        return False

    for match in re.findall(r"\{.*?\}", text, flags=re.DOTALL):
        if '"action"' not in match or '"input"' not in match:
            continue
        try:
            data = json.loads(match)
        except Exception:
            continue
        if isinstance(data, dict) and "action" in data and "input" in data:
            return True

    # Fallback: keys are present but regex couldn't extract a valid object
    # (e.g. due to nested braces). Still treat as embedded.
    return True


def _looks_like_broken_tool_call(text: str) -> bool:
    clean = text.strip()
    if not clean:
        return False
    if clean.startswith("```") and '"action"' in clean:
        return True
    if clean.startswith("{") and '"action"' in clean:
        return True
    return False


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

def parse(text) -> ParsedResponse:
    """
    Parse a raw LLM response string.

    Returns a ParsedResponse with kind == "tool", "final", or "invalid".
    """
    if not isinstance(text, str):
        return _invalid("Model response must be a string.")

    clean = text.strip()
    if not clean:
        return _invalid("Model response is empty.")

    try:
        data = json.loads(clean)
    except json.JSONDecodeError as e:
        if _looks_like_broken_tool_call(clean):
            return _invalid(
                "The response looks like an attempted tool call, but is not valid raw JSON. "
                f"JSON error: {e.msg} at line {e.lineno}, column {e.colno}. "
                "Tool calls must be a single raw JSON object with no Markdown or prose."
            )
        if _contains_embedded_tool_call(clean):
            return _invalid(
                "The response contains an embedded tool call inside normal text. "
                "If you want to call a tool, the entire response must be exactly one "
                'raw JSON object like {"action": "tool_name", "input": {...}}. '
                "Do not introduce, explain, quote, or wrap the tool call."
            )
        return _final(text)

    if isinstance(data, dict):
        keys = set(data.keys())

        if "action" in keys or "input" in keys:
            return _validate_tool_call(data)

        # Legacy compatibility: {"final": "..."}
        if keys == {"final"} and isinstance(data["final"], str):
            return _final(data["final"])

        return _final(text)

    return _final(text)
