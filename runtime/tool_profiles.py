"""Explicit tool-capability profiles for head and worker agents.

Profiles are allowlists. Adding a tool to the global discovery registry does not
make it available to any agent until it is deliberately added here.
"""

from __future__ import annotations

from enum import Enum

from core.tool_registry import ToolRegistry, registry


class AgentProfile(str, Enum):
    """Supported agent roles with independently assembled tool registries."""

    HEAD = "head"
    CODING_WORKER = "coding-worker"
    READ_ONLY_WORKER = "read-only-worker"
    REVIEW_WORKER = "review-worker"


_INSPECTION_TOOLS = (
    "analyze_python_file",
    "analyze_python_files",
    "file_info",
    "pwd",
    "ls",
    "cd",
    "read_file",
    "find_files",
    "search_text",
)

_MUTATION_TOOLS = (
    "propose_file_edit",
    "propose_file_replace",
    "create_file",
    "move_file",
    "delete_path",
    "copy_file",
    "create_folder",
)

_ARITHMETIC_TOOLS = (
    "add",
    "subtract",
    "multiply",
    "divide",
    "power",
)

# Every profile is intentionally explicit. In particular, future orchestration
# tools must be added only to HEAD and must never be inherited by workers.
_PROFILE_TOOLS: dict[AgentProfile, tuple[str, ...]] = {
    AgentProfile.HEAD: (
        *_INSPECTION_TOOLS,
        *_MUTATION_TOOLS,
        "knowledge_search",
        *_ARITHMETIC_TOOLS,
        "http_get",
        "run_shell_command",
    ),
    AgentProfile.CODING_WORKER: (
        *_INSPECTION_TOOLS,
        *_MUTATION_TOOLS,
        *_ARITHMETIC_TOOLS,
        "run_shell_command",
    ),
    AgentProfile.READ_ONLY_WORKER: (
        *_INSPECTION_TOOLS,
        "knowledge_search",
        *_ARITHMETIC_TOOLS,
    ),
    AgentProfile.REVIEW_WORKER: (
        *_INSPECTION_TOOLS,
        *_ARITHMETIC_TOOLS,
        "run_shell_command",
    ),
}


def profile_tool_names(profile: AgentProfile | str) -> tuple[str, ...]:
    """Return the immutable tool allowlist for ``profile``."""
    try:
        normalized = AgentProfile(profile)
    except ValueError as exc:
        choices = ", ".join(item.value for item in AgentProfile)
        raise ValueError(f"Unknown agent profile '{profile}'. Expected one of: {choices}") from exc
    return _PROFILE_TOOLS[normalized]


def build_profile_registry(
    profile: AgentProfile | str,
    *,
    source_registry: ToolRegistry | None = None,
) -> ToolRegistry:
    """Build an independent, fail-closed registry for an agent profile."""
    source = source_registry if source_registry is not None else registry
    return source.select(profile_tool_names(profile), strict=True)
