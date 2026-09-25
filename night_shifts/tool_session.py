"""Host-side contract for one bounded sandbox tool session (no VM transport yet).

A transport must frame exactly one JSONL message per receive, bound I/O by the
supplied monotonic timeout, and unblock in-flight I/O when closed. The existing
whole-task WorkerChannel protocol is independent of this session.
"""

from __future__ import annotations

import base64
import binascii
import json
import math
import re
import secrets
import threading
import time
from collections.abc import Mapping
from typing import Any, Protocol

from night_shifts.contracts.worker_tool import (
    WorkerToolCall,
    WorkerToolProvider,
    WorkerToolResult,
    WorkerToolSpec,
)
from night_shifts.models import SandboxRecord
from night_shifts.worker_capabilities import (
    APPLY_PATCH_TOOL, LIST_FILES_TOOL, READ_FILE_TOOL, RUN_COMMAND_TOOL,
    SEARCH_TEXT_TOOL, WRITE_ARTIFACT_TOOL, worker_tool_names,
)
from night_shifts.worker_policy import WorkerPolicyError, approve_worker_command

VERSION = 1
_SANDBOX_ID = re.compile(r"[0-9a-f]{32}\Z")
_ARTIFACT_NAME = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}\Z")
_REPO_PART = re.compile(r"[A-Za-z0-9._-]{1,100}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_RESERVED = frozenset({"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                       *(f"LPT{i}" for i in range(1, 10))})


def _repo_path(value: Any, *, root: bool = False) -> None:
    if root and value == ".":
        return
    if (not isinstance(value, str) or not value or len(value) > 240
            or value.startswith("/") or "\\" in value):
        raise ValueError("repository path must be a bounded relative POSIX path")
    parts = value.split("/")
    if len(parts) > 8 or any(
        not _REPO_PART.fullmatch(part) or part.endswith(".") or part.lower() == ".git"
        or part.upper().split(".")[0] in _RESERVED for part in parts
    ):
        raise ValueError("repository path is not portable or escapes the workspace")
_ARTIFACT_KINDS = frozenset({"test-log", "analysis", "report", "metadata"})
_ERROR_CODES = frozenset({"invalid_request", "policy_denied", "operation_failed", "tool_error"})


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON field")
        value[key] = item
    return value


def _reject_constant(value: str) -> None:
    raise ValueError(f"nonfinite JSON constant: {value}")


class ToolSessionError(RuntimeError):
    """A session is unusable; never replay an operation after this error."""


