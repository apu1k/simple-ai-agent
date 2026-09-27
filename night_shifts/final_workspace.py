"""Bounded, canonical final workspace envelope for an orchestrator-only export.

Bytes arriving from a guest remain untrusted even with a matching session ID.
The live transport/VM binding and complete enumeration must be established
separately. This module never reads a host repository or runs host Git.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from night_shifts.snapshot import (
    MAX_FILE_BYTES, MAX_FILES, MAX_SNAPSHOT_BYTES, Snapshot, SnapshotFile,
    encode_snapshot, validate_workspace_files,
)

_ID = re.compile(r"[0-9a-f]{32}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class FinalWorkspaceError(ValueError):
    """The guest final export is incomplete, unbound, or outside its policy."""


@dataclass(frozen=True)
class FinalWorkspace:
    base: Snapshot
    sandbox_id: str
    session_id: str
    files: tuple[SnapshotFile, ...]


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise FinalWorkspaceError("duplicate final workspace field")
        result[key] = value
    return result


def encode_final_workspace(export: FinalWorkspace) -> bytes:
    """Serialize the *complete* guest file set (including all-deleted workspaces)."""
    if not isinstance(export, FinalWorkspace):
        raise FinalWorkspaceError("final workspace envelope is invalid")
    encode_snapshot(export.base)  # already approved, exact source object identity
    if (not isinstance(export.sandbox_id, str) or not _ID.fullmatch(export.sandbox_id)
            or not isinstance(export.session_id, str) or not _ID.fullmatch(export.session_id)
            or not isinstance(export.files, tuple)):
        raise FinalWorkspaceError("final workspace identity or file list is invalid")
    validate_workspace_files(export.files)
    base = export.base
    body = {"version": 1, "kind": "final-workspace", "job_id": base.job_id,
            "sandbox_id": export.sandbox_id, "session_id": export.session_id,
            "repository_id": base.repository_id, "revision": base.revision,
            "image_sha256": base.image_sha256,
            "files": [{"path": item.path, "mode": item.mode,
                       "sha256": hashlib.sha256(item.content).hexdigest(),
                       "data": base64.b64encode(item.content).decode("ascii")}
                      for item in export.files]}
    data = json.dumps(body, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")
    if len(data) > MAX_SNAPSHOT_BYTES:
        raise FinalWorkspaceError("final workspace exceeds transfer limit")
    return data


def decode_final_workspace(
    data: bytes, *, base: Snapshot, sandbox_id: str, session_id: str,
) -> FinalWorkspace:
    """Reject noncanonical/partial data, wrong binding, links and unsupported files."""
    if not isinstance(data, bytes) or len(data) > MAX_SNAPSHOT_BYTES:
        raise FinalWorkspaceError("final workspace frame exceeds limit")
    if not isinstance(sandbox_id, str) or not _ID.fullmatch(sandbox_id) or not isinstance(session_id, str) or not _ID.fullmatch(session_id):
        raise FinalWorkspaceError("expected sandbox/session ID is invalid")
    encode_snapshot(base)
    try:
        body = json.loads(data.decode("utf-8"), object_pairs_hook=_unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(FinalWorkspaceError("nonfinite JSON")))
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise FinalWorkspaceError("final workspace is not valid UTF-8 JSON") from exc
    if (not isinstance(body, dict) or set(body) != {"version", "kind", "job_id", "sandbox_id",
            "session_id", "repository_id", "revision", "image_sha256", "files"}
            or type(body["version"]) is not int or body["version"] != 1
            or body["kind"] != "final-workspace" or body["job_id"] != base.job_id
            or body["sandbox_id"] != sandbox_id or body["session_id"] != session_id
            or body["repository_id"] != base.repository_id or body["revision"] != base.revision
            or body["image_sha256"] != base.image_sha256 or not isinstance(body["files"], list)
            or len(body["files"]) > MAX_FILES):
        raise FinalWorkspaceError("final workspace envelope or binding is invalid")
    files: list[SnapshotFile] = []
    for entry in body["files"]:
        if (not isinstance(entry, dict) or set(entry) != {"path", "mode", "sha256", "data"}
                or not all(isinstance(value, str) for value in entry.values())
                or not _DIGEST.fullmatch(entry["sha256"])
                or len(entry["data"]) > (4 * MAX_FILE_BYTES // 3 + 4)):
            raise FinalWorkspaceError("final file record is invalid")
        try:
            content = base64.b64decode(entry["data"], validate=True)
        except (ValueError, binascii.Error) as exc:
            raise FinalWorkspaceError("final file encoding is invalid") from exc
        if hashlib.sha256(content).hexdigest() != entry["sha256"]:
            raise FinalWorkspaceError("final file digest differs")
        files.append(SnapshotFile(entry["path"], entry["mode"], content))
    final = FinalWorkspace(base, sandbox_id, session_id, tuple(files))
    if encode_final_workspace(final) != data:
        raise FinalWorkspaceError("final workspace is not canonical")
    return final
