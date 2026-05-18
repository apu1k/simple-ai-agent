"""
editing/store.py

EditStore owns the full pending-edit lifecycle:
  propose()  →  creates a PendingEdit, returns its id
  approve()  →  writes the file, marks as applied
  reject()   →  marks as rejected without writing
  list()     →  returns all pending edits

This consolidates logic that was previously split between
agent/loop.py (approve/reject) and tools/file_tools.py (propose).
"""

from __future__ import annotations

from pathlib import Path

from editing.diff import create_unified_diff
from editing.model import FileEdit, PendingEdit


class EditStore:
    def __init__(self):
        self._edits: dict[int, PendingEdit] = {}
        self._next_id: int = 1

    # ------------------------------------------------------------------
    # Propose
    # ------------------------------------------------------------------

    def propose(
        self,
        path: Path,
        edits: list[FileEdit],
    ) -> tuple[PendingEdit, str]:
        """
        Apply edits to the file content in memory, create a PendingEdit,
        and store it. Does NOT write to disk.

        Returns (pending_edit, diff_string).
        Raises ValueError if an edit find-block is not found or matches multiple times.
        """
        original_content = path.read_text(encoding="utf-8")
        updated_content = original_content

        for edit in edits:
            updated_content = _apply_exact_edit(updated_content, edit)

        diff = create_unified_diff(path, original_content, updated_content)
        edit_id = self._next_id
        self._next_id += 1

        pending = PendingEdit(
            id=edit_id,
            path=path,
            original_content=original_content,
            new_content=updated_content,
            diff=diff,
            edits=edits,
        )
        self._edits[edit_id] = pending
        return pending, diff

    # ------------------------------------------------------------------
    # Approve
    # ------------------------------------------------------------------

    def approve(self, edit_id: int) -> str:
        """
        Write the pending edit to disk and mark it as applied.

        Returns a human-readable result message.
        Raises KeyError if the edit_id does not exist.
        Raises ValueError if the file changed since the edit was proposed.
        """
        if edit_id not in self._edits:
            raise KeyError(f"Pending edit #{edit_id} does not exist.")

        edit = self._edits[edit_id]

        current = edit.path.read_text(encoding="utf-8")
        if current != edit.original_content:
            raise ValueError(
                f"File changed since edit #{edit_id} was proposed. "
                "Edit is stale and cannot be applied safely."
            )

        edit.path.write_text(edit.new_content, encoding="utf-8")
        edit.status = "applied"
        return f"Applied pending edit #{edit_id} to {edit.path}."

    # ------------------------------------------------------------------
    # Reject
    # ------------------------------------------------------------------

    def reject(self, edit_id: int) -> str:
        """
        Mark a pending edit as rejected. Does not touch the file.

        Returns a human-readable result message.
        Raises KeyError if the edit_id does not exist.
        """
        if edit_id not in self._edits:
            raise KeyError(f"Pending edit #{edit_id} does not exist.")

        self._edits[edit_id].status = "rejected"
        return f"Rejected pending edit #{edit_id}."

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get(self, edit_id: int) -> PendingEdit | None:
        return self._edits.get(edit_id)

    def all(self) -> dict[int, PendingEdit]:
        return dict(self._edits)

    def pending(self) -> dict[int, PendingEdit]:
        return {k: v for k, v in self._edits.items() if v.status == "pending"}


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _apply_exact_edit(content: str, edit: FileEdit) -> str:
    """
    Apply one find-and-replace edit. The find-block must match exactly once.
    Raises ValueError otherwise.
    """
    matches = content.count(edit.find)

    if matches == 0:
        raise ValueError(f"Edit find-block not found in file:\n{edit.find}")

    if matches > 1:
        raise ValueError(
            "Edit find-block matched multiple locations. "
            "Each edit must match exactly once. Make the find-block more specific."
        )

    return content.replace(edit.find, edit.replace, 1)
