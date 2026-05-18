"""
tests/tools/fs/test_edit.py

Tests for tools/fs/edit.py — especially the bug fix where
resolve_path was called with state.cwd instead of state.
"""

from dataclasses import dataclass, field
from pathlib import Path

from editing.store import EditStore
from tools.fs.edit import propose_file_edit


@dataclass
class FakeState:
    cwd: Path
    edit_store: EditStore = field(default_factory=EditStore)


def make_state(tmp_path):
    return FakeState(cwd=tmp_path)


def test_propose_creates_pending_edit(tmp_path):
    state = make_state(tmp_path)
    f = tmp_path / "hello.py"
    f.write_text("print('hello')\n", encoding="utf-8")

    result = propose_file_edit(
        state,
        path="hello.py",
        edits=[{"find": "hello", "replace": "world"}],
    )

    assert "Pending edit #1" in result
    assert "hello.py" in result
    assert "-print('hello')" in result
    assert "+print('world')" in result

    # The file must NOT be written yet
    assert f.read_text(encoding="utf-8") == "print('hello')\n"


def test_propose_then_approve_writes_file(tmp_path):
    state = make_state(tmp_path)
    f = tmp_path / "hello.py"
    f.write_text("print('hello')\n", encoding="utf-8")

    propose_file_edit(
        state,
        path="hello.py",
        edits=[{"find": "hello", "replace": "world"}],
    )

    state.edit_store.approve(1)
    assert f.read_text(encoding="utf-8") == "print('world')\n"


def test_propose_error_file_not_found(tmp_path):
    state = make_state(tmp_path)
    result = propose_file_edit(state, path="missing.py", edits=[{"find": "x", "replace": "y"}])
    assert result.startswith("Error:")
    assert "does not exist" in result


def test_propose_error_find_not_in_file(tmp_path):
    state = make_state(tmp_path)
    (tmp_path / "f.py").write_text("hello\n", encoding="utf-8")
    result = propose_file_edit(state, path="f.py", edits=[{"find": "not_there", "replace": "x"}])
    assert result.startswith("Error:")


def test_propose_error_invalid_edit_not_dict(tmp_path):
    state = make_state(tmp_path)
    (tmp_path / "f.py").write_text("hello\n", encoding="utf-8")
    result = propose_file_edit(state, path="f.py", edits=["not a dict"])
    assert result.startswith("Error:")


def test_propose_error_find_not_string(tmp_path):
    state = make_state(tmp_path)
    (tmp_path / "f.py").write_text("hello\n", encoding="utf-8")
    result = propose_file_edit(state, path="f.py", edits=[{"find": 123, "replace": "x"}])
    assert result.startswith("Error:")


def test_bug_fix_resolve_path_uses_state_not_state_cwd(tmp_path):
    """
    Regression test for the original bug:
        resolved_path = resolve_path(state.cwd, path)
    which passed a raw Path instead of the state object.
    resolve_path(state, path) is correct — it reads state.cwd internally.
    """
    state = make_state(tmp_path)
    f = tmp_path / "f.py"
    f.write_text("old\n", encoding="utf-8")

    # This must not raise AttributeError: 'PosixPath' object has no attribute 'cwd'
    result = propose_file_edit(state, path="f.py", edits=[{"find": "old", "replace": "new"}])
    assert "Pending edit" in result
