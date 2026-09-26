"""Killable, host-only inference conversation for one job (not a VM tool channel).

Only a trusted factory enters the spawned host child. Repository data remains text;
no repository code or worker tool implementation is loaded in this process. This
is an offline boundary, not permission to start live tasks before Gates A/B.
"""

from __future__ import annotations

import json
import math
import multiprocessing as mp
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict
from multiprocessing.connection import Connection
from typing import Any

from night_shifts.contracts.inference import (
    InferenceMessage, InferenceResponse, InferenceToolCall, InferenceUsage,
)
from night_shifts.contracts.worker_tool import WorkerToolSpec
from night_shifts.inference import InferenceBoundaryError, InferenceModel

_MAX_FRAME = 4 * 1024 * 1024
_POLL_SECONDS = 0.02
_STOP_SECONDS = 1.0


def _encode(value: object, maximum: int) -> bytes:
    try:
        data = json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode("ascii")
    except (TypeError, ValueError, RecursionError) as exc:
        raise InferenceBoundaryError("inference process payload is not JSON-compatible") from exc
    if len(data) > maximum:
        raise InferenceBoundaryError("inference process frame exceeds the limit")
    return data


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate inference process field")
        value[key] = item
    return value


def _reject_constant(value: str) -> None:
    raise ValueError("nonfinite inference process JSON")


def _decode(data: bytes, maximum: int) -> dict[str, Any]:
    if len(data) > maximum:
        raise InferenceBoundaryError("inference process frame exceeds the limit")
    try:
        value = json.loads(
            data, object_pairs_hook=_unique_object, parse_constant=_reject_constant
        )
    except (UnicodeError, ValueError) as exc:
        raise InferenceBoundaryError("inference process returned malformed JSON") from exc
    if not isinstance(value, dict):
        raise InferenceBoundaryError("inference process returned a non-object")
    return value


def _child(
    pipe: Connection,
    factory: Callable[[], InferenceModel],
    max_input_bytes: int,
    max_output_bytes: int,
) -> None:
    """Trusted child: instantiate model once, preserve Responses continuation state."""
    try:
        model = factory()
        pipe.send_bytes(b'{"type":"ready"}')
        while True:
            frame = _decode(pipe.recv_bytes(maxlength=max_input_bytes), max_input_bytes)
            if set(frame) != {"type", "messages", "tools"} or frame["type"] != "infer":
                raise ValueError("invalid inference request shape")
            messages = tuple(InferenceMessage(
                role=item["role"], content=item["content"],
                tool_calls=tuple(InferenceToolCall(**call) for call in item["tool_calls"]),
                tool_call_id=item["tool_call_id"],
            ) for item in frame["messages"])
            tools = tuple(WorkerToolSpec(**item) for item in frame["tools"])
            response = model.infer(messages, tools)
            if not isinstance(response, InferenceResponse):
                raise ValueError("invalid inference response")
            pipe.send_bytes(_encode({"type": "result", "response": asdict(response)}, max_output_bytes))
    except (EOFError, BrokenPipeError):
        pass
    except Exception:
        # Never send provider exceptions or credentials over the process pipe.
        try:
            pipe.send_bytes(b'{"type":"error"}')
        except (BrokenPipeError, OSError):
            pass
    finally:
        pipe.close()


