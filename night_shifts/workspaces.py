"""Trusted repository registry and isolated workspace preparation.

Repository locations are orchestrator configuration. Tasks select only an
opaque repository ID and revision; they never provide a host path or Git URL.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence


class WorkspaceError(RuntimeError):
    """Raised when a trusted repository workspace cannot be prepared safely."""


@dataclass(frozen=True)
class TrustedRepository:
    repository_id: str
    source: Path


@dataclass(frozen=True)
class PreparedWorkspace:
    job_id: str
    repository_id: str
    revision: str
    path: Path


class GitRunner(Protocol):
    def run(self, argv: Sequence[str], *, cwd: Path | None = None) -> str: ...


class SubprocessGitRunner:
    """Run fixed Git argv vectors directly, without a command shell."""

    def __init__(self, *, executable: str = "git", timeout_seconds: float = 120.0) -> None:
        self._executable = executable
        self._timeout_seconds = timeout_seconds

    def run(self, argv: Sequence[str], *, cwd: Path | None = None) -> str:
        environment = os.environ.copy()
        environment.update(
            {
                "GIT_ALLOW_PROTOCOL": "file",
                "GIT_ASKPASS": "",
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_TERMINAL_PROMPT": "0",
            }
        )
        try:
            completed = subprocess.run(
                [self._executable, *argv],
                cwd=cwd,
                check=False,
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
                shell=False,
                env=environment,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise WorkspaceError(f"Git operation failed: {exc}") from exc
        if completed.returncode != 0:
            detail = completed.stderr.strip()[:2000] or "Git returned a non-zero status"
            raise WorkspaceError(detail)
        return completed.stdout.strip()


_REPOSITORY_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
_JOB_ID = re.compile(r"[0-9a-f]{32}")
_REVISION = re.compile(r"[^\x00\r\n]{1,200}")
_COMMIT = re.compile(r"[0-9a-f]{40,64}")
WORKSPACE_MANIFEST = "workspace.json"
WORKSPACE_ARTIFACTS = "artifacts"


class RepositoryRegistry:
    """Fail-closed mapping from opaque IDs to administrator-configured sources."""

    def __init__(self, repositories: Sequence[TrustedRepository]) -> None:
        registered: dict[str, TrustedRepository] = {}
        for repository in repositories:
            if not _REPOSITORY_ID.fullmatch(repository.repository_id):
                raise ValueError(f"invalid repository ID: {repository.repository_id!r}")
            if repository.repository_id in registered:
                raise ValueError(f"duplicate repository ID: {repository.repository_id!r}")
            source = repository.source.resolve()
            registered[repository.repository_id] = TrustedRepository(repository.repository_id, source)
        self._repositories = registered

    def require(self, repository_id: str) -> TrustedRepository:
        try:
            return self._repositories[repository_id]
        except KeyError as exc:
            raise WorkspaceError(f"repository ID is not approved: {repository_id!r}") from exc


class WorkspacePreparer:
    """Create one detached, origin-free repository copy under a trusted root."""

    def __init__(
        self,
        root: Path,
        repositories: RepositoryRegistry,
        *,
        runner: GitRunner | None = None,
    ) -> None:
        self._root = root.resolve()
        self._repositories = repositories
        self._runner = runner or SubprocessGitRunner()

    def prepare(self, *, job_id: str, repository_id: str, revision: str) -> PreparedWorkspace:
        if not _JOB_ID.fullmatch(job_id):
            raise WorkspaceError("job ID must be 32 lowercase hexadecimal characters")
        if not _REVISION.fullmatch(revision) or revision.startswith("-"):
            raise WorkspaceError("starting revision is malformed")

        repository = self._repositories.require(repository_id)
        if not repository.source.is_dir():
            raise WorkspaceError(f"trusted repository source is unavailable: {repository_id!r}")
        destination = self._root / job_id / "repository"
        if destination.exists():
            raise WorkspaceError(f"workspace already exists for job {job_id}")

        commit = self._runner.run(
            ["rev-parse", "--verify", f"{revision}^{{commit}}"],
            cwd=repository.source,
        )
        if not _COMMIT.fullmatch(commit):
            raise WorkspaceError("trusted repository returned an invalid commit identity")

        destination.parent.mkdir(parents=True, exist_ok=False)
        try:
            self._runner.run(
                ["clone", "--no-checkout", "--no-hardlinks", "--", str(repository.source), str(destination)]
            )
            self._runner.run(["checkout", "--detach", commit], cwd=destination)
            self._runner.run(["remote", "remove", "origin"], cwd=destination)
            actual = self._runner.run(["rev-parse", "HEAD"], cwd=destination)
            if actual != commit:
                raise WorkspaceError("prepared workspace revision does not match the requested commit")
            artifacts = destination.parent / WORKSPACE_ARTIFACTS
            artifacts.mkdir(mode=0o700)
            manifest = destination.parent / WORKSPACE_MANIFEST
            manifest.write_text(
                json.dumps(
                    {
                        "job_id": job_id,
                        "repository_id": repository_id,
                        "starting_revision": revision,
                        "revision": commit,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
            manifest.chmod(0o444)
        except Exception:
            _remove_workspace_tree(destination.parent)
            raise

        return PreparedWorkspace(job_id, repository_id, commit, destination)

    def destroy(self, workspace: PreparedWorkspace) -> None:
        """Remove only a workspace whose path matches this preparer's derivation."""

        expected = self._root / workspace.job_id / "repository"
        if workspace.path.resolve() != expected or not _JOB_ID.fullmatch(workspace.job_id):
            raise WorkspaceError("refusing to destroy a workspace with an untrusted path")
        _remove_workspace_tree(expected.parent)


def _remove_workspace_tree(path: Path) -> None:
    """Remove a workspace, including its read-only manifest on Windows."""

    if not path.exists():
        return
    manifest = path / WORKSPACE_MANIFEST
    if manifest.exists():
        manifest.chmod(0o600)
    shutil.rmtree(path)
