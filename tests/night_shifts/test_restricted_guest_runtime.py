from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path
from typing import Any

from night_shifts.contracts.worker_tool import WorkerToolCall, WorkerToolProvider
from night_shifts.guest.runtime import MAX_FRAME_BYTES, EmitEvent, run_once
from night_shifts.protocol import (
    WorkerOutcome,
    WorkerResult,
    WorkerTask,
    decode_worker_message,
    encode_task,
)
from night_shifts.workspaces import RepositoryRegistry, TrustedRepository, WorkspacePreparer


class MemoryChannel:
    def __init__(self, task: WorkerTask) -> None:
        self._input = io.BytesIO((encode_task(task) + "\n").encode("utf-8"))
        self.output = io.BytesIO()

    def readline(self, size: int = -1) -> bytes:
        return self._input.readline(size)

    def write(self, value: bytes) -> int:
        return self.output.write(value)

    def flush(self) -> None:
        return None


class OversizedExecutor:
    def execute(
        self,
        task: WorkerTask,
        tools: WorkerToolProvider,
        emit_event: EmitEvent,
    ) -> WorkerResult:
        del tools, emit_event
        return WorkerResult(
            job_id=task.job_id,
            outcome=WorkerOutcome.SUCCESS,
            summary="x" * MAX_FRAME_BYTES,
        )


class SuccessfulExecutor:
    def __init__(self) -> None:
        self.called = False

    def execute(
        self,
        task: WorkerTask,
        tools: WorkerToolProvider,
        emit_event: EmitEvent,
    ) -> WorkerResult:
        self.called = True
        assert {spec.name for spec in tools.available_tools()} == {
            "list_files", "read_file", "search_text", "run_command", "write_artifact",
        }
        tool_result = tools.invoke(
            WorkerToolCall(
                "write_artifact",
                {
                    "name": "checks.txt",
                    "kind": "test-log",
                    "content": "identity passed\n",
                },
            )
        )
        assert not tool_result.is_error
        artifact_reference = json.loads(tool_result.output)["reference"]
        emit_event("worker_check", {"name": "identity", "passed": True})
        return WorkerResult(
            job_id=task.job_id,
            outcome=WorkerOutcome.SUCCESS,
            summary="Injected restricted executor completed.",
            artifacts=(artifact_reference,),
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


def _workspace(tmp_path: Path, job_id: str) -> tuple[Path, str]:
    source = tmp_path / "source"
    source.mkdir()
    _git(source, "init")
    _git(source, "config", "user.name", "Night Shift Test")
    _git(source, "config", "user.email", "night-shift@example.invalid")
    (source / "file.txt").write_text("content\n", encoding="utf-8")
    _git(source, "add", "file.txt")
    _git(source, "commit", "-m", "initial")
    commit = _git(source, "rev-parse", "HEAD")
    preparer = WorkspacePreparer(
        tmp_path / "workspaces",
        RepositoryRegistry([TrustedRepository("example", source)]),
    )
    workspace = preparer.prepare(job_id=job_id, repository_id="example", revision=commit)
    return workspace.path.parent, commit


def _messages(channel: MemoryChannel) -> list[Any]:
    return [
        decode_worker_message(line.decode("utf-8"))
        for line in channel.output.getvalue().splitlines()
    ]


def test_guest_loop_validates_identity_emits_events_and_one_result(tmp_path: Path) -> None:
    job_id = "c" * 32
    root, commit = _workspace(tmp_path, job_id)
    task = WorkerTask(
        job_id=job_id,
        objective="Inspect the prepared repository.",
        worker_profile="review-worker",
        repository_id="example",
        starting_revision=commit,
    )
    channel = MemoryChannel(task)
    executor = SuccessfulExecutor()

    run_once(
        channel,
        workspace_root=root,
        executor=executor,
        require_root_owned_manifest=False,
    )

    messages = _messages(channel)
    assert executor.called
    assert [message.event_type for message in messages[:-1]] == ["worker_started", "worker_check"]
    assert isinstance(messages[-1], WorkerResult)
    assert messages[-1].outcome is WorkerOutcome.SUCCESS
    assert messages[-1].artifacts == ("guest-artifact/checks.txt",)
    assert (root / "artifacts" / "checks.txt").read_text(encoding="utf-8") == "identity passed\n"


def test_guest_loop_rejects_task_that_does_not_match_root_owned_manifest(tmp_path: Path) -> None:
    job_id = "d" * 32
    root, commit = _workspace(tmp_path, job_id)
    task = WorkerTask(
        job_id=job_id,
        objective="Inspect another repository.",
        worker_profile="review-worker",
        repository_id="unapproved",
        starting_revision=commit,
    )
    channel = MemoryChannel(task)
    executor = SuccessfulExecutor()

    run_once(
        channel,
        workspace_root=root,
        executor=executor,
        require_root_owned_manifest=False,
    )

    messages = _messages(channel)
    assert not executor.called
    assert len(messages) == 1
    assert isinstance(messages[0], WorkerResult)
    assert messages[0].outcome is WorkerOutcome.FAILED
    assert "does not match" in (messages[0].error or "")


def test_guest_loop_default_executor_fails_closed(tmp_path: Path) -> None:
    job_id = "e" * 32
    root, commit = _workspace(tmp_path, job_id)
    channel = MemoryChannel(
        WorkerTask(
            job_id=job_id,
            objective="Do not execute without an adapter.",
            worker_profile="coding-worker",
            repository_id="example",
            starting_revision=commit,
        )
    )

    run_once(channel, workspace_root=root, require_root_owned_manifest=False)

    messages = _messages(channel)
    assert messages[-1].outcome is WorkerOutcome.FAILED
    assert any(getattr(message, "event_type", "") == "worker_executor_unavailable" for message in messages)


def test_guest_loop_replaces_an_oversized_result_with_bounded_failure(tmp_path: Path) -> None:
    job_id = "f" * 32
    root, commit = _workspace(tmp_path, job_id)
    channel = MemoryChannel(
        WorkerTask(
            job_id=job_id,
            objective="Return a bounded result.",
            worker_profile="review-worker",
            repository_id="example",
            starting_revision=commit,
        )
    )

    run_once(
        channel,
        workspace_root=root,
        executor=OversizedExecutor(),
        require_root_owned_manifest=False,
    )

    messages = _messages(channel)
    assert messages[-1].outcome is WorkerOutcome.FAILED
    assert "exceeded" in messages[-1].summary
