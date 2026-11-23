import os
import sys
import threading

import pytest

from night_shifts.backends.hyperv import HyperVError
from night_shifts.backends.hyperv_serial import HyperVSerialTransport, close_channel
from night_shifts.models import SandboxRecord


class PipeConnector:
    def __init__(self, channel):
        self.channel = channel

    def connect(self, path: str, *, timeout_seconds: float):
        return self.channel


def _sandbox() -> SandboxRecord:
    return SandboxRecord(job_id="job-1", backend="hyperv",
                         sandbox_id="0123456789abcdef0123456789abcdef")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows synchronous-handle behaviour")
def test_close_does_not_deadlock_on_a_blocked_reader_of_a_silent_peer():
    read_fd, write_fd = os.pipe()
    channel = os.fdopen(read_fd, "rb", buffering=0)
    transport = HyperVSerialTransport(connector=PipeConnector(channel))
    record = _sandbox()
    errors: list[BaseException] = []
    reading = threading.Event()

    def reader() -> None:
        reading.set()
        try:
            transport.retrieve_result(record)
        except BaseException as exc:  # noqa: BLE001 - recorded for assertion
            errors.append(exc)

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    assert reading.wait(5)
    thread.join(0.5)
    assert thread.is_alive(), "reader should be blocked on the silent pipe"

    closer = threading.Thread(target=transport.close, args=(record,), daemon=True)
    closer.start()
    closer.join(10)
    try:
        assert not closer.is_alive(), "close() deadlocked on the blocked reader"
        thread.join(10)
        assert not thread.is_alive()
        assert len(errors) == 1 and isinstance(errors[0], HyperVError)
    finally:
        os.close(write_fd)


def test_close_channel_closes_fakes_without_a_handle():
    class Fake:
        closed = False

        def close(self) -> None:
            self.closed = True

    fake = Fake()
    assert close_channel(fake) is True  # type: ignore[arg-type]
    assert fake.closed
