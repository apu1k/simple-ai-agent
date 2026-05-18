"""
editing/diff.py

Unified diff generation for pending edits.
"""

import difflib
from pathlib import Path


def create_unified_diff(path: Path, original: str, updated: str) -> str:
    return "\n".join(
        difflib.unified_diff(
            original.splitlines(),
            updated.splitlines(),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            lineterm="",
        )
    )
