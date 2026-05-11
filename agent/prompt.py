import json

from tools import TOOLS


def format_tool_signature(name, spec):
    parameters = spec.get("parameters", {})

    if not parameters:
        return f"{name}()"

    parameter_names = ", ".join(parameters.keys())
    return f"{name}({parameter_names})"


def build_tools_prompt():
    lines = []

    for name, spec in TOOLS.items():
        signature = format_tool_signature(name, spec)
        description = spec.get("description", "")
        parameters = spec.get("parameters", {})
        example = spec.get("example")

        lines.append(f"- {signature}: {description}")

        if parameters:
            lines.append("  Parameters:")
            for param_name, param_description in parameters.items():
                lines.append(f"  - {param_name}: {param_description}")

        if example:
            example_json = json.dumps(example, ensure_ascii=False)
            lines.append(f"  Example: {example_json}")

    return "\n".join(lines)


def build_system_prompt():
    tools_prompt = build_tools_prompt()

    return f"""
You are an AI agent connected to a local Python runtime.

You must respond with valid JSON only.
Do not include Markdown.
Do not include explanations outside the JSON object.
Do not include code fences.

If you want to use a tool, respond with:
{{
  "action": "tool_name",
  "input": {{"param": "value"}}
}}

If you are done and want to answer the user, respond with:
{{
  "final": "your answer"
}}

Tool calling rules:
- You may call only one tool per response.
- Never combine multiple tool calls in one JSON object.
- If a task requires multiple steps, call exactly one tool first.
- After receiving a tool result, decide the next step and respond again with valid JSON.
- Do not pretend that you have performed a filesystem action without using the appropriate tool.

Available tools:
{tools_prompt}

Filesystem behavior:
- You are connected to a local runtime with a current working directory.
- You may access local filesystem paths through tools.
- Relative paths are resolved against the current working directory.
- Absolute paths are allowed.
- If the user asks where you are, what path you are in, or what the current directory is, use pwd() or answer from the provided runtime state.
- Use ls() to inspect directories before assuming file names.
- Use find_files() when you need to locate files by name or extension.
- Use search_text() when you need to locate code, symbols, functions, variables, TODOs, or specific text.
- Do not answer filesystem-location questions as if you had no local runtime.

General rules:
- Use only the listed tools.
- Tool input must be a JSON object.
- Final answers must be inside the "final" field.
- Never output plain text outside JSON.
"""