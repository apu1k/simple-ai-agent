import json
from pathlib import Path

from tools.results import DisplayItem, ToolResult

IGNORED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "dist",
    "build",
}

MAX_FILE_SIZE_BYTES = 1_000_000

MAX_DISPLAY_FILE_SIZE_BYTES = 100_000
MAX_DISPLAY_TOTAL_BYTES = 500_000
MAX_DISPLAY_FILES = 30
MAX_DISPLAY_LINES = 2_000


def resolve_path(state, path="."):
    target_path = Path(path).expanduser()

    if not target_path.is_absolute():
        target_path = state.cwd / target_path

    return target_path.resolve()


def should_skip_path(path):
    return any(part in IGNORED_DIRS for part in path.parts)


def quote_value(value):
    return json.dumps(str(value), ensure_ascii=False)


def format_ls_entry(entry):
    if entry.is_dir():
        entry_type = "DIR"
    elif entry.is_file():
        entry_type = "FILE"
    else:
        entry_type = "OTHER"

    return (
        f"[{entry_type}] "
        f"name={quote_value(entry.name)} "
        f"path={quote_value(entry)}"
    )


def guess_language(path):
    suffix = Path(path).suffix.lower()

    language_by_suffix = {
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
    }

    return language_by_suffix.get(suffix, "text")


def build_display_path(state, file_path):
    try:
        return str(file_path.relative_to(state.cwd))
    except ValueError:
        return str(file_path)


def build_file_panel_title(display_path, complete, start_line, end_line):
    if complete:
        return f"File: {display_path} Complete"

    return f"File: {display_path} Lines: {start_line}-{end_line}"

def direct_display_guidance():
    return (
        "Important: The file contents were rendered directly in the local CLI for the user. "
        "The contents were not returned to you in this tool result. "
        "Do not repeat, reconstruct, or include the displayed file contents in your final answer. "
        "If this completed the user's request, give only a short confirmation. "
        "If you need to inspect or analyze the file contents yourself, call read_file separately."
    )

def validate_file_for_reading(file_path):
    if not file_path.exists():
        return f"Error: File does not exist: {file_path}"

    if not file_path.is_file():
        return f"Error: Path is not a file: {file_path}"

    return None


def normalize_optional_int(value, name):
    if value is None:
        return None

    if value == "":
        return None

    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be an integer.")

    return parsed


def normalize_line_range(start_line=None, end_line=None):
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

    if end_line is not None:
        requested_lines = end_line - start_line + 1
        if requested_lines > MAX_DISPLAY_LINES:
            raise ValueError(
                f"Requested line range is too large: {requested_lines} lines. "
                f"Maximum allowed range is {MAX_DISPLAY_LINES} lines."
            )

    return start_line, end_line, False


def read_complete_file_for_display(file_path):
    if file_path.stat().st_size > MAX_DISPLAY_FILE_SIZE_BYTES:
        return (
            None,
            None,
            None,
            f"Error: File is too large to display completely: {file_path}. "
            "Request a line range instead.",
        )

    try:
        with file_path.open("r", encoding="utf-8") as f:
            content = f.read()
    except UnicodeDecodeError:
        return None, None, None, f"Error: File is not a valid UTF-8 text file: {file_path}"
    except PermissionError:
        return None, None, None, f"Error: Permission denied: {file_path}"
    except Exception as e:
        return None, None, None, f"Error: Failed to read file '{file_path}': {e}"

    line_count = len(content.splitlines())
    return content, 1, line_count, None


def read_line_range_for_display(file_path, start_line, end_line):
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

                line_bytes = len(line.encode("utf-8"))
                selected_bytes += line_bytes

                if selected_bytes > MAX_DISPLAY_FILE_SIZE_BYTES:
                    return (
                        None,
                        None,
                        f"Error: Selected line range is too large to display from: {file_path}. "
                        "Request a smaller line range.",
                    )

                selected_lines.append(line)
                end_line_actual = line_number

                if len(selected_lines) > MAX_DISPLAY_LINES:
                    return (
                        None,
                        None,
                        f"Error: Selected line range is too large. "
                        f"Maximum allowed range is {MAX_DISPLAY_LINES} lines.",
                    )

    except UnicodeDecodeError:
        return None, None, f"Error: File is not a valid UTF-8 text file: {file_path}"
    except PermissionError:
        return None, None, f"Error: Permission denied: {file_path}"
    except Exception as e:
        return None, None, f"Error: Failed to read file '{file_path}': {e}"

    if not selected_lines:
        return (
            None,
            None,
            f"Error: start_line is beyond the end of the file: {file_path}",
        )

    content = "".join(selected_lines)
    return content, end_line_actual, None


def create_file_display_item(
    state,
    file_path,
    content,
    start_line,
    end_line,
    complete,
):
    display_path = build_display_path(state, file_path)
    title = build_file_panel_title(
        display_path=display_path,
        complete=complete,
        start_line=start_line,
        end_line=end_line,
    )

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


def pwd(state):
    return str(state.cwd)


