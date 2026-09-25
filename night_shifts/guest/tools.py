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
from night_shifts.guest.repository import GuestRepository, RepositoryToolError
from night_shifts.worker_capabilities import (
    APPLY_PATCH_TOOL,
    LIST_FILES_TOOL,
    READ_FILE_TOOL,
    RUN_COMMAND_TOOL,
    SEARCH_TEXT_TOOL,
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
                "maximum": 16 * 1024,
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
    LIST_FILES_TOOL: WorkerToolSpec(
        LIST_FILES_TOOL, "List bounded workspace files (no links).",
        {"type": "object", "properties": {"path": {"type": "string", "maxLength": 240}},
         "additionalProperties": False},
    ),
    READ_FILE_TOOL: WorkerToolSpec(
        READ_FILE_TOOL, "Read one bounded UTF-8 workspace file with its SHA-256.",
        {"type": "object", "properties": {"path": {"type": "string", "maxLength": 240}},
         "required": ["path"], "additionalProperties": False},
    ),
    SEARCH_TEXT_TOOL: WorkerToolSpec(
        SEARCH_TEXT_TOOL, "Search bounded UTF-8 workspace files for a literal line fragment.",
        {"type": "object", "properties": {"query": {"type": "string", "maxLength": 256}},
         "required": ["query"], "additionalProperties": False},
    ),
    APPLY_PATCH_TOOL: WorkerToolSpec(
        APPLY_PATCH_TOOL, "Create or replace one exact text span with a stale-content guard.",
        {"type": "object", "properties": {
            "path": {"type": "string", "maxLength": 240},
            "expected_sha256": {"type": ["string", "null"]},
            "find": {"type": "string", "maxLength": 16384},
            "replace": {"type": "string", "maxLength": 16384},
        }, "required": ["path", "expected_sha256", "find", "replace"],
         "additionalProperties": False},
    ),
}


class GuestWorkerTools:
    """Profile-scoped adapter over reviewed command and artifact primitives."""

    def __init__(
        self,
        profile: str,
        commands: RestrictedCommandRunner,
        artifacts: ArtifactWriter,
        repository: GuestRepository | None = None,
    ) -> None:
        self._allowed = worker_tool_names(profile)
        self._commands = commands
        self._artifacts = artifacts
        self._repository = repository

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
            elif call.name in (LIST_FILES_TOOL, READ_FILE_TOOL, SEARCH_TEXT_TOOL, APPLY_PATCH_TOOL):
                output = self._repository_tool(call.name, arguments)
            else:  # The allowlist and implementation registry must agree.
                return self._error(call.name, "approved worker tool has no implementation")
        except (ArtifactPolicyError, WorkerExecutionError, WorkerPolicyError,
                RepositoryToolError, ValueError) as exc:
            return self._error(call.name, str(exc) or exc.__class__.__name__)
        encoded = json.dumps(output, sort_keys=True)
        if len(encoded.encode("utf-8")) > 16 * 1024:
            return self._error(call.name, "tool response exceeds 16 KiB limit")
        return WorkerToolResult(call.name, encoded)

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
            arguments.get("max_output_bytes", 16 * 1024),
            "max_output_bytes",
        )
        if output_limit <= 0 or output_limit > 16 * 1024:
            raise ValueError("tool output must be between 1 byte and 16 KiB")
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

    def _repository_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if self._repository is None:
            raise RepositoryToolError("guest repository tools are not configured")
        if name == LIST_FILES_TOOL:
            self._require_keys(arguments, required=frozenset(), optional=frozenset({"path"}))
            return self._repository.list_files(self._text(arguments.get("path", "."), "path"))
        if name == READ_FILE_TOOL:
            self._require_keys(arguments, required=frozenset({"path"}), optional=frozenset())
            return self._repository.read_file(self._text(arguments["path"], "path"))
        if name == SEARCH_TEXT_TOOL:
            self._require_keys(arguments, required=frozenset({"query"}), optional=frozenset())
            return self._repository.search_text(self._text(arguments["query"], "query"))
        self._require_keys(arguments, required=frozenset({"path", "expected_sha256",
                                                           "find", "replace"}), optional=frozenset())
        if not all(isinstance(arguments[key], str) for key in ("path", "find", "replace")):
            raise ValueError("patch path and text must be strings")
        return self._repository.apply_patch(arguments["path"], arguments["expected_sha256"],
                                            arguments["find"], arguments["replace"])

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
