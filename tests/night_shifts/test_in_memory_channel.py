import pytest

from night_shifts.channels import InMemoryWorkerChannel
from night_shifts.contracts import WorkerChannel
from night_shifts.models import NightShiftEvent, SandboxRecord, SandboxSpec
from night_shifts.protocol import WorkerOutcome, WorkerResult, WorkerTask


def _sandbox() -> SandboxRecord:
    return SandboxRecord(job_id="job-1", backend="test", spec=SandboxSpec())


def test_in_memory_channel_implements_contract_and_preserves_messages():
    sandbox = _sandbox()
    channel = InMemoryWorkerChannel()
    task = WorkerTask("job-1", "Work", "coding-worker")
    event = NightShiftEvent("progress", "worker", {}, "job-1")
    result = WorkerResult("job-1", WorkerOutcome.SUCCESS, "done")

    assert isinstance(channel, WorkerChannel)
    channel.send_task(sandbox, task)
    channel.queue_event(sandbox, event)
    channel.set_result(sandbox, result)

    assert channel.sent_tasks[sandbox.sandbox_id] == [task]
    assert list(channel.events(sandbox)) == [event]
    assert channel.retrieve_result(sandbox) == result


def test_in_memory_channel_fails_after_close():
    sandbox = _sandbox()
    channel = InMemoryWorkerChannel()
    channel.close(sandbox)

    with pytest.raises(RuntimeError, match="worker channel is closed"):
        channel.send_task(sandbox, WorkerTask("job-1", "Work", "coding-worker"))
