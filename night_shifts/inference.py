"""Trusted host-side, session-bound model inference mediation."""

from __future__ import annotations

import json
import re
import secrets
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Protocol

from llm.base import LLMClient, LLMResponse, NativeToolOutput
from night_shifts.contracts.inference import (
    InferenceMessage,
    InferenceRequest,
    InferenceResponse,
    InferenceToolCall,
    InferenceUsage,
    WorkerInferenceClient,
)
from night_shifts.contracts.worker_tool import WorkerToolSpec
from night_shifts.worker_capabilities import worker_tool_names

_COMPONENT_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
_CALL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")


class InferenceBoundaryError(RuntimeError):
    """Raised when an inference session or payload fails closed."""


@dataclass(frozen=True)
class InferenceLimits:
    """Host-enforced limits for one short-lived inference session."""

    max_requests: int = 32
    max_messages: int = 96
    max_input_bytes: int = 512 * 1024
    max_output_bytes: int = 128 * 1024
    max_tool_calls_per_response: int = 8
    max_tool_schema_bytes: int = 64 * 1024
    ttl_seconds: int = 3600

    def __post_init__(self) -> None:
        if self.max_requests <= 0 or self.max_requests > 256:
            raise ValueError("max_requests must be between 1 and 256")
        if self.max_messages <= 0 or self.max_messages > 512:
            raise ValueError("max_messages must be between 1 and 512")
        if self.max_input_bytes <= 0 or self.max_input_bytes > 4 * 1024 * 1024:
            raise ValueError("max_input_bytes must be between 1 byte and 4 MiB")
        if self.max_output_bytes <= 0 or self.max_output_bytes > 1024 * 1024:
            raise ValueError("max_output_bytes must be between 1 byte and 1 MiB")
        if self.max_tool_calls_per_response <= 0 or self.max_tool_calls_per_response > 32:
            raise ValueError("max_tool_calls_per_response must be between 1 and 32")
        if self.max_tool_schema_bytes <= 0 or self.max_tool_schema_bytes > 256 * 1024:
            raise ValueError("max_tool_schema_bytes must be between 1 byte and 256 KiB")
        if self.ttl_seconds <= 0 or self.ttl_seconds > 24 * 60 * 60:
            raise ValueError("ttl_seconds must be between 1 second and 24 hours")


class InferenceModel(Protocol):
    """One host-owned model conversation, created for exactly one session."""

    def infer(
        self,
        messages: Sequence[InferenceMessage],
        tools: Sequence[WorkerToolSpec],
    ) -> InferenceResponse: ...


InferenceModelFactory = Callable[[], InferenceModel]


@dataclass
class _Session:
    job_id: str
    worker_profile: str
    model_id: str
    model: InferenceModel
    limits: InferenceLimits
    expires_at: datetime
    requests: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)


class BoundInferenceClient:
    """Client capability bound to an opaque, short-lived host session token."""

    def __init__(self, gateway: TrustedInferenceGateway, token: str) -> None:
        self._gateway = gateway
        self._token = token

    def infer(self, request: InferenceRequest) -> InferenceResponse:
        return self._gateway.infer(self._token, request)


