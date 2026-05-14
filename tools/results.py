from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class DisplayItem:
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
    observation: str
    display_items: list[DisplayItem] = field(default_factory=list)