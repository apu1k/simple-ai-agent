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


@dataclass
class PendingEdit:
    """
    A proposed file change that requires user approval before it is written.

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
