"""Small, exact, text-only Git snapshot for the sandbox fixture transfer.

No checkout, clone, archive extraction, filters, hooks or repository executables
are invoked on the host. A trusted operator must approve the SHA-256 of *every*
tracked file in the pinned commit; an unknown file is an error, not an omission.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from night_shifts.workspaces import RepositoryRegistry

MAX_SNAPSHOT_BYTES = 4 * 1024 * 1024
MAX_FILES = 64
MAX_FILE_BYTES = 256 * 1024
MAX_CONTENT_BYTES = 2 * 1024 * 1024
MAX_LISTING_BYTES = 64 * 1024
_COMMIT = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_JOB = re.compile(r"[0-9a-f]{32}\Z")
_REPO = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z")
_PART = re.compile(r"[A-Za-z0-9._-]{1,100}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_RESERVED = frozenset({"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                       *(f"LPT{i}" for i in range(1, 10))})


class SnapshotError(RuntimeError):
    """Snapshot is incomplete, unapproved or cannot be represented safely."""


@dataclass(frozen=True)
class SnapshotFile:
    path: str
    mode: str
    content: bytes


@dataclass(frozen=True)
class Snapshot:
    job_id: str
    repository_id: str
    revision: str
    image_sha256: str
    files: tuple[SnapshotFile, ...]


def _path(value: str) -> str:
    if (not isinstance(value, str) or len(value) > 240 or value.startswith("/")
            or any(not _PART.fullmatch(part) or part.endswith(".")
                   or part.upper().split(".")[0] in _RESERVED
                   or part.lower() == ".git" for part in value.split("/"))):
        raise SnapshotError("snapshot path is not portable and relative")
    return value


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SnapshotError("duplicate snapshot JSON field")
        result[key] = value
    return result


def _files_valid(files: Sequence[SnapshotFile]) -> None:
    if not 0 < len(files) <= MAX_FILES:
        raise SnapshotError("snapshot file count is invalid")
    seen: set[str] = set()
    total = 0
    for item in files:
        path = _path(item.path)
        if path.casefold() in seen or item.mode not in ("100644", "100755"):
            raise SnapshotError("duplicate path or unsupported file mode")
        seen.add(path.casefold())
        if (len(item.content) > MAX_FILE_BYTES or b"\0" in item.content
                or item.content.startswith(b"version https://git-lfs.github.com/spec/v1")):
            raise SnapshotError("binary, LFS pointer or oversized file is unsupported")
        try:
            item.content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SnapshotError("non-UTF-8 file is unsupported") from exc
        total += len(item.content)
        if total > MAX_CONTENT_BYTES:
            raise SnapshotError("snapshot content is too large")


def encode_snapshot(snapshot: Snapshot) -> bytes:
    """Canonical bounded bytes; manifest digest is SHA-256 of these entire bytes."""
    if (not isinstance(snapshot.job_id, str) or not _JOB.fullmatch(snapshot.job_id)
            or not isinstance(snapshot.repository_id, str) or not _REPO.fullmatch(snapshot.repository_id)
            or not isinstance(snapshot.revision, str) or not _COMMIT.fullmatch(snapshot.revision)
            or not isinstance(snapshot.image_sha256, str)
            or not _DIGEST.fullmatch(snapshot.image_sha256)):
        raise SnapshotError("snapshot identity or image digest is invalid")
    _files_valid(snapshot.files)
    if tuple(sorted(snapshot.files, key=lambda item: item.path)) != snapshot.files:
        raise SnapshotError("snapshot entries must be sorted")
    payload = {"version": 1, "job_id": snapshot.job_id,
               "repository_id": snapshot.repository_id, "revision": snapshot.revision,
               "image_sha256": snapshot.image_sha256,
               "files": [{"path": item.path, "mode": item.mode,
                          "sha256": hashlib.sha256(item.content).hexdigest(),
                          "data": base64.b64encode(item.content).decode("ascii")}
                         for item in snapshot.files]}
    result = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(result) > MAX_SNAPSHOT_BYTES:
        raise SnapshotError("encoded snapshot exceeds transfer limit")
    return result


def decode_snapshot(data: bytes) -> Snapshot:
    """Reject unsafe, malformed, re-encoded, corrupt or noncanonical snapshots."""
    if not isinstance(data, bytes) or len(data) > MAX_SNAPSHOT_BYTES:
        raise SnapshotError("snapshot transfer exceeds limit")
    try:
        payload = json.loads(data.decode("utf-8"), object_pairs_hook=_object,
                             parse_constant=lambda _: (_ for _ in ()).throw(SnapshotError("nonfinite JSON")))
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise SnapshotError("snapshot is not valid JSON") from exc
    if (not isinstance(payload, dict) or set(payload) != {"version", "job_id", "repository_id",
            "revision", "image_sha256", "files"} or type(payload["version"]) is not int
            or payload["version"] != 1 or not isinstance(payload["files"], list)
            or len(payload["files"]) > MAX_FILES):
        raise SnapshotError("snapshot envelope is invalid")
    files: list[SnapshotFile] = []
    for entry in payload["files"]:
        if (not isinstance(entry, dict) or set(entry) != {"path", "mode", "sha256", "data"}
                or not all(isinstance(value, str) for value in entry.values())
                or not _DIGEST.fullmatch(entry["sha256"]) or len(entry["data"]) > 4 * MAX_FILE_BYTES // 3 + 4):
            raise SnapshotError("snapshot file record is invalid")
        try:
            content = base64.b64decode(entry["data"], validate=True)
        except (ValueError, binascii.Error) as exc:
            raise SnapshotError("snapshot file encoding is invalid") from exc
        if hashlib.sha256(content).hexdigest() != entry["sha256"]:
            raise SnapshotError("snapshot file digest mismatch")
        files.append(SnapshotFile(entry["path"], entry["mode"], content))
    snapshot = Snapshot(payload["job_id"], payload["repository_id"],
                        payload["revision"], payload["image_sha256"], tuple(files))
    if encode_snapshot(snapshot) != data:
        raise SnapshotError("snapshot encoding is not canonical")
    return snapshot


def _bounded_git(source: Path, argv: Sequence[str], *, limit: int, timeout: float) -> bytes:
    """Read only bounded Git stdout/stderr; kill and join on overflow or deadline."""
    environment = {key: value for key, value in os.environ.items()
                   if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR"}}
    environment.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                        "GIT_NO_REPLACE_OBJECTS": "1", "GIT_NO_LAZY_FETCH": "1",
                        "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0",
                        "GIT_ALLOW_PROTOCOL": "file"})
    try:
        process = subprocess.Popen(
            ["git", "-c", "core.fsmonitor=false", *argv], cwd=source,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=environment, shell=False,
        )
    except OSError as exc:
        raise SnapshotError("trusted Git operation could not start") from exc
    output: list[bytearray] = [bytearray(), bytearray()]
    exceeded = threading.Event()

    def drain(index: int, capacity: int) -> None:
        stream = process.stdout if index == 0 else process.stderr
        assert stream is not None
        try:
            while True:
                chunk = stream.read(4096)
                if not chunk:
                    break
                if len(output[index]) + len(chunk) > capacity:
                    exceeded.set()
                    break
                output[index].extend(chunk)
        except OSError:
            exceeded.set()

    readers = [threading.Thread(target=drain, args=(0, limit)),
               threading.Thread(target=drain, args=(1, 2048))]
    for reader in readers:
        reader.start()
    deadline = time.monotonic() + timeout
    try:
        while process.poll() is None:
            if exceeded.is_set() or time.monotonic() >= deadline:
                raise SnapshotError("Git output or deadline exceeded")
            time.sleep(0.01)
        for reader in readers:
            reader.join(timeout=max(0.0, deadline - time.monotonic()))
        if exceeded.is_set() or any(reader.is_alive() for reader in readers):
            raise SnapshotError("Git output or deadline exceeded")
        if process.returncode != 0:
            raise SnapshotError("trusted Git object read failed")
        return bytes(output[0])
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                stream.close()
        for reader in readers:
            reader.join(timeout=2)


class GitSnapshotExporter:
    """Export only an exact operator-reviewed commit and complete file/hash policy."""

    def __init__(self, repositories: RepositoryRegistry, *, timeout_seconds: float = 10.0) -> None:
        if not 0 < timeout_seconds <= 120:
            raise ValueError("Git snapshot timeout is invalid")
        self._repositories = repositories
        self._timeout = timeout_seconds

    def export(self, *, job_id: str, repository_id: str, revision: str,
               image_sha256: str, approved_files: dict[str, str]) -> Snapshot:
        if (not isinstance(job_id, str) or not _JOB.fullmatch(job_id)
                or not isinstance(revision, str) or not _COMMIT.fullmatch(revision)
                or not isinstance(image_sha256, str) or not _DIGEST.fullmatch(image_sha256)
                or not isinstance(approved_files, dict)
                or not 0 < len(approved_files) <= MAX_FILES):
            raise SnapshotError("unapproved snapshot identity, revision, image or file policy")
        for path, digest in approved_files.items():
            _path(path)
            if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
                raise SnapshotError("file approval requires an exact SHA-256")
        source = self._repositories.require(repository_id).source
        if not source.is_dir() or not (source / ".git").is_dir():
            raise SnapshotError("approved source must be a non-bare Git checkout")
        def git(args: Sequence[str], limit: int) -> bytes:
            return _bounded_git(source, args, limit=limit, timeout=self._timeout)
        if git(["cat-file", "-t", revision], 32).strip() != b"commit":
            raise SnapshotError("approved revision is not a commit")
        listing = git(["ls-tree", "--full-tree", "-r", "-z", "-l", revision], MAX_LISTING_BYTES)
        if listing and not listing.endswith(b"\0"):
            raise SnapshotError("truncated Git tree listing")
        files: list[SnapshotFile] = []
        seen: set[str] = set()
        total = 0
        for raw in listing.split(b"\0"):
            if not raw:
                continue
            try:
                header, name = raw.split(b"\t", 1)
                mode, kind, oid, size = header.split()  # ls-tree -l pads blob sizes
                path = _path(name.decode("utf-8"))
                digest = approved_files[path]
                length = int(size)
            except (ValueError, UnicodeError, KeyError) as exc:
                raise SnapshotError("unapproved or malformed Git tree entry") from exc
            if (path.casefold() in seen or mode not in (b"100644", b"100755")
                    or kind != b"blob" or not _COMMIT.fullmatch(oid.decode("ascii"))
                    or length < 0 or length > MAX_FILE_BYTES or len(files) >= MAX_FILES):
                raise SnapshotError("Git tree has unsupported or oversized entries")
            seen.add(path.casefold())
            total += length
            if total > MAX_CONTENT_BYTES:
                raise SnapshotError("Git tree content is too large")
            content = git(["cat-file", "blob", oid.decode("ascii")], length + 1)
            if len(content) != length or hashlib.sha256(content).hexdigest() != digest:
                raise SnapshotError("Git blob differs from operator-approved digest")
            files.append(SnapshotFile(path, mode.decode("ascii"), content))
        if set(approved_files) != {item.path for item in files}:
            raise SnapshotError("Git tree differs from the approved complete file list")
        snapshot = Snapshot(job_id, repository_id, revision, image_sha256,
                            tuple(sorted(files, key=lambda item: item.path)))
        encode_snapshot(snapshot)
        return snapshot
