from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from night_shifts.guest.commands import RestrictedCommandRunner
from night_shifts.worker_policy import WorkerPolicyError, approve_worker_command
from night_shifts.workspaces import (
    RepositoryRegistry,
    TrustedRepository,
    WorkspaceError,
    WorkspacePreparer,
)


def _git(cwd: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        shell=False,
    )
    return completed.stdout.strip()


def _repository(path: Path) -> str:
    path.mkdir()
    _git(path, "init")
    _git(path, "config", "user.name", "Night Shift Test")
    _git(path, "config", "user.email", "night-shift@example.invalid")
    (path / "tracked.txt").write_text("trusted content\n", encoding="utf-8")
    _git(path, "add", "tracked.txt")
    _git(path, "commit", "-m", "initial")
    return _git(path, "rev-parse", "HEAD")


def test_command_policy_allows_only_structured_bounded_checks() -> None:
    approved = approve_worker_command(
        "coding-worker",
        ["pytest", "-q", "tests/night_shifts/test_process_backend.py::test_protocol_round_trips_task_and_result"],
        timeout_seconds=60,
    )

    assert approved.argv[0] == "pytest"
    assert approved.timeout_seconds == 60
    assert approve_worker_command("review-worker", ["git", "diff", "--check"]).argv == (
        "git",
        "diff",
        "--check",
    )
    assert approve_worker_command("coding-worker", ["python", "-m", "compileall", "-q", "."]).argv


@pytest.mark.parametrize(
    ("profile", "argv"),
    [
        ("read-only-worker", ["git", "status"]),
        ("coding-worker", ["sh", "-c", "echo unsafe"]),
        ("coding-worker", ["git", "push"]),
        ("coding-worker", ["git", "-C", "/tmp", "status"]),
        ("coding-worker", ["pytest", "--override-ini", "addopts=-p malicious"]),
        ("coding-worker", ["pytest", "../outside"]),
        ("review-worker", ["python", "script.py"]),
    ],
)
def test_command_policy_fails_closed(profile: str, argv: list[str]) -> None:
    with pytest.raises(WorkerPolicyError):
        approve_worker_command(profile, argv)


def test_restricted_runner_uses_workspace_policy_and_output_limit(tmp_path: Path) -> None:
    source = tmp_path / "repository"
    _repository(source)
    runner = RestrictedCommandRunner(source, "coding-worker", environment=os.environ)

    status = runner.run(["git", "status", "--short"], timeout_seconds=10)
    assert status.return_code == 0
    assert not status.timed_out
    assert not status.output_truncated

    (source / "tracked.txt").write_text("x" * 4096, encoding="utf-8")
    bounded = runner.run(["git", "diff"], timeout_seconds=10, max_output_bytes=64)
    assert bounded.output_truncated
    assert len(bounded.output.encode("utf-8")) <= 64

    with pytest.raises(WorkerPolicyError):
        runner.run(["git", "push"])


def test_workspace_is_selected_by_id_pinned_detached_and_origin_free(tmp_path: Path) -> None:
    source = tmp_path / "trusted-source"
    commit = _repository(source)
    registry = RepositoryRegistry([TrustedRepository("example", source)])
    preparer = WorkspacePreparer(tmp_path / "workspaces", registry)

    workspace = preparer.prepare(
        job_id="a" * 32,
        repository_id="example",
        revision="HEAD",
    )

    assert workspace.revision == commit
    assert workspace.path == (tmp_path / "workspaces" / ("a" * 32) / "repository").resolve()
    assert _git(workspace.path, "rev-parse", "HEAD") == commit
    assert _git(workspace.path, "branch", "--show-current") == ""
    assert _git(workspace.path, "remote") == ""
    assert (workspace.path / "tracked.txt").read_text(encoding="utf-8") == "trusted content\n"

    preparer.destroy(workspace)
    assert not workspace.path.parent.exists()


def test_workspace_rejects_paths_and_unknown_repositories_before_creation(tmp_path: Path) -> None:
    source = tmp_path / "trusted-source"
    _repository(source)
    preparer = WorkspacePreparer(
        tmp_path / "workspaces",
        RepositoryRegistry([TrustedRepository("example", source)]),
    )

    with pytest.raises(WorkspaceError, match="job ID"):
        preparer.prepare(job_id="../escape", repository_id="example", revision="HEAD")
    with pytest.raises(WorkspaceError, match="not approved"):
        preparer.prepare(job_id="b" * 32, repository_id="other", revision="HEAD")
    with pytest.raises(WorkspaceError, match="malformed"):
        preparer.prepare(job_id="b" * 32, repository_id="example", revision="--help")

    assert not (tmp_path / "workspaces").exists()
