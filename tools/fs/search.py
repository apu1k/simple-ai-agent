"""
tools/fs/search.py

Filesystem search tools: find_files, search_text.
"""

from tools._base import tool
from tools.fs._shared import (
    MAX_FILE_SIZE_BYTES,
    resolve_path,
    should_skip_path,
)


@tool(
    description="Recursively find files by filename pattern.",
    params={
        "pattern": "Filename pattern, e.g. '*.py', '*.md', 'config*'.",
        "path": "Directory to search in. Defaults to '.'.",
        "max_results": "Maximum number of results to return. Defaults to 100.",
    },
    requires_state=True,
    example={"action": "find_files", "input": {"pattern": "*.py", "path": ".", "max_results": 100}},
)
def find_files(state, pattern: str, path=".", max_results=100) -> str:
    search_root = resolve_path(state, path)

    try:
        max_results = int(max_results)

        if not search_root.exists():
            return f"Error: Path does not exist: {search_root}"
        if not search_root.is_dir():
            return f"Error: Path is not a directory: {search_root}"

        matches = []
        for item in search_root.rglob(pattern):
            if should_skip_path(item) or not item.is_file():
                continue
            matches.append(str(item))
            if len(matches) >= max_results:
                break

        if not matches:
            return f"No files found for pattern '{pattern}' in {search_root}."

        lines = [f"Found {len(matches)} file(s) for pattern '{pattern}' in {search_root}:", ""]
        lines.extend(matches)
        if len(matches) >= max_results:
            lines += ["", f"Result limit reached: {max_results}"]
        return "\n".join(lines)

    except PermissionError:
        return f"Error: Permission denied while searching in: {search_root}"
    except Exception as e:
        return f"Error: Failed to find files in '{search_root}': {e}"


@tool(
    description="Recursively search for exact text in files.",
    params={
        "query": "Exact text to search for.",
        "path": "Directory to search in. Defaults to '.'.",
        "file_pattern": "Filename pattern to limit searched files. Defaults to '*'.",
        "max_results": "Maximum number of matches to return. Defaults to 100.",
    },
    requires_state=True,
    example={
        "action": "search_text",
        "input": {"query": "def parse", "path": ".", "file_pattern": "*.py", "max_results": 100},
    },
)
def search_text(state, query: str, path=".", file_pattern="*", max_results=100) -> str:
    search_root = resolve_path(state, path)

    try:
        max_results = int(max_results)

        if not search_root.exists():
            return f"Error: Path does not exist: {search_root}"
        if not search_root.is_dir():
            return f"Error: Path is not a directory: {search_root}"

        matches = []
        for file_path in search_root.rglob(file_pattern):
            if should_skip_path(file_path) or not file_path.is_file():
                continue
            try:
                if file_path.stat().st_size > MAX_FILE_SIZE_BYTES:
                    continue
                with file_path.open("r", encoding="utf-8") as f:
                    for line_number, line in enumerate(f, start=1):
                        if query in line:
                            matches.append(f"{file_path}:{line_number}: {line.rstrip()}")
                            if len(matches) >= max_results:
                                break
                if len(matches) >= max_results:
                    break
            except (UnicodeDecodeError, PermissionError, OSError):
                continue

        if not matches:
            return (
                f"No text matches found for query '{query}' "
                f"in {search_root} with file pattern '{file_pattern}'."
            )

        lines = [
            f"Found {len(matches)} text match(es) for query '{query}' "
            f"in {search_root} with file pattern '{file_pattern}':",
            "",
        ]
        lines.extend(matches)
        if len(matches) >= max_results:
            lines += ["", f"Result limit reached: {max_results}"]
        return "\n".join(lines)

    except PermissionError:
        return f"Error: Permission denied while searching in: {search_root}"
    except Exception as e:
        return f"Error: Failed to search text in '{search_root}': {e}"