def ls(state, path="."):
    directory_path = resolve_path(state, path)

    try:
        if not directory_path.exists():
            return f"Error: Path does not exist: {directory_path}"

        if not directory_path.is_dir():
            return f"Error: Path is not a directory: {directory_path}"

        entries = sorted(
            directory_path.iterdir(),
            key=lambda entry: (not entry.is_dir(), entry.name.lower()),
        )

        if not entries:
            return f"Directory is empty: {directory_path}"

        lines = [
            f"Directory: {directory_path}",
            f"Entries: {len(entries)}",
            "",
        ]

        for entry in entries:
            lines.append(format_ls_entry(entry))

        return "\n".join(lines)

    except PermissionError:
        return f"Error: Permission denied: {directory_path}"
    except Exception as e:
        return f"Error: Failed to list directory '{directory_path}': {e}"


def cd(state, path):
    directory_path = resolve_path(state, path)

    try:
        if not directory_path.exists():
            return f"Error: Path does not exist: {directory_path}"

        if not directory_path.is_dir():
            return f"Error: Path is not a directory: {directory_path}"

        state.cwd = directory_path
        return f"Changed directory to: {state.cwd}"

    except PermissionError:
        return f"Error: Permission denied: {directory_path}"
    except Exception as e:
        return f"Error: Failed to change directory to '{directory_path}': {e}"


def read_file(state, path):
    file_path = resolve_path(state, path)

    try:
        validation_error = validate_file_for_reading(file_path)
        if validation_error:
            return validation_error

        if file_path.stat().st_size > MAX_FILE_SIZE_BYTES:
            return f"Error: File is too large to read: {file_path}"

        with file_path.open("r", encoding="utf-8") as f:
            return f.read()

    except UnicodeDecodeError:
        return f"Error: File is not a valid UTF-8 text file: {file_path}"
    except PermissionError:
        return f"Error: Permission denied: {file_path}"
    except Exception as e:
        return f"Error: Failed to read file '{file_path}': {e}"


def show_file(state, path, start_line=None, end_line=None):
    file_path = resolve_path(state, path)

    try:
        validation_error = validate_file_for_reading(file_path)
        if validation_error:
            return validation_error

        start_line, end_line, complete = normalize_line_range(start_line, end_line)

        if complete:
            content, display_start_line, display_end_line, read_error = (
                read_complete_file_for_display(file_path)
            )

            if read_error:
                return read_error

            display_item = create_file_display_item(
                state=state,
                file_path=file_path,
                content=content,
                start_line=display_start_line,
                end_line=display_end_line,
                complete=True,
            )

            observation = "\n".join([
                f"Displayed file directly to the user: {file_path}",
                f"Display range: complete file, lines 1-{display_end_line}.",
                direct_display_guidance(),
            ])

            return ToolResult(
                observation=observation,
                display_items=[display_item],
            )

        content, display_end_line, read_error = read_line_range_for_display(
            file_path=file_path,
            start_line=start_line,
            end_line=end_line,
        )

        if read_error:
            return read_error

        display_item = create_file_display_item(
            state=state,
            file_path=file_path,
            content=content,
            start_line=start_line,
            end_line=display_end_line,
            complete=False,
        )

        observation = "\n".join([
            f"Displayed file range directly to the user: {file_path}",
            f"Display range: lines {start_line}-{display_end_line}.",
            direct_display_guidance(),
        ])

        return ToolResult(
            observation=observation,
            display_items=[display_item],
        )

    except ValueError as e:
        return f"Error: Invalid line range for show_file: {e}"
    except PermissionError:
        return f"Error: Permission denied: {file_path}"
    except Exception as e:
        return f"Error: Failed to display file '{file_path}': {e}"


def find_files(state, pattern, path=".", max_results=100):
    search_root = resolve_path(state, path)

    try:
        max_results = int(max_results)

        if not search_root.exists():
            return f"Error: Path does not exist: {search_root}"

        if not search_root.is_dir():
            return f"Error: Path is not a directory: {search_root}"

        matches = []

        for item in search_root.rglob(pattern):
            if should_skip_path(item):
                continue

            if item.is_file():
                matches.append(str(item))

            if len(matches) >= max_results:
                break

        if not matches:
            return f"No files found for pattern '{pattern}' in {search_root}"

        result = [
            f"Found {len(matches)} file(s) for pattern '{pattern}' in {search_root}:",
            "",
        ]
        result.extend(matches)

        if len(matches) >= max_results:
            result.append("")
            result.append(f"Result limit reached: {max_results}")

        return "\n".join(result)

    except PermissionError:
        return f"Error: Permission denied while searching in: {search_root}"
    except Exception as e:
        return f"Error: Failed to find files in '{search_root}': {e}"


