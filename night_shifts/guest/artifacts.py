"""Bounded artifact staging inside a restricted worker guest."""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path


class ArtifactPolicyError(ValueError):
    """Raised when guest artifact output violates its staging policy."""


@dataclass(frozen=True)
class StagedArtifact:
    name: str
    kind: str
    size_bytes: int
    sha256: str

    @property
    def reference(self) -> str:
        return f"guest-artifact/{self.name}"


_NAME = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}")
_KINDS = frozenset({"test-log", "analysis", "report", "metadata"})


class ArtifactWriter:
    """Write small, non-symlink artifacts to one pre-created guest directory."""

    def __init__(
        self,
        root: Path,
        *,
        max_files: int = 16,
        max_file_bytes: int = 1024 * 1024,
        max_total_bytes: int = 4 * 1024 * 1024,
    ) -> None:
        resolved = root.resolve()
        if root.is_symlink() or not resolved.is_dir():
            raise ArtifactPolicyError("artifact staging directory is unavailable")
        if max_files <= 0 or max_files > 128:
            raise ValueError("artifact file limit must be between 1 and 128")
        if max_file_bytes <= 0 or max_total_bytes < max_file_bytes:
            raise ValueError("artifact byte limits are invalid")
        self._root = resolved
        self._max_files = max_files
        self._max_file_bytes = max_file_bytes
        self._max_total_bytes = max_total_bytes
        self._artifacts: list[StagedArtifact] = []
        self._total_bytes = 0

    @property
    def artifacts(self) -> tuple[StagedArtifact, ...]:
        return tuple(self._artifacts)

    def write_text(self, *, name: str, kind: str, content: str) -> StagedArtifact:
        if not _NAME.fullmatch(name):
            raise ArtifactPolicyError("artifact name is invalid")
        if kind not in _KINDS:
            raise ArtifactPolicyError(f"artifact kind is not allowed: {kind!r}")
        if len(self._artifacts) >= self._max_files:
            raise ArtifactPolicyError("artifact file count limit exceeded")
        encoded = content.encode("utf-8")
        if len(encoded) > self._max_file_bytes:
            raise ArtifactPolicyError("artifact file size limit exceeded")
        if self._total_bytes + len(encoded) > self._max_total_bytes:
            raise ArtifactPolicyError("artifact total size limit exceeded")

        destination = self._root / name
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(destination, flags, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError as exc:
            raise ArtifactPolicyError("artifact names must be unique") from exc
        except OSError as exc:
            raise ArtifactPolicyError(f"artifact could not be staged: {exc}") from exc

        artifact = StagedArtifact(
            name=name,
            kind=kind,
            size_bytes=len(encoded),
            sha256=hashlib.sha256(encoded).hexdigest(),
        )
        self._artifacts.append(artifact)
        self._total_bytes += len(encoded)
        return artifact
