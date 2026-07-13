from core.tool_registry import ToolSpec
from llm.schema import (
    tool_spec_to_openai_function,
    tool_spec_to_responses_function,
)


def _edit_spec() -> ToolSpec:
    return ToolSpec(
        name="propose_file_edit",
        function=lambda: None,
        description="Propose edits.",
        parameters={
            "path": "File path.",
            "edits": {
                "type": "array",
                "description": "Exact-match edits.",
                "items": {
                    "type": "object",
                    "properties": {
                        "find": {"type": "string"},
                        "replace": {"type": "string"},
                    },
                    "required": ["find", "replace"],
                    "additionalProperties": False,
                },
            },
        },
    )


def test_explicit_parameter_schema_is_preserved_for_chat_completions():
    tool = tool_spec_to_openai_function(_edit_spec())
    properties = tool["function"]["parameters"]["properties"]

    assert properties["path"] == {"type": "string", "description": "File path."}
    assert properties["edits"]["type"] == "array"
    assert properties["edits"]["items"]["properties"]["find"]["type"] == "string"


def test_explicit_parameter_schema_is_preserved_for_responses():
    tool = tool_spec_to_responses_function(_edit_spec())
    edits = tool["parameters"]["properties"]["edits"]

    assert edits["type"] == "array"
    assert edits["items"]["required"] == ["find", "replace"]
