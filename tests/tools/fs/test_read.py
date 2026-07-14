"""
tests/tools/fs/test_read.py

Tests for tools/fs/read.py: pwd, ls, cd, and read_file.
"""

import sys
import types

import pytest
from dataclasses import dataclass
from pathlib import Path

from editing.store import EditStore
from tools.fs.read import pwd, ls, cd, read_file


@dataclass
class FakeState:
    cwd: Path
    edit_store: EditStore = None

    def __post_init__(self):
        if self.edit_store is None:
            self.edit_store = EditStore()


def make_state(tmp_path):
    return FakeState(cwd=tmp_path)


# ---------------------------------------------------------------------------
# pwd
# ---------------------------------------------------------------------------

def test_pwd_returns_cwd(tmp_path):
    state = make_state(tmp_path)
    assert pwd(state) == str(tmp_path)


# ---------------------------------------------------------------------------
# ls
# ---------------------------------------------------------------------------

def test_ls_lists_files_and_dirs(tmp_path):
    state = make_state(tmp_path)
    (tmp_path / "dir_a").mkdir()
    (tmp_path / "file_b.txt").write_text("hello", encoding="utf-8")

    result = ls(state, ".")

    assert "Directory:" in result
    assert "Entries: 2" in result
    assert 'name="dir_a"' in result
    assert 'name="file_b.txt"' in result
    assert "[DIR]" in result
    assert "[FILE]" in result


def test_ls_error_on_missing_path(tmp_path):
    result = ls(make_state(tmp_path), "does-not-exist")
    assert result.startswith("Error:")
    assert "does not exist" in result


# ---------------------------------------------------------------------------
# cd
# ---------------------------------------------------------------------------

def test_cd_changes_cwd(tmp_path):
    state = make_state(tmp_path)
    target = tmp_path / "target"
    target.mkdir()

    result = cd(state, "target")

    assert result == f"Changed directory to: {target.resolve()}"
    assert state.cwd == target.resolve()


def test_cd_error_on_file(tmp_path):
    state = make_state(tmp_path)
    (tmp_path / "file.txt").write_text("x", encoding="utf-8")

    result = cd(state, "file.txt")

    assert result.startswith("Error:")
    assert "not a directory" in result
    assert state.cwd == tmp_path   # unchanged


# ---------------------------------------------------------------------------
# read_file
# ---------------------------------------------------------------------------

def test_read_file_returns_content(tmp_path):
    state = make_state(tmp_path)
    (tmp_path / "hello.txt").write_text("hello world", encoding="utf-8")
    assert read_file(state, "hello.txt") == "hello world"


def test_read_file_error_missing(tmp_path):
    result = read_file(make_state(tmp_path), "missing.txt")
    assert result.startswith("Error:")
    assert "does not exist" in result


def test_read_file_error_on_directory(tmp_path):
    (tmp_path / "some_dir").mkdir()
    result = read_file(make_state(tmp_path), "some_dir")
    assert result.startswith("Error:")
    assert "not a file" in result


def test_read_file_error_too_large(tmp_path, monkeypatch):
    import tools.fs._shared as shared
    state = make_state(tmp_path)
    (tmp_path / "large.txt").write_text("1234567890", encoding="utf-8")
    monkeypatch.setattr(shared, "MAX_FILE_SIZE_BYTES", 5)

    result = read_file(state, "large.txt")
    assert result.startswith("Error:")
    assert "too large" in result


def test_read_file_line_range_returns_content(tmp_path):
    state = make_state(tmp_path)
    (tmp_path / "lines.txt").write_text("line 1\nline 2\nline 3\nline 4\n", encoding="utf-8")

    result = read_file(state, "lines.txt", start_line=2, end_line=3)

    assert result == "line 2\nline 3\n"


def test_read_file_line_range_open_end(tmp_path):
    state = make_state(tmp_path)
    (tmp_path / "lines.txt").write_text("line 1\nline 2\nline 3\n", encoding="utf-8")

    result = read_file(state, "lines.txt", start_line=2)

    assert result == "line 2\nline 3\n"


@pytest.mark.parametrize("start_line,end_line,expected", [
    (0, 2, "greater than or equal to 1"),
    (5, 2, "greater than or equal to start_line"),
    ("abc", 2, "must be an integer"),
    (1, "abc", "must be an integer"),
])
def test_read_file_line_range_invalid_values(tmp_path, start_line, end_line, expected):
    state = make_state(tmp_path)
    (tmp_path / "lines.txt").write_text("line 1\nline 2\n", encoding="utf-8")

    result = read_file(state, "lines.txt", start_line=start_line, end_line=end_line)

    assert result.startswith("Error:")
    assert "Invalid line range" in result
    assert expected in result


def test_read_file_line_range_start_beyond_eof(tmp_path):
    state = make_state(tmp_path)
    (tmp_path / "lines.txt").write_text("line 1\nline 2\n", encoding="utf-8")

    result = read_file(state, "lines.txt", start_line=10, end_line=12)

    assert result.startswith("Error:")
    assert "beyond end of file" in result


