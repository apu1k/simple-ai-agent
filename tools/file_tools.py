import json
from pathlib import Path


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
        if not file_path.exists():
            return f"Error: File does not exist: {file_path}"

        if not file_path.is_file():
            return f"Error: Path is not a file: {file_path}"

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