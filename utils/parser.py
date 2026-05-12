import json
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


def looks_like_attempted_tool_call(text):
    clean_text = text.strip()

    if not clean_text:
        return False

    starts_like_json_tool = clean_text.startswith("{") or clean_text.startswith("```")

    return starts_like_json_tool and '"action"' in clean_text


def parse_model_response(text):
    """
    New model response format:

    1. Tool call:
       The entire model response must be strict JSON:
       {"action": "tool_name", "input": {...}}

    2. Final answer:
       Any normal non-tool text is treated as the final answer.

    Transitional compatibility:
    - {"final": "..."} is still accepted and unwrapped as a final answer,
      but the prompt should no longer ask the model to use this format.
    """

    if not isinstance(text, str):
        return invalid_response("Model response must be a string.")

    clean_text = text.strip()

    if not clean_text:
        return invalid_response("Model response is empty.")

    try:
        data = json.loads(clean_text)
    except json.JSONDecodeError as e:
        if looks_like_attempted_tool_call(clean_text):
            return invalid_response(
                "The response looks like an attempted tool call, but it is not valid raw JSON. "
                f"JSON error: {e.msg} at line {e.lineno}, column {e.colno}. "
                "Tool calls must be a single raw JSON object without Markdown or code fences."
            )

        return final_response(text)

    if isinstance(data, dict):
        keys = set(data.keys())

        if "action" in keys or "input" in keys:
            return validate_tool_call(data)

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