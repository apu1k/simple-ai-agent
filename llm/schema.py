"""
llm/schema.py

Converts ToolSpec objects to provider-specific tool definition formats.

Supports:
- OpenAI Chat Completions API (nested function structure)
- OpenAI Responses API (flat function structure)
"""

from core.tool_registry import ToolRegistry, ToolSpec


def _to_json_schema_parameters(spec: ToolSpec) -> dict:
    """Convert ToolSpec.parameters (name -> description) into JSON Schema."""
    params = spec.parameters or {}
    if not isinstance(params, dict):
        params = {}

    properties = {}
    required = []
    for name, definition in params.items():
        if isinstance(definition, dict):
            # Copy explicit schemas so provider-specific processing cannot
            # mutate the registry's ToolSpec. A JSON Schema default marks the
            # function parameter as optional in the containing object.
            property_schema = dict(definition)
            properties[name] = property_schema
            if "default" not in property_schema:
                required.append(name)
        else:
            properties[name] = {
                "type": "string",
                "description": str(definition),
            }
            required.append(name)

    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def tool_spec_to_openai_function(spec: ToolSpec) -> dict:
    """Convert a ToolSpec to OpenAI Chat Completions API format (nested)."""
    return {
        "type": "function",
        "function": {
            "name": spec.name,
            "description": spec.description or "",
            "parameters": _to_json_schema_parameters(spec),
        },
    }


def tool_spec_to_responses_function(spec: ToolSpec) -> dict:
    """Convert a ToolSpec to OpenAI Responses API format (flat)."""
    return {
        "type": "function",
        "name": spec.name,
        "description": spec.description or "",
        "parameters": _to_json_schema_parameters(spec),
    }


def build_tools_list(registry: ToolRegistry, api_type: str = "chat_completions") -> list[dict]:
    """Build tool definitions in the format required by the target API."""
    if api_type == "responses":
        return [
            tool_spec_to_responses_function(spec)
            for spec in registry.all().values()
        ]

    return [
        tool_spec_to_openai_function(spec)
        for spec in registry.all().values()
    ]
