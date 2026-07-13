"""
editing/store.py

EditStore owns the full pending-change lifecycle:
  propose()         → creates a PendingEdit, returns its id
  propose_create()  → proposes creating a file
  propose_move()    → proposes moving/renaming a file or directory
  propose_delete()  → proposes deleting a file or directory
  propose_copy()    → proposes copying a file or directory
  approve()         → writes/applies the pending change, marks it as applied
  reject()          → marks as rejected without writing/applying
  pending()         → returns all pending changes

This store intentionally re-validates filesystem state at approval time. Exact
find-and-replace edits can be safely replayed on changed file content, while
ambiguous, conflicting, and whole-file replacements are rejected as stale.
"""

from __future__ import annotations

import shutil
from difflib import SequenceMatcher
from pathlib import Path

from editing.diff import create_unified_diff
from editing.model import FileEdit, PendingEdit


MAX_OPERATION_PREVIEW_ENTRIES = 100
MAX_CHARACTER_DIFF_CELLS = 1_000_000


class EditStore:
    def __init__(self):
        self._edits: dict[int, PendingEdit] = {}
        self._next_id: int = 1

    # ------------------------------------------------------------------
    # Propose content edits
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
            kind="edit",
        )
        self._edits[edit_id] = pending
        return pending, diff

    def propose_create(self, path: Path, content: str) -> tuple[PendingEdit, str]:
        """
        Create a pending proposal for creating a brand-new file.
        Does NOT write to disk until approve() is called.
        """
        if path.exists():
            raise ValueError(f"File already exists: {path}")

        diff = create_unified_diff(path, "", content)
        edit_id = self._next_id
        self._next_id += 1

        pending = PendingEdit(
            id=edit_id,
            path=path,
            original_content="",
            new_content=content,
            diff=diff,
            edits=[],
            kind="create",
        )
        self._edits[edit_id] = pending
        return pending, diff

    def propose_replace(
        self,
        path: Path,
        content: str,
        create_if_missing: bool = False,
    ) -> tuple[PendingEdit, str]:
        """
        Create a pending proposal for replacing the complete content of a file.
        Does NOT write to disk until approve() is called.

        If create_if_missing is true and the file does not exist, this delegates
        to propose_create().
        """
        if not path.exists():
            if create_if_missing:
                return self.propose_create(path, content)
            raise ValueError(f"File does not exist: {path}")

        if not path.is_file():
            raise ValueError(f"Path is not a file: {path}")

        original_content = path.read_text(encoding="utf-8")

        if original_content == content:
            raise ValueError("New content is identical to existing file content.")

        diff = create_unified_diff(path, original_content, content)
        edit_id = self._next_id
        self._next_id += 1

        pending = PendingEdit(
            id=edit_id,
            path=path,
            original_content=original_content,
            new_content=content,
            diff=diff,
            edits=[],
            kind="edit",
        )
        self._edits[edit_id] = pending
        return pending, diff

    # ------------------------------------------------------------------
    # Propose filesystem operations
    # ------------------------------------------------------------------

    def propose_move(
        self,
        source: Path,
        destination: Path,
        force: bool = False,
    ) -> tuple[PendingEdit, str]:
        """
        Create a pending proposal for moving/renaming a file or directory.
        Does NOT touch disk until approve() is called.
        """
        if not source.exists():
            raise ValueError(f"Source does not exist: {source}")
        if source == destination:
            raise ValueError("Source and destination are the same path.")
        if source.is_dir() and _is_relative_to(destination, source):
            raise ValueError(f"Cannot move a directory into itself: {source} -> {destination}")
        if destination.exists() and not force:
            raise ValueError(f"Destination already exists: {destination}")

        preview = _operation_preview(
            "Pending filesystem operation: move/rename",
            [
                f"Source: {source}",
                f"Destination: {destination}",
                f"Source type: {'directory' if source.is_dir() else 'file'}",
                f"Force overwrite: {force}",
            ],
        )

        edit_id = self._next_id
        self._next_id += 1

        pending = PendingEdit(
            id=edit_id,
            path=source,
            original_content="",
            new_content="",
            diff=preview,
            edits=[],
            kind="move",
            destination_path=destination,
            force=force,
            is_directory=source.is_dir(),
        )
        self._edits[edit_id] = pending
        return pending, preview

    def propose_delete(
        self,
        path: Path,
        recursive: bool = False,
        force: bool = False,
    ) -> tuple[PendingEdit, str]:
        """
        Create a pending proposal for deleting a file or directory.
        Does NOT touch disk until approve() is called.
        """
        if not path.exists():
            if not force:
                raise ValueError(f"Path does not exist: {path}")
            preview = _operation_preview(
                "Pending filesystem operation: delete",
                [
                    f"Path: {path}",
                    "Path currently does not exist.",
                    "Force: true",
                    "Approval will mark this operation as applied if the path is still absent.",
                ],
            )
            is_directory = False
        else:
            is_directory = path.is_dir()
            if is_directory and not recursive:
                raise ValueError(
                    f"Path is a directory: {path}. "
                    "Set recursive=true to propose deleting it."
                )

            lines = [
                f"Path: {path}",
                f"Type: {'directory' if is_directory else 'file'}",
                f"Recursive: {recursive}",
                f"Force: {force}",
            ]
            if is_directory:
                lines += ["", "Will delete:", *_build_tree_preview(path)]
            else:
                lines += ["", f"Will delete file: {path}"]
            preview = _operation_preview("Pending filesystem operation: delete", lines)

        edit_id = self._next_id
        self._next_id += 1

        pending = PendingEdit(
            id=edit_id,
            path=path,
            original_content="",
            new_content="",
            diff=preview,
            edits=[],
            kind="delete",
            recursive=recursive,
            force=force,
            is_directory=is_directory,
        )
        self._edits[edit_id] = pending
        return pending, preview

    def propose_copy(
        self,
        source: Path,
        destination: Path,
        recursive: bool = False,
        force: bool = False,
    ) -> tuple[PendingEdit, str]:
        """
        Create a pending proposal for copying a file or directory.
        Does NOT touch disk until approve() is called.
        """
        if not source.exists():
            raise ValueError(f"Source does not exist: {source}")
        if source == destination:
            raise ValueError("Source and destination are the same path.")
        if source.is_dir() and not recursive:
            raise ValueError(
                f"Source is a directory: {source}. "
                "Set recursive=true to propose copying it."
            )
        if source.is_dir() and _is_relative_to(destination, source):
            raise ValueError(f"Cannot copy a directory into itself: {source} -> {destination}")
        if destination.exists() and not force:
            raise ValueError(f"Destination already exists: {destination}")

        lines = [
            f"Source: {source}",
            f"Destination: {destination}",
            f"Source type: {'directory' if source.is_dir() else 'file'}",
            f"Recursive: {recursive}",
            f"Force overwrite: {force}",
        ]
        if source.is_dir():
            lines += ["", "Will copy:", *_build_tree_preview(source)]
        preview = _operation_preview("Pending filesystem operation: copy", lines)

        edit_id = self._next_id
        self._next_id += 1

        pending = PendingEdit(
            id=edit_id,
            path=source,
            original_content="",
            new_content="",
            diff=preview,
            edits=[],
            kind="copy",
            destination_path=destination,
            recursive=recursive,
            force=force,
            is_directory=source.is_dir(),
        )
        self._edits[edit_id] = pending
        return pending, preview

    # ------------------------------------------------------------------
    # Approve
    # ------------------------------------------------------------------

    def approve(self, edit_id: int) -> str:
        """
        Apply the pending edit/operation to disk and mark it as applied.

        Raises KeyError if the edit_id does not exist.
        Raises ValueError if the pending change cannot be applied safely.
        """
        if edit_id not in self._edits:
            raise KeyError(f"Pending edit #{edit_id} does not exist.")

        edit = self._edits[edit_id]

        if edit.status != "pending":
            raise ValueError(f"Pending edit #{edit_id} is already {edit.status}.")

        if edit.kind == "edit":
            current = edit.path.read_text(encoding="utf-8")
            rebased = current != edit.original_content

            if rebased:
                if not edit.edits:
                    raise ValueError(
                        f"File changed since edit #{edit_id} was proposed. "
                        "Whole-file replacement is stale and cannot be applied safely."
                    )

                if _changes_overlap(
                    edit.original_content,
                    current,
                    edit.new_content,
                ):
                    raise ValueError(
                        f"File changed since edit #{edit_id} was proposed and its "
                        "exact replacements cannot be safely reapplied because their "
                        "changes overlap content modified since the proposal."
                    )

                updated_content = current
                try:
                    for file_edit in edit.edits:
                        updated_content = _apply_exact_edit(updated_content, file_edit)
                except ValueError as exc:
                    raise ValueError(
                        f"File changed since edit #{edit_id} was proposed and its "
                        f"exact replacements cannot be safely reapplied: {exc}"
                    ) from exc
            else:
                updated_content = edit.new_content

            edit.path.write_text(updated_content, encoding="utf-8")
            if rebased:
                message = (
                    f"Applied pending edit #{edit_id} to the updated file "
                    f"using exact-match rebasing: {edit.path}."
                )
            else:
                message = f"Applied pending edit #{edit_id} to {edit.path}."

        elif edit.kind == "create":
            if edit.path.exists():
                raise ValueError(
                    f"Cannot apply create edit #{edit_id}: file already exists at {edit.path}."
                )
            edit.path.parent.mkdir(parents=True, exist_ok=True)
            edit.path.write_text(edit.new_content, encoding="utf-8")
            message = f"Applied pending file creation #{edit_id}: {edit.path}."

        elif edit.kind == "move":
            destination = _require_destination(edit)
            if not edit.path.exists():
                raise ValueError(f"Cannot apply move #{edit_id}: source no longer exists: {edit.path}")
            if edit.path.is_dir() and _is_relative_to(destination, edit.path):
                raise ValueError(f"Cannot apply move #{edit_id}: cannot move a directory into itself.")
            if destination.exists():
                if not edit.force:
                    raise ValueError(
                        f"Cannot apply move #{edit_id}: destination already exists: {destination}"
                    )
                _remove_path(destination)

            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(edit.path), str(destination))
            message = f"Applied pending move #{edit_id}: {edit.path} -> {destination}."

        elif edit.kind == "delete":
            if not edit.path.exists():
                if edit.force:
                    message = f"Applied pending delete #{edit_id}: path already absent: {edit.path}."
                else:
                    raise ValueError(
                        f"Cannot apply delete #{edit_id}: path no longer exists: {edit.path}"
                    )
            else:
                if edit.path.is_dir() and not edit.path.is_symlink() and not edit.recursive:
                    raise ValueError(
                        f"Cannot apply delete #{edit_id}: directory requires recursive=true: {edit.path}"
                    )
                _remove_path(edit.path)
                message = f"Applied pending delete #{edit_id}: {edit.path}."

        elif edit.kind == "copy":
            destination = _require_destination(edit)
            if not edit.path.exists():
                raise ValueError(f"Cannot apply copy #{edit_id}: source no longer exists: {edit.path}")
            if edit.path.is_dir() and not edit.recursive:
                raise ValueError(
                    f"Cannot apply copy #{edit_id}: directory requires recursive=true: {edit.path}"
                )
            if edit.path.is_dir() and _is_relative_to(destination, edit.path):
                raise ValueError(f"Cannot apply copy #{edit_id}: cannot copy a directory into itself.")
            if destination.exists():
                if not edit.force:
                    raise ValueError(
                        f"Cannot apply copy #{edit_id}: destination already exists: {destination}"
                    )
                _remove_path(destination)

            destination.parent.mkdir(parents=True, exist_ok=True)
            if edit.path.is_dir():
                shutil.copytree(edit.path, destination)
            else:
                shutil.copy2(edit.path, destination)
            message = f"Applied pending copy #{edit_id}: {edit.path} -> {destination}."

        else:
            raise ValueError(f"Unknown pending edit kind: {edit.kind}")

        edit.status = "applied"
        return message

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

        edit = self._edits[edit_id]
        if edit.status != "pending":
            raise ValueError(f"Pending edit #{edit_id} is already {edit.status}.")

        edit.status = "rejected"
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
# Internal helpers
# ---------------------------------------------------------------------------