class ProcessInferenceModel:
    """One spawned, cancellable model conversation; only one request in flight.

    For use behind TrustedInferenceGateway, whose independent request/response
    checks still apply. The caller must close/cancel the bound client in finally.
    """

    def __init__(
        self,
        factory: Callable[[], InferenceModel],
        *,
        deadline: float,
        cancellation_requested: Callable[[], bool] | None = None,
        max_input_bytes: int = 512 * 1024,
        max_output_bytes: int = 128 * 1024,
    ) -> None:
        if (
            type(deadline) not in (int, float) or not math.isfinite(deadline)
            or deadline <= time.monotonic()
        ):
            raise ValueError("inference process deadline must be in the future")
        if not 1 <= max_input_bytes <= _MAX_FRAME or not 1 <= max_output_bytes <= _MAX_FRAME:
            raise ValueError("inference process frame limits are invalid")
        self._deadline = deadline
        self._cancel = cancellation_requested or (lambda: False)
        self._max_input = max_input_bytes
        self._max_output = max_output_bytes
        self._stopped = threading.Event()
        self._state_lock = threading.Lock()
        self._inference_lock = threading.Lock()
        self._cleanup_error: str | None = None
        self._reaped = False
        context = mp.get_context("spawn")
        parent, child = context.Pipe(duplex=True)
        self._pipe = parent
        self._process = context.Process(
            target=_child, args=(child, factory, max_input_bytes, max_output_bytes),
            name="night-shift-inference",
        )
        try:
            self._process.start()
        except BaseException:
            parent.close()
            child.close()
            raise
        child.close()
        try:
            ready = self._receive()
            if ready != {"type": "ready"}:
                raise InferenceBoundaryError("inference process failed to initialize")
        except BaseException:
            self.close()
            raise

    def infer(
        self,
        messages: Sequence[InferenceMessage],
        tools: Sequence[WorkerToolSpec],
    ) -> InferenceResponse:
        if not self._inference_lock.acquire(blocking=False):
            raise InferenceBoundaryError("another inference request is in flight")
        try:
            self._require_running()
            frame = _encode({
                "type": "infer", "messages": [asdict(item) for item in messages],
                "tools": [asdict(item) for item in tools],
            }, self._max_input)
            # A child sends ready before we write; one outstanding operation only.
            # The pipe must be closed by cancel if the child stalls during a send.
            try:
                self._pipe.send_bytes(frame)
            except (BrokenPipeError, OSError) as exc:
                raise InferenceBoundaryError("inference process send failed or was cancelled") from exc
            value = self._receive()
            if set(value) != {"type", "response"} or value["type"] != "result":
                raise InferenceBoundaryError("inference process failed or returned a late response")
            raw = value["response"]
            if not isinstance(raw, dict) or set(raw) != {"content", "tool_calls", "usage"}:
                raise InferenceBoundaryError("inference process returned invalid response fields")
            calls = raw["tool_calls"]
            if not isinstance(calls, list):
                raise InferenceBoundaryError("inference process returned invalid tool calls")
            usage = raw["usage"]
            if usage is not None and not isinstance(usage, dict):
                raise InferenceBoundaryError("inference process returned invalid usage")
            parsed_usage = InferenceUsage(**usage) if isinstance(usage, dict) else None
            result = InferenceResponse(
                content=raw["content"],
                tool_calls=tuple(InferenceToolCall(**call) for call in calls),
                usage=parsed_usage,
            )
            self._require_running()  # Cancellation wins over any late success.
            return result
        except Exception:
            self.close()
            raise
        finally:
            self._inference_lock.release()

    def _require_running(self) -> None:
        if self._stopped.is_set() or self._cancel() or time.monotonic() >= self._deadline:
            self.close()
            raise InferenceBoundaryError("inference session was cancelled or timed out")
        if not self._process.is_alive():
            self.close()
            raise InferenceBoundaryError("inference process disconnected")

    def _receive(self) -> dict[str, Any]:
        while True:
            self._require_running()
            try:
                available = self._pipe.poll(
                    min(_POLL_SECONDS, max(0.0, self._deadline - time.monotonic()))
                )
            except (EOFError, OSError) as exc:
                raise InferenceBoundaryError("inference process disconnected") from exc
            if available:
                try:
                    data = self._pipe.recv_bytes(maxlength=self._max_output)
                except (EOFError, OSError) as exc:
                    raise InferenceBoundaryError("inference process disconnected") from exc
                self._require_running()
                return _decode(data, self._max_output)

    def cancel(self) -> None:
        self.close()

    def close(self) -> None:
        """Kill and reap; never call this a clean stop if the process remains alive."""
        with self._state_lock:
            if self._stopped.is_set():
                if self._cleanup_error:
                    raise InferenceBoundaryError(self._cleanup_error)
                return
            self._stopped.set()
            self._pipe.close()
            if self._process.is_alive():
                self._process.terminate()
            self._process.join(timeout=_STOP_SECONDS)
            if self._process.is_alive():
                self._process.kill()
                self._process.join(timeout=_STOP_SECONDS)
            if self._process.is_alive():
                self._cleanup_error = "inference child could not be reaped"
                raise InferenceBoundaryError(self._cleanup_error)
            self._process.close()
            self._reaped = True

    @property
    def alive(self) -> bool:
        return not self._reaped and self._process.is_alive()
