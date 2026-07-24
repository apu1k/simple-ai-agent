"""
tools/fs/read.py

Filesystem read tools: pwd, ls, cd, and read_file.

All tools here work on the local filesystem relative to state.cwd.
They only import from tools/_base.py and tools/fs/_shared.py.
"""

import json
from pathlib import Path

import tools.fs._shared as _s
from tools._base import tool


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

    if len(selected_lines) > _s.MAX_READ_RANGE_LINES:
        return None, None, total_lines, (
            f"Error: Selected PDF Markdown line range exceeds {_s.MAX_READ_RANGE_LINES} lines. "
            "Request a smaller line range."
        )

    content = "".join(selected_lines)
    if len(content.encode("utf-8")) > _s.MAX_READ_RANGE_BYTES:
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
            if file_path.stat().st_size > _s.MAX_PDF_FILE_SIZE_BYTES:
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

        content, _actual_end, read_error = _s.read_line_range(file_path, start_line, end_line)
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
