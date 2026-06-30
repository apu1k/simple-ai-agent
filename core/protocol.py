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
from dataclasses import dataclass, field
from typing import Literal


# ---------------------------------------------------------------------------
# Response types
# ---------------------------------------------------------------------------

MAX_TOOL_CALLS_PER_TURN = 10


_OPENAI_TEXTUAL_TOOL_CALL_RE = re.compile(
    r"<tool_call>\s*(?P<body>.*?)\s*</tool_call>",
    flags=re.DOTALL | re.IGNORECASE,
)


@dataclass(frozen=True)
class ToolCall:
    action: str
    tool_input: dict


@dataclass(frozen=True)
class ParsedResponse:
    kind: Literal["tool", "final", "invalid"]
    tool_calls: list[ToolCall] = field(default_factory=list)
    final: str | None = None
    error: str | None = None
    assistant_text: str = ""
    consumed_tool_call_markup: bool = False

    @property
    def is_valid(self) -> bool:
        return self.kind != "invalid"

    # Backward compatibility for existing call sites/tests
    @property
    def action(self) -> str | None:
        return self.tool_calls[0].action if self.tool_calls else None

    @property
    def tool_input(self) -> dict | None:
        return self.tool_calls[0].tool_input if self.tool_calls else None


def _tool(action: str, tool_input: dict) -> ParsedResponse:
    return ParsedResponse(
        kind="tool",
        tool_calls=[ToolCall(action=action, tool_input=tool_input)],
    )


def _tools(
    tool_calls: list[ToolCall],
    *,
    assistant_text: str = "",
    consumed_tool_call_markup: bool = False,
) -> ParsedResponse:
    return ParsedResponse(
        kind="tool",
        tool_calls=tool_calls,
        assistant_text=assistant_text,
        consumed_tool_call_markup=consumed_tool_call_markup,
    )


def _final(text: str) -> ParsedResponse:
    return ParsedResponse(kind="final", final=text)


def _invalid(message: str) -> ParsedResponse:
    return ParsedResponse(kind="invalid", error=message)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _validate_single_tool_call_dict(data: dict) -> ParsedResponse:
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


def _validate_tool_call_list(items) -> ParsedResponse:
    if not isinstance(items, list):
        return _invalid("'tool_calls' must be a JSON array.")

    if not items:
        return _invalid("'tool_calls' must contain at least one tool call.")

    if len(items) > MAX_TOOL_CALLS_PER_TURN:
        return _invalid(
            f"Too many tool calls in one response: {len(items)} > {MAX_TOOL_CALLS_PER_TURN}."
        )

    calls: list[ToolCall] = []
    for item in items:
        if not isinstance(item, dict):
            return _invalid("Each entry in 'tool_calls' must be an object.")

        validated = _validate_single_tool_call_dict(item)
        if validated.kind == "invalid":
            return validated

        calls.extend(validated.tool_calls)

    return _tools(calls)


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


def _normalize_textual_recipient_name(name: str) -> str:
    clean = name.strip()
    if clean.startswith("functions."):
        clean = clean[len("functions."):]
    return clean


def _maybe_json_decode_string(value):
    if not isinstance(value, str):
        return value

    stripped = value.strip()
    if not stripped:
        return value

    if not (
        stripped.startswith("{")
        or stripped.startswith("[")
        or stripped.startswith('"')
        or stripped in {"true", "false", "null"}
    ):
        return value

    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return value


def _coerce_textual_parameters(parameters: dict) -> dict:
    fixed = {}
    for key, value in parameters.items():
        fixed[key] = _maybe_json_decode_string(value)
    return fixed


def _parse_textual_tool_call_body(body: str) -> ToolCall | str:
    try:
        data = json.loads(body)
    except json.JSONDecodeError as e:
        return (
            f"Invalid <tool_call> JSON: {e.msg} "
            f"at line {e.lineno}, column {e.colno}."
        )

    if not isinstance(data, dict):
        return "Invalid <tool_call>: body must be a JSON object."

    allowed = {"recipient_name", "parameters"}
    extra = set(data.keys()) - allowed
    if extra:
        return f"Invalid <tool_call>: unsupported key(s): {sorted(extra)}."

    recipient_name = data.get("recipient_name")
    if not isinstance(recipient_name, str) or not recipient_name.strip():
        return "Invalid <tool_call>: 'recipient_name' must be a non-empty string."

    parameters = data.get("parameters", {})
    if parameters is None:
        parameters = {}

    if isinstance(parameters, str):
        parameters = _maybe_json_decode_string(parameters)

    if not isinstance(parameters, dict):
        return "Invalid <tool_call>: 'parameters' must be a JSON object."

    action = _normalize_textual_recipient_name(recipient_name)
    if not action:
        return "Invalid <tool_call>: tool name must not be empty."

    return ToolCall(action=action, tool_input=_coerce_textual_parameters(parameters))


def _extract_textual_tool_calls(text: str) -> ParsedResponse | None:
    matches = list(_OPENAI_TEXTUAL_TOOL_CALL_RE.finditer(text))
    if not matches:
        return None

    if len(matches) > MAX_TOOL_CALLS_PER_TURN:
        return _invalid(
            f"Too many textual tool calls in one response: "
            f"{len(matches)} > {MAX_TOOL_CALLS_PER_TURN}."
        )

    calls: list[ToolCall] = []
    errors: list[str] = []

    for match in matches:
        body = match.group("body").strip()
        parsed = _parse_textual_tool_call_body(body)
        if isinstance(parsed, str):
            errors.append(parsed)
        else:
            calls.append(parsed)

    if errors:
        return _invalid(" ".join(errors))

    if not calls:
        return _invalid("No valid <tool_call> blocks found.")

    visible_text = _OPENAI_TEXTUAL_TOOL_CALL_RE.sub("", text).strip()

    return _tools(
        calls,
        assistant_text=visible_text,
        consumed_tool_call_markup=True,
    )


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

    textual_tool_calls = _extract_textual_tool_calls(clean)
    if textual_tool_calls is not None:
        return textual_tool_calls

    if "<tool_call>" in clean.lower() or "</tool_call>" in clean.lower():
        return _invalid(
            "Incomplete or malformed <tool_call> block. "
            "Textual tool calls must include both opening and closing tags, "
            "and the body must be valid JSON."
        )

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

        if "tool_calls" in keys:
            if "action" in keys or "input" in keys:
                return _invalid(
                    "Tool call JSON must use either {'action','input'} or 'tool_calls', not both."
                )
            return _validate_tool_call_list(data["tool_calls"])

        if "action" in keys or "input" in keys:
            return _validate_single_tool_call_dict(data)

        # Legacy compatibility: {"final": "..."}
        if keys == {"final"} and isinstance(data["final"], str):
            return _final(data["final"])

        return _final(text)

    return _final(text)
