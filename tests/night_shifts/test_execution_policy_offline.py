"""Offline Commit 07 tests: immutable budgets, usage and honest cancellation limits."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from night_shifts.contracts.inference import (
    InferenceMessage, InferenceRequest, InferenceResponse, InferenceToolCall, InferenceUsage,
)
from night_shifts.contracts.worker_tool import WorkerToolCall, WorkerToolResult, WorkerToolSpec
from night_shifts.execution_policy import ExecutionPolicyBlocked, WorkerExecutionPolicy
from night_shifts.executor import ExecutionControl, MediatedModelExecutor
from night_shifts.inference import InferenceBoundaryError, LLMInferenceModel, openai_usage
from night_shifts.models import JobBudget, NightShiftJob, SandboxSpec
from night_shifts.protocol import WorkerOutcome, WorkerTask
from night_shifts.service import NightShiftService
from night_shifts.storage import EventStore, JobStore
from night_shifts.models import JobStatus


@pytest.mark.parametrize("kwargs", [
    {"max_cost_usd": float("nan")}, {"max_cost_usd": float("inf")},
    {"max_cost_usd": -0.01}, {"max_cost_usd": True},
    {"max_tool_calls": 0}, {"max_tool_calls": 501},
    {"max_model_requests": 0}, {"max_model_requests": 129},
    {"timeout_seconds": float("inf")}, {"max_input_bytes": False},
    {"max_output_bytes": -1}, {"max_command_seconds": 0},
])
def test_invalid_budget_limits_fail_closed(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        JobBudget(**kwargs)


def _job(*, budget: JobBudget | None = None) -> NightShiftJob:
    return NightShiftJob(
        "Approved fixture", "Fix a bug", "coding-worker", repository_id="fixture",
        starting_revision="a" * 40, budget=budget or JobBudget(),
    )


def _policy(job: NightShiftJob) -> WorkerExecutionPolicy:
    return WorkerExecutionPolicy.snapshot(
        job, image_sha256="f" * 64, provider_id="approved-provider", model_id="approved-model",
        reasoning_effort="low", service_tier="flex",
    )


def test_policy_snapshots_value_only_settings_and_matches_executor_gateway_limits() -> None:
    job = _job(budget=JobBudget(
        timeout_seconds=10, max_model_requests=3, max_tool_calls=2,
        max_input_bytes=2048, max_output_bytes=4096, max_command_seconds=5,
    ))
    policy = _policy(job)
    job.starting_revision = "changed"
    job.worker_profile = "review-worker"
    assert policy.base_revision == "a" * 40
    assert policy.worker_profile == "coding-worker"
    assert policy.reasoning_effort == "low"
    assert policy.service_tier == "flex"
    assert policy.image_sha256 == "f" * 64
    assert policy.executor_limits().max_turns == policy.inference_limits().max_requests == 3
    assert policy.executor_limits().max_tool_calls == 2
    assert policy.inference_limits().max_input_bytes == 2048
    assert policy.inference_limits().max_output_bytes == 4096
    assert policy.inference_limits().ttl_seconds == 10
    with pytest.raises(FrozenInstanceError):
        policy.model_id = "unapproved"  # type: ignore[misc]


@pytest.mark.parametrize("override", [
    {"image_sha256": "wrong"}, {"provider_id": "../escape"},
    {"reasoning_effort": "unlimited"}, {"service_tier": "priority"},
    {"sandbox": SandboxSpec(network_enabled=True)},
])
def test_policy_rejects_unapproved_configuration(override: dict) -> None:
    params = dict(image_sha256="f" * 64, provider_id="trusted", model_id="approved")
    params.update(override)
    with pytest.raises(ValueError):
        WorkerExecutionPolicy.snapshot(_job(), **params)


def test_live_preflight_rejects_unbounded_cost_and_hung_sdk_before_any_call() -> None:
    strict = _policy(_job(budget=JobBudget(max_cost_usd=0.25)))
    with pytest.raises(ExecutionPolicyBlocked, match="pricing and pre-call reservation"):
        strict.require_live_guarantees()
    without_usd = _policy(_job())
    with pytest.raises(ExecutionPolicyBlocked, match="hard-cancellable"):
        without_usd.require_live_guarantees()
    # A fake or real provider must not be dispatched on either path.


def test_legacy_service_never_dispatches_a_job_with_strict_usd_budget(tmp_path: Path) -> None:
    database = tmp_path / "strict.db"
    service = NightShiftService(JobStore(database), EventStore(database))
    job = service.create(_job(budget=JobBudget(max_cost_usd=0.01)))
    service.transition(job.job_id, JobStatus.QUEUED, actor="user")

    class MustNotRun:
        def run(self, *args: object, **kwargs: object) -> None:
            pytest.fail("paid or unbounded work must not start")

    result = service.run_local(job.job_id, MustNotRun())
    assert result.outcome is WorkerOutcome.BLOCKED
    assert service.jobs.get(job.job_id).status is JobStatus.FAILED  # type: ignore[union-attr]
    payload = service.events.list(job_id=job.job_id)[-1].payload
    assert payload["outcome"] == "blocked"
    assert payload["check_status"] == "not_run"
    assert payload["cleanup_status"] == "unknown"


def test_budget_sqlite_round_trip_and_legacy_json_defaults(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "old.db")
    job = _job(budget=JobBudget(max_model_requests=4, max_command_seconds=15))
    store.create(job)
    assert store.get(job.job_id).budget == job.budget  # type: ignore[union-attr]
    with sqlite3.connect(store.path) as conn:
        conn.execute(
            "UPDATE jobs SET budget_json=? WHERE job_id=?",
            (json.dumps({"timeout_seconds": 100, "max_tool_calls": 500, "max_cost_usd": None}), job.job_id),
        )
    old = store.get(job.job_id)
    assert old is not None
    assert old.budget.max_model_requests == 24
    assert old.budget.max_command_seconds == 300


@pytest.mark.parametrize("usage", [
    InferenceUsage(input_tokens=10, output_tokens=6, cached_input_tokens=3, reasoning_output_tokens=2),
    InferenceUsage(input_tokens=0, output_tokens=0),
])
def test_openai_usage_parses_totals_without_double_counting(usage: InferenceUsage) -> None:
    raw = {
        "input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens,
        "input_tokens_details": {"cached_tokens": usage.cached_input_tokens},
        "output_tokens_details": {"reasoning_tokens": usage.reasoning_output_tokens},
    }
    assert openai_usage(raw) == usage
    assert openai_usage({"prompt_tokens": 10, "completion_tokens": 6,
                         "prompt_tokens_details": {"cached_tokens": 3},
                         "completion_tokens_details": {"reasoning_tokens": 2}}) == InferenceUsage(
                             input_tokens=10, output_tokens=6,
                             cached_input_tokens=3, reasoning_output_tokens=2,
                         )
    assert openai_usage({}) is None


@pytest.mark.parametrize("raw", [
    {"input_tokens": -1}, {"input_tokens": True},
    {"input_tokens": 2, "input_tokens_details": {"cached_tokens": 3}},
    {"output_tokens": 2, "output_tokens_details": {"reasoning_tokens": 3}},
])
def test_invalid_usage_rejected_not_recorded_as_zero(raw: dict) -> None:
    with pytest.raises(InferenceBoundaryError):
        openai_usage(raw)


class _Tools:
    def available_tools(self) -> tuple[WorkerToolSpec, ...]:
        return (WorkerToolSpec("read_file", "fixture", {"type": "object"}),)

    def invoke(self, call: WorkerToolCall) -> WorkerToolResult:
        return WorkerToolResult(call.name, "fixture")


class _Model:
    def __init__(self, responses: list[InferenceResponse]) -> None:
        self.responses = iter(responses)
        self.calls = 0

    def infer(self, request: InferenceRequest) -> InferenceResponse:
        self.calls += 1
        return next(self.responses)


def _execute(model: _Model, control: ExecutionControl | None = None):
    return MediatedModelExecutor(model).execute(
        WorkerTask("job", "work", "coding-worker"), _Tools(),
        lambda _name, _data: None, control=control,
    )


def test_usage_reports_unknown_separately_from_included_cached_and_reasoning_tokens() -> None:
    result = _execute(_Model([
        InferenceResponse(tool_calls=(InferenceToolCall("c1", "read_file", {}),),
                          usage=InferenceUsage(10, 6, 3, 2)),
        InferenceResponse("submit", usage=InferenceUsage(5, 4, 0, 1)),
    ]))
    assert result.outcome is WorkerOutcome.SUBMITTED
    assert result.metrics["usage"] == {
        "input_tokens": 15, "output_tokens": 10,
        "cached_input_tokens": 3, "reasoning_output_tokens": 3,
        "unknown_requests": 0,
    }
    unknown = _execute(_Model([InferenceResponse("submit")]))
    assert unknown.metrics["usage"]["input_tokens"] is None
    assert unknown.metrics["usage"]["unknown_requests"] == 1


@pytest.mark.parametrize("deadline", [float("nan"), float("inf"), True])
def test_invalid_deadline_rejected(deadline: float) -> None:
    with pytest.raises(ValueError, match="deadline must be a finite"):
        ExecutionControl(deadline, lambda: False)


def test_cooperative_cancel_or_deadline_prevents_followup_dispatch() -> None:
    clock = [1.0]
    cancelled = [False]
    control = ExecutionControl(5.0, lambda: cancelled[0], lambda: clock[0])
    model = _Model([InferenceResponse("unused")])
    cancelled[0] = True
    assert _execute(model, control).outcome is WorkerOutcome.CANCELLED
    assert model.calls == 0
    cancelled[0] = False
    clock[0] = 5.0
    assert _execute(model, control).outcome is WorkerOutcome.TIMED_OUT
    assert model.calls == 0

    class CancelAfterInference(_Model):
        def infer(self, request: InferenceRequest) -> InferenceResponse:
            cancelled[0] = True
            return super().infer(request)

    cancelled[0] = False
    clock[0] = 1.0
    model = CancelAfterInference([
        InferenceResponse(tool_calls=(InferenceToolCall("c1", "read_file", {}),)),
    ])
    assert _execute(model, control).outcome is WorkerOutcome.CANCELLED
    assert model.calls == 1


class _NativeClient:
    supports_native_tools = True
    api_type = "chat_completions"

    def __init__(self) -> None:
        self.last_usage = {"prompt_tokens": 12, "completion_tokens": 4}

    def chat(self, messages: list[dict], tools=None, tool_choice=None) -> str:
        return "done"


def test_host_adapter_propagates_usage_without_requiring_provider_credentials() -> None:
    model = LLMInferenceModel(_NativeClient())
    response = model.infer((InferenceMessage("user", "fixture"),), ())
    assert response.usage == InferenceUsage(input_tokens=12, output_tokens=4)
