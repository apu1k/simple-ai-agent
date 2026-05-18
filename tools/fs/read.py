"""
tools/fs/read.py

Filesystem read tools: pwd, ls, cd, read_file, show_file, show_files.

All tools here work on the local filesystem relative to state.cwd.
They only import from tools/_base.py and tools/fs/_shared.py.
"""

import json
from pathlib import Path

import tools.fs._shared as _s
from tools._base import tool, ToolResult


# ---------------------------------------------------------------------------
# pwd
# ---------------------------------------------------------------------------

@tool(
    description="Show the current local working directory of the agent.",
    requires_state=True,
    example={"action": "pwd", "input": {}},
)
def pwd(state) -> str:
    return str(state.cwd)


# ---------------------------------------------------------------------------
# ls
# ---------------------------------------------------------------------------

def _quote(value) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def _format_entry(entry: Path) -> str:
    if entry.is_dir():
        kind = "DIR"
    elif entry.is_file():
        kind = "FILE"
    else:
        kind = "OTHER"
    return f"[{kind}] name={_quote(entry.name)} path={_quote(entry)}"


@tool(
    description=(
        "List files and directories in a local directory. "
        "Relative paths are resolved against the current working directory."
    ),
    params={"path": "Directory path to list. Defaults to '.'."},
    requires_state=True,
    example={"action": "ls", "input": {"path": "."}},
)
def ls(state, path=".") -> str:
    directory = _s.resolve_path(state, path)

    try:
        if not directory.exists():
            return f"Error: Path does not exist: {directory}"
        if not directory.is_dir():
            return f"Error: Path is not a directory: {directory}"

        entries = sorted(
            directory.iterdir(),
            key=lambda e: (not e.is_dir(), e.name.lower()),
        )

        if not entries:
            return f"Directory is empty: {directory}"

        lines = [f"Directory: {directory}", f"Entries: {len(entries)}", ""]
        lines.extend(_format_entry(e) for e in entries)
        return "\n".join(lines)

    except PermissionError:
        return f"Error: Permission denied: {directory}"
    except Exception as e:
        return f"Error: Failed to list directory '{directory}': {e}"


# ---------------------------------------------------------------------------
# cd
# ---------------------------------------------------------------------------

@tool(
    description="Change the current local working directory.",
    params={"path": "Directory path to change into."},
    requires_state=True,
    example={"action": "cd", "input": {"path": "tools"}},
)
def cd(state, path: str) -> str:
    directory = _s.resolve_path(state, path)

    try:
        if not directory.exists():
            return f"Error: Path does not exist: {directory}"
        if not directory.is_dir():
            return f"Error: Path is not a directory: {directory}"

        state.cwd = directory
        return f"Changed directory to: {state.cwd}"

    except PermissionError:
        return f"Error: Permission denied: {directory}"
    except Exception as e:
        return f"Error: Failed to change directory to '{directory}': {e}"


# ---------------------------------------------------------------------------
# read_file
# ---------------------------------------------------------------------------

@tool(
    description=(
        "Read a UTF-8 text file and return its contents to the model for analysis. "
        "Use this when you need to inspect, reason about, summarize, or modify file contents."
    ),
    params={"path": "File path to read. Relative and absolute paths are allowed."},
    requires_state=True,
    example={"action": "read_file", "input": {"path": "main.py"}},
)
def read_file(state, path: str) -> str:
    file_path = _s.resolve_path(state, path)

    try:
        error = _s.validate_file_for_reading(file_path)
        if error:
            return error

        if file_path.stat().st_size > _s.MAX_FILE_SIZE_BYTES:
            return f"Error: File is too large to read: {file_path}"

        with file_path.open("r", encoding="utf-8") as f:
            return f.read()

    except UnicodeDecodeError:
        return f"Error: File is not valid UTF-8: {file_path}"
    except PermissionError:
        return f"Error: Permission denied: {file_path}"
    except Exception as e:
        return f"Error: Failed to read file '{file_path}': {e}"


# ---------------------------------------------------------------------------
# show_file
# ---------------------------------------------------------------------------