def _operation_preview(title: str, lines: list[str]) -> str:
    return "\n".join([title, "", *lines])


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, onexc=_handle_remove_error)
    else:
        _make_writable(path)
        path.unlink()


def _handle_remove_error(function, path, exc_info) -> None:
    target = Path(path)
    _make_writable(target)
    function(path)


def _make_writable(path: Path) -> None:
    try:
        path.chmod(path.stat().st_mode | 0o700)
    except FileNotFoundError:
        return


def _require_destination(edit: PendingEdit) -> Path:
    if edit.destination_path is None:
        raise ValueError(f"Pending {edit.kind} #{edit.id} is missing destination_path.")
    return edit.destination_path


def _build_tree_preview(path: Path) -> list[str]:
    """Build a bounded recursive preview for directory operations."""
    if not path.is_dir():
        return [f"[FILE] {path}"]

    lines: list[str] = []
    file_count = 0
    dir_count = 0
    other_count = 0
    truncated = False

    for child in path.rglob("*"):
        if len(lines) >= MAX_OPERATION_PREVIEW_ENTRIES:
            truncated = True
            break

        if child.is_dir():
            dir_count += 1
            kind = "DIR"
        elif child.is_file():
            file_count += 1
            kind = "FILE"
        else:
            other_count += 1
            kind = "OTHER"

        lines.append(f"[{kind}] {child}")

    lines.append("")
    lines.append(
        f"Total previewed: {file_count} file(s), "
        f"{dir_count} directorie(s), {other_count} other item(s)"
    )
    if truncated:
        lines.append(f"Preview truncated after {MAX_OPERATION_PREVIEW_ENTRIES} entries.")

    return lines


