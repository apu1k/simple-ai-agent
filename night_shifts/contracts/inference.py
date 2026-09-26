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
class InferenceUsage:
    """One provider response; totals INCLUDE cached input and reasoning output."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_input_tokens: int | None = None
    reasoning_output_tokens: int | None = None

    def __post_init__(self) -> None:
        for value in (
            self.input_tokens, self.output_tokens,
            self.cached_input_tokens, self.reasoning_output_tokens,
        ):
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError("inference token usage must be non-negative integers or unknown")
        if (
            self.input_tokens is not None and self.cached_input_tokens is not None
            and self.cached_input_tokens > self.input_tokens
        ):
            raise ValueError("cached input tokens cannot exceed total input tokens")
        if (
            self.output_tokens is not None and self.reasoning_output_tokens is not None
            and self.reasoning_output_tokens > self.output_tokens
        ):
            raise ValueError("reasoning output tokens cannot exceed total output tokens")


@dataclass(frozen=True)
class InferenceResponse:
    """A provider-neutral model response returned to the guest executor."""

    content: str = ""
    tool_calls: tuple[InferenceToolCall, ...] = ()
    usage: InferenceUsage | None = None


@runtime_checkable
class WorkerInferenceClient(Protocol):
    """Pre-authenticated inference capability injected into one worker."""

    def infer(self, request: InferenceRequest) -> InferenceResponse: ...
