"""Offline patch-shape tests; these are not guest retrieval or VM replay evidence."""

from __future__ import annotations

import hashlib

import pytest

from night_shifts.review_patch import ReviewPatchError, build_review_patch
from night_shifts.snapshot import Snapshot, SnapshotError, SnapshotFile, encode_snapshot


def fixture(*files: SnapshotFile) -> Snapshot:
    return Snapshot("a" * 32, "fixture", "b" * 40, "c" * 64, tuple(files))


def file(path: str, content: bytes, mode: str = "100644") -> SnapshotFile:
    return SnapshotFile(path, mode, content)


def test_independent_inventory_includes_additions_deletions_modes_and_no_newline() -> None:
    base = fixture(file("delete.txt", b"old\n"), file("edit.txt", b"old"),
                   file("mode.txt", b"same\n"))
    final = (file("added.txt", b"new\n"), file("edit.txt", b"new"),
             file("mode.txt", b"same\n", "100755"))

    result = build_review_patch(base, final)

    assert [item.change for item in result.changes] == [
        "added", "deleted", "modified", "mode_changed",
    ]
    assert [item.path for item in result.changes] == [
        "added.txt", "delete.txt", "edit.txt", "mode.txt",
    ]
    assert result.changes[0].before_sha256 is None
    assert result.changes[1].after_sha256 is None
    assert result.changes[2].after_sha256 == hashlib.sha256(b"new").hexdigest()
    assert result.base_snapshot_sha256 == hashlib.sha256(encode_snapshot(base)).hexdigest()
    assert result.patch_sha256 == hashlib.sha256(result.patch).hexdigest()
    assert b"new file mode 100644\n--- /dev/null\n+++ b/added.txt\n" in result.patch
    assert b"deleted file mode 100644\n--- a/delete.txt\n+++ /dev/null\n" in result.patch
    assert b"-old\n\\ No newline at end of file\n+new\n\\ No newline at end of file\n" in result.patch
    assert b"old mode 100644\nnew mode 100755\n" in result.patch


def test_noop_and_delete_last_file_are_explicit() -> None:
    base = fixture(file("last.txt", b"last\n"))
    unchanged = build_review_patch(base, base.files)
    assert unchanged.patch == b"" and unchanged.changes == ()
    deleted = build_review_patch(base, ())
    assert deleted.changes[0].change == "deleted"
    assert b"+++ /dev/null\n" in deleted.patch


@pytest.mark.parametrize("final", [
    (file("x", b"\0"),),
    (file("x", b"\xff"),),
    (file("x", b"version https://git-lfs.github.com/spec/v1\n"),),
    (file("../escape", b"x"),),
    (file("x", b"x"), file("x", b"y")),
    (file("x", b"x"), file("X", b"y")),
    (file("x", b"x"), file("x/child", b"y")),
    (file("z", b"z"), file("a", b"a")),
])
def test_unsafe_or_incomplete_workspace_cannot_yield_partial_patch(
    final: tuple[SnapshotFile, ...],
) -> None:
    with pytest.raises(SnapshotError):
        build_review_patch(fixture(file("base", b"base\n")), final)


def test_limits_empty_file_and_directory_swap_fail_closed() -> None:
    base = fixture(file("base", b"base\n"))
    with pytest.raises(ReviewPatchError, match="byte limit"):
        build_review_patch(base, (file("base", b"different\n"),), max_patch_bytes=10)
    with pytest.raises(ReviewPatchError, match="empty files"):
        build_review_patch(base, (file("added", b""), file("base", b"base\n")))
    with pytest.raises(ReviewPatchError, match="file-to-directory"):
        build_review_patch(base, (file("base/child", b"new\n"),))
    with pytest.raises(ReviewPatchError, match="lone CR"):
        build_review_patch(base, (file("base", b"one\rtwo"),))
    with pytest.raises(ValueError, match="patch byte limit"):
        build_review_patch(base, base.files, max_patch_bytes=True)
