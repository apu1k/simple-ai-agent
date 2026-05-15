from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class FileEdit:
    find: str
    replace: str


@dataclass
class PendingEdit:
    id: int
    path: Path
    original_content: str
    new_content: str
    diff: str
    edits: list[FileEdit]
    status: Literal[
        "pending",
        "approved",
        "rejected",
        "applied",
    ] = "pending"