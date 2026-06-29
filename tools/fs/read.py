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

def _is_pdf(file_path: Path) -> bool:
    return file_path.suffix.lower() == ".pdf"


def _normalize_extracted_markdown(value) -> str:
    """Normalize Markdown returned by PDF extractors."""
    if value is None:
        return ""
    if isinstance(value, list):
        value = "\n\n".join(str(item) for item in value)
    return str(value).replace("\r\n", "\n").replace("\r", "\n").strip()


def _pdf_dependency_error() -> str:
    return (
        "Error: PDF reading requires the dependency 'pymupdf4llm'. "
        "Install it with: pip install pymupdf4llm"
    )


def _import_pdf_dependencies():
    """
    Import PDF dependencies lazily so normal text-file reading does not require
    PDF packages at import time.

    Returns (pymupdf4llm, fitz, error).
    """
    try:
        import pymupdf4llm
    except ImportError:
        return None, None, _pdf_dependency_error()

    try:
        import fitz
    except ImportError:
        try:
            import pymupdf as fitz
        except ImportError:
            return None, None, _pdf_dependency_error()

    return pymupdf4llm, fitz, None


def _is_pdf_encrypted(doc) -> bool:
    return bool(
        getattr(doc, "needs_pass", False)
        or getattr(doc, "is_encrypted", False)
    )


def _pdf_exception_error(file_path: Path, exc: Exception) -> str:
    message = str(exc).lower()
    if (
        "encrypted" in message
        or "password" in message
        or "decrypt" in message
        or "authentication" in message
    ):
        return (
            f"Error: Cannot read encrypted/password-protected PDF: {file_path}. "
            "Encrypted PDFs are not currently supported."
        )
    return f"Error: Failed to extract text from PDF '{file_path}': {exc}"


def _extract_pdf_markdown(file_path: Path) -> tuple[str | None, str | None]:
    """
    Extract a PDF as Markdown using PyMuPDF4LLM.

    Returns (markdown, error). The Markdown includes tiny page separators.
    """
    pymupdf4llm, fitz, import_error = _import_pdf_dependencies()
    if import_error:
        return None, import_error

    try:
        doc = fitz.open(str(file_path))
        try:
            if _is_pdf_encrypted(doc):
                return None, (
                    f"Error: Cannot read encrypted/password-protected PDF: {file_path}. "
                    "Encrypted PDFs are not currently supported."
                )
            page_count = int(getattr(doc, "page_count", 0))
        finally:
            close = getattr(doc, "close", None)
            if callable(close):
                close()

        page_chunks = []
        for page_index in range(page_count):
            page_markdown = pymupdf4llm.to_markdown(
                str(file_path),
                pages=[page_index],
            )
            page_markdown = _normalize_extracted_markdown(page_markdown)
            if page_markdown:
                page_chunks.append(
                    f"--- Page {page_index + 1} ---\n\n{page_markdown}"
                )

        markdown = "\n\n".join(page_chunks).strip()

    except Exception as e:
        return None, _pdf_exception_error(file_path, e)

    if not markdown:
        return None, (
            f"Error: No extractable text was found in this PDF: {file_path}. "
            "It may be scanned/image-only, encrypted, or contain only embedded images. "
            "OCR is not currently enabled."
        )

    return markdown + "\n", None


def _slice_markdown_lines(
    markdown: str,
    start_line: int,
    end_line: int | None,
    file_path: Path,
) -> tuple[str | None, int | None, int, str | None]:
    """
    Slice extracted Markdown by 1-based line range.

    Returns (content, actual_end_line, total_lines, error).
    """
    lines = markdown.splitlines(keepends=True)
    total_lines = len(lines)

    if start_line > total_lines:
        return None, None, total_lines, (
            f"Error: start_line is beyond end of extracted PDF Markdown: {file_path} "
            f"({total_lines} lines)."
        )

    start_index = start_line - 1
    end_index = end_line if end_line is not None else total_lines
    selected_lines = lines[start_index:end_index]

    if len(selected_lines) > _s.MAX_DISPLAY_LINES:
        return None, None, total_lines, (
            f"Error: Selected PDF Markdown line range exceeds {_s.MAX_DISPLAY_LINES} lines. "
            "Request a smaller line range."
        )

    content = "".join(selected_lines)
    if len(content.encode("utf-8")) > _s.MAX_DISPLAY_FILE_SIZE_BYTES:
        return None, None, total_lines, (
            f"Error: Selected PDF Markdown line range is too large: {file_path}. "
            "Request a smaller line range."
        )

    actual_end = start_line + len(selected_lines) - 1
    return content, actual_end, total_lines, None


@tool(
    description=(
        "Read a UTF-8 text file or PDF and return its contents to the model for analysis. "
        "PDFs are extracted locally as Markdown using PyMuPDF4LLM. "
        "Use this when you need to inspect, reason about, summarize, or modify file contents. "
        "Optionally provide start_line/end_line to read only a specific line range."
    ),
    params={
        "path": "File path to read. Relative and absolute paths are allowed.",
        "start_line": "Optional 1-based start line.",
        "end_line": "Optional 1-based inclusive end line.",
    },
    requires_state=True,
    example={"action": "read_file", "input": {"path": "main.py"}},
)
def read_file(state, path: str, start_line=None, end_line=None) -> str:
    file_path = _s.resolve_path(state, path)

    try:
        error = _s.validate_file_for_reading(file_path)
        if error:
            return error

        start_line, end_line, complete = _s.normalize_line_range(start_line, end_line)

        if _is_pdf(file_path):
            if file_path.stat().st_size > _s.MAX_FILE_SIZE_BYTES:
                return f"Error: PDF file is too large to read: {file_path}"

            markdown, pdf_error = _extract_pdf_markdown(file_path)
            if pdf_error:
                return pdf_error

            total_lines = len(markdown.splitlines())

            if complete:
                extracted_bytes = len(markdown.encode("utf-8"))
                if extracted_bytes > _s.MAX_FILE_SIZE_BYTES:
                    return (
                        f"Error: Extracted PDF Markdown is too large to read completely: "
                        f"{file_path} ({total_lines} lines, {extracted_bytes} bytes). "
                        "Request a line range instead."
                    )

                return "\n".join([
                    f"[PDF extracted as Markdown: {file_path.name}]",
                    f"[Total extracted Markdown lines: {total_lines}]",
                    "",
                    markdown,
                ])

            content, actual_end, total_lines, range_error = _slice_markdown_lines(
                markdown,
                start_line,
                end_line,
                file_path,
            )
            if range_error:
                return range_error

            return "\n".join([
                f"[PDF extracted as Markdown: {file_path.name}]",
                f"[Showing extracted Markdown lines {start_line}-{actual_end} of {total_lines}]",
                "",
                content,
            ])

        if complete:
            if file_path.stat().st_size > _s.MAX_FILE_SIZE_BYTES:
                return f"Error: File is too large to read: {file_path}"

            with file_path.open("r", encoding="utf-8") as f:
                return f.read()

        content, _actual_end, read_error = _s.read_line_range_for_display(file_path, start_line, end_line)
        if read_error:
            return read_error
        return content

    except ValueError as e:
        return f"Error: Invalid line range: {e}"
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