"""
tools/fs/ops.py

Filesystem operation tools:
  - move_file
  - delete_path
  - copy_file
  - create_folder
  - file_info

Destructive/content-changing operations are proposed through EditStore and
require user approval with \\approve <id>.
"""

from __future__ import annotations

import os
import stat
from datetime import datetime
from pathlib import Path

from tools._base import tool
from tools.fs._shared import format_path, parse_bool, resolve_path


PROTECTED_DELETE_NAMES = {
    ".git",
    ".hg",
    ".svn",
}


def _format_time(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")


def _protected_delete_error(path: Path, force: bool) -> str | None:
    if path.name in PROTECTED_DELETE_NAMES and not force:
        return (
            f"Error: Refusing to delete protected path without force=true: {path}\n"
            "If you are sure, call delete_path with recursive=true and force=true."
        )
    return None


@tool(
    description=(
        "Propose moving or renaming a file or directory. "
        "The operation is pending until the user approves it with \\approve <id>."
    ),
    params={
        "source": "Source file or directory path.",
        "destination": "Destination path.",
        "force": "Overwrite destination if it exists. Defaults to false.",
    },
    requires_state=True,
    example={
        "action": "move_file",
        "input": {"source": "old_name.py", "destination": "new_name.py", "force": False},
    },
)
def move_file(state, source: str, destination: str, force=False) -> str:
    try:
        force = parse_bool(force, default=False)
    except ValueError as e:
        return f"Error: {e}"

    src = resolve_path(state, source)
    dst = resolve_path(state, destination)

    try:
        pending, preview = state.edit_store.propose_move(src, dst, force=force)
    except ValueError as e:
        return f"Error: {e}"
    except PermissionError:
        return f"Error: Permission denied while proposing move: {src} -> {dst}"
    except Exception as e:
        return f"Error: Failed to propose move: {e}"

    return (
        f"Pending move #{pending.id} created.\n\n"
        f"{preview}\n\n"
        f"Run \\approve {pending.id} to move/rename or \\reject {pending.id} to discard."
    )


@tool(
    description=(
        "Propose deleting a file or directory. "
        "Directories require recursive=true. "
        "The operation is pending until the user approves it with \\approve <id>."
    ),
    params={
        "path": "File or directory path to delete.",
        "recursive": "Required true for deleting directories. Defaults to false.",
        "force": "If true, approval succeeds when the path is already absent. Defaults to false.",
    },
    requires_state=True,
    example={
        "action": "delete_path",
        "input": {"path": "old_folder", "recursive": True, "force": False},
    },
)
def delete_path(state, path: str, recursive=False, force=False) -> str:
    try:
        recursive = parse_bool(recursive, default=False)
        force = parse_bool(force, default=False)
    except ValueError as e:
        return f"Error: {e}"

    target = resolve_path(state, path)

    protected_err = _protected_delete_error(target, force=force)
    if protected_err:
        return protected_err

    try:
        pending, preview = state.edit_store.propose_delete(
            target,
            recursive=recursive,
            force=force,
        )
    except ValueError as e:
        return f"Error: {e}"
    except PermissionError:
        return f"Error: Permission denied while proposing delete: {target}"
    except Exception as e:
        return f"Error: Failed to propose delete: {e}"

    return (
        f"Pending delete #{pending.id} created.\n\n"
        f"{preview}\n\n"
        f"Run \\approve {pending.id} to delete or \\reject {pending.id} to discard."
    )


@tool(
    description=(
        "Propose copying a file or directory. "
        "Directories require recursive=true. "
        "The operation is pending until the user approves it with \\approve <id>."
    ),
    params={
        "source": "Source file or directory path.",
        "destination": "Destination path.",
        "recursive": "Required true for copying directories. Defaults to false.",
        "force": "Overwrite destination if it exists. Defaults to false.",
    },
    requires_state=True,
    example={
        "action": "copy_file",
        "input": {"source": "a.txt", "destination": "b.txt", "recursive": False, "force": False},
    },
)
def copy_file(state, source: str, destination: str, recursive=False, force=False) -> str:
    try:
        recursive = parse_bool(recursive, default=False)
        force = parse_bool(force, default=False)
    except ValueError as e:
        return f"Error: {e}"

    src = resolve_path(state, source)
    dst = resolve_path(state, destination)

    try:
        pending, preview = state.edit_store.propose_copy(
            src,
            dst,
            recursive=recursive,
            force=force,
        )
    except ValueError as e:
        return f"Error: {e}"
    except PermissionError:
        return f"Error: Permission denied while proposing copy: {src} -> {dst}"
    except Exception as e:
        return f"Error: Failed to propose copy: {e}"

    return (
        f"Pending copy #{pending.id} created.\n\n"
        f"{preview}\n\n"
        f"Run \\approve {pending.id} to copy or \\reject {pending.id} to discard."
    )


@tool(
    description="Create a directory. This operation is applied immediately.",
    params={
        "path": "Directory path to create.",
        "parents": "Create parent directories as needed. Defaults to true.",
        "exist_ok": "Do not error if the directory already exists. Defaults to true.",
    },
    requires_state=True,
    example={
        "action": "create_folder",
        "input": {"path": "new_folder", "parents": True, "exist_ok": True},
    },
)
def create_folder(state, path: str, parents=True, exist_ok=True) -> str:
    try:
        parents = parse_bool(parents, default=True)
        exist_ok = parse_bool(exist_ok, default=True)
    except ValueError as e:
        return f"Error: {e}"

    directory = resolve_path(state, path)

    if directory.exists() and not directory.is_dir():
        return f"Error: Path already exists and is not a directory: {directory}"

    try:
        directory.mkdir(parents=parents, exist_ok=exist_ok)
    except FileExistsError:
        return f"Error: Directory already exists: {directory}"
    except PermissionError:
        return f"Error: Permission denied while creating directory: {directory}"
    except Exception as e:
        return f"Error: Failed to create directory '{directory}': {e}"

    return f"Directory ready: {directory}"


@tool(
    description="Get metadata for a file or directory.",
    params={
        "path": "File or directory path to inspect.",
    },
    requires_state=True,
    example={"action": "file_info", "input": {"path": "README.md"}},
)
def file_info(state, path: str) -> str:
    target = resolve_path(state, path)

    try:
        if not target.exists() and not target.is_symlink():
            return f"Error: Path does not exist: {target}"

        st = target.lstat() if target.is_symlink() else target.stat()

        if target.is_symlink():
            kind = "symlink"
        elif target.is_dir():
            kind = "directory"
        elif target.is_file():
            kind = "file"
        else:
            kind = "other"

        lines = [
            f"Path: {target}",
            f"Path: {format_path(state, target)}",
            f"Type: {kind}",
            f"Size: {st.st_size} bytes",
            f"Created: {_format_time(st.st_ctime)}",
            f"Modified: {_format_time(st.st_mtime)}",
            f"Accessed: {_format_time(st.st_atime)}",
            f"Mode: {stat.filemode(st.st_mode)}",
            f"Readable: {'yes' if os.access(target, os.R_OK) else 'no'}",
            f"Writable: {'yes' if os.access(target, os.W_OK) else 'no'}",
            f"Executable: {'yes' if os.access(target, os.X_OK) else 'no'}",
        ]

        if target.is_symlink():
            try:
                lines.append(f"Symlink target: {target.readlink()}")
            except Exception as e:
                lines.append(f"Symlink target: <failed to read: {e}>")

        if target.is_dir():
            try:
                child_count = sum(1 for _ in target.iterdir())
                lines.append(f"Direct children: {child_count}")
            except PermissionError:
                lines.append("Direct children: <permission denied>")

        return "\n".join(lines)

    except PermissionError:
        return f"Error: Permission denied while reading metadata: {target}"
    except Exception as e:
        return f"Error: Failed to get file info for '{target}': {e}"
