"""
tools/fs/edit.py

File edit tool: propose_file_edit.

The bug in the original code:
    resolved_path = resolve_path(state.cwd, path)
                                 ^^^^^^^^^
    resolve_path expects (state, path) — an object with a .cwd attribute.
    Passing state.cwd (a raw Path) caused an AttributeError on state.cwd.cwd.

Fixed here by passing `state` correctly.
"""

import json

from tools._base import tool
from tools.fs._shared import parse_bool, resolve_path
from editing.model import FileEdit


def _should_include_diff(state, requested: bool) -> bool:
    setting = getattr(getattr(state, "model_settings", None), "include_diff", False)
    if setting is True:
        return True
    if setting == "model":
        try:
            return parse_bool(requested, default=False)
        except ValueError:
            return False
    return False


def _proposal_result(message: str, diff: str, include_diff: bool, instruction: str) -> str:
    parts = [message]
    if include_diff:
        parts.append(f"Diff:\n{diff}")
    parts.append(instruction)
    return "\n\n".join(parts)


@tool(
    description=(
        "Propose exact-match file edits without directly modifying the file. "
        "The edit becomes pending until the user approves it with \\approve <id>. "
        "Separate proposals may target the same file: at approval, non-overlapping "
        "exact replacements are replayed on the latest content. A proposal is rejected "
        "if its changes overlap newer changes, or if a find block is missing or no "
        "longer unique."
    ),
    params={
        "path": "Path to the file to edit.",
        "edits": {
            "type": "array",
            "description": (
                "List of edits. Each edit must have 'find' and 'replace' string fields."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "find": {"type": "string"},
                    "replace": {"type": "string"},
                },
                "required": ["find", "replace"],
                "additionalProperties": False,
            },
        },
        "include_diff": {
            "type": "boolean",
            "description": (
                "Request the generated diff in the result. Defaults to false and is "
                "honored only when the runtime include-diff setting is 'model choice'."
            ),
            "default": False,
        },
    },
    requires_state=True,
    example={
        "action": "propose_file_edit",
        "input": {
            "path": "main.py",
            "edits": [{"find": "print('hello')", "replace": "print('hello world')"}],
        },
    },
)
def propose_file_edit(
    state,
    path: str,
    edits: list,
    include_diff: bool = False,
) -> str:
    if isinstance(edits, str):
        s = edits.strip()
        if not s:
            return "Error: 'edits' must be a non-empty list of edit objects."
        try:
            edits = json.loads(s)
        except Exception as e:
            return f"Error: 'edits' must be a list of edit objects (invalid JSON string): {e}"

    if isinstance(edits, dict):
        edits = [edits]

    if not isinstance(edits, list):
        return "Error: 'edits' must be a list of edit objects."

    if not edits:
        return "Error: 'edits' list is empty. Must provide at least one edit."

    # FIX: pass state (not state.cwd) so resolve_path can access state.cwd
    resolved_path = resolve_path(state, path)

    if not resolved_path.exists():
        return f"Error: File does not exist: {resolved_path}"

    if not resolved_path.is_file():
        return f"Error: Path is not a file: {resolved_path}"

    # Validate and parse edits before touching anything
    parsed_edits = []
    for i, raw_edit in enumerate(edits):
        if not isinstance(raw_edit, dict):
            return f"Error: Edit #{i + 1} must be an object with 'find' and 'replace' keys."

        find = raw_edit.get("find")
        replace = raw_edit.get("replace")

        if not isinstance(find, str):
            return f"Error: Edit #{i + 1} 'find' must be a string."
        if not isinstance(replace, str):
            return f"Error: Edit #{i + 1} 'replace' must be a string."
        if not find:
            return (
                f"Error: Edit #{i + 1} 'find' cannot be empty. "
                "Use propose_file_replace to replace the entire file, including empty files."
            )

        parsed_edits.append(FileEdit(find=find, replace=replace))

    try:
        pending_edit, diff = state.edit_store.propose(resolved_path, parsed_edits)
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error: Failed to propose edit: {e}"

    return _proposal_result(
        f"Pending edit #{pending_edit.id} created for {resolved_path}.",
        diff,
        _should_include_diff(state, include_diff),
        f"Run \\approve {pending_edit.id} to apply or \\reject {pending_edit.id} to discard.",
    )


@tool(
    description=(
        "Propose replacing the entire content of a file without directly modifying it. "
        "This is useful for empty files, notes, generated files, or complete rewrites. "
        "The replacement is added to pending edits and must be approved with \\approve <id>."
    ),
    params={
        "path": "Path to the file whose complete content should be replaced.",
        "content": "The new complete UTF-8 content for the file.",
        "create_if_missing": (
            "If true, propose creating the file when it does not exist. "
            "Defaults to false."
        ),
        "include_diff": {
            "type": "boolean",
            "description": (
                "Request the generated diff in the result. Defaults to false and is "
                "honored only when the runtime include-diff setting is 'model choice'."
            ),
            "default": False,
        },
    },
    requires_state=True,
    example={
        "action": "propose_file_replace",
        "input": {
            "path": "notes.md",
            "content": "Hello, these are my notes:\n1. make more\n",
            "create_if_missing": False,
        },
    },
)
def propose_file_replace(
    state,
    path: str,
    content: str = "",
    create_if_missing: bool = False,
    include_diff: bool = False,
) -> str:
    resolved_path = resolve_path(state, path)

    if content is None:
        content = ""

    if not isinstance(content, str):
        return "Error: 'content' must be a string."

    try:
        should_create = parse_bool(create_if_missing, default=False)
    except ValueError as e:
        return f"Error: {e}"

    try:
        pending_edit, diff = state.edit_store.propose_replace(
            resolved_path,
            content,
            create_if_missing=should_create,
        )
    except ValueError as e:
        return f"Error: {e}"
    except UnicodeDecodeError:
        return f"Error: File is not valid UTF-8: {resolved_path}"
    except PermissionError:
        return f"Error: Permission denied: {resolved_path}"
    except Exception as e:
        return f"Error: Failed to propose file replacement: {e}"

    action = "creation" if pending_edit.kind == "create" else "replacement"

    return _proposal_result(
        f"Pending file {action} #{pending_edit.id} created for {resolved_path}.",
        diff,
        _should_include_diff(state, include_diff),
        f"Run \\approve {pending_edit.id} to apply or \\reject {pending_edit.id} to discard.",
    )


@tool(
    description=(
        "Propose creating a new file without writing it immediately. "
        "The creation is added to pending edits and must be approved with \\approve <id>."
    ),
    params={
        "path": "Path of the file to create.",
        "content": "Initial UTF-8 content for the new file.",
        "include_diff": {
            "type": "boolean",
            "description": (
                "Request the generated diff in the result. Defaults to false and is "
                "honored only when the runtime include-diff setting is 'model choice'."
            ),
            "default": False,
        },
    },
    requires_state=True,
)
def create_file(
    state,
    path: str,
    content: str = "",
    include_diff: bool = False,
) -> str:
    resolved_path = resolve_path(state, path)

    if resolved_path.exists():
        return f"Error: File already exists: {resolved_path}"

    try:
        pending_edit, diff = state.edit_store.propose_create(resolved_path, content)
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error: Failed to propose file creation: {e}"

    return _proposal_result(
        f"Pending file creation #{pending_edit.id} created for {resolved_path}.",
        diff,
        _should_include_diff(state, include_diff),
        f"Run \\approve {pending_edit.id} to create or \\reject {pending_edit.id} to discard.",
    )