class ToolSessionRemoteError(ToolSessionError):
    """A typed, bounded guest error (not proof that a mutation was rolled back)."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


class ToolSessionTransport(Protocol):
    """One bounded duplex channel, supplied by trusted composition.

    Each send/receive must finish within timeout_seconds or raise TimeoutError.
    receive(max_bytes=...) must not buffer unbounded data. close must interrupt
    concurrent I/O, including blocked receives; no daemon-reader workaround.
    """

    def send(self, frame: bytes, *, timeout_seconds: float) -> None: ...
    def receive(self, *, max_bytes: int, timeout_seconds: float) -> bytes: ...
    def close(self) -> None: ...


class _ModelTools:
    """Only this facade, never the orchestrator session, goes to the model loop."""

    def __init__(self, session: SandboxToolSession) -> None:
        self._session = session

    def available_tools(self) -> tuple[WorkerToolSpec, ...]:
        return self._session._tools

    def invoke(self, call: WorkerToolCall) -> WorkerToolResult:
        return self._session._invoke(call)


class SandboxToolSession:
    """One host-initiated session bound to a persisted Hyper-V sandbox and job.

    The echoed random session ID detects cross-session/replayed bytes, not a
    malicious guest's identity. Pipe ACLs and VM binding must be validated before
    a real transport is connected. One request can be in flight at a time.
    """

    def __init__(
        self,
        sandbox: SandboxRecord,
        profile: str,
        tools: tuple[WorkerToolSpec, ...],
        transport: ToolSessionTransport,
        *,
        deadline: float,
        operation_timeout_seconds: float = 30.0,
        max_frame_bytes: int = 64 * 1024,
        max_chunk_bytes: int = 16 * 1024,
        max_transfer_bytes: int = 4 * 1024 * 1024,
    ) -> None:
        if (sandbox.backend != "hyperv" or not _SANDBOX_ID.fullmatch(sandbox.sandbox_id)
                or sandbox.external_id != f"night-shift-{sandbox.sandbox_id}"
                or not sandbox.job_id):
            raise ValueError("session needs a persisted, correctly identified Hyper-V sandbox")
        if tuple(spec.name for spec in tools) != worker_tool_names(profile):
            raise ValueError("tool schemas do not match the approved worker profile")
        if (not math.isfinite(deadline) or deadline <= time.monotonic()
                or not math.isfinite(operation_timeout_seconds)
                or not 0 < operation_timeout_seconds <= 120):
            raise ValueError("session deadline or operation timeout is invalid")
        if (not 4096 <= max_frame_bytes <= 1024 * 1024
                or not 1 <= max_chunk_bytes <= max_frame_bytes // 4
                or not max_chunk_bytes <= max_transfer_bytes <= 64 * 1024 * 1024):
            raise ValueError("session frame or transfer limits are invalid")
        self._job_id = sandbox.job_id
        self._sandbox_id = sandbox.sandbox_id
        self._profile = profile
        self._tools = tools
        self._transport = transport
        self._deadline = deadline
        self._timeout = operation_timeout_seconds
        self._max_frame = max_frame_bytes
        self._max_chunk = max_chunk_bytes
        self._max_transfer = max_transfer_bytes
        self._session_id = secrets.token_hex(16)
        self._next_id = 1
        self._load_offset = 0
        self._export_offset = 0
        self._phase = "new"
        self._closed = False
        self._state_lock = threading.Lock()
        self._operation_lock = threading.Lock()

    def model_tools(self) -> WorkerToolProvider:
        return _ModelTools(self)

    def start(self) -> None:
        """Exchange an identity-bound handshake before loading any data."""
        if not self._operation_lock.acquire(blocking=False):
            raise ToolSessionError("another session operation is in progress")
        try:
            self._require_phase("new")
            operation_deadline = time.monotonic() + self._timeout
            self._transport.send(self._encode({"type": "hello", **self._identity()}),
                                 timeout_seconds=self._remaining(operation_deadline))
            reply = self._receive("hello_ack", {"version", "type", *self._identity()},
                                  deadline=operation_deadline)
            if reply != {"version": VERSION, "type": "hello_ack", **self._identity()}:
                raise ToolSessionError("handshake identity or shape mismatch")
            self._require_phase("new")
            self._phase = "loading"
        except Exception as exc:
            self._abort(exc)
        finally:
            self._operation_lock.release()

    def load_chunk(self, data: bytes, *, offset: int, final: bool) -> None:
        """Orchestrator-only staging; an error leaves the load status unknown."""
        if not isinstance(data, bytes) or len(data) > self._max_chunk or (not data and not final):
            raise ValueError("workspace chunk is invalid or too large")
        if type(offset) is not int or type(final) is not bool or offset != self._load_offset:
            raise ValueError("workspace chunk offset or final flag is invalid")
        if offset + len(data) > self._max_transfer:
            raise ValueError("workspace transfer exceeds the session limit")
        result = self._exchange("loading", "load_chunk", {
            "offset": offset, "data": base64.b64encode(data).decode("ascii"), "final": final,
        })
        if result != {}:
            self._abort(ToolSessionError("invalid load acknowledgement"))
        self._load_offset += len(data)
        if final:
            self._phase = "ready"

    def finalize(self) -> None:
        """Stop model operations; later export is orchestrator-only."""
        result = self._exchange("ready", "finalize", {})
        if result != {}:
            self._abort(ToolSessionError("invalid finalize acknowledgement"))
        self._phase = "exporting"

    def export_chunk(self, *, offset: int, limit_bytes: int) -> tuple[bytes, bool]:
        if (type(offset) is not int or offset != self._export_offset
                or type(limit_bytes) is not int or not 1 <= limit_bytes <= self._max_chunk
                or offset + limit_bytes > self._max_transfer):
            raise ValueError("export offset or chunk limit is invalid")
        result = self._exchange("exporting", "export_chunk", {
            "offset": offset, "limit_bytes": limit_bytes,
        })
        if set(result) != {"data", "eof"} or not isinstance(result["data"], str) or type(result["eof"]) is not bool:
            self._abort(ToolSessionError("invalid export response"))
        try:
            data = base64.b64decode(result["data"], validate=True)
        except (binascii.Error, ValueError) as exc:
            self._abort(ToolSessionError("invalid export encoding"))
            raise AssertionError("unreachable") from exc
        if len(data) > limit_bytes or (not data and not result["eof"]):
            self._abort(ToolSessionError("invalid export chunk length"))
        self._export_offset += len(data)
        if result["eof"]:
            self._phase = "done"
        return data, result["eof"]

    def cancel(self) -> None:
        """Invalidate the session immediately, then interrupt the bounded transport."""
        with self._state_lock:
            if self._closed:
                return
            self._closed = True
        self._transport.close()

    def close(self) -> None:
        self.cancel()

    def _invoke(self, call: WorkerToolCall) -> WorkerToolResult:
        try:
            self._validate_call(call)
        except (ValueError, WorkerPolicyError) as exc:
            return WorkerToolResult(call.name, str(exc)[:4000], is_error=True)
        result = self._exchange("ready", "tool", {"name": call.name, "arguments": call.arguments})
        if (set(result) != {"output", "is_error"} or not isinstance(result["output"], str)
                or type(result["is_error"]) is not bool
                or len(result["output"].encode("utf-8")) > self._max_frame // 2):
            self._abort(ToolSessionError("invalid tool response"))
        return WorkerToolResult(call.name, result["output"], result["is_error"])

    def _validate_call(self, call: WorkerToolCall) -> None:
        if not isinstance(call, WorkerToolCall) or call.name not in tuple(spec.name for spec in self._tools):
            raise ValueError("tool is not approved for this worker profile")
        if not isinstance(call.arguments, Mapping) or not all(isinstance(key, str) for key in call.arguments):
            raise ValueError("tool arguments must be a JSON object")
        arguments = call.arguments
        if call.name == RUN_COMMAND_TOOL:
            if set(arguments) - {"argv", "timeout_seconds", "max_output_bytes"}:
                raise ValueError("unexpected command arguments")
            argv = arguments.get("argv")
            if not isinstance(argv, list) or not all(isinstance(item, str) for item in argv):
                raise ValueError("command argv must be an array of strings")
            timeout = arguments.get("timeout_seconds", 300)
            output = arguments.get("max_output_bytes", 16 * 1024)
            if type(timeout) is not int or type(output) is not int or not 1 <= output <= 16 * 1024:
                raise ValueError("command limits must be bounded integers")
            approve_worker_command(self._profile, argv, timeout_seconds=timeout, max_output_bytes=output)
        elif call.name == WRITE_ARTIFACT_TOOL:
            if set(arguments) != {"name", "kind", "content"} or not all(
                isinstance(arguments[key], str) for key in ("name", "kind", "content")
            ):
                raise ValueError("artifact arguments must contain name, kind and text content")
            if (not _ARTIFACT_NAME.fullmatch(arguments["name"])
                    or arguments["kind"] not in _ARTIFACT_KINDS):
                raise ValueError("artifact name or kind is not approved")
        elif call.name == LIST_FILES_TOOL:
            if set(arguments) - {"path"}:
                raise ValueError("unexpected list arguments")
            _repo_path(arguments.get("path", "."), root=True)
        elif call.name == READ_FILE_TOOL:
            if set(arguments) != {"path"}:
                raise ValueError("read_file needs a path")
            _repo_path(arguments["path"])
        elif call.name == SEARCH_TEXT_TOOL:
            if set(arguments) != {"query"} or not isinstance(arguments["query"], str):
                raise ValueError("search_text needs a literal query")
            query = arguments["query"]
            if not query or len(query.encode("utf-8")) > 256 or "\n" in query or "\r" in query:
                raise ValueError("search query is invalid or too large")
        elif call.name == APPLY_PATCH_TOOL:
            if set(arguments) != {"path", "expected_sha256", "find", "replace"}:
                raise ValueError("apply_patch needs path, digest, find and replace")
            _repo_path(arguments["path"])
            digest = arguments["expected_sha256"]
            if digest is not None and (not isinstance(digest, str) or not _DIGEST.fullmatch(digest)):
                raise ValueError("patch digest is invalid")
            find, replace = arguments["find"], arguments["replace"]
            if (not isinstance(find, str) or not isinstance(replace, str)
                    or len(find.encode("utf-8")) > 16 * 1024
                    or len(replace.encode("utf-8")) > 16 * 1024
                    or (digest is None and find) or (digest is not None and not find)):
                raise ValueError("patch text or creation context is invalid")
        else:
            raise ValueError("approved tool has no host-side validator")
        self._encode({"type": "request", "operation": "tool", "payload": dict(arguments), **self._identity(), "request_id": self._next_id})

    def _exchange(self, phase: str, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self._operation_lock.acquire(blocking=False):
            raise ToolSessionError("another session operation is in progress")
        try:
            self._require_phase(phase)
            request_id = self._next_id
            self._next_id += 1
            operation_deadline = time.monotonic() + self._timeout
            self._transport.send(self._encode({
                "type": "request", "request_id": request_id, "operation": operation,
                "payload": payload, **self._identity(),
            }), timeout_seconds=self._remaining(operation_deadline))
            reply = self._receive("response", {
                "version", "type", *self._identity(), "request_id", "ok", "payload", "error",
            }, deadline=operation_deadline)
            if (type(reply.get("request_id")) is not int or reply["request_id"] != request_id
                    or type(reply.get("ok")) is not bool):
                raise ToolSessionError("response request ID or status mismatch")
            if reply["ok"]:
                if set(reply) != {"version", "type", *self._identity(), "request_id", "ok", "payload"} or not isinstance(reply["payload"], dict):
                    raise ToolSessionError("invalid success response")
                self._require_phase(phase)  # a concurrent cancel wins over a late reply
                return reply["payload"]
            if set(reply) != {"version", "type", *self._identity(), "request_id", "ok", "error"}:
                raise ToolSessionError("invalid error response")
            error = reply["error"]
            if (not isinstance(error, dict) or set(error) != {"code", "message"}
                    or not isinstance(error["code"], str) or error["code"] not in _ERROR_CODES
                    or not isinstance(error["message"], str)
                    or len(error["message"].encode("utf-8")) > 1024):
                raise ToolSessionError("invalid guest error")
            raise ToolSessionRemoteError(error["code"], error["message"])
        except Exception as exc:
            self._abort(exc)
            raise AssertionError("unreachable") from exc
        finally:
            self._operation_lock.release()

    def _identity(self) -> dict[str, str]:
        return {"job_id": self._job_id, "sandbox_id": self._sandbox_id,
                "session_id": self._session_id}

    def _encode(self, message: dict[str, Any]) -> bytes:
        try:
            frame = json.dumps({"version": VERSION, **message}, ensure_ascii=False,
                               allow_nan=False, separators=(",", ":")).encode("utf-8") + b"\n"
        except (TypeError, ValueError, UnicodeError) as exc:
            raise ToolSessionError("session payload is not finite JSON") from exc
        if len(frame) > self._max_frame:
            raise ToolSessionError("outgoing session frame is too large")
        return frame

    def _receive(self, expected: str, keys: set[str], *, deadline: float) -> dict[str, Any]:
        frame = self._transport.receive(max_bytes=self._max_frame,
                                        timeout_seconds=self._remaining(deadline))
        self._remaining(deadline)  # reject a transport that returned after the deadline
        if (not isinstance(frame, bytes) or not frame.endswith(b"\n")
                or len(frame) > self._max_frame or b"\n" in frame[:-1]):
            raise ToolSessionError("truncated, oversized or malformed session frame")
        try:
            message = json.loads(frame[:-1].decode("utf-8"),
                                 object_pairs_hook=_unique_object, parse_constant=_reject_constant)
        except (UnicodeError, ValueError, RecursionError) as exc:
            raise ToolSessionError("invalid session JSON") from exc
        if (not isinstance(message, dict) or not all(isinstance(key, str) for key in message)
                or not set(message) <= keys or type(message.get("version")) is not int
                or message["version"] != VERSION
                or message.get("type") != expected):
            raise ToolSessionError("unexpected session message type, version or fields")
        if any(message.get(key) != value for key, value in self._identity().items()):
            raise ToolSessionError("session job, sandbox or nonce mismatch")
        return message

    def _require_phase(self, phase: str) -> None:
        with self._state_lock:
            if self._closed or self._phase != phase:
                raise ToolSessionError("session is closed or in the wrong phase")
        self._remaining()

    def _remaining(self, deadline: float | None = None) -> float:
        remaining = min(self._deadline, deadline if deadline is not None else self._deadline) - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("sandbox tool session deadline expired")
        return min(remaining, self._timeout)

    def _abort(self, exc: Exception) -> None:
        try:
            self.cancel()
        except Exception as cleanup_exc:
            raise ToolSessionError(f"{exc}; session transport close failed: {cleanup_exc}") from exc
        if isinstance(exc, ToolSessionError):
            raise exc
        raise ToolSessionError(f"session operation failed: {exc}") from exc