def _changes_overlap(original: str, current: str, proposed: str) -> bool:
    """Return whether current and proposed changes touch the same original region."""
    current_spans = _changed_spans(original, current)
    proposed_spans = _changed_spans(original, proposed)
    return any(
        _spans_overlap(current_span, proposed_span)
        for current_span in current_spans
        for proposed_span in proposed_spans
    )


def _changed_spans(original: str, modified: str) -> list[tuple[int, int]]:
    """Map changes to original character ranges using a line-first diff."""
    original_lines = original.splitlines(keepends=True)
    modified_lines = modified.splitlines(keepends=True)
    original_offsets = _line_offsets(original_lines)
    modified_offsets = _line_offsets(modified_lines)
    spans: list[tuple[int, int]] = []

    for tag, original_start, original_end, modified_start, modified_end in SequenceMatcher(
        None,
        original_lines,
        modified_lines,
        autojunk=False,
    ).get_opcodes():
        if tag == "equal":
            continue

        start_offset = original_offsets[original_start]
        end_offset = original_offsets[original_end]
        if tag != "replace":
            spans.append((start_offset, end_offset))
            continue

        original_block = original[start_offset:end_offset]
        modified_block = modified[
            modified_offsets[modified_start] : modified_offsets[modified_end]
        ]
        spans.extend(_character_changed_spans(original_block, modified_block, start_offset))

    return spans


def _line_offsets(lines: list[str]) -> list[int]:
    """Return the character offset at every line boundary, including EOF."""
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    return offsets


def _character_changed_spans(
    original_block: str,
    modified_block: str,
    block_offset: int,
) -> list[tuple[int, int]]:
    """Refine a changed line block to character spans when bounded in size."""
    if len(original_block) * len(modified_block) > MAX_CHARACTER_DIFF_CELLS:
        return [(block_offset, block_offset + len(original_block))]

    return [
        (block_offset + original_start, block_offset + original_end)
        for tag, original_start, original_end, _, _ in SequenceMatcher(
            None,
            original_block,
            modified_block,
            autojunk=False,
        ).get_opcodes()
        if tag != "equal"
    ]


def _spans_overlap(first: tuple[int, int], second: tuple[int, int]) -> bool:
    """Treat insertions at the same point or at a changed range boundary as overlap."""
    first_start, first_end = first
    second_start, second_end = second

    if first_start == first_end:
        return second_start <= first_start <= second_end
    if second_start == second_end:
        return first_start <= second_start <= first_end
    return first_start < second_end and second_start < first_end


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
