"""Offline adversarial tests for the host-to-guest tool-session contract."""

from __future__ import annotations

import base64
import json
import threading
import time
from collections.abc import Callable
from typing import Any

import pytest

from night_shifts.contracts.worker_tool import WorkerToolCall, WorkerToolProvider, WorkerToolSpec
from night_shifts.models import SandboxRecord, SandboxSpec
from night_shifts.tool_session import SandboxToolSession, ToolSessionError
from night_shifts.worker_capabilities import worker_tool_names


class FakeTransport:
    def __init__(self, reply: Callable[[dict[str, Any]], bytes] | None = None) -> None:
        self.reply = reply or _reply
        self.sent: list[dict[str, Any]] = []
        self.pending: list[bytes] = []
        self.closed = False

    def send(self, frame: bytes, *, timeout_seconds: float) -> None:
        assert timeout_seconds > 0
        if self.closed:
            raise OSError("closed")
        message = json.loads(frame)
        self.sent.append(message)
        self.pending.append(self.reply(message))

    def receive(self, *, max_bytes: int, timeout_seconds: float) -> bytes:
        assert max_bytes > 0 and timeout_seconds > 0
        if self.closed:
            raise OSError("closed")
        return self.pending.pop(0)

    def close(self) -> None:
        self.closed = True


def _frame(value: dict[str, Any]) -> bytes:
    return json.dumps(value, separators=(",", ":")).encode() + b"\n"


def _reply(message: dict[str, Any]) -> bytes:
    identity = {key: message[key] for key in ("job_id", "sandbox_id", "session_id")}
    if message["type"] == "hello":
        return _frame({"version": 1, "type": "hello_ack", **identity})
    operation = message["operation"]
    if operation == "tool":
        payload = {"output": "fixture-result", "is_error": False}
    elif operation == "export_chunk":
        payload = {"data": base64.b64encode(b"patch").decode(), "eof": True}
    else:
        payload = {}
    return _frame({"version": 1, "type": "response", **identity,
                   "request_id": message["request_id"], "ok": True, "payload": payload})


def _session(transport: FakeTransport, profile: str = "coding-worker", **limits: Any) -> SandboxToolSession:
    sandbox_id = "a" * 32
    sandbox = SandboxRecord(
        job_id="fixture-job", sandbox_id=sandbox_id, backend="hyperv",
        external_id=f"night-shift-{sandbox_id}", spec=SandboxSpec(),
    )
    tools = tuple(WorkerToolSpec(name, "fixture", {"type": "object"})
                  for name in worker_tool_names(profile))
    return SandboxToolSession(sandbox, profile, tools, transport,
                              deadline=time.monotonic() + 10, **limits)


def _ready(transport: FakeTransport, profile: str = "coding-worker", **limits: Any) -> SandboxToolSession:
    session = _session(transport, profile, **limits)
    session.start()
    session.load_chunk(b"snapshot", offset=0, final=True)
    return session


def test_bound_handshake_model_facade_and_orchestrator_only_transfer() -> None:
    transport = FakeTransport()
    session = _ready(transport)
    tools = session.model_tools()
    assert isinstance(tools, WorkerToolProvider)
    assert not hasattr(tools, "load_chunk")
    assert not hasattr(tools, "export_chunk")
    assert tuple(spec.name for spec in tools.available_tools()) == worker_tool_names("coding-worker")

    result = tools.invoke(WorkerToolCall("run_command", {"argv": ["git", "status"]}))
    assert result.output == "fixture-result" and not result.is_error
    assert transport.sent[-1]["payload"]["name"] == "run_command"
    session.finalize()
    assert session.export_chunk(offset=0, limit_bytes=16) == (b"patch", True)
    assert [message.get("operation") for message in transport.sent] == [
        None, "load_chunk", "tool", "finalize", "export_chunk",
    ]
    with pytest.raises(ToolSessionError, match="wrong phase"):
        tools.invoke(WorkerToolCall("run_command", {"argv": ["git", "status"]}))
    session.close()
    assert transport.closed


