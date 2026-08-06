"""Guest-safe model tool boundary for restricted worker executors."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, runtime_checkable


@dataclass(frozen=True)
class WorkerToolSpec:
    """One bounded tool exposed to a model adapter inside the worker guest."""

    name: str
    description: str
    input_schema: Mapping[str, Any]


@dataclass(frozen=True)
class WorkerToolCall:
    """A model-requested tool invocation with JSON-compatible arguments."""

    name: str
    arguments: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkerToolResult:
    """Bounded text returned to the model after one tool invocation."""

    tool_name: str
    output: str
    is_error: bool = False


@runtime_checkable
class WorkerToolProvider(Protocol):
    """Profile-scoped tools available to a replaceable worker executor.

    Implementations enforce authorization and input limits. Model adapters must
    not receive the underlying filesystem, command runner, or artifact writer.
    """

    def available_tools(self) -> tuple[WorkerToolSpec, ...]: ...

    def invoke(self, call: WorkerToolCall) -> WorkerToolResult: ...
