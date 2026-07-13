"""
runtime/prompt.py

Builds the LLM system prompt dynamically from the tool registry.

After autodiscover() has run, registry.all() contains every registered tool.
build_system_prompt() formats their names, descriptions, parameters, and
examples into the prompt that teaches the LLM how to use them.

For native tool calling, the prompt omits JSON syntax instructions since
tools are passed via the API instead.
"""

import json
from config import MAX_AGENT_STEPS, MAX_BATCH_TOOL_CALLS
from core.tool_registry import registry
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from runtime.state import AgentState


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
            for param_name, param_definition in spec.parameters.items():
                if isinstance(param_definition, dict):
                    param_desc = param_definition.get("description", "")
                else:
                    param_desc = param_definition
                lines.append(f"  - {param_name}: {param_desc}")

        if spec.example:
            lines.append(f"  Example: {json.dumps(spec.example, ensure_ascii=False)}")

    return "\n".join(lines)


def _runtime_context(state: "AgentState") -> str:
    """Build runtime context section of the system prompt."""
    return (
        "Current local agent runtime state:\n"
        f"- current working directory: {state.cwd}\n"
        f"- selected provider: {state.model_config.provider_label}\n"
        f"- selected model: {state.model_config.model}\n\n"
        "Important:\n"
        "- You are controlling a local agent runtime through tools.\n"
        "- If the user asks where you are in the filesystem, use the current working directory.\n"
        "- If the user asks for the current path, directory, or location, call pwd().\n"
        "- Do not answer such questions as if you were only a remote AI model.\n"
    )


def _tool_syntax_instructions() -> str:
    """Build JSON tool-call syntax instructions for parser mode."""
    return """
You have two response modes:

1. Tool call mode

Use this when you need to perform an action through a tool.

In tool call mode, your entire response must be exactly one valid raw JSON object.

Allowed tool-call JSON root shapes:

1) Single tool call:
{
  "action": "tool_name",
  "input": {}
}

2) Batch tool calls:
{
  "tool_calls": [
    {"action": "tool_name_1", "input": {}},
    {"action": "tool_name_2", "input": {}}
  ]
}

2. Final answer mode

Use this only when you are done and want to answer the user.

In final answer mode, write normal human-readable text.

Do not wrap final answers in JSON.
Do not use a "final" JSON field for final answers.

Critical tool-use rules:
- Never Say "Sure - I can do that ...". Just do it, call your tools and then answer with the results.
- You can call multiple tools before an answer.
- You may issue a single tool call or a batch of tool calls in one response.
- You CAN call tools by replying with the raw JSON tool-call object.
- If the next step requires a tool, do not explain the tool call. Call the tool.
- Never say that you cannot call tools from the current message.
- Never say "I would call", "I need to call", "Here is the tool call", or similar.
- Never show a tool call as an example in a final answer when you actually intend to use it.
- If you intend to use tools, the entire response must be only the raw JSON object.
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
- JSON root may be either:
  - single-call object with exactly "action" and "input", or
  - batch object with exactly "tool_calls".
- In a batch, each entry must contain exactly "action" and "input".
- "action" must be a non-empty string.
- "input" must be a JSON object (use {} if the tool has no parameters).

Tool calling rules:
- You may call one tool or multiple tools in a single response (batch).
- Batch calls are executed in order with fail-fast behavior.
- If one call fails, the remaining calls in that batch are skipped.
- Order dependent calls carefully.
- After receiving tool result(s), decide the next step.
- Do not pretend to have performed a filesystem action without using the tool.
"""


def build_system_prompt(state: "AgentState" = None, use_native_tools: bool = False) -> str:
    """Build the system prompt.
    
    Args:
        state: Runtime state for context injection (optional).
        use_native_tools: If True, omit JSON syntax instructions
                         (tools are passed via API instead).
    """
    tools_section = _build_tools_section()
    
    parts = []
    
    # Runtime context (if state provided)
    if state is not None:
        parts.append(_runtime_context(state))
    
    # Tool syntax instructions ONLY for JSON parser mode
    if not use_native_tools:
        parts.append(_tool_syntax_instructions())
    
    # Available tools section (always include)
    parts.append(f"Available tools:\n\n{tools_section}")
    
    # Common instructions (always include)
    parts.append(f"""
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
- Use raw JSON only for tool calls (when not using native tool calling).
- Use normal text only for final answers.

Operational constraints:
- You have a maximum of {MAX_AGENT_STEPS} steps per user message.
- Each call to the LLM (whether tool calls or a final answer) counts as one step.
- You can make up to {MAX_BATCH_TOOL_CALLS} tool calls in a single batch response.
- Plan your actions carefully, use batch tool calls when possible, and produce a final answer before running out of steps.
""")
    
    return "\n\n".join(parts)
