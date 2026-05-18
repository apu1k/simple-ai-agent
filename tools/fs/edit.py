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

from tools._base import tool
from tools.fs._shared import resolve_path
from editing.model import FileEdit


@tool(
    description=(
        "Propose exact-match file edits without directly modifying the file. "
        "The edit becomes pending until the user approves it with \\approve <id>."
    ),
    params={
        "path": "Path to the file to edit.",
        "edits": "List of edits. Each edit must have 'find' and 'replace' string fields.",
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
def propose_file_edit(state, path: str, edits: list) -> str:
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

        parsed_edits.append(FileEdit(find=find, replace=replace))

    try:
        pending_edit, diff = state.edit_store.propose(resolved_path, parsed_edits)
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error: Failed to propose edit: {e}"

    return (
        f"Pending edit #{pending_edit.id} created for {resolved_path}\n\n"
        f"Diff:\n{diff}\n\n"
        f"Run \\approve {pending_edit.id} to apply or \\reject {pending_edit.id} to discard."
    )
