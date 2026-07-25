import json
from collections.abc import Callable

from night_shifts.guest.protocol_test_bootstrap import run_once
from night_shifts.models import AgentPlan
from night_shifts.protocol import WorkerOutcome, WorkerTask, encode_task


class MemoryChannel:
    def __init__(self, task: WorkerTask):
        self.input = bytearray((encode_task(task) + "\n").encode())
        self.output = bytearray()

    def readline(self, size: int = -1) -> bytes:
        if not self.input:
            return b""
        limit = len(self.input) if size < 0 else min(size, len(self.input))
        newline = self.input.find(b"\n", 0, limit)
        end = limit if newline < 0 else newline + 1
        value = bytes(self.input[:end])
        del self.input[:end]
        return value

    def write(self, value: bytes) -> int:
        self.output.extend(value)
        return len(value)

    def flush(self) -> None:
        pass


def _task(objective: str) -> WorkerTask:
    return WorkerTask(
        job_id="phase3-test-job",
        objective=objective,
        worker_profile="protocol-test-worker",
        plan=AgentPlan.NORMAL,
    )


def _messages(channel: MemoryChannel) -> list[dict]:
    return [json.loads(line) for line in channel.output.decode().splitlines()]


def test_protocol_bootstrap_emits_events_and_one_success_result():
    channel = MemoryChannel(_task("phase3-protocol-success"))

    run_once(channel)  # type: ignore[arg-type]

    messages = _messages(channel)
    assert [message["kind"] for message in messages] == ["event", "event", "result"]
    assert messages[-1]["payload"]["outcome"] == WorkerOutcome.SUCCESS.value
    assert all(message["version"] == 1 for message in messages)


def test_protocol_bootstrap_supports_a_controlled_delay():
    channel = MemoryChannel(_task("phase3-protocol-sleep:12.5"))
    delays: list[float] = []
    sleeper: Callable[[float], None] = delays.append

    run_once(channel, sleep=sleeper)  # type: ignore[arg-type]

    messages = _messages(channel)
    assert delays == [12.5]
    assert messages[1]["payload"]["event_type"] == "protocol_test_sleeping"
    assert messages[-1]["payload"]["outcome"] == WorkerOutcome.SUCCESS.value


def test_protocol_bootstrap_rejects_arbitrary_objectives_without_executing_them():
    channel = MemoryChannel(_task("python -c 'do something'"))

    run_once(channel)  # type: ignore[arg-type]

    result = _messages(channel)[-1]
    assert result["kind"] == "result"
    assert result["payload"]["outcome"] == WorkerOutcome.FAILED.value
    assert "fixed Phase 3" in result["payload"]["error"]