class TrustedInferenceGateway:
    """Mediate inference without exposing model selection or credentials to guests."""

    def __init__(self, models: Mapping[str, InferenceModelFactory]) -> None:
        if not models:
            raise ValueError("at least one trusted inference model is required")
        validated: dict[str, InferenceModelFactory] = {}
        for model_id, factory in models.items():
            if not _COMPONENT_ID.fullmatch(model_id):
                raise ValueError(f"invalid trusted model ID: {model_id!r}")
            if not callable(factory):
                raise TypeError(f"inference model factory is not callable: {model_id!r}")
            validated[model_id] = factory
        self._models = validated
        self._sessions: dict[str, _Session] = {}
        self._lock = threading.Lock()

    def create_client(
        self,
        *,
        job_id: str,
        worker_profile: str,
        model_id: str,
        limits: InferenceLimits | None = None,
    ) -> WorkerInferenceClient:
        """Create a pre-authenticated client; this is a trusted-host operation."""

        if not job_id:
            raise ValueError("job_id must not be empty")
        worker_tool_names(worker_profile)
        try:
            factory = self._models[model_id]
        except KeyError as exc:
            raise InferenceBoundaryError(f"unknown trusted model ID: {model_id!r}") from exc
        selected_limits = limits or InferenceLimits()
        token = secrets.token_urlsafe(32)
        session = _Session(
            job_id=job_id,
            worker_profile=worker_profile,
            model_id=model_id,
            model=factory(),
            limits=selected_limits,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=selected_limits.ttl_seconds),
        )
        with self._lock:
            self._sessions[token] = session
        return BoundInferenceClient(self, token)

    def authorize_client(
        self, client: WorkerInferenceClient, *, job_id: str,
        worker_profile: str, model_id: str,
    ) -> None:
        """Verify the trusted job snapshot before the first model dispatch."""
        if not isinstance(client, BoundInferenceClient) or client._gateway is not self:
            raise InferenceBoundaryError("inference client is not owned by this gateway")
        with self._lock:
            session = self._sessions.get(client._token)
        if (session is None or session.job_id != job_id
                or session.worker_profile != worker_profile or session.model_id != model_id):
            raise InferenceBoundaryError("inference client does not match approved job policy")

    def close_client(self, client: WorkerInferenceClient) -> None:
        """Revoke a locally bound client without accepting a token from task text."""

        if not isinstance(client, BoundInferenceClient) or client._gateway is not self:
            raise InferenceBoundaryError("inference client is not owned by this gateway")
        with self._lock:
            session = self._sessions.pop(client._token, None)
        if session is not None:
            close = getattr(session.model, "close", None)
            if callable(close):
                close()  # Do not wait for session.lock: a model call may be stalled.

    def cancel_client(self, client: WorkerInferenceClient) -> None:
        """Revoke and interrupt a process-backed session without waiting for infer."""
        if not isinstance(client, BoundInferenceClient) or client._gateway is not self:
            raise InferenceBoundaryError("inference client is not owned by this gateway")
        with self._lock:
            session = self._sessions.pop(client._token, None)
        if session is None:
            return
        cancel = getattr(session.model, "cancel", None)
        if not callable(cancel):
            raise InferenceBoundaryError("inference model has no hard cancellation capability")
        cancel()

    def infer(self, token: str, request: InferenceRequest) -> InferenceResponse:
        with self._lock:
            session = self._sessions.get(token)
        if session is None:
            raise InferenceBoundaryError("inference session is unavailable or revoked")
        with session.lock:
            self._authorize(session, request)
            self._validate_request(session, request)
            session.requests += 1
            response = session.model.infer(request.messages, request.tools)
            self._validate_response(session, response)
            return response

    @staticmethod
    def _authorize(session: _Session, request: InferenceRequest) -> None:
        if datetime.now(timezone.utc) >= session.expires_at:
            raise InferenceBoundaryError("inference session has expired")
        if request.job_id != session.job_id:
            raise InferenceBoundaryError("inference request job does not match the session")
        if request.worker_profile != session.worker_profile:
            raise InferenceBoundaryError("inference request profile does not match the session")
        if session.requests >= session.limits.max_requests:
            raise InferenceBoundaryError("inference request limit exceeded")

    @classmethod
    def _validate_request(cls, session: _Session, request: InferenceRequest) -> None:
        limits = session.limits
        if not request.messages or len(request.messages) > limits.max_messages:
            raise InferenceBoundaryError("inference message count is invalid")
        expected_tools = worker_tool_names(session.worker_profile)
        actual_tools = tuple(tool.name for tool in request.tools)
        if actual_tools != expected_tools or len(set(actual_tools)) != len(actual_tools):
            raise InferenceBoundaryError("inference tools do not match the worker profile")
        try:
            schema_bytes = len(
                json.dumps(
                    [
                        {
                            "name": tool.name,
                            "description": tool.description,
                            "input_schema": tool.input_schema,
                        }
                        for tool in request.tools
                    ],
                    sort_keys=True,
                ).encode("utf-8")
            )
        except (TypeError, ValueError) as exc:
            raise InferenceBoundaryError("worker tool schemas are not JSON-compatible") from exc
        if schema_bytes > limits.max_tool_schema_bytes:
            raise InferenceBoundaryError("worker tool schemas exceed the session limit")

        total = 0
        known_calls: set[str] = set()
        for message in request.messages:
            if message.role not in {"system", "user", "assistant", "tool"}:
                raise InferenceBoundaryError("inference message role is invalid")
            total += len(message.content.encode("utf-8"))
            if message.role == "assistant":
                if len(message.tool_calls) > limits.max_tool_calls_per_response:
                    raise InferenceBoundaryError("transcript tool call count exceeds the session limit")
                for call in message.tool_calls:
                    cls._validate_tool_call(call, frozenset(expected_tools))
                    if call.call_id in known_calls:
                        raise InferenceBoundaryError("duplicate inference tool call ID")
                    known_calls.add(call.call_id)
                    total += cls._tool_call_size(call)
            elif message.tool_calls:
                raise InferenceBoundaryError("only assistant messages may contain tool calls")
            if message.role == "tool":
                if message.tool_call_id not in known_calls:
                    raise InferenceBoundaryError("tool result does not match an earlier call")
            elif message.tool_call_id is not None:
                raise InferenceBoundaryError("only tool messages may identify a tool call")
        if total > limits.max_input_bytes:
            raise InferenceBoundaryError("inference input exceeds the session limit")

    @classmethod
    def _validate_response(cls, session: _Session, response: InferenceResponse) -> None:
        if not isinstance(response, InferenceResponse):
            raise InferenceBoundaryError("inference model returned an invalid response")
        if response.usage is not None and not isinstance(response.usage, InferenceUsage):
            raise InferenceBoundaryError("inference model returned invalid usage")
        output_bytes = len(response.content.encode("utf-8"))
        if len(response.tool_calls) > session.limits.max_tool_calls_per_response:
            raise InferenceBoundaryError("inference tool call count exceeds the session limit")
        allowed = frozenset(worker_tool_names(session.worker_profile))
        seen: set[str] = set()
        for call in response.tool_calls:
            cls._validate_tool_call(call, allowed)
            if call.call_id in seen:
                raise InferenceBoundaryError("duplicate response tool call ID")
            seen.add(call.call_id)
            output_bytes += cls._tool_call_size(call)
        if output_bytes > session.limits.max_output_bytes:
            raise InferenceBoundaryError("inference output exceeds the session limit")
        if not response.content.strip() and not response.tool_calls:
            raise InferenceBoundaryError("inference model returned an empty response")

    @staticmethod
    def _tool_call_size(call: InferenceToolCall) -> int:
        return len(call.call_id.encode("utf-8")) + len(call.name.encode("utf-8")) + len(
            json.dumps(call.arguments, sort_keys=True).encode("utf-8")
        )

    @staticmethod
    def _validate_tool_call(call: InferenceToolCall, allowed: frozenset[str]) -> None:
        if not _CALL_ID.fullmatch(call.call_id):
            raise InferenceBoundaryError("inference tool call ID is invalid")
        if call.name not in allowed:
            raise InferenceBoundaryError(f"model requested an unauthorized tool: {call.name!r}")
        if not isinstance(call.arguments, Mapping) or not all(
            isinstance(key, str) for key in call.arguments
        ):
            raise InferenceBoundaryError("inference tool arguments must be an object")
        try:
            encoded = json.dumps(call.arguments, sort_keys=True).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise InferenceBoundaryError("inference tool arguments are not JSON-compatible") from exc
        if len(encoded) > 256 * 1024:
            raise InferenceBoundaryError("inference tool arguments exceed the limit")


