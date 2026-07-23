"""Versioned JSONL protocol shared by orchestrator and worker processes."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from night_shifts.models import AgentPlan, NightShiftEvent, NightShiftJob

PROTOCOL_VERSION = 1


class ProtocolError(ValueError):
    """Raised for malformed or unsupported worker messages."""


class WorkerOutcome(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


@dataclass(frozen=True)
class WorkerTask:
    job_id: str
    objective: str
    worker_profile: str
    acceptance_criteria: tuple[str, ...] = ()
    repository_id: str | None = None
    starting_revision: str | None = None
    plan: AgentPlan = AgentPlan.FLEX

    @classmethod
    def from_job(cls, job: NightShiftJob) -> "WorkerTask":
        return cls(
            job_id=job.job_id,
            objective=job.objective,
            worker_profile=job.worker_profile,
            acceptance_criteria=job.acceptance_criteria,
            repository_id=job.repository_id,
            starting_revision=job.starting_revision,
            plan=job.plan,
        )


@dataclass(frozen=True)
class WorkerResult:
    job_id: str
    outcome: WorkerOutcome
    summary: str
    error: str | None = None
    checks: tuple[dict[str, Any], ...] = ()
    artifacts: tuple[str, ...] = ()
    metrics: dict[str, Any] = field(default_factory=dict)


def encode_task(task: WorkerTask) -> str:
    return _encode("task", {
        "job_id": task.job_id,
        "objective": task.objective,
        "worker_profile": task.worker_profile,
        "acceptance_criteria": list(task.acceptance_criteria),
        "repository_id": task.repository_id,
        "starting_revision": task.starting_revision,
        "plan": task.plan.value,
    })


def decode_task(line: str) -> WorkerTask:
    message = _decode_envelope(line, expected_kind="task")
    payload = _object(message.get("payload"), "task payload")
    return WorkerTask(
        job_id=_text(payload, "job_id"),
        objective=_text(payload, "objective"),
        worker_profile=_text(payload, "worker_profile"),
        acceptance_criteria=tuple(_text_list(payload.get("acceptance_criteria", []))),
        repository_id=_optional_text(payload, "repository_id"),
        starting_revision=_optional_text(payload, "starting_revision"),
        plan=_agent_plan(payload.get("plan", AgentPlan.FLEX.value)),
    )


def encode_event(event: NightShiftEvent) -> str:
    return _encode("event", {
        "event_id": event.event_id,
        "job_id": event.job_id,
        "event_type": event.event_type,
        "actor": event.actor,
        "payload": event.payload,
        "created_at": event.created_at.isoformat(),
    })


def encode_result(result: WorkerResult) -> str:
    return _encode("result", {
        "job_id": result.job_id,
        "outcome": result.outcome.value,
        "summary": result.summary,
        "error": result.error,
        "checks": list(result.checks),
        "artifacts": list(result.artifacts),
        "metrics": result.metrics,
    })


def decode_worker_message(line: str) -> NightShiftEvent | WorkerResult:
    message = _decode_envelope(line)
    kind = message.get("kind")
    payload = _object(message.get("payload"), f"{kind} payload")
    if kind == "event":
        from datetime import datetime

        created_at_text = _text(payload, "created_at")
        try:
            created_at = datetime.fromisoformat(created_at_text)
        except ValueError as exc:
            raise ProtocolError(f"Invalid event timestamp: {created_at_text!r}") from exc
        return NightShiftEvent(
            event_id=_text(payload, "event_id"),
            job_id=_optional_text(payload, "job_id"),
            event_type=_text(payload, "event_type"),
            actor=_text(payload, "actor"),
            payload=_object(payload.get("payload", {}), "event payload"),
            created_at=created_at,
        )
    if kind == "result":
        try:
            outcome = WorkerOutcome(_text(payload, "outcome"))
        except ValueError as exc:
            raise ProtocolError(f"Unknown worker outcome: {payload.get('outcome')!r}") from exc
        checks = payload.get("checks", [])
        if not isinstance(checks, list) or not all(isinstance(item, dict) for item in checks):
            raise ProtocolError("result checks must be a list of objects")
        metrics = _object(payload.get("metrics", {}), "result metrics")
        return WorkerResult(
            job_id=_text(payload, "job_id"),
            outcome=outcome,
            summary=_text(payload, "summary", allow_empty=True),
            error=_optional_text(payload, "error"),
            checks=tuple(checks),
            artifacts=tuple(_text_list(payload.get("artifacts", []))),
            metrics=metrics,
        )
    raise ProtocolError(f"Expected worker event or result, got {kind!r}")


def _encode(kind: str, payload: dict[str, Any]) -> str:
    return json.dumps(
        {"version": PROTOCOL_VERSION, "kind": kind, "payload": payload},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _decode_envelope(line: str, expected_kind: str | None = None) -> dict[str, Any]:
    try:
        value = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"Invalid worker JSON: {exc.msg}") from exc
    message = _object(value, "protocol envelope")
    if message.get("version") != PROTOCOL_VERSION:
        raise ProtocolError(f"Unsupported protocol version: {message.get('version')!r}")
    kind = message.get("kind")
    if not isinstance(kind, str):
        raise ProtocolError("Protocol kind must be a string")
    if expected_kind is not None and kind != expected_kind:
        raise ProtocolError(f"Expected {expected_kind!r} message, got {kind!r}")
    return message


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProtocolError(f"{label} must be an object")
    return value


def _text(payload: dict[str, Any], key: str, *, allow_empty: bool = False) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or (not allow_empty and not value):
        raise ProtocolError(f"{key} must be a non-empty string")
    return value


def _optional_text(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ProtocolError(f"{key} must be a string or null")
    return value


def _text_list(value: Any) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ProtocolError("Expected a list of strings")
    return value


def _agent_plan(value: Any) -> AgentPlan:
    try:
        return AgentPlan(value)
    except (TypeError, ValueError) as exc:
        raise ProtocolError(f"Unknown agent plan: {value!r}") from exc
