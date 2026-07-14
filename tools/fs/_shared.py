"""
tools/fs/_shared.py

Internal helpers shared by all fs/ tool modules.
NOT imported by anything outside tools/fs/.

Provides:
  - Constants (limits, ignored dirs)
  - resolve_path()
  - should_skip_path()
  - format_path()
  - validate_file_for_reading()
  - read_line_range()
"""

from pathlib import Path


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
MAX_READ_RANGE_BYTES = 100_000
MAX_READ_RANGE_LINES = 2_000
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


def format_path(state, path: Path) -> str:
    """Format a path relative to the working directory when possible."""
    try:
        return str(path.relative_to(state.cwd))
    except ValueError:
        return str(path)


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
# File range reading
# ---------------------------------------------------------------------------

def read_line_range(file_path: Path, start_line: int, end_line: int | None) -> tuple:
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
                if selected_bytes > MAX_READ_RANGE_BYTES:
                    return None, None, (
                        f"Error: Selected line range is too large: {file_path}. "
                        "Request a smaller line range."
                    )

                selected_lines.append(line)
                end_line_actual = line_number

                if len(selected_lines) > MAX_READ_RANGE_LINES:
                    return None, None, (
                        f"Error: Selected line range exceeds {MAX_READ_RANGE_LINES} lines."
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
    if end_line is not None and (end_line - start_line + 1) > MAX_READ_RANGE_LINES:
        raise ValueError(
            f"Requested line range is too large. Maximum is {MAX_READ_RANGE_LINES} lines."
        )

    return start_line, end_line, False