def _field(value: object, name: str) -> object:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _token(value: object) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise InferenceBoundaryError("provider reported invalid token usage")
    return value


def openai_usage(value: object) -> InferenceUsage | None:
    """Read OpenAI and compatible usage shapes, without treating absent data as zero."""
    if value is None:
        return None
    input_total = _field(value, "input_tokens")
    output_total = _field(value, "output_tokens")
    input_details = _field(value, "input_tokens_details")
    output_details = _field(value, "output_tokens_details")
    if input_total is None:
        input_total = _field(value, "prompt_tokens")
        input_details = _field(value, "prompt_tokens_details")
    if output_total is None:
        output_total = _field(value, "completion_tokens")
        output_details = _field(value, "completion_tokens_details")
    cached = _field(input_details, "cached_tokens")
    reasoning = _field(output_details, "reasoning_tokens")
    if all(item is None for item in (input_total, output_total, cached, reasoning)):
        return None
    try:
        return InferenceUsage(
            input_tokens=_token(input_total),
            output_tokens=_token(output_total),
            cached_input_tokens=_token(cached),
            reasoning_output_tokens=_token(reasoning),
        )
    except ValueError as exc:
        raise InferenceBoundaryError("provider reported inconsistent token usage") from exc


class LLMInferenceModel:
    """Host-only adapter from the existing LLM client to inference contracts."""

    def __init__(self, client: LLMClient) -> None:
        if not getattr(client, "supports_native_tools", False):
            raise ValueError("worker inference requires native tool support")
        self._client = client
        self._api_type = getattr(client, "api_type", "chat_completions")
        if self._api_type not in {"chat_completions", "responses"}:
            raise ValueError(f"unsupported worker inference API type: {self._api_type!r}")

    def infer(
        self,
        messages: Sequence[InferenceMessage],
        tools: Sequence[WorkerToolSpec],
    ) -> InferenceResponse:
        native_tools = [self._tool_schema(tool) for tool in tools]
        if self._api_type == "responses" and messages and messages[-1].role == "tool":
            trailing = []
            for message in reversed(messages):
                if message.role != "tool":
                    break
                trailing.append(message)
            reply = self._client.submit_tool_outputs(
                [
                    NativeToolOutput(message.tool_call_id or "", message.content)
                    for message in reversed(trailing)
                ]
            )
        else:
            reply = self._client.chat(
                [self._message(message) for message in messages],
                tools=native_tools,
                tool_choice="auto",
            )
        usage = openai_usage(getattr(self._client, "last_usage", None))
        if isinstance(reply, str):
            return InferenceResponse(content=reply, usage=usage)
        if not isinstance(reply, LLMResponse):
            raise InferenceBoundaryError("LLM client returned an unsupported response")
        calls = tuple(
            InferenceToolCall(call.id, call.name, call.arguments or {})
            for call in (reply.tool_calls or [])
        )
        return InferenceResponse(content=reply.content or "", tool_calls=calls, usage=usage)

    def _tool_schema(self, tool: WorkerToolSpec) -> dict[str, object]:
        function = {
            "name": tool.name,
            "description": tool.description,
            "parameters": dict(tool.input_schema),
        }
        if self._api_type == "responses":
            return {"type": "function", **function}
        return {"type": "function", "function": function}

    @staticmethod
    def _message(message: InferenceMessage) -> dict[str, object]:
        value: dict[str, object] = {"role": message.role, "content": message.content}
        if message.tool_calls:
            value["tool_calls"] = [
                {
                    "id": call.call_id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(call.arguments, sort_keys=True),
                    },
                }
                for call in message.tool_calls
            ]
        if message.tool_call_id is not None:
            value["tool_call_id"] = message.tool_call_id
        return value
