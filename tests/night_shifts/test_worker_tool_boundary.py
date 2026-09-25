"""Tests for the profile-scoped guest-safe worker tool boundary."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from night_shifts.contracts.worker_tool import WorkerToolCall, WorkerToolProvider
from night_shifts.guest.artifacts import ArtifactWriter
from night_shifts.guest.commands import RestrictedCommandRunner
from night_shifts.guest.repository import GuestRepository
from night_shifts.guest.tools import GuestWorkerTools
from night_shifts.worker_capabilities import worker_tool_names


def _tools(tmp_path: Path, profile: str) -> GuestWorkerTools:
    repository = tmp_path / "repository"
    artifacts = tmp_path / "artifacts"
    repository.mkdir(parents=True)
    artifacts.mkdir()
    return GuestWorkerTools(
        profile,
        RestrictedCommandRunner(repository, profile),
        ArtifactWriter(artifacts),
        GuestRepository(repository),
    )


def test_guest_tool_provider_contract_and_profile_allowlists(tmp_path: Path) -> None:
    coding = _tools(tmp_path / "coding", "coding-worker")

    assert isinstance(coding, WorkerToolProvider)
    assert tuple(spec.name for spec in coding.available_tools()) == worker_tool_names(
        "coding-worker"
    )
    assert worker_tool_names("read-only-worker") == (
        "list_files", "read_file", "search_text", "write_artifact",
    )
    assert worker_tool_names("review-worker") == (
        "list_files", "read_file", "search_text", "run_command", "write_artifact",
    )


def test_read_only_profile_cannot_invoke_command_tool(tmp_path: Path) -> None:
    tools = _tools(tmp_path, "read-only-worker")

    result = tools.invoke(WorkerToolCall("run_command", {"argv": ["git", "status"]}))

    assert result.is_error
    assert "not allowed" in result.output


def test_command_requests_still_pass_through_command_policy(tmp_path: Path) -> None:
    tools = _tools(tmp_path, "coding-worker")

    result = tools.invoke(WorkerToolCall("run_command", {"argv": ["sh", "-c", "pwd"]}))

    assert result.is_error
    assert "not allowed" in result.output


def test_command_tool_returns_bounded_structured_result(tmp_path: Path) -> None:
    tools = _tools(tmp_path, "review-worker")

    result = tools.invoke(
        WorkerToolCall("run_command", {"argv": ["python", "-m", "compileall", "-q", "."]})
    )

    payload = json.loads(result.output)
    assert not result.is_error
    assert payload["return_code"] == 0
    assert payload["argv"] == ["python", "-m", "compileall", "-q", "."]


def test_artifact_tool_stages_only_through_artifact_policy(tmp_path: Path) -> None:
    tools = _tools(tmp_path, "read-only-worker")

    result = tools.invoke(
        WorkerToolCall(
            "write_artifact",
            {"name": "review.txt", "kind": "report", "content": "Looks good.\n"},
        )
    )

    payload = json.loads(result.output)
    assert not result.is_error
    assert payload["reference"] == "guest-artifact/review.txt"
    assert (tmp_path / "artifacts" / "review.txt").read_text(encoding="utf-8") == "Looks good.\n"


@pytest.mark.parametrize(
    "arguments",
    [
        {"name": "review.txt", "kind": "report"},
        {"name": "review.txt", "kind": "report", "content": "x", "path": "elsewhere"},
    ],
)
def test_tool_arguments_fail_closed(arguments: dict[str, str], tmp_path: Path) -> None:
    result = _tools(tmp_path, "coding-worker").invoke(
        WorkerToolCall("write_artifact", arguments)
    )

    assert result.is_error
