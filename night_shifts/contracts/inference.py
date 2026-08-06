"""Backend-independent model-inference contracts for restricted workers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Mapping, Protocol, runtime_checkable

from night_shifts.contracts.worker_tool import WorkerToolSpec

InferenceRole = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True)
class InferenceToolCall:
    """One provider-neutral model request to invoke a guest tool."""

    call_id: str
    name: str
    arguments: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class InferenceMessage:
    """One provider-neutral inference transcript entry."""

    role: InferenceRole
    content: str = ""
    tool_calls: tuple[InferenceToolCall, ...] = ()
    tool_call_id: str | None = None


@dataclass(frozen=True)
class InferenceRequest:
    """A bounded request that cannot select a provider, model, or credential."""

    job_id: str
    worker_profile: str
    messages: tuple[InferenceMessage, ...]
    tools: tuple[WorkerToolSpec, ...]


@dataclass(frozen=True)
class InferenceResponse:
    """A provider-neutral model response returned to the guest executor."""

    content: str = ""
    tool_calls: tuple[InferenceToolCall, ...] = ()


@runtime_checkable
class WorkerInferenceClient(Protocol):
    """Pre-authenticated inference capability injected into one worker."""

    def infer(self, request: InferenceRequest) -> InferenceResponse: ...
