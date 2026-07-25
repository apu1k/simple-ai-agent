"""Orchestrator-controlled retrieval of bounded guest artifacts."""

from __future__ import annotations

import hashlib
import os
import re
import stat
from pathlib import Path
from typing import Sequence

from night_shifts.models import ArtifactRecord
from night_shifts.storage import ArtifactStore


class ArtifactRetrievalError(RuntimeError):
    """Raised when an untrusted guest artifact fails host-side validation."""


_JOB_ID = re.compile(r"[0-9a-f]{32}")
_REFERENCE = re.compile(r"guest-artifact/([a-z0-9][a-z0-9._-]{0,127})")


class ArtifactCollector:
    """Copy validated guest files into trusted host storage and record metadata."""

    def __init__(
        self,
        destination_root: Path,
        store: ArtifactStore,
        *,
        max_files: int = 16,
        max_file_bytes: int = 1024 * 1024,
        max_total_bytes: int = 4 * 1024 * 1024,
    ) -> None:
        if destination_root.is_symlink():
            raise ArtifactRetrievalError("artifact destination must not be a symlink")
        destination_root.mkdir(parents=True, exist_ok=True)
        self._destination_root = destination_root.resolve()
        self._store = store
        self._max_files = max_files
        self._max_file_bytes = max_file_bytes
        self._max_total_bytes = max_total_bytes
        if max_files <= 0 or max_file_bytes <= 0 or max_total_bytes < max_file_bytes:
            raise ValueError("artifact retrieval limits are invalid")

    def collect(
        self,
        *,
        job_id: str,
        staging_root: Path,
        references: Sequence[str],
    ) -> tuple[ArtifactRecord, ...]:
        if not _JOB_ID.fullmatch(job_id):
            raise ArtifactRetrievalError("artifact job ID is invalid")
        if len(references) > self._max_files or len(set(references)) != len(references):
            raise ArtifactRetrievalError("artifact references exceed count or uniqueness limits")
        if staging_root.is_symlink():
            raise ArtifactRetrievalError("artifact staging root must not be a symlink")
        source_root = staging_root.resolve()
        if not source_root.is_dir():
            raise ArtifactRetrievalError("artifact staging root is unavailable")

        validated: list[tuple[str, bytes]] = []
        total_bytes = 0
        for reference in references:
            match = _REFERENCE.fullmatch(reference)
            if match is None:
                raise ArtifactRetrievalError(f"artifact reference is invalid: {reference!r}")
            name = match.group(1)
            content = self._read_file(source_root / name)
            total_bytes += len(content)
            if total_bytes > self._max_total_bytes:
                raise ArtifactRetrievalError("artifact total size limit exceeded")
            try:
                content.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ArtifactRetrievalError("guest text artifact is not valid UTF-8") from exc
            validated.append((name, content))

        destination = self._destination_root / job_id
        if destination.is_symlink():
            raise ArtifactRetrievalError("artifact job destination must not be a symlink")
        destination.mkdir(mode=0o700, exist_ok=True)
        records: list[ArtifactRecord] = []
        for name, content in validated:
            record = ArtifactRecord(
                job_id=job_id,
                kind="guest-output",
                path="",
                content_type="text/plain; charset=utf-8",
                size_bytes=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
            )
            output = destination / f"{record.artifact_id}-{name}"
            self._write_exclusive(output, content)
            record = ArtifactRecord(
                job_id=record.job_id,
                kind=record.kind,
                path=str(output),
                artifact_id=record.artifact_id,
                content_type=record.content_type,
                size_bytes=record.size_bytes,
                sha256=record.sha256,
                created_at=record.created_at,
            )
            try:
                self._store.add(record)
            except Exception:
                output.unlink(missing_ok=True)
                raise
            records.append(record)
        return tuple(records)

    def _read_file(self, path: Path) -> bytes:
        try:
            status = path.lstat()
        except OSError as exc:
            raise ArtifactRetrievalError("referenced artifact is unavailable") from exc
        if path.is_symlink() or not stat.S_ISREG(status.st_mode):
            raise ArtifactRetrievalError("referenced artifact must be a regular file")
        if status.st_size > self._max_file_bytes:
            raise ArtifactRetrievalError("artifact file size limit exceeded")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
            with os.fdopen(descriptor, "rb") as stream:
                content = stream.read(self._max_file_bytes + 1)
        except OSError as exc:
            raise ArtifactRetrievalError("referenced artifact could not be read safely") from exc
        if len(content) > self._max_file_bytes:
            raise ArtifactRetrievalError("artifact file grew beyond its size limit")
        return content

    @staticmethod
    def _write_exclusive(path: Path, content: bytes) -> None:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
        except OSError as exc:
            raise ArtifactRetrievalError("trusted artifact copy could not be created") from exc