def test_read_file_pdf_returns_markdown_with_page_separators(tmp_path, monkeypatch):
    state = make_state(tmp_path)
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF fake")

    class FakeDoc:
        needs_pass = False
        is_encrypted = False
        page_count = 2

        def close(self):
            pass

    fake_fitz = types.SimpleNamespace(open=lambda path: FakeDoc())

    def fake_to_markdown(path, pages=None):
        if pages == [0]:
            return "# Page One\ncontent one"
        if pages == [1]:
            return "## Page Two\ncontent two"
        return ""

    fake_pymupdf4llm = types.SimpleNamespace(to_markdown=fake_to_markdown)

    monkeypatch.setitem(sys.modules, "fitz", fake_fitz)
    monkeypatch.setitem(sys.modules, "pymupdf4llm", fake_pymupdf4llm)

    result = read_file(state, "doc.pdf")

    assert "[PDF extracted as Markdown: doc.pdf]" in result
    assert "[Total extracted Markdown lines:" in result
    assert "--- Page 1 ---" in result
    assert "# Page One" in result
    assert "content one" in result
    assert "--- Page 2 ---" in result
    assert "## Page Two" in result
    assert "content two" in result


def test_read_file_pdf_line_range_returns_selected_markdown_lines(tmp_path, monkeypatch):
    state = make_state(tmp_path)
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF fake")

    class FakeDoc:
        needs_pass = False
        is_encrypted = False
        page_count = 1

        def close(self):
            pass

    fake_fitz = types.SimpleNamespace(open=lambda path: FakeDoc())
    fake_pymupdf4llm = types.SimpleNamespace(
        to_markdown=lambda path, pages=None: "alpha\nbravo\ncharlie\ndelta"
    )

    monkeypatch.setitem(sys.modules, "fitz", fake_fitz)
    monkeypatch.setitem(sys.modules, "pymupdf4llm", fake_pymupdf4llm)

    result = read_file(state, "doc.pdf", start_line=4, end_line=5)

    assert "[PDF extracted as Markdown: doc.pdf]" in result
    assert "[Showing extracted Markdown lines 4-5 of 6]" in result
    assert "bravo\ncharlie" in result
    assert "alpha" not in result
    assert "delta" not in result


def test_read_file_pdf_line_range_start_beyond_extracted_markdown(tmp_path, monkeypatch):
    state = make_state(tmp_path)
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF fake")

    class FakeDoc:
        needs_pass = False
        is_encrypted = False
        page_count = 1

        def close(self):
            pass

    fake_fitz = types.SimpleNamespace(open=lambda path: FakeDoc())
    fake_pymupdf4llm = types.SimpleNamespace(
        to_markdown=lambda path, pages=None: "only one line"
    )

    monkeypatch.setitem(sys.modules, "fitz", fake_fitz)
    monkeypatch.setitem(sys.modules, "pymupdf4llm", fake_pymupdf4llm)

    result = read_file(state, "doc.pdf", start_line=99, end_line=100)

    assert result.startswith("Error:")
    assert "beyond end of extracted PDF Markdown" in result


def test_read_file_pdf_encrypted_returns_clear_error(tmp_path, monkeypatch):
    state = make_state(tmp_path)
    pdf = tmp_path / "locked.pdf"
    pdf.write_bytes(b"%PDF fake")

    class FakeDoc:
        needs_pass = True
        is_encrypted = True
        page_count = 1

        def close(self):
            pass

    fake_fitz = types.SimpleNamespace(open=lambda path: FakeDoc())
    fake_pymupdf4llm = types.SimpleNamespace(
        to_markdown=lambda path, pages=None: "should not be called"
    )

    monkeypatch.setitem(sys.modules, "fitz", fake_fitz)
    monkeypatch.setitem(sys.modules, "pymupdf4llm", fake_pymupdf4llm)

    result = read_file(state, "locked.pdf")

    assert result.startswith("Error:")
    assert "encrypted/password-protected PDF" in result
    assert "not currently supported" in result


def test_read_file_pdf_scanned_or_image_only_returns_clear_error(tmp_path, monkeypatch):
    state = make_state(tmp_path)
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF fake")

    class FakeDoc:
        needs_pass = False
        is_encrypted = False
        page_count = 2

        def close(self):
            pass

    fake_fitz = types.SimpleNamespace(open=lambda path: FakeDoc())
    fake_pymupdf4llm = types.SimpleNamespace(
        to_markdown=lambda path, pages=None: ""
    )

    monkeypatch.setitem(sys.modules, "fitz", fake_fitz)
    monkeypatch.setitem(sys.modules, "pymupdf4llm", fake_pymupdf4llm)

    result = read_file(state, "scan.pdf")

    assert result.startswith("Error:")
    assert "No extractable text" in result
    assert "OCR is not currently enabled" in result


def test_read_file_pdf_missing_dependency_returns_clear_error(tmp_path, monkeypatch):
    state = make_state(tmp_path)
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF fake")

    monkeypatch.setitem(sys.modules, "pymupdf4llm", None)

    result = read_file(state, "doc.pdf")

    assert result.startswith("Error:")
    assert "pymupdf4llm" in result
    assert "pip install pymupdf4llm" in result
