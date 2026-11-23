"""The host holds the task until the guest announces it has opened ttyS0."""

from collections.abc import Sequence

import pytest

from night_shifts.backends.hyperv import HyperVError
from night_shifts.backends.hyperv_serial import HyperVSerialTransport
from night_shifts.models import NightShiftEvent, SandboxRecord
from night_shifts.protocol import (
    ProtocolError,
    WorkerOutcome,
    WorkerResult,
    WorkerTask,
    decode_task,
    encode_event,
    encode_ready,
    encode_result,
)

READY = (encode_ready() + "\n").encode()
EVENT = (encode_event(NightShiftEvent("protocol_test_started", "worker", {}, "job-1")) + "\n").encode()
RESULT = (encode_result(WorkerResult("job-1", WorkerOutcome.SUCCESS, "done")) + "\n").encode()
TASK = WorkerTask("job-1", "phase3-protocol-success", "protocol-test-worker")


class ScriptedChannel:
    """Records how many chunks the host had read when it wrote."""

    def __init__(self, chunks: Sequence[bytes]):
        self.chunks = list(chunks)
        self.reads = 0
        self.writes: list[tuple[int, bytes]] = []
        self.closed = False

    def read(self, size: int = -1) -> bytes:
        if not self.chunks:
            return b""
        self.reads += 1
        return self.chunks.pop(0)

    def write(self, data: bytes) -> int:
        self.writes.append((self.reads, bytes(data)))
        return len(data)

    def flush(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class Connector:
    def __init__(self, channel: ScriptedChannel):
        self.channel = channel

    def connect(self, path: str, *, timeout_seconds: float) -> ScriptedChannel:
        return self.channel


def _record() -> SandboxRecord:
    return SandboxRecord(job_id="job-1", backend="hyperv",
                         sandbox_id="0123456789abcdef0123456789abcdef")


def _transport(channel: ScriptedChannel, *, await_ready: bool = True) -> HyperVSerialTransport:
    return HyperVSerialTransport(connector=Connector(channel), await_guest_ready=await_ready)


def test_ready_frame_matches_the_guest_encoding():
    from night_shifts.guest import protocol_test_bootstrap as guest

    class Sink:
        data = b""

        def write(self, chunk: bytes) -> int:
            self.data += chunk
            return len(chunk)

        def flush(self) -> None:
            return None

    sink = Sink()
    guest._write_frame(sink, "ready", {})  # type: ignore[arg-type]
    assert sink.data == READY


def test_task_is_held_until_ready_and_boot_noise_is_ignored():
    channel = ScriptedChannel([b"\x1b[0m\xff\r\n", b"\r\n", b"booting\n", READY, READY, EVENT, RESULT])
    transport = _transport(channel)
    record = _record()

    transport.send_task(record, TASK)
    assert channel.writes == []
    events = list(transport.events(record))
    result = transport.retrieve_result(record)

    assert [reads for reads, _ in channel.writes] == [4]  # written right after the first ready
    assert decode_task(channel.writes[0][1].decode().rstrip("\n")) == TASK
    assert [event.event_type for event in events] == ["protocol_test_started"]
    assert result.outcome is WorkerOutcome.SUCCESS


def test_guest_eof_before_ready_never_sends_the_task():
    channel = ScriptedChannel([b"noise\n"])
    transport = _transport(channel)
    record = _record()
    transport.send_task(record, TASK)

    with pytest.raises(HyperVError, match="closed before a result"):
        list(transport.events(record))
    assert channel.writes == [] and channel.closed


def test_unbounded_noise_before_ready_fails_closed():
    channel = ScriptedChannel([b"x\n"] * 65 + [READY])
    transport = _transport(channel)
    record = _record()
    transport.send_task(record, TASK)

    with pytest.raises(HyperVError, match="before it was ready"):
        list(transport.events(record))
    assert channel.writes == [] and channel.closed


def test_repeated_ready_after_the_task_is_bounded():
    channel = ScriptedChannel([READY] * 18 + [RESULT])
    transport = _transport(channel)
    record = _record()
    transport.send_task(record, TASK)

    with pytest.raises(HyperVError, match="kept announcing readiness"):
        transport.retrieve_result(record)
    assert len(channel.writes) == 1


def test_garbage_after_the_task_is_still_a_protocol_error():
    channel = ScriptedChannel([READY, b"not json\n"])
    transport = _transport(channel)
    record = _record()
    transport.send_task(record, TASK)

    with pytest.raises(ProtocolError):
        transport.retrieve_result(record)


def test_without_handshake_task_is_written_immediately_and_stray_ready_is_ignored():
    channel = ScriptedChannel([READY, RESULT])
    transport = _transport(channel, await_ready=False)
    record = _record()

    transport.send_task(record, TASK)
    assert [reads for reads, _ in channel.writes] == [0]
    assert transport.retrieve_result(record).outcome is WorkerOutcome.SUCCESS