def test_job_command_budget_is_applied_even_when_model_omits_timeout() -> None:
    transport = FakeTransport()
    session = _ready(transport, max_command_seconds=5)
    tools = session.model_tools()
    assert not tools.invoke(WorkerToolCall("run_command", {"argv": ["git", "status"]})).is_error
    assert transport.sent[-1]["payload"]["arguments"]["timeout_seconds"] == 5
    previous = len(transport.sent)
    assert tools.invoke(WorkerToolCall("run_command", {
        "argv": ["git", "status"], "timeout_seconds": 6,
    })).is_error
    assert len(transport.sent) == previous
    session.cancel()


def test_repository_tool_arguments_are_rejected_on_host_before_transport() -> None:
    transport = FakeTransport()
    worker = _ready(transport).model_tools()
    initial = len(transport.sent)
    for name, arguments in (
        ("read_file", {"path": "../secret"}),
        ("list_files", {"path": "/tmp"}),
        ("search_text", {"query": "x" * 257}),
        ("apply_patch", {"path": "x.txt", "expected_sha256": "no",
                         "find": "x", "replace": "y"}),
        ("apply_patch", {"path": "x.txt", "expected_sha256": None,
                         "find": "x", "replace": "y"}),
        ("run_command", {"argv": ["git", "status"], "max_output_bytes": 65536}),
    ):
        assert worker.invoke(WorkerToolCall(name, arguments)).is_error
    assert len(transport.sent) == initial
    assert not worker.invoke(WorkerToolCall("read_file", {"path": "x.txt"})).is_error
    assert not worker.invoke(WorkerToolCall("apply_patch", {
        "path": "x.txt", "expected_sha256": None, "find": "", "replace": "new",
    })).is_error
    read_only = _ready(FakeTransport(), "read-only-worker").model_tools()
    assert read_only.invoke(WorkerToolCall("apply_patch", {
        "path": "x.txt", "expected_sha256": None, "find": "", "replace": "new",
    })).is_error


def test_unauthorized_and_invalid_model_calls_do_not_reach_guest() -> None:
    transport = FakeTransport()
    session = _ready(transport, "read-only-worker")
    count = len(transport.sent)
    assert session.model_tools().invoke(WorkerToolCall("run_command", {"argv": ["git", "status"]})).is_error
    assert session.model_tools().invoke(WorkerToolCall("unknown", {})).is_error
    assert len(transport.sent) == count

    coding = FakeTransport()
    worker = _ready(coding).model_tools()
    assert worker.invoke(WorkerToolCall("run_command", {"argv": ["sh", "-c", "pwd"]})).is_error
    assert worker.invoke(WorkerToolCall("run_command", {"argv": ["git", "status"], "timeout_seconds": True})).is_error
    assert worker.invoke(WorkerToolCall("write_artifact", {"name": "../secret", "kind": "report", "content": "x"})).is_error
    assert len(coding.sent) == 2


@pytest.mark.parametrize("field", ["job_id", "sandbox_id", "session_id"])
def test_handshake_rejects_wrong_identity(field: str) -> None:
    def bad(message: dict[str, Any]) -> bytes:
        reply = json.loads(_reply(message))
        reply[field] = "wrong"
        return _frame(reply)

    transport = FakeTransport(bad)
    with pytest.raises(ToolSessionError, match="mismatch"):
        _session(transport).start()
    assert transport.closed


@pytest.mark.parametrize("field", ["job_id", "sandbox_id", "session_id"])
def test_operation_rejects_wrong_identity(field: str) -> None:
    def bad(message: dict[str, Any]) -> bytes:
        reply = json.loads(_reply(message))
        if message.get("operation") == "tool":
            reply[field] = "wrong"
        return _frame(reply)

    transport = FakeTransport(bad)
    session = _ready(transport)
    with pytest.raises(ToolSessionError, match="mismatch"):
        session.model_tools().invoke(WorkerToolCall("run_command", {"argv": ["git", "status"]}))
    assert transport.closed


