"""
tools/fs/_shared.py

Internal helpers shared by all fs/ tool modules.
NOT imported by anything outside tools/fs/.

Provides:
  - Constants (limits, ignored dirs)
  - resolve_path()
  - should_skip_path()
  - guess_language()
  - build_display_path()
  - build_file_panel_title()
  - create_file_display_item()
  - direct_display_guidance()
  - validate_file_for_reading()
  - read_complete_file_for_display()
  - read_line_range_for_display()
"""

from pathlib import Path

from tools._base import DisplayItem


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

IGNORED_DIRS = {
    ".git", ".hg", ".svn",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".venv", "venv", "env",
    "site-packages",
    "node_modules", "dist", "build",
}

MAX_FILE_SIZE_BYTES = 1_000_000          # read_file / analyze
MAX_DISPLAY_FILE_SIZE_BYTES = 100_000    # show_file / show_files (per file)
MAX_DISPLAY_TOTAL_BYTES = 500_000        # show_files (total across all files)
MAX_DISPLAY_FILES = 30
MAX_DISPLAY_LINES = 2_000
MAX_ANALYZE_FILES = 30
MAX_OPERATION_PREVIEW_ENTRIES = 100


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def resolve_path(state, path=".") -> Path:
    """Resolve a path string relative to state.cwd, or keep it absolute."""
    target = Path(path).expanduser()
    if not target.is_absolute():
        target = state.cwd / target
    return target.resolve()


def should_skip_path(path: Path) -> bool:
    return any(part in IGNORED_DIRS for part in path.parts)


def parse_bool(value, default: bool = False) -> bool:
    """
    Safely parse bool-like tool input.

    Important because bool("false") is True in Python.
    """
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y", "on"}:
            return True
        if normalized in {"false", "0", "no", "n", "off", ""}:
            return False
    raise ValueError(f"Invalid boolean value: {value!r}")


def is_inside_cwd(state, path: Path) -> bool:
    """Return True if path is inside state.cwd."""
    try:
        path.resolve().relative_to(state.cwd.resolve())
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def guess_language(path) -> str:
    suffix = Path(path).suffix.lower()
    return {
        ".py": "python",
        ".md": "markdown",
        ".json": "json",
        ".toml": "toml",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".txt": "text",
        ".env": "bash",
        ".sh": "bash",
        ".html": "html",
        ".css": "css",
        ".js": "javascript",
        ".ts": "typescript",
    }.get(suffix, "text")


def build_display_path(state, file_path: Path) -> str:
    try:
        return str(file_path.relative_to(state.cwd))
    except ValueError:
        return str(file_path)


def build_file_panel_title(display_path: str, complete: bool, start_line: int, end_line: int) -> str:
    if complete:
        return f"File: {display_path} Complete"
    return f"File: {display_path} Lines: {start_line}-{end_line}"


def create_file_display_item(state, file_path: Path, content: str, start_line: int, end_line: int, complete: bool) -> DisplayItem:
    display_path = build_display_path(state, file_path)
    title = build_file_panel_title(display_path, complete, start_line, end_line)
    return DisplayItem(
        kind="file",
        title=title,
        content=content,
        path=str(file_path),
        display_path=display_path,
        language=guess_language(file_path),
        start_line=start_line,
        end_line=end_line,
        complete=complete,
    )


def direct_display_guidance() -> str:
    return (
        "Important: The file contents were rendered directly in the local CLI for the user. "
        "The contents were not returned to you in this tool result. "
        "Do not repeat, reconstruct, or include the displayed file contents in your final answer. "
        "If this completed the user's request, give only a short confirmation. "
        "If you need to inspect or analyze the file contents yourself, call read_file separately."
    )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_file_for_reading(file_path: Path) -> str | None:
    """Return an error string if the file can't be read, or None if it's fine."""
    if not file_path.exists():
        return f"Error: File does not exist: {file_path}"
    if not file_path.is_file():
        return f"Error: Path is not a file: {file_path}"
    return None


# ---------------------------------------------------------------------------
# File reading for display
# ---------------------------------------------------------------------------

def read_complete_file_for_display(file_path: Path) -> tuple:
    """Returns (content, start_line, end_line, error) where error is str|None."""
    if file_path.stat().st_size > MAX_DISPLAY_FILE_SIZE_BYTES:
        return (
            None, None, None,
            f"Error: File is too large to display completely: {file_path}. "
            "Request a line range instead.",
        )
    try:
        with file_path.open("r", encoding="utf-8") as f:
            content = f.read()
    except UnicodeDecodeError:
        return None, None, None, f"Error: File is not valid UTF-8: {file_path}"
    except PermissionError:
        return None, None, None, f"Error: Permission denied: {file_path}"
    except Exception as e:
        return None, None, None, f"Error: Failed to read file '{file_path}': {e}"

    line_count = len(content.splitlines())
    return content, 1, line_count, None


def read_line_range_for_display(file_path: Path, start_line: int, end_line: int | None) -> tuple:
    """Returns (content, actual_end_line, error) where error is str|None."""
    selected_lines = []
    selected_bytes = 0
    end_line_actual = None

    try:
        with file_path.open("r", encoding="utf-8") as f:
            for line_number, line in enumerate(f, start=1):
                if line_number < start_line:
                    continue
                if end_line is not None and line_number > end_line:
                    break

                selected_bytes += len(line.encode("utf-8"))
                if selected_bytes > MAX_DISPLAY_FILE_SIZE_BYTES:
                    return None, None, (
                        f"Error: Selected line range is too large: {file_path}. "
                        "Request a smaller line range."
                    )

                selected_lines.append(line)
                end_line_actual = line_number

                if len(selected_lines) > MAX_DISPLAY_LINES:
                    return None, None, (
                        f"Error: Selected line range exceeds {MAX_DISPLAY_LINES} lines."
                    )

    except UnicodeDecodeError:
        return None, None, f"Error: File is not valid UTF-8: {file_path}"
    except PermissionError:
        return None, None, f"Error: Permission denied: {file_path}"
    except Exception as e:
        return None, None, f"Error: Failed to read file '{file_path}': {e}"

    if not selected_lines:
        return None, None, f"Error: start_line is beyond end of file: {file_path}"

    return "".join(selected_lines), end_line_actual, None


# ---------------------------------------------------------------------------
# Line range normalisation
# ---------------------------------------------------------------------------

def normalize_optional_int(value, name: str) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be an integer.")


def normalize_line_range(start_line=None, end_line=None) -> tuple[int | None, int | None, bool]:
    """Returns (start, end, is_complete)."""
    start_line = normalize_optional_int(start_line, "start_line")
    end_line = normalize_optional_int(end_line, "end_line")

    if start_line is None and end_line is None:
        return None, None, True

    if start_line is None:
        start_line = 1
    if start_line < 1:
        raise ValueError("start_line must be greater than or equal to 1.")
    if end_line is not None and end_line < start_line:
        raise ValueError("end_line must be greater than or equal to start_line.")
    if end_line is not None and (end_line - start_line + 1) > MAX_DISPLAY_LINES:
        raise ValueError(
            f"Requested line range is too large. Maximum is {MAX_DISPLAY_LINES} lines."
        )

    return start_line, end_line, False
