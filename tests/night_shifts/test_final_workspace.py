"""Offline final-export fixtures; no real serial transport or VM attestation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from night_shifts.final_workspace import (
    FinalWorkspace, FinalWorkspaceError, decode_final_workspace, encode_final_workspace,
)
from night_shifts.guest.repository import GuestRepository, RepositoryToolError
from night_shifts.snapshot import MAX_FILE_BYTES, Snapshot, SnapshotError, SnapshotFile


def _base() -> Snapshot:
    return Snapshot("a" * 32, "fixture", "b" * 40, "c" * 64,
                    (SnapshotFile("fixture.txt", "100644", b"base\n"),))


def _export(*files: SnapshotFile) -> FinalWorkspace:
    return FinalWorkspace(_base(), "d" * 32, "e" * 32, tuple(files))


def test_final_envelope_roundtrip_new_deleted_and_all_deleted() -> None:
    for files in ((SnapshotFile("new.txt", "100644", b"changed\n"),), ()):
        export = _export(*files)
        wire = encode_final_workspace(export)
        assert decode_final_workspace(wire, base=export.base, sandbox_id=export.sandbox_id,
                                      session_id=export.session_id) == export
    assert len(encode_final_workspace(_export())) > 0  # empty is not missing evidence


@pytest.mark.parametrize("field", ["job_id", "sandbox_id", "session_id", "repository_id",
                                    "revision", "image_sha256"])
def test_wrong_binding_is_rejected(field: str) -> None:
    export = _export(SnapshotFile("new.txt", "100644", b"ok"))
    body = json.loads(encode_final_workspace(export))
    body[field] = "f" * 32
    wire = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    with pytest.raises(FinalWorkspaceError):
        decode_final_workspace(wire, base=export.base, sandbox_id=export.sandbox_id,
                               session_id=export.session_id)


def test_malformed_truncated_replayed_or_noncanonical_export_is_rejected() -> None:
    export = _export(SnapshotFile("new.txt", "100644", b"ok"))
    wire = encode_final_workspace(export)
    variants = [wire[:-1], wire.replace(b'"version":1', b'"version":1,"version":1'),
                wire + b" ", wire.replace(b'"kind":"final-workspace"', b'"kind":"tool"')]
    for candidate in variants:
        with pytest.raises((FinalWorkspaceError, SnapshotError)):
            decode_final_workspace(candidate, base=export.base, sandbox_id=export.sandbox_id,
                                   session_id=export.session_id)
    with pytest.raises(FinalWorkspaceError):
        decode_final_workspace(wire, base=export.base, sandbox_id="f" * 32,
                               session_id=export.session_id)


@pytest.mark.parametrize("file", [
    SnapshotFile("../escape", "100644", b"x"),
    SnapshotFile("link", "120000", b"outside"),
    SnapshotFile("binary", "100644", b"\0"),
    SnapshotFile("large", "100644", b"x" * (MAX_FILE_BYTES + 1)),
    SnapshotFile("pointer", "100644", b"version https://git-lfs.github.com/spec/v1\n"),
])
def test_unsupported_content_fails_instead_of_being_omitted(file: SnapshotFile) -> None:
    with pytest.raises((SnapshotError, FinalWorkspaceError)):
        encode_final_workspace(_export(file))


def test_guest_enumerates_all_files_and_rejects_links(tmp_path: Path) -> None:
    root = tmp_path / "guest-workspace"
    root.mkdir()
    (root / "sub").mkdir()
    (root / "sub" / "a.txt").write_bytes(b"a\n")
    (root / "b.txt").write_bytes(b"b\n")
    exported = GuestRepository(root).export_workspace()
    assert [(item.path, item.content) for item in exported] == [
        ("b.txt", b"b\n"), ("sub/a.txt", b"a\n"),
    ]
    wire = encode_final_workspace(_export(*exported))
    assert decode_final_workspace(wire, base=_base(), sandbox_id="d" * 32,
                                  session_id="e" * 32).files == exported
    external = tmp_path / "outside.txt"
    external.write_bytes(b"outside\n")
    try:
        (root / "link").symlink_to(external)
    except OSError:
        pytest.skip("test account cannot create links")
    with pytest.raises(RepositoryToolError, match="links and special"):
        GuestRepository(root).export_workspace()


def test_guest_export_rejects_excess_count_before_reading_files(tmp_path: Path) -> None:
    root = tmp_path / "guest-workspace"
    root.mkdir()
    for i in range(65):
        (root / f"{i:03}.txt").write_bytes(b"x")
    with pytest.raises(RepositoryToolError, match="count"):
        GuestRepository(root).export_workspace()
