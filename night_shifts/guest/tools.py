"""Concrete guest-safe tools exposed to a replaceable worker executor."""

from __future__ import annotations

import json
from typing import Any, Mapping

from night_shifts.contracts.worker_tool import (
    WorkerToolCall,
    WorkerToolResult,
    WorkerToolSpec,
)
from night_shifts.guest.artifacts import ArtifactPolicyError, ArtifactWriter
from night_shifts.guest.commands import RestrictedCommandRunner, WorkerExecutionError
from night_shifts.worker_capabilities import (
    RUN_COMMAND_TOOL,
    WRITE_ARTIFACT_TOOL,
    worker_tool_names,
)
from night_shifts.worker_policy import WorkerPolicyError

_RUN_COMMAND_SPEC = WorkerToolSpec(
    name=RUN_COMMAND_TOOL,
    description="Run one policy-approved argv vector in the isolated repository.",
    input_schema={
        "type": "object",
        "properties": {
            "argv": {"type": "array", "items": {"type": "string"}, "minItems": 1},
            "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 1800},
            "max_output_bytes": {
                "type": "integer",
                "minimum": 1,
                "maximum": 4 * 1024 * 1024,
            },
        },
        "required": ["argv"],
        "additionalProperties": False,
    },
)
_WRITE_ARTIFACT_SPEC = WorkerToolSpec(
    name=WRITE_ARTIFACT_TOOL,
    description="Stage one bounded UTF-8 text artifact outside the repository.",
    input_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "kind": {
                "type": "string",
                "enum": ["test-log", "analysis", "report", "metadata"],
            },
            "content": {"type": "string"},
        },
        "required": ["name", "kind", "content"],
        "additionalProperties": False,
    },
)
_SPECS = {
    RUN_COMMAND_TOOL: _RUN_COMMAND_SPEC,
    WRITE_ARTIFACT_TOOL: _WRITE_ARTIFACT_SPEC,
}


class GuestWorkerTools:
    """Profile-scoped adapter over reviewed command and artifact primitives."""

    def __init__(
        self,
        profile: str,
        commands: RestrictedCommandRunner,
        artifacts: ArtifactWriter,
    ) -> None:
        self._allowed = worker_tool_names(profile)
        self._commands = commands
        self._artifacts = artifacts

    def available_tools(self) -> tuple[WorkerToolSpec, ...]:
        return tuple(_SPECS[name] for name in self._allowed)

    def invoke(self, call: WorkerToolCall) -> WorkerToolResult:
        if call.name not in self._allowed:
            return self._error(call.name, f"tool is not allowed for this worker: {call.name!r}")
        try:
            arguments = self._arguments(call.arguments)
            if call.name == RUN_COMMAND_TOOL:
                output = self._run_command(arguments)
            elif call.name == WRITE_ARTIFACT_TOOL:
                output = self._write_artifact(arguments)
            else:  # The allowlist and implementation registry must agree.
                return self._error(call.name, "approved worker tool has no implementation")
        except (ArtifactPolicyError, WorkerExecutionError, WorkerPolicyError, ValueError) as exc:
            return self._error(call.name, str(exc) or exc.__class__.__name__)
        return WorkerToolResult(call.name, json.dumps(output, sort_keys=True))

    def _run_command(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self._require_keys(
            arguments,
            required=frozenset({"argv"}),
            optional=frozenset({"timeout_seconds", "max_output_bytes"}),
        )
        argv = arguments["argv"]
        if not isinstance(argv, list) or not all(isinstance(item, str) for item in argv):
            raise ValueError("argv must be an array of strings")
        timeout = self._integer(arguments.get("timeout_seconds", 300), "timeout_seconds")
        output_limit = self._integer(
            arguments.get("max_output_bytes", 1024 * 1024),
            "max_output_bytes",
        )
        result = self._commands.run(
            argv,
            timeout_seconds=timeout,
            max_output_bytes=output_limit,
        )
        return {
            "argv": list(result.argv),
            "return_code": result.return_code,
            "output": result.output,
            "duration_seconds": result.duration_seconds,
            "timed_out": result.timed_out,
            "output_truncated": result.output_truncated,
        }

    def _write_artifact(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self._require_keys(
            arguments,
            required=frozenset({"name", "kind", "content"}),
            optional=frozenset(),
        )
        name = self._text(arguments["name"], "name")
        kind = self._text(arguments["kind"], "kind")
        content = arguments["content"]
        if not isinstance(content, str):
            raise ValueError("content must be a string")
        artifact = self._artifacts.write_text(name=name, kind=kind, content=content)
        return {
            "reference": artifact.reference,
            "kind": artifact.kind,
            "size_bytes": artifact.size_bytes,
            "sha256": artifact.sha256,
        }

    @staticmethod
    def _arguments(arguments: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(arguments, Mapping) or not all(
            isinstance(key, str) for key in arguments
        ):
            raise ValueError("tool arguments must be an object with string keys")
        return dict(arguments)

    @staticmethod
    def _require_keys(
        arguments: Mapping[str, Any],
        *,
        required: frozenset[str],
        optional: frozenset[str],
    ) -> None:
        keys = frozenset(arguments)
        missing = required - keys
        extra = keys - required - optional
        if missing:
            raise ValueError(f"missing tool argument(s): {', '.join(sorted(missing))}")
        if extra:
            raise ValueError(f"unknown tool argument(s): {', '.join(sorted(extra))}")

    @staticmethod
    def _integer(value: Any, label: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{label} must be an integer")
        return value

    @staticmethod
    def _text(value: Any, label: str) -> str:
        if not isinstance(value, str) or not value:
            raise ValueError(f"{label} must be a non-empty string")
        return value

    @staticmethod
    def _error(tool_name: str, message: str) -> WorkerToolResult:
        return WorkerToolResult(tool_name, message[:4000], is_error=True)
