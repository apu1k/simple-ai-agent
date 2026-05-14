import json
import re
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ParsedModelResponse:
    kind: Literal["tool", "final", "invalid"]
    action: str | None = None
    tool_input: dict | None = None
    final: str | None = None
    error: str | None = None

    @property
    def is_valid(self):
        return self.kind != "invalid"


def tool_response(action, tool_input):
    return ParsedModelResponse(
        kind="tool",
        action=action,
        tool_input=tool_input,
    )


def final_response(text):
    return ParsedModelResponse(
        kind="final",
        final=text,
    )


def invalid_response(message):
    return ParsedModelResponse(
        kind="invalid",
        error=message,
    )


def validate_tool_call(data):
    if not isinstance(data, dict):
        return invalid_response("Tool call JSON root must be an object.")

    keys = set(data.keys())
    allowed_keys = {"action", "input"}

    extra_keys = keys - allowed_keys
    if extra_keys:
        return invalid_response(
            f"Tool call contains unsupported key(s): {sorted(extra_keys)}."
        )

    missing_keys = allowed_keys - keys
    if missing_keys:
        return invalid_response(
            f"Tool call is missing required key(s): {sorted(missing_keys)}."
        )

    action = data["action"]
    tool_input = data["input"]

    if not isinstance(action, str):
        return invalid_response("'action' must be a string.")

    action = action.strip()

    if not action:
        return invalid_response("'action' must not be empty.")

    if not isinstance(tool_input, dict):
        return invalid_response("'input' must be a JSON object.")

    return tool_response(action, tool_input)


def _contains_embedded_tool_call(text):
    """
    Detects cases where the model prints a tool call inside a normal answer,
    for example:

    "I would use this:
    {\"action\": \"pwd\", \"input\": {}}"

    This should be invalid, because actual tool calls must be the entire response.
    """

    if not isinstance(text, str):
        return False

    # Fast cheap check first.
    if '"action"' not in text or '"input"' not in text:
        return False

    # Look for JSON-looking objects that contain action/input.
    # This is intentionally conservative enough for our tool-call protocol.
    possible_objects = re.findall(r"\{.*?\}", text, flags=re.DOTALL)

    for possible_object in possible_objects:
        if '"action"' not in possible_object or '"input"' not in possible_object:
            continue

        try:
            data = json.loads(possible_object)
        except Exception:
            continue

        if isinstance(data, dict) and "action" in data and "input" in data:
            return True

    # Fallback: even if the regex fails because nested braces are involved,
    # the text clearly contains tool-call protocol keys embedded in prose.
    return True


def _looks_like_invalid_raw_tool_call(text):
    clean_text = text.strip()

    if not clean_text:
        return False

    if clean_text.startswith("```") and '"action"' in clean_text:
        return True

    if clean_text.startswith("{") and '"action"' in clean_text:
        return True

    return False


def parse_model_response(text):
    """
    Response protocol:

    1. Tool call:
       The entire model response must be strict raw JSON:
       {"action": "tool_name", "input": {...}}

    2. Final answer:
       Normal non-tool text is treated as the final answer.

    Important:
    - If a tool call JSON is embedded inside normal text, that is invalid.
      The model must retry and output only the raw JSON tool call.
    """

    if not isinstance(text, str):
        return invalid_response("Model response must be a string.")

    clean_text = text.strip()

    if not clean_text:
        return invalid_response("Model response is empty.")

    try:
        data = json.loads(clean_text)
    except json.JSONDecodeError as e:
        if _looks_like_invalid_raw_tool_call(clean_text):
            return invalid_response(
                "The response looks like an attempted tool call, but it is not valid raw JSON. "
                f"JSON error: {e.msg} at line {e.lineno}, column {e.colno}. "
                "Tool calls must be a single raw JSON object without Markdown, code fences, or prose."
            )

        if _contains_embedded_tool_call(clean_text):
            return invalid_response(
                "The response contains an embedded tool call inside normal text. "
                "If you want to call a tool, the entire response must be exactly one raw JSON object "
                'like {"action": "tool_name", "input": {...}}. '
                "Do not introduce, explain, quote, or wrap the tool call."
            )

        return final_response(text)

    if isinstance(data, dict):
        keys = set(data.keys())

        if "action" in keys or "input" in keys:
            return validate_tool_call(data)

        # Transitional compatibility: accept legacy final JSON, but do not encourage it.
        if keys == {"final"} and isinstance(data["final"], str):
            return final_response(data["final"])

        return final_response(text)

    return final_response(text)


def parse_action(text):
    """
    Backward-compatible wrapper.

    Older code expects:
    - (action, input_dict) for tool calls
    - (None, final_text) for final answers
    - (None, None) for invalid tool-call-like responses
    """

    parsed = parse_model_response(text)

    if parsed.kind == "tool":
        return parsed.action, parsed.tool_input

    if parsed.kind == "final":
        return None, parsed.final

    print("PARSE ERROR:", parsed.error)
    print("RAW TEXT:", text)
    return None, None