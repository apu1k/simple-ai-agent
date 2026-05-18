"""
tools/_base.py

The only file that tool modules need to import from outside their own folder.

Provides:
  - @tool decorator  (re-exported from core/tool_registry.py)
  - ToolResult       (what tools return when they have display items)
  - DisplayItem      (a file panel to render in the UI)

Tool modules should do:
    from tools._base import tool, ToolResult, DisplayItem
"""

from dataclasses import dataclass, field
from typing import Literal

# Re-export so tool files have a single import point.
from core.tool_registry import tool  # noqa: F401


# ---------------------------------------------------------------------------
# Display types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DisplayItem:
    """
    A piece of content to be rendered visually in the UI (e.g. a file panel).

    The tool returns this inside a ToolResult. The IO adapter decides how to
    render it — the tool itself has no knowledge of the UI.
    """
    kind: Literal["file"]
    title: str
    content: str
    path: str
    display_path: str
    language: str | None = None
    start_line: int = 1
    end_line: int = 0
    complete: bool = False


@dataclass(frozen=True)
class ToolResult:
    """
    Return type for tools that need to pass both a text observation (for the
    LLM) and visual display items (for the user's UI).

    If a tool just returns a string, that string becomes the observation.
    """
    observation: str
    display_items: list[DisplayItem] = field(default_factory=list)
