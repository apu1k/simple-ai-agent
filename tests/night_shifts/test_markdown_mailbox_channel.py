from pathlib import Path

import pytest

from night_shifts.channels import MarkdownMailboxChannel, MarkdownMailboxError
from night_shifts.contracts import WorkerChannel
from night_shifts.models import SandboxRecord
from night_shifts.protocol import WorkerOutcome, WorkerTask


def _sandbox() -> SandboxRecord:
    return SandboxRecord(
        job_id="job-1",
        backend="test",
        sandbox_id="0123456789abcdef0123456789abcdef",
    )


def test_mailbox_writes_small_markdown_task_and_reads_result(tmp_path: Path):
    sandbox = _sandbox()
    channel = MarkdownMailboxChannel(tmp_path)
    task = WorkerTask(
        "job-1",
        "Implement the parser.",
        "coding-worker",
        ("Tests pass",),
        "repo",
        "main",
    )

    assert isinstance(channel, WorkerChannel)
    channel.send_task(sandbox, task)
    mailbox = tmp_path / sandbox.sandbox_id
    task_text = (mailbox / "TASK.md").read_text(encoding="utf-8")
    assert "# Night Shift Task" in task_text
    assert "Implement the parser." in task_text
    assert "- Tests pass" in task_text
    assert not list(channel.events(sandbox))

    (mailbox / "RESULT.md").write_text(
        "# Night Shift Result\nOutcome: success\n\nImplemented and tested.\n",
        encoding="utf-8",
    )
    result = channel.retrieve_result(sandbox)
    assert result.outcome is WorkerOutcome.SUCCESS
    assert result.summary == "Implemented and tested."


def test_mailbox_emits_progress_only_when_content_changes(tmp_path: Path):
    sandbox = _sandbox()
    channel = MarkdownMailboxChannel(tmp_path)
    channel.send_task(sandbox, WorkerTask("job-1", "Work", "coding-worker"))
    progress = tmp_path / sandbox.sandbox_id / "PROGRESS.md"

    progress.write_text("Running tests.\n", encoding="utf-8")
    first = list(channel.events(sandbox))
    assert first[0].payload == {"markdown": "Running tests.\n"}
    assert not list(channel.events(sandbox))

    progress.write_text("Tests passed.\n", encoding="utf-8")
    second = list(channel.events(sandbox))
    assert second[0].payload == {"markdown": "Tests passed.\n"}


def test_mailbox_refuses_overwrite_malformed_result_and_oversized_file(tmp_path: Path):
    sandbox = _sandbox()
    channel = MarkdownMailboxChannel(tmp_path, max_file_bytes=1024)
    task = WorkerTask("job-1", "Work", "coding-worker")
    channel.send_task(sandbox, task)

    with pytest.raises(MarkdownMailboxError, match="already exists"):
        channel.send_task(sandbox, task)

    result_path = tmp_path / sandbox.sandbox_id / "RESULT.md"
    result_path.write_text("not the protocol", encoding="utf-8")
    with pytest.raises(MarkdownMailboxError, match="invalid heading"):
        channel.retrieve_result(sandbox)

    result_path.write_bytes(b"x" * 1025)
    with pytest.raises(MarkdownMailboxError, match="size limit"):
        channel.retrieve_result(sandbox)


def test_mailbox_rejects_untrusted_sandbox_identity(tmp_path: Path):
    sandbox = _sandbox()
    sandbox.sandbox_id = "../escape"
    channel = MarkdownMailboxChannel(tmp_path)

    with pytest.raises(MarkdownMailboxError, match="trusted mailbox identifier"):
        channel.send_task(sandbox, WorkerTask("job-1", "Work", "coding-worker"))