@tool(
    description=(
        "Display a UTF-8 text file, or a line range from a file, directly to the user. "
        "File contents are NOT returned to the model — use read_file if you need to inspect them. "
        "Use this only when the user explicitly asks to see a file."
    ),
    params={
        "path": "File path to display.",
        "start_line": "Optional 1-based start line.",
        "end_line": "Optional 1-based inclusive end line.",
    },
    requires_state=True,
    example={"action": "show_file", "input": {"path": "main.py"}},
)
def show_file(state, path: str, start_line=None, end_line=None):
    file_path = _s.resolve_path(state, path)

    try:
        error = _s.validate_file_for_reading(file_path)
        if error:
            return error

        start_line, end_line, complete = _s.normalize_line_range(start_line, end_line)

        if complete:
            content, s, e, read_error = _s.read_complete_file_for_display(file_path)
            if read_error:
                return read_error

            display_item = _s.create_file_display_item(state, file_path, content, s, e, True)
            observation = "\n".join([
                f"Displayed file directly to the user: {file_path}",
                f"Display range: complete file, lines 1-{e}.",
                _s.direct_display_guidance(),
            ])
            return ToolResult(observation=observation, display_items=[display_item])

        content, actual_end, read_error = _s.read_line_range_for_display(file_path, start_line, end_line)
        if read_error:
            return read_error

        display_item = _s.create_file_display_item(state, file_path, content, start_line, actual_end, False)
        observation = "\n".join([
            f"Displayed file range directly to the user: {file_path}",
            f"Display range: lines {start_line}-{actual_end}.",
            _s.direct_display_guidance(),
        ])
        return ToolResult(observation=observation, display_items=[display_item])

    except ValueError as e:
        return f"Error: Invalid line range: {e}"
    except PermissionError:
        return f"Error: Permission denied: {file_path}"
    except Exception as e:
        return f"Error: Failed to display file '{file_path}': {e}"


# ---------------------------------------------------------------------------
# show_files
# ---------------------------------------------------------------------------

@tool(
    description=(
        "Recursively find matching UTF-8 text files and display their complete contents "
        "directly to the user. File contents are NOT returned to the model. "
        "Use this when the user asks to see many files at once."
    ),
    params={
        "pattern": "Filename pattern, e.g. '*.py', '*.md'.",
        "path": "Directory to search in. Defaults to '.'.",
        "max_files": "Maximum number of files to display.",
    },
    requires_state=True,
    example={"action": "show_files", "input": {"pattern": "*.py", "path": ".", "max_files": 30}},
)
def show_files(state, pattern: str, path=".", max_files=_s.MAX_DISPLAY_FILES):
    search_root = _s.resolve_path(state, path)

    try:
        max_files = int(max_files)
        if max_files < 1:
            return "Error: max_files must be at least 1."

        effective_max = min(max_files, _s.MAX_DISPLAY_FILES)

        if not search_root.exists():
            return f"Error: Path does not exist: {search_root}"
        if not search_root.is_dir():
            return f"Error: Path is not a directory: {search_root}"

        display_items = []
        displayed_files = []
        skipped_too_large = []
        skipped_unreadable = []
        total_bytes = 0
        result_limit_reached = False
        size_limit_reached = False

        matching = sorted(search_root.rglob(pattern), key=lambda p: str(p).lower())

        for file_path in matching:
            if _s.should_skip_path(file_path) or not file_path.is_file():
                continue

            if len(display_items) >= effective_max:
                result_limit_reached = True
                break

            try:
                file_size = file_path.stat().st_size
            except OSError as e:
                skipped_unreadable.append(f"{file_path} ({e})")
                continue

            if file_size > _s.MAX_DISPLAY_FILE_SIZE_BYTES:
                skipped_too_large.append(str(file_path))
                continue

            if total_bytes + file_size > _s.MAX_DISPLAY_TOTAL_BYTES:
                size_limit_reached = True
                break

            content, s, e, read_error = _s.read_complete_file_for_display(file_path)
            if read_error:
                skipped_unreadable.append(f"{file_path} ({read_error})")
                continue

            item = _s.create_file_display_item(state, file_path, content, s, e, True)
            display_items.append(item)
            displayed_files.append(item.display_path)
            total_bytes += file_size

        if not display_items:
            parts = [f"No files were displayed for pattern '{pattern}' in {search_root}."]
            if skipped_too_large:
                parts.append(f"Skipped {len(skipped_too_large)} too-large file(s).")
            if skipped_unreadable:
                parts.append(f"Skipped {len(skipped_unreadable)} unreadable file(s).")
            return " ".join(parts)

        obs_lines = [
            f"Displayed {len(display_items)} file(s) matching '{pattern}' in {search_root}.",
            _s.direct_display_guidance(),
            "",
            "Displayed files:",
            *[f"- {f}" for f in displayed_files],
        ]
        if skipped_too_large:
            obs_lines.append(f"\nSkipped {len(skipped_too_large)} too-large file(s).")
        if skipped_unreadable:
            obs_lines.append(f"Skipped {len(skipped_unreadable)} unreadable file(s).")
        if result_limit_reached:
            obs_lines.append(f"Result limit reached: displayed at most {effective_max} file(s).")
        if size_limit_reached:
            obs_lines.append(f"Total size limit reached: {_s.MAX_DISPLAY_TOTAL_BYTES} bytes.")

        return ToolResult(observation="\n".join(obs_lines), display_items=display_items)

    except ValueError:
        return "Error: max_files must be an integer."
    except PermissionError:
        return f"Error: Permission denied while searching in: {search_root}"
    except Exception as e:
        return f"Error: Failed to display files in '{search_root}': {e}"