"""Offline guest-tool contract tests; no VM or repository code execution."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from night_shifts.contracts.worker_tool import WorkerToolCall
from night_shifts.guest.artifacts import ArtifactWriter
from night_shifts.guest.commands import RestrictedCommandRunner
from night_shifts.guest.repository import GuestRepository
from night_shifts.guest.tools import GuestWorkerTools


def tools(tmp_path: Path, profile: str = "coding-worker") -> tuple[Path, GuestWorkerTools]:
    root = tmp_path / "repo"
    root.mkdir()
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    return root, GuestWorkerTools(profile, RestrictedCommandRunner(root, profile),
                                  ArtifactWriter(artifacts), GuestRepository(root))


def call(tool: GuestWorkerTools, name: str, **kwargs: object) -> dict[str, object]:
    result = tool.invoke(WorkerToolCall(name, kwargs))
    assert not result.is_error, result.output
    value: dict[str, object] = json.loads(result.output)
    return value


def test_inspect_edit_conflict_and_create(tmp_path: Path) -> None:
    root, tool = tools(tmp_path)
    (root / "hello.txt").write_bytes(b"bug\n")
    assert call(tool, "list_files")["files"] == ["hello.txt"]
    digest = call(tool, "read_file", path="hello.txt")["sha256"]
    assert call(tool, "search_text", query="bug")["matches"] == [
        {"path": "hello.txt", "line": 1, "text": "bug"},
    ]
    changed = call(tool, "apply_patch", path="hello.txt", expected_sha256=digest,
                   find="bug", replace="fixed")
    assert changed["sha256"] == hashlib.sha256(b"fixed\n").hexdigest()
    assert (root / "hello.txt").read_text(encoding="utf-8") == "fixed\n"
    stale = tool.invoke(WorkerToolCall("apply_patch", {"path": "hello.txt",
                              "expected_sha256": digest, "find": "fixed", "replace": "wrong"}))
    assert stale.is_error and "stale" in stale.output
    assert (root / "hello.txt").read_text(encoding="utf-8") == "fixed\n"
    call(tool, "apply_patch", path="new.txt", expected_sha256=None,
         find="", replace="new\n")
    assert (root / "new.txt").read_text(encoding="utf-8") == "new\n"
    assert tool.invoke(WorkerToolCall("apply_patch", {
        "path": "new.txt", "expected_sha256": None, "find": "", "replace": "again"
    })).is_error
    assert sorted(call(tool, "list_files")["files"]) == ["hello.txt", "new.txt"]


@pytest.mark.parametrize("path", ["../escape", "/etc/passwd", ".git/config", "a//b", "a\\b"])
def test_rejects_escape_and_control_paths(tmp_path: Path, path: str) -> None:
    _, tool = tools(tmp_path)
    assert tool.invoke(WorkerToolCall("read_file", {"path": path})).is_error
    assert tool.invoke(WorkerToolCall("apply_patch", {
        "path": path, "expected_sha256": None, "find": "", "replace": "x",
    })).is_error


def test_rejects_links_and_nontext_without_skipping(tmp_path: Path) -> None:
    root, tool = tools(tmp_path)
    (root / "binary.txt").write_bytes(b"abc\0def")
    assert tool.invoke(WorkerToolCall("search_text", {"query": "abc"})).is_error
    assert tool.invoke(WorkerToolCall("read_file", {"path": "binary.txt"})).is_error
    try:
        (root / "linked.txt").symlink_to(tmp_path / "outside")
    except (OSError, NotImplementedError):
        pytest.skip("fixture OS cannot create symlinks")
    assert tool.invoke(WorkerToolCall("list_files", {})).is_error
    assert tool.invoke(WorkerToolCall("read_file", {"path": "linked.txt"})).is_error
    assert tool.invoke(WorkerToolCall("apply_patch", {
        "path": "linked.txt", "expected_sha256": None, "find": "", "replace": "x",
    })).is_error
    assert not (tmp_path / "outside").exists()


def test_read_only_profile_and_result_limits(tmp_path: Path) -> None:
    root, tool = tools(tmp_path, "read-only-worker")
    (root / "large.txt").write_bytes(b"x\n" * 9000)
    assert tool.invoke(WorkerToolCall("read_file", {"path": "large.txt"})).is_error
    assert tool.invoke(WorkerToolCall("search_text", {"query": "x"})).is_error
    assert tool.invoke(WorkerToolCall("apply_patch", {
        "path": "large.txt", "expected_sha256": None, "find": "", "replace": "y",
    })).is_error
    assert tool.invoke(WorkerToolCall("run_command", {"argv": ["pytest"]})).is_error
    assert (root / "large.txt").stat().st_size == 18000


def test_patch_rejects_ambiguous_span_and_bounds(tmp_path: Path) -> None:
    root, tool = tools(tmp_path)
    (root / "x.txt").write_text("a a", encoding="utf-8")
    digest = hashlib.sha256(b"a a").hexdigest()
    for replacement in ("ok", "y" * (16 * 1024 + 1)):
        result = tool.invoke(WorkerToolCall("apply_patch", {
            "path": "x.txt", "expected_sha256": digest, "find": "a", "replace": replacement,
        }))
        assert result.is_error
    assert (root / "x.txt").read_text(encoding="utf-8") == "a a"