def show_files(state, pattern, path=".", max_files=MAX_DISPLAY_FILES):
    search_root = resolve_path(state, path)

    try:
        max_files = int(max_files)

        if max_files < 1:
            return "Error: max_files must be greater than or equal to 1."

        effective_max_files = min(max_files, MAX_DISPLAY_FILES)

        if not search_root.exists():
            return f"Error: Path does not exist: {search_root}"

        if not search_root.is_dir():
            return f"Error: Path is not a directory: {search_root}"

        display_items = []
        displayed_files = []
        skipped_too_large = []
        skipped_unreadable = []
        total_display_bytes = 0
        result_limit_reached = False
        total_size_limit_reached = False

        matching_paths = sorted(
            search_root.rglob(pattern),
            key=lambda candidate: str(candidate).lower(),
        )

        for file_path in matching_paths:
            if should_skip_path(file_path):
                continue

            if not file_path.is_file():
                continue

            if len(display_items) >= effective_max_files:
                result_limit_reached = True
                break

            try:
                file_size = file_path.stat().st_size
            except OSError as e:
                skipped_unreadable.append(f"{file_path} ({e})")
                continue

            if file_size > MAX_DISPLAY_FILE_SIZE_BYTES:
                skipped_too_large.append(str(file_path))
                continue

            if total_display_bytes + file_size > MAX_DISPLAY_TOTAL_BYTES:
                total_size_limit_reached = True
                break

            content, display_start_line, display_end_line, read_error = (
                read_complete_file_for_display(file_path)
            )

            if read_error:
                skipped_unreadable.append(f"{file_path} ({read_error})")
                continue

            display_item = create_file_display_item(
                state=state,
                file_path=file_path,
                content=content,
                start_line=display_start_line,
                end_line=display_end_line,
                complete=True,
            )

            display_items.append(display_item)
            displayed_files.append(display_item.display_path)
            total_display_bytes += file_size

        if not display_items:
            details = [
                f"No files were displayed for pattern '{pattern}' in {search_root}."
            ]

            if skipped_too_large:
                details.append(f"Skipped too-large files: {len(skipped_too_large)}.")

            if skipped_unreadable:
                details.append(f"Skipped unreadable files: {len(skipped_unreadable)}.")

            return " ".join(details)

        observation_lines = [
            (
                f"Displayed {len(display_items)} file(s) matching '{pattern}' "
                f"in {search_root} directly to the user."
            ),
            direct_display_guidance(),
            "",
            "Displayed files:",
        ]

        for displayed_file in displayed_files:
            observation_lines.append(f"- {displayed_file}")

        if skipped_too_large:
            observation_lines.append("")
            observation_lines.append(
                f"Skipped {len(skipped_too_large)} file(s) because they were too large."
            )

        if skipped_unreadable:
            observation_lines.append("")
            observation_lines.append(
                f"Skipped {len(skipped_unreadable)} unreadable file(s)."
            )

        if result_limit_reached:
            observation_lines.append("")
            observation_lines.append(
                f"Result limit reached: displayed at most {effective_max_files} file(s)."
            )

        if total_size_limit_reached:
            observation_lines.append("")
            observation_lines.append(
                f"Total display size limit reached: {MAX_DISPLAY_TOTAL_BYTES} bytes."
            )

        if max_files > MAX_DISPLAY_FILES:
            observation_lines.append("")
            observation_lines.append(
                f"Requested max_files was {max_files}, but hard limit is {MAX_DISPLAY_FILES}."
            )

        return ToolResult(
            observation="\n".join(observation_lines),
            display_items=display_items,
        )

    except ValueError:
        return "Error: max_files must be an integer."
    except PermissionError:
        return f"Error: Permission denied while searching in: {search_root}"
    except Exception as e:
        return f"Error: Failed to display files in '{search_root}': {e}"


def search_text(state, query, path=".", file_pattern="*", max_results=100):
    search_root = resolve_path(state, path)

    try:
        max_results = int(max_results)

        if not search_root.exists():
            return f"Error: Path does not exist: {search_root}"

        if not search_root.is_dir():
            return f"Error: Path is not a directory: {search_root}"

        matches = []

        for file_path in search_root.rglob(file_pattern):
            if should_skip_path(file_path):
                continue

            if not file_path.is_file():
                continue

            try:
                if file_path.stat().st_size > MAX_FILE_SIZE_BYTES:
                    continue

                with file_path.open("r", encoding="utf-8") as f:
                    for line_number, line in enumerate(f, start=1):
                        if query in line:
                            clean_line = line.rstrip()
                            matches.append(f"{file_path}:{line_number}: {clean_line}")

                            if len(matches) >= max_results:
                                break

                if len(matches) >= max_results:
                    break

            except (UnicodeDecodeError, PermissionError, OSError):
                continue

        if not matches:
            return (
                f"No text matches found for query '{query}' "
                f"in {search_root} with file pattern '{file_pattern}'"
            )

        result = [
            f"Found {len(matches)} text match(es) for query '{query}' "
            f"in {search_root} with file pattern '{file_pattern}':",
            "",
        ]
        result.extend(matches)

        if len(matches) >= max_results:
            result.append("")
            result.append(f"Result limit reached: {max_results}")

        return "\n".join(result)

    except PermissionError:
        return f"Error: Permission denied while searching in: {search_root}"
    except Exception as e:
        return f"Error: Failed to search text in '{search_root}': {e}"