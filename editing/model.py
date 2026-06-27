"""
editing/model.py

Data models for the pending-edit workflow.
No logic — just types.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class FileEdit:
    """A single find-and-replace operation within a file."""
    find: str
    replace: str


EditStatus = Literal["pending", "applied", "rejected"]
EditKind = Literal["edit", "create", "move", "delete", "copy"]


@dataclass
class PendingEdit:
    """
    A proposed file change or filesystem operation that requires user approval
    before it is written/applied.

    Lifecycle:
        pending  →  applied   (user ran \\approve <id>)
        pending  →  rejected  (user ran \\reject <id>)
    """
    id: int
    path: Path
    original_content: str
    new_content: str
    diff: str
    edits: list[FileEdit]
    status: EditStatus = "pending"
    kind: EditKind = "edit"

    # Used by pending filesystem operations such as move/copy/delete.
    destination_path: Path | None = None
    recursive: bool = False
    force: bool = False
    is_directory: bool = False