@pytest.mark.parametrize("corrupt", [
    lambda msg: b"{",  # truncated
    lambda msg: b"\xff\n",  # invalid UTF-8
    lambda msg: b"{" + b"x" * 65536 + b"}\n",  # oversized
    lambda msg: _frame({"version": 99, "type": "response"}),
    lambda msg: _frame({"version": 1, "type": "request", "payload": {}}),
    lambda msg: _frame({"version": 1, "type": "response", "unexpected": True}),
    lambda msg: _reply(msg)[:-1] + b"\n\n",  # two frames at once
])
def test_malformed_and_unexpected_reply_fails_closed(corrupt: Callable[[dict[str, Any]], bytes]) -> None:
    def bad(message: dict[str, Any]) -> bytes:
        return corrupt(message) if message.get("operation") == "tool" else _reply(message)

    transport = FakeTransport(bad)
    session = _ready(transport)
    with pytest.raises(ToolSessionError):
        session.model_tools().invoke(WorkerToolCall("run_command", {"argv": ["git", "status"]}))
    assert transport.closed


@pytest.mark.parametrize("change", [
    lambda msg, reply: reply.update(request_id=msg["request_id"] - 1),  # replay
    lambda msg, reply: reply.update(request_id=msg["request_id"] + 1),
    lambda msg, reply: reply.update(ok="true"),
    lambda msg, reply: reply.update(request_id=True),  # bool is not request ID 1
])
def test_replayed_mismatched_or_bad_status_response_is_rejected(
    change: Callable[[dict[str, Any], dict[str, Any]], None],
) -> None:
    def bad(message: dict[str, Any]) -> bytes:
        reply = json.loads(_reply(message))
        if message.get("operation") == "tool":
            change(message, reply)
        return _frame(reply)

    transport = FakeTransport(bad)
    session = _ready(transport)
    with pytest.raises(ToolSessionError):
        session.model_tools().invoke(WorkerToolCall("run_command", {"argv": ["git", "status"]}))
    assert transport.closed


def test_late_reply_after_operation_timeout_is_terminal_even_if_transport_ignores_timeout() -> None:
    class LateTransport(FakeTransport):
        def receive(self, *, max_bytes: int, timeout_seconds: float) -> bytes:
            if self.sent[-1].get("operation") == "load_chunk":
                time.sleep(0.03)  # deliberately violate the fake transport's I/O deadline
            return super().receive(max_bytes=max_bytes, timeout_seconds=timeout_seconds)

    transport = LateTransport()
    session = _session(transport, operation_timeout_seconds=0.01)
    session.start()
    with pytest.raises(ToolSessionError, match="deadline"):
        session.load_chunk(b"a", offset=0, final=True)
    assert transport.closed


def test_mutating_request_timeout_is_terminal_no_replay() -> None:
    class TimeoutTransport(FakeTransport):
        def receive(self, *, max_bytes: int, timeout_seconds: float) -> bytes:
            if self.sent[-1].get("operation") == "load_chunk":
                raise TimeoutError("completion unknown")
            return super().receive(max_bytes=max_bytes, timeout_seconds=timeout_seconds)

    transport = TimeoutTransport()
    session = _session(transport)
    session.start()
    with pytest.raises(ToolSessionError, match="completion unknown"):
        session.load_chunk(b"a", offset=0, final=True)
    assert transport.closed
    with pytest.raises(ToolSessionError):
        session.load_chunk(b"a", offset=0, final=True)
    assert [message.get("operation") for message in transport.sent].count("load_chunk") == 1


def test_cancellation_discards_late_reply_and_closes_in_flight_transport() -> None:
    entered = threading.Event()
    released = threading.Event()

    class BlockedTransport(FakeTransport):
        def receive(self, *, max_bytes: int, timeout_seconds: float) -> bytes:
            if self.sent[-1].get("operation") == "tool":
                entered.set()
                assert released.wait(3), "fake transport failed to unblock"
                return self.pending.pop(0)  # hostile late success after cancellation
            return super().receive(max_bytes=max_bytes, timeout_seconds=timeout_seconds)

        def close(self) -> None:
            super().close()
            released.set()

    transport = BlockedTransport()
    session = _ready(transport)
    errors: list[Exception] = []

    def invoke() -> None:
        try:
            session.model_tools().invoke(WorkerToolCall("run_command", {"argv": ["git", "status"]}))
        except Exception as exc:
            errors.append(exc)

    worker = threading.Thread(target=invoke)
    worker.start()
    assert entered.wait(3)
    with pytest.raises(ToolSessionError, match="in progress"):
        session.finalize()  # one outstanding request
    session.cancel()
    worker.join(3)
    assert not worker.is_alive()
    assert len(errors) == 1 and isinstance(errors[0], ToolSessionError)
    assert transport.closed
    with pytest.raises(ToolSessionError):
        session.finalize()


