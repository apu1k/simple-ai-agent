"""
tests/editing/test_store.py

Tests for editing/store.py — the pending edit lifecycle.
"""

import pytest
from editing.model import FileEdit
from editing.store import EditStore, _apply_exact_edit


# ---------------------------------------------------------------------------
# _apply_exact_edit unit tests
# ---------------------------------------------------------------------------

def test_apply_exact_edit_replaces_once():
    content = "hello world"
    edit = FileEdit(find="world", replace="there")
    assert _apply_exact_edit(content, edit) == "hello there"


def test_apply_exact_edit_raises_if_not_found():
    with pytest.raises(ValueError, match="not found"):
        _apply_exact_edit("hello world", FileEdit(find="missing", replace="x"))


def test_apply_exact_edit_raises_if_multiple_matches():
    with pytest.raises(ValueError, match="multiple"):
        _apply_exact_edit("aa aa", FileEdit(find="aa", replace="bb"))


def test_apply_exact_edit_raises_on_empty_find():
    with pytest.raises(ValueError):
        _apply_exact_edit("hello", FileEdit(find="", replace="x"))


# ---------------------------------------------------------------------------
# EditStore.propose
# ---------------------------------------------------------------------------

def test_propose_creates_pending_edit(tmp_path):
    f = tmp_path / "hello.py"
    f.write_text("print('hello')\n", encoding="utf-8")

    store = EditStore()
    edit, diff = store.propose(f, [FileEdit(find="hello", replace="world")])

    assert edit.id == 1
    assert edit.path == f
    assert edit.status == "pending"
    assert edit.new_content == "print('world')\n"
    assert "-print('hello')" in diff
    assert "+print('world')" in diff


def test_propose_increments_ids(tmp_path):
    f = tmp_path / "f.py"
    f.write_text("a\nb\n", encoding="utf-8")

    store = EditStore()
    e1, _ = store.propose(f, [FileEdit(find="a", replace="x")])
    # reset file for second proposal
    f.write_text("a\nb\n", encoding="utf-8")
    e2, _ = store.propose(f, [FileEdit(find="b", replace="y")])

    assert e1.id == 1
    assert e2.id == 2


def test_propose_raises_on_bad_find(tmp_path):
    f = tmp_path / "f.py"
    f.write_text("hello\n", encoding="utf-8")
    store = EditStore()
    with pytest.raises(ValueError):
        store.propose(f, [FileEdit(find="not_there", replace="x")])


def test_propose_applies_multiple_edits_in_order(tmp_path):
    f = tmp_path / "f.py"
    f.write_text("A\nB\n", encoding="utf-8")

    store = EditStore()
    edit, _ = store.propose(
        f,
        [
            FileEdit(find="A\nB\n", replace="X\nB\n"),
            FileEdit(find="X\nB\n", replace="X\nY\n"),
        ],
    )

    assert edit.original_content == "A\nB\n"
    assert edit.new_content == "X\nY\n"


def test_propose_returns_diff_with_expected_markers(tmp_path):
    f = tmp_path / "f.py"
    f.write_text("hello\n", encoding="utf-8")

    store = EditStore()
    _, diff = store.propose(f, [FileEdit(find="hello", replace="hi")])

    assert "---" in diff
    assert "+++" in diff
    assert "-hello" in diff
    assert "+hi" in diff


# ---------------------------------------------------------------------------
# EditStore.approve
# ---------------------------------------------------------------------------

def test_approve_writes_file(tmp_path):
    f = tmp_path / "f.py"
    f.write_text("old content\n", encoding="utf-8")

    store = EditStore()
    edit, _ = store.propose(f, [FileEdit(find="old", replace="new")])
    message = store.approve(edit.id)

    assert f.read_text(encoding="utf-8") == "new content\n"
    assert edit.status == "applied"
    assert "applied" in message.lower()


def test_approve_raises_if_id_missing():
    store = EditStore()
    with pytest.raises(KeyError):
        store.approve(999)


def test_approve_raises_if_file_changed(tmp_path):
    f = tmp_path / "f.py"
    f.write_text("original\n", encoding="utf-8")

    store = EditStore()
    edit, _ = store.propose(f, [FileEdit(find="original", replace="changed")])

    # Simulate external change to the file
    f.write_text("something else\n", encoding="utf-8")

    with pytest.raises(ValueError, match="stale"):
        store.approve(edit.id)


def test_approve_raises_if_already_applied(tmp_path):
    f = tmp_path / "f.py"
    f.write_text("hello\n", encoding="utf-8")

    store = EditStore()
    edit, _ = store.propose(f, [FileEdit(find="hello", replace="world")])

    store.approve(edit.id)

    with pytest.raises(ValueError, match="already applied"):
        store.approve(edit.id)


def test_approve_raises_if_already_rejected(tmp_path):
    f = tmp_path / "f.py"
    f.write_text("hello\n", encoding="utf-8")

    store = EditStore()
    edit, _ = store.propose(f, [FileEdit(find="hello", replace="world")])

    store.reject(edit.id)

    with pytest.raises(ValueError, match="already rejected"):
        store.approve(edit.id)


# ---------------------------------------------------------------------------
# EditStore.reject
# ---------------------------------------------------------------------------

def test_reject_marks_edit_rejected(tmp_path):
    f = tmp_path / "f.py"
    f.write_text("hello\n", encoding="utf-8")

    store = EditStore()
    edit, _ = store.propose(f, [FileEdit(find="hello", replace="bye")])
    message = store.reject(edit.id)

    assert edit.status == "rejected"
    assert f.read_text(encoding="utf-8") == "hello\n"   # file untouched
    assert "rejected" in message.lower()


def test_reject_raises_if_id_missing():
    store = EditStore()
    with pytest.raises(KeyError):
        store.reject(42)


def test_reject_raises_if_already_rejected(tmp_path):
    f = tmp_path / "f.py"
    f.write_text("hello\n", encoding="utf-8")

    store = EditStore()
    edit, _ = store.propose(f, [FileEdit(find="hello", replace="bye")])

    store.reject(edit.id)

    with pytest.raises(ValueError, match="already rejected"):
        store.reject(edit.id)


def test_reject_raises_if_already_applied(tmp_path):
    f = tmp_path / "f.py"
    f.write_text("hello\n", encoding="utf-8")

    store = EditStore()
    edit, _ = store.propose(f, [FileEdit(find="hello", replace="world")])

    store.approve(edit.id)

    with pytest.raises(ValueError, match="already applied"):
        store.reject(edit.id)


# ---------------------------------------------------------------------------
# EditStore.pending / all
# ---------------------------------------------------------------------------

def test_pending_returns_only_pending_edits(tmp_path):
    f = tmp_path / "f.py"
    f.write_text("a\nb\nc\n", encoding="utf-8")

    store = EditStore()
    e1, _ = store.propose(f, [FileEdit(find="a", replace="x")])
    f.write_text("a\nb\nc\n", encoding="utf-8")
    e2, _ = store.propose(f, [FileEdit(find="b", replace="y")])

    store.reject(e1.id)

    pending = store.pending()
    assert e1.id not in pending
    assert e2.id in pending
