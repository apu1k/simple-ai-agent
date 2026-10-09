"""Offline bootstrap entry-point regressions; never open a real serial device."""

from __future__ import annotations

import errno
import io
import json
from pathlib import Path

import pytest

from night_shifts.guest import protocol_test_bootstrap as bootstrap
from night_shifts.models import AgentPlan
from night_shifts.protocol import WorkerTask, encode_task


class _DuplexChannel:
    def __init__(self, incoming: bytes):
        self.incoming = io.BytesIO(incoming)
        self.outgoing = io.BytesIO()
        self.closed = False

    def __enter__(self) -> _DuplexChannel:
        return self

    def __exit__(self, *_exception: object) -> None:
        self.closed = True

    def readline(self, size: int = -1) -> bytes:
        return self.incoming.readline(size)

    def read(self, size: int = -1) -> bytes:
        return self.incoming.read(size)

    def write(self, data: bytes) -> int:
        return self.outgoing.write(data)

    def flush(self) -> None:
        self.outgoing.flush()


def _bind_channel(monkeypatch: pytest.MonkeyPatch, channel: _DuplexChannel) -> None:
    def open_fake(path: str) -> _DuplexChannel:
        assert path == "/dev/ttyS0"
        return channel

    monkeypatch.setattr(bootstrap, "_open_serial", open_fake)


def test_main_fails_closed_when_serial_open_raises_io_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def unavailable(path: str) -> None:
        assert path == "/dev/ttyS0"
        raise OSError(errno.EIO, "Input/output error")

    monkeypatch.setattr(bootstrap, "_open_serial", unavailable)

    assert bootstrap.main([]) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert "protocol bootstrap failed:" in output.err
    assert "Input/output error" in output.err


def test_main_closes_channel_when_reading_task_raises_io_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    channel = _DuplexChannel(b"")
    _bind_channel(monkeypatch, channel)

    def unreadable(_size: int = -1) -> bytes:
        raise OSError(errno.EIO, "Input/output error")

    monkeypatch.setattr(channel, "readline", unreadable)

    assert bootstrap.main([]) == 1
    assert channel.closed
    assert channel.outgoing.getvalue() == b""
    assert "Input/output error" in capsys.readouterr().err


def test_main_fails_closed_on_controller_disconnect_before_task(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    channel = _DuplexChannel(b"")
    _bind_channel(monkeypatch, channel)

    assert bootstrap.main([]) == 1
    assert channel.closed
    assert channel.outgoing.getvalue() == b""
    assert "controller closed the serial channel before sending a task" in capsys.readouterr().err


def test_main_emits_result_and_closes_after_controller_eof(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    task = WorkerTask(
        job_id="bootstrap-main-test",
        objective="phase3-protocol-success",
        worker_profile="protocol-test-worker",
        plan=AgentPlan.NORMAL,
    )
    channel = _DuplexChannel((encode_task(task) + "\n").encode())
    _bind_channel(monkeypatch, channel)

    assert bootstrap.main([]) == 0
    assert channel.closed
    messages = [json.loads(line) for line in channel.outgoing.getvalue().splitlines()]
    assert [message["kind"] for message in messages] == ["event", "event", "result"]
    assert messages[-1]["payload"]["job_id"] == task.job_id
    assert messages[-1]["payload"]["outcome"] == "success"
    assert capsys.readouterr().err == ""


def test_protocol_unit_keeps_poweroff_on_success_and_failure() -> None:
    # A stopped console is not enough to distinguish task success from bootstrap failure.
    unit = Path(bootstrap.__file__).with_name("night-shift-protocol-test.service").read_text(encoding="utf-8")
    lines = unit.splitlines()
    assert "SuccessAction=poweroff" in lines
    assert "FailureAction=poweroff" in lines