@pytest.mark.parametrize("corrupt", [
    lambda msg: _frame({"version": True, "type": "response",  # bool is not version 1
                         **{key: msg[key] for key in ("job_id", "sandbox_id", "session_id")},
                         "request_id": msg["request_id"], "ok": True, "payload": {}}),
    lambda msg: _reply(msg).replace(b'"ok":true', b'"ok":true,"ok":true'),
    lambda msg: _reply(msg).replace(b'"payload":', b'"payload":{"x":1,"x":2},"other":'),
])
def test_duplicate_keys_and_boolean_version_are_rejected(
    corrupt: Callable[[dict[str, Any]], bytes],
) -> None:
    transport = FakeTransport(lambda msg: corrupt(msg) if msg.get("operation") == "finalize" else _reply(msg))
    session = _ready(transport)
    with pytest.raises(ToolSessionError):
        session.finalize()
    assert transport.closed


@pytest.mark.parametrize("operation", ["load_chunk", "finalize"])
def test_mutating_acknowledgement_must_be_empty(operation: str) -> None:
    def bad(message: dict[str, Any]) -> bytes:
        reply = json.loads(_reply(message))
        if message.get("operation") == operation:
            reply["payload"] = {"unexpected": "not an ack"}
        return _frame(reply)

    transport = FakeTransport(bad)
    session = _session(transport)
    session.start()
    if operation == "finalize":
        session.load_chunk(b"a", offset=0, final=True)
    with pytest.raises(ToolSessionError, match="acknowledgement"):
        if operation == "load_chunk":
            session.load_chunk(b"a", offset=0, final=True)
        else:
            session.finalize()
    assert transport.closed


def test_bound_identity_is_snapshotted_from_trusted_record() -> None:
    sandbox_id = "a" * 32
    sandbox = SandboxRecord(job_id="fixture-job", sandbox_id=sandbox_id,
                            backend="hyperv", external_id=f"night-shift-{sandbox_id}",
                            spec=SandboxSpec())
    specs = tuple(WorkerToolSpec(name, "fixture", {"type": "object"})
                  for name in worker_tool_names("coding-worker"))
    transport = FakeTransport()
    session = SandboxToolSession(sandbox, "coding-worker", specs, transport,
                                 deadline=time.monotonic() + 10)
    sandbox.job_id = "changed-later"
    session.start()
    assert transport.sent[0]["job_id"] == "fixture-job"
    session.close()


def test_bad_export_or_unknown_error_code_closes_session() -> None:
    def bad(message: dict[str, Any]) -> bytes:
        reply = json.loads(_reply(message))
        if message.get("operation") == "export_chunk":
            reply["payload"] = {"data": "invalid!", "eof": True}
        return _frame(reply)

    transport = FakeTransport(bad)
    session = _ready(transport)
    session.finalize()
    with pytest.raises(ToolSessionError, match="encoding"):
        session.export_chunk(offset=0, limit_bytes=16)
    assert transport.closed

    def bad_error(message: dict[str, Any]) -> bytes:
        reply = json.loads(_reply(message))
        if message.get("operation") == "tool":
            reply.pop("payload")
            reply.update(ok=False, error={"code": "arbitrary", "message": "x"})
        return _frame(reply)

    second = FakeTransport(bad_error)
    ready = _ready(second)
    with pytest.raises(ToolSessionError, match="invalid guest error"):
        ready.model_tools().invoke(WorkerToolCall("run_command", {"argv": ["git", "status"]}))
    assert second.closed
