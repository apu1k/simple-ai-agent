"""Offline, bounded review patch from an approved base and untrusted final file list.

This does not retrieve a guest workspace or attest its contents. The caller must
bind final-file transfer to the job and sandbox before using this for a result.
No host checkout is opened, checked out or modified here.
"""

from __future__ import annotations

import difflib
import hashlib
from dataclasses import dataclass
from typing import Sequence

from night_shifts.snapshot import Snapshot, SnapshotFile, encode_snapshot, validate_workspace_files

MAX_PATCH_BYTES = 4 * 1024 * 1024


class ReviewPatchError(ValueError):
    """A complete, reviewable patch cannot be represented within the policy."""


@dataclass(frozen=True)
class ChangedFile:
    path: str
    change: str  # added, deleted, modified, mode_changed
    before_sha256: str | None
    after_sha256: str | None
    before_mode: str | None
    after_mode: str | None


@dataclass(frozen=True)
class ReviewPatch:
    base_snapshot_sha256: str
    patch: bytes
    patch_sha256: str
    changes: tuple[ChangedFile, ...]


def _git_text_lines(content: bytes) -> list[str]:
    # Only LF delimits patch lines. Python splitlines() also splits Unicode
    # separators and lone CR, silently changing the bytes in a Git patch.
    text = content.decode("utf-8")
    if "\r" in text.replace("\r\n", ""):
        raise ReviewPatchError("lone CR in a changed file needs separate review")
    pieces = text.split("\n")
    return [part + "\n" for part in pieces[:-1]] + ([pieces[-1]] if pieces[-1] else [])


def build_review_patch(
    base: Snapshot,
    final_files: Sequence[SnapshotFile],
    *,
    max_patch_bytes: int = MAX_PATCH_BYTES,
) -> ReviewPatch:
    """Compare *all* final files, not model-selected artifact references.

    Final files must come from a separately bounded, identity-checked export.
    Missing files are deletions, not silently skipped. Unsupported files and
    unrepresentable changes fail closed instead of yielding a partial patch.
    A no-op returns empty patch bytes and an empty inventory.
    """
    if type(max_patch_bytes) is not int or not 1 <= max_patch_bytes <= MAX_PATCH_BYTES:
        raise ValueError("patch byte limit is invalid")
    base_digest = hashlib.sha256(encode_snapshot(base)).hexdigest()
    final_files = tuple(final_files)  # freeze a potentially mutable retrieval buffer
    validate_workspace_files(final_files)  # allows an entirely deleted workspace
    initial = {item.path: item for item in base.files}
    final = {item.path: item for item in final_files}
    # A file-to-directory swap can depend on patch application ordering.
    for path in initial:
        if path not in final and any(other.startswith(path + "/") for other in final):
            raise ReviewPatchError("file-to-directory replacements require separate review")
    for path in final:
        if path not in initial and any(other.startswith(path + "/") for other in initial):
            raise ReviewPatchError("directory-to-file replacements require separate review")

    output = bytearray()
    changes: list[ChangedFile] = []

    def append(text: str) -> None:
        encoded = text.encode("utf-8")
        if len(output) + len(encoded) > max_patch_bytes:
            raise ReviewPatchError("review patch exceeds the byte limit")
        output.extend(encoded)

    for path in sorted(initial.keys() | final.keys()):
        before = initial.get(path)
        after = final.get(path)
        if before == after:
            continue
        if before is None:
            change = "added"
        elif after is None:
            change = "deleted"
        elif before.content == after.content:
            change = "mode_changed"
        else:
            change = "modified"
        # Headers-only creation/deletion of an empty file cannot be assumed to
        # replay on every Git version. Refuse rather than silently lose the file.
        if (before is None and after is not None and not after.content) or (
            after is None and before is not None and not before.content
        ):
            raise ReviewPatchError("creation/deletion of empty files needs patch replay support")
        changes.append(ChangedFile(
            path=path,
            change=change,
            before_sha256=hashlib.sha256(before.content).hexdigest() if before else None,
            after_sha256=hashlib.sha256(after.content).hexdigest() if after else None,
            before_mode=before.mode if before else None,
            after_mode=after.mode if after else None,
        ))
        append(f"diff --git a/{path} b/{path}\n")
        if before is None:
            assert after is not None
            append(f"new file mode {after.mode}\n")
        elif after is None:
            append(f"deleted file mode {before.mode}\n")
        elif before.mode != after.mode:
            append(f"old mode {before.mode}\nnew mode {after.mode}\n")
        if before is not None and after is not None and before.content == after.content:
            continue
        old_lines = _git_text_lines(before.content) if before else []
        new_lines = _git_text_lines(after.content) if after else []
        # difflib's metadata and hunk lines lack a trailing newline for a
        # no-newline source line. Emit Git's explicit marker in that case.
        for line in difflib.unified_diff(
            old_lines, new_lines,
            fromfile=f"a/{path}" if before else "/dev/null",
            tofile=f"b/{path}" if after else "/dev/null",
            lineterm="\n",
        ):
            if line.endswith("\n"):
                append(line)
            else:
                append(line + "\n\\ No newline at end of file\n")
    patch = bytes(output)
    return ReviewPatch(base_digest, patch, hashlib.sha256(patch).hexdigest(), tuple(changes))
