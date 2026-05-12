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

You have two response modes:

1. Tool call mode
Use this only when you need to call a tool.
In tool call mode, your entire response must be exactly one valid raw JSON object:

{{
  "action": "tool_name",
  "input": {{}}
}}

2. Final answer mode
Use this when you are done and want to answer the user.
In final answer mode, write normal human-readable text.
Do not wrap final answers in JSON.
Do not use a "final" JSON field for final answers.

Strict tool call JSON rules:
- Tool calls must be valid raw JSON.
- Tool calls must not use Markdown.
- Tool calls must not use code fences.
- Tool calls must not include explanations outside the JSON object.
- Tool calls must not include comments.
- Tool calls must not include extra keys.
- Tool calls must not include multiple JSON objects.
- The JSON root must be an object.
- For tool calls, the object must contain exactly these keys: "action" and "input".
- "action" must be a string.
- "input" must be a JSON object.
- Always include "input", even if the tool has no parameters. Use an empty object: {{}}.

Tool calling rules:
- You may call only one tool per response.
- Never combine multiple tool calls in one JSON object.
- If a task requires multiple steps, call exactly one tool first.
- After receiving a tool result, decide the next step.
- If another tool is needed, call exactly one tool again.
- If no more tools are needed, answer normally in plain text.
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
- ls() returns entries with explicit name="..." and path="..." fields.
- When referring to files or directories from ls(), use the exact quoted name or path from the ls() result.
- This is important for names with spaces, special characters, leading dashes, or unusual capitalization.
- Use find_files() when you need to locate files by name or extension.
- Use search_text() when you need to locate code, symbols, functions, variables, TODOs, or specific text.
- Do not answer filesystem-location questions as if you had no local runtime.

General rules:
- Use only the listed tools.
- Use raw JSON only for tool calls.
- Use normal text for final answers.
"""