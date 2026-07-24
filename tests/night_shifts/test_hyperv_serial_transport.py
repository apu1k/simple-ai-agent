from collections.abc import Sequence

import pytest

from night_shifts.backends.hyperv import HyperVError
from night_shifts.backends.hyperv_serial import HyperVSerialTransport, serial_pipe_path
from night_shifts.models import NightShiftEvent, SandboxRecord
from night_shifts.protocol import (
    WorkerOutcome,
    WorkerResult,
    WorkerTask,
    decode_task,
    decode_worker_message,
    encode_event,
    encode_result,
    encode_task,
)


class DuplexChannel:
    def __init__(self, chunks: Sequence[bytes]):
        self.chunks = list(chunks)
        self.written = bytearray()
        self.closed = False

    def read(self, size: int = -1) -> bytes:
        if not self.chunks:
            return b""
        return self.chunks.pop(0)

    def write(self, data: bytes) -> int:
        self.written.extend(data)
        return len(data)

    def flush(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class FakeConnector:
    def __init__(self, channel: DuplexChannel):
        self.channel = channel
        self.calls: list[tuple[str, float]] = []

    def connect(self, path: str, *, timeout_seconds: float) -> DuplexChannel:
        self.calls.append((path, timeout_seconds))
        return self.channel


def sandbox() -> SandboxRecord:
    return SandboxRecord(
        job_id="job-1",
        backend="hyperv",
        sandbox_id="0123456789abcdef0123456789abcdef",
    )


def test_serial_transport_round_trips_fragmented_jsonl_frames():
    event_line = encode_event(
        NightShiftEvent("progress_updated", "worker", {"percent": 50}, "job-1")
    )
    result_line = encode_result(
        WorkerResult("job-1", WorkerOutcome.SUCCESS, "completed")
    )
    payload = f"{event_line}\r\n{result_line}\n".encode()
    channel = DuplexChannel([payload[:11], payload[11:37], payload[37:]])
    connector = FakeConnector(channel)
    transport = HyperVSerialTransport(connector=connector, read_size=16)
    record = sandbox()
    task = WorkerTask("job-1", "Work", "coding-worker")

    transport.send(record, encode_task(task))
    events = list(transport.event_messages(record))
    result = decode_worker_message(transport.result_message(record))

    assert decode_task(channel.written.decode().rstrip("\n")) == task
    assert decode_worker_message(events[0]).event_type == "progress_updated"
    assert isinstance(result, WorkerResult)
    assert result.outcome is WorkerOutcome.SUCCESS
    assert connector.calls == [(serial_pipe_path(record.sandbox_id), 30.0)]


def test_result_retrieval_preserves_events_not_consumed_yet():
    event_line = encode_event(NightShiftEvent("check_passed", "worker", {}, "job-1"))
    result_line = encode_result(WorkerResult("job-1", WorkerOutcome.SUCCESS, "done"))
    channel = DuplexChannel([f"{event_line}\n{result_line}\n".encode()])
    transport = HyperVSerialTransport(connector=FakeConnector(channel))
    record = sandbox()

    result = decode_worker_message(transport.result_message(record))
    events = list(transport.event_messages(record))

    assert isinstance(result, WorkerResult)
    assert decode_worker_message(events[0]).event_type == "check_passed"


def test_serial_transport_rejects_duplicate_tasks_and_oversized_frames():
    channel = DuplexChannel([b"12345"])
    transport = HyperVSerialTransport(
        connector=FakeConnector(channel),
        max_message_bytes=4,
    )
    record = sandbox()
    transport.send(record, "{}")

    with pytest.raises(HyperVError, match="already been sent"):
        transport.send(record, "{}")
    with pytest.raises(HyperVError, match="size limit"):
        list(transport.event_messages(record))

    assert channel.closed


def test_serial_transport_rejects_untrusted_sandbox_ids_before_connecting():
    channel = DuplexChannel([])
    connector = FakeConnector(channel)
    transport = HyperVSerialTransport(connector=connector)
    record = sandbox()
    record.sandbox_id = "../../personal-pipe"

    with pytest.raises(HyperVError, match="trusted 32-character hexadecimal"):
        transport.send(record, "{}")

    assert connector.calls == []


def test_close_is_idempotent():
    channel = DuplexChannel([])
    transport = HyperVSerialTransport(connector=FakeConnector(channel))
    record = sandbox()
    transport.send(record, "{}")

    transport.close(record)
    transport.close(record)

    assert channel.closed
