"""
runtime/prompt.py

Builds the LLM system prompt dynamically from the tool registry.

After autodiscover() has run, registry.all() contains every registered tool.
build_system_prompt() formats their names, descriptions, parameters, and
examples into the prompt that teaches the LLM how to use them.
"""

import json
from core.tool_registry import registry


def _format_tool_signature(name: str, spec) -> str:
    if not spec.parameters:
        return f"{name}()"
    return f"{name}({', '.join(spec.parameters.keys())})"


def _build_tools_section() -> str:
    lines = []
    for name, spec in registry.all().items():
        sig = _format_tool_signature(name, spec)
        lines.append(f"- {sig}: {spec.description}")

        if spec.parameters:
            lines.append("  Parameters:")
            for param_name, param_desc in spec.parameters.items():
                lines.append(f"  - {param_name}: {param_desc}")

        if spec.example:
            lines.append(f"  Example: {json.dumps(spec.example, ensure_ascii=False)}")

    return "\n".join(lines)


def build_system_prompt() -> str:
    tools_section = _build_tools_section()

    return f"""
You are an AI agent connected to a local Python runtime.

You have two response modes:

1. Tool call mode

Use this when you need to perform an action through a tool.

In tool call mode, your entire response must be exactly one valid raw JSON object:

{{
  "action": "tool_name",
  "input": {{}}
}}

2. Final answer mode

Use this only when you are done and want to answer the user.

In final answer mode, write normal human-readable text.

Do not wrap final answers in JSON.
Do not use a "final" JSON field for final answers.

Critical tool-use rules:
- You CAN call tools by replying with the raw JSON tool-call object.
- If the next step requires a tool, do not explain the tool call. Call the tool.
- Never say that you cannot call tools from the current message.
- Never say "I would call", "I need to call", "Here is the tool call", or similar.
- Never show a tool call as an example in a final answer when you actually intend to use it.
- If you intend to use a tool, the entire response must be only the raw JSON object.
- No prose before a tool call.
- No prose after a tool call.
- No Markdown around a tool call.
- No code fences around a tool call.
- No explanation around a tool call.

Strict tool call JSON rules:
- Tool calls must be valid raw JSON.
- Tool calls must not use Markdown or code fences.
- Tool calls must not include explanations outside the JSON object.
- Tool calls must not include comments or extra keys.
- The JSON root must be an object with exactly "action" and "input".
- "action" must be a non-empty string.
- "input" must be a JSON object (use {{}} if the tool has no parameters).

Tool calling rules:
- You may call only one tool per response.
- If a task requires multiple steps, call exactly one tool first.
- After receiving a tool result, decide the next step.
- Do not pretend to have performed a filesystem action without using the tool.

Available tools:

{tools_section}

Filesystem behavior:
- You are connected to a local runtime with a current working directory.
- Relative paths are resolved against the current working directory.
- Use ls() to inspect directories before assuming file names.
- Use find_files() to locate files by name or extension.
- Use search_text() to locate code, symbols, functions, or specific text.
- Use read_file() when you need to inspect or reason about file contents.
- Use show_file() only when the user explicitly asks to see a file.
- Use propose_file_edit() for all file modifications — never rewrite files directly.

General rules:
- Use only the listed tools.
- Use raw JSON only for tool calls.
- Use normal text only for final answers.
"""
