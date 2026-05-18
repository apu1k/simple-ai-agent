"""
tests/tools/fs/test_search.py

Tests for tools/fs/search.py: find_files, search_text.
"""

from dataclasses import dataclass
from pathlib import Path

from editing.store import EditStore
from tools.fs.search import find_files, search_text


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
# find_files
# ---------------------------------------------------------------------------

def test_find_files_finds_matching_skips_ignored(tmp_path):
    state = make_state(tmp_path)
    (tmp_path / "keep.py").write_text("x", encoding="utf-8")
    pycache = tmp_path / "__pycache__"
    pycache.mkdir()
    (pycache / "ignored.py").write_text("x", encoding="utf-8")

    result = find_files(state, "*.py", path=".", max_results=100)

    assert "Found 1 file(s)" in result
    assert "keep.py" in result
    assert "ignored.py" not in result


def test_find_files_no_results(tmp_path):
    result = find_files(make_state(tmp_path), "*.go", path=".")
    assert "No files found" in result


# ---------------------------------------------------------------------------
# search_text
# ---------------------------------------------------------------------------

def test_search_text_finds_matches(tmp_path):
    state = make_state(tmp_path)
    (tmp_path / "example.py").write_text(
        "alpha\nneedle here\nomega\n", encoding="utf-8"
    )

    result = search_text(state, "needle", path=".", file_pattern="*.py")

    assert "Found 1 text match(es)" in result
    assert "example.py:2: needle here" in result


def test_search_text_skips_ignored_dirs(tmp_path):
    state = make_state(tmp_path)
    venv = tmp_path / ".venv"
    venv.mkdir()
    (venv / "ignored.py").write_text("needle\n", encoding="utf-8")

    result = search_text(state, "needle", path=".", file_pattern="*.py")

    assert "No text matches found" in result
