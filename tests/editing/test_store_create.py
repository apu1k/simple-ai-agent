from pathlib import Path

import pytest

from editing.store import EditStore


def test_propose_create_adds_pending_with_create_kind(tmp_path: Path):
    store = EditStore()
    target = tmp_path / "new_file.txt"

    pending, diff = store.propose_create(target, "hello\nworld\n")

    assert pending.id == 1
    assert pending.path == target
    assert pending.kind == "create"
    assert pending.status == "pending"
    assert pending.original_content == ""
    assert pending.new_content == "hello\nworld\n"
    assert pending.edits == []
    assert target.exists() is False
    assert "new_file.txt" in diff or str(target) in diff
    assert store.pending()[1].kind == "create"


def test_approve_create_writes_file_and_marks_applied(tmp_path: Path):
    store = EditStore()
    target = tmp_path / "dir" / "created.py"

    pending, _ = store.propose_create(target, "print('ok')\n")
    msg = store.approve(pending.id)

    assert target.exists() is True
    assert target.read_text(encoding="utf-8") == "print('ok')\n"
    assert store.get(pending.id).status == "applied"
    assert f"#{pending.id}" in msg


def test_reject_create_does_not_write_file(tmp_path: Path):
    store = EditStore()
    target = tmp_path / "nope.md"

    pending, _ = store.propose_create(target, "# title\n")
    msg = store.reject(pending.id)

    assert target.exists() is False
    assert store.get(pending.id).status == "rejected"
    assert f"#{pending.id}" in msg


def test_propose_create_fails_if_file_already_exists(tmp_path: Path):
    store = EditStore()
    target = tmp_path / "exists.txt"
    target.write_text("already here", encoding="utf-8")

    with pytest.raises(ValueError, match="already exists"):
        store.propose_create(target, "new content")


def test_approve_create_fails_if_file_appears_before_approval(tmp_path: Path):
    store = EditStore()
    target = tmp_path / "race.txt"

    pending, _ = store.propose_create(target, "planned\n")
    target.write_text("someone else created this", encoding="utf-8")

    with pytest.raises(ValueError, match="already exists"):
        store.approve(pending.id)