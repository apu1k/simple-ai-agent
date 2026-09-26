"""Offline, deterministic tests of the location-neutral host worker loop."""

from __future__ import annotations

import json
from collections import deque
from pathlib import Path

import pytest

from night_shifts.contracts.inference import InferenceRequest, InferenceResponse, InferenceToolCall
from night_shifts.contracts.worker_tool import WorkerToolCall, WorkerToolResult, WorkerToolSpec
from night_shifts.executor import MediatedModelExecutor, ModelExecutorLimits
from night_shifts.models import JobStatus, NightShiftJob
from night_shifts.protocol import (
    CheckStatus,
    CleanupStatus,
    ProtocolError,
    ReviewStatus,
    WorkerOutcome,
    WorkerResult,
    WorkerTask,
    decode_worker_message,
    encode_result,
)
from night_shifts.service import NightShiftService
from night_shifts.storage import EventStore, JobStore


class ScriptedInference:
    def __init__(self, *responses: InferenceResponse) -> None:
        self.responses = deque(responses)
        self.requests: list[InferenceRequest] = []

    def infer(self, request: InferenceRequest) -> InferenceResponse:
        self.requests.append(request)
        return self.responses.popleft()


class ScriptedTools:
    def __init__(self, *, error_on: str | None = None) -> None:
        self.calls: list[WorkerToolCall] = []
        self.error_on = error_on

    def available_tools(self) -> tuple[WorkerToolSpec, ...]:
        return tuple(
            WorkerToolSpec(name, name, {"type": "object"})
            for name in ("read_file", "apply_patch", "run_command", "write_artifact")
        )

    def invoke(self, call: WorkerToolCall) -> WorkerToolResult:
        self.calls.append(call)
        return WorkerToolResult(
            call.name,
            "tool failed" if call.name == self.error_on else "fixture output",
            is_error=call.name == self.error_on,
        )


def _task() -> WorkerTask:
    return WorkerTask("job-1", "Fix a fixture", "coding-worker", repository_id="fixture")


def _run(model: ScriptedInference, tools: ScriptedTools, **limits: int) -> WorkerResult:
    return MediatedModelExecutor(model, limits=ModelExecutorLimits(**limits)).execute(
        _task(), tools, lambda _name, _payload: None
    )


def test_inspect_edit_test_then_submit_is_not_verified_success() -> None:
    model = ScriptedInference(
        InferenceResponse(tool_calls=(InferenceToolCall("c1", "read_file", {"path": "a.py"}),)),
        InferenceResponse(tool_calls=(InferenceToolCall("c2", "apply_patch", {"path": "a.py"}),)),
        InferenceResponse(tool_calls=(InferenceToolCall("c3", "run_command", {"argv": ["pytest"]}),)),
        InferenceResponse("Changed a.py and ran pytest; review the result."),
    )
    tools = ScriptedTools()

    result = _run(model, tools)

    assert result.outcome is WorkerOutcome.SUBMITTED
    assert [call.name for call in tools.calls] == ["read_file", "apply_patch", "run_command"]
    assert result.check_status is CheckStatus.NOT_RUN  # Model's check claim is not trusted evidence.
    assert result.review_status is ReviewStatus.NOT_REVIEWED
    assert result.cleanup_status is CleanupStatus.UNKNOWN
    assert result.metrics == {"inference_turns": 4, "tool_calls": 3, "tool_errors": 0}
    assert [message.role for message in model.requests[-1].messages] == [
        "system", "user", "assistant", "tool", "assistant", "tool", "assistant", "tool",
    ]
    prompt = model.requests[0].messages[0].content
    assert "model conversation runs on the trusted host" in prompt
    assert "supplied tools operate in a disposable sandbox" in prompt


def test_explicit_blocker_is_not_success_or_interactive_wait() -> None:
    result = _run(ScriptedInference(InferenceResponse("BLOCKED: missing fixture dependency")), ScriptedTools())
    assert result.outcome is WorkerOutcome.BLOCKED
    assert result.summary == "BLOCKED: missing fixture dependency"
    assert result.check_status is CheckStatus.NOT_RUN


def test_tool_error_is_reported_to_model_and_not_turned_into_verified_check() -> None:
    model = ScriptedInference(
        InferenceResponse(tool_calls=(InferenceToolCall("c1", "run_command", {"argv": ["pytest"]}),)),
        InferenceResponse("Tests could not run; see limitations."),
    )
    result = _run(model, ScriptedTools(error_on="run_command"))
    assert model.requests[1].messages[-1].content == "tool failed"
    assert result.outcome is WorkerOutcome.SUBMITTED
    assert result.metrics["tool_errors"] == 1
    assert result.check_status is CheckStatus.NOT_RUN


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (InferenceResponse("  "), "empty final"),
        (InferenceResponse("ééé"), "summary exceeded"),
        (InferenceResponse(tool_calls=(InferenceToolCall("c1", "host_shell", {}),)), "invalid tool"),
        (InferenceResponse(tool_calls=(InferenceToolCall("c1", "read_file", []),)), "invalid tool"),
        (InferenceResponse(tool_calls=(InferenceToolCall("c1", [], {}),)), "invalid tool"),
        (InferenceResponse(tool_calls=(object(),)), "invalid tool"),
        (InferenceResponse(tool_calls=(
            InferenceToolCall("c1", "read_file", {}),
            InferenceToolCall("c1", "read_file", {}),
        )), "invalid tool"),
        (InferenceResponse(tool_calls=(InferenceToolCall("c1", "read_file", {"path": float("nan")}),)), "invalid tool"),
    ],
)
def test_empty_oversize_and_malformed_model_responses_fail_closed(
    response: InferenceResponse, error: str
) -> None:
    tools = ScriptedTools()
    result = _run(ScriptedInference(response), tools, max_summary_bytes=4)
    assert result.outcome is WorkerOutcome.FAILED
    assert error in (result.error or "")
    assert not tools.calls


def test_empty_blocker_cannot_be_submitted() -> None:
    result = _run(ScriptedInference(InferenceResponse("BLOCKED: ")), ScriptedTools())
    assert result.outcome is WorkerOutcome.FAILED
    assert "without a reason" in (result.error or "")


def test_tool_provider_exceptions_and_invalid_results_fail_closed() -> None:
    class BrokenTools(ScriptedTools):
        def invoke(self, call: WorkerToolCall) -> WorkerToolResult:
            raise RuntimeError("tool service disconnected")

    class MismatchedTools(ScriptedTools):
        def invoke(self, call: WorkerToolCall) -> WorkerToolResult:
            return WorkerToolResult("different_tool", "wrong result")

    for provider in (BrokenTools(), MismatchedTools()):
        model = ScriptedInference(
            InferenceResponse(tool_calls=(InferenceToolCall("c1", "read_file", {}),)),
        )
        result = _run(model, provider)
        assert result.outcome is WorkerOutcome.FAILED
        assert "worker tool provider" in (result.error or "")


def test_replayed_call_id_is_not_invoked_twice() -> None:
    model = ScriptedInference(
        InferenceResponse(tool_calls=(InferenceToolCall("c1", "read_file", {}),)),
        InferenceResponse(tool_calls=(InferenceToolCall("c1", "apply_patch", {}),)),
    )
    tools = ScriptedTools()
    result = _run(model, tools)
    assert result.outcome is WorkerOutcome.FAILED
    assert [call.name for call in tools.calls] == ["read_file"]


def test_turn_and_tool_limits_fail_without_extra_dispatch() -> None:
    model = ScriptedInference(
        InferenceResponse(tool_calls=(InferenceToolCall("c1", "read_file", {}),)),
    )
    tools = ScriptedTools()
    result = _run(model, tools, max_tool_calls=1, max_turns=1)
    assert result.outcome is WorkerOutcome.FAILED
    assert "turn limit" in (result.error or "")
    assert len(tools.calls) == 1
    result = _run(
        ScriptedInference(InferenceResponse(tool_calls=(
            InferenceToolCall("c2", "read_file", {}), InferenceToolCall("c3", "apply_patch", {}),
        ))),
        tools, max_tool_calls=1,
    )
    assert result.outcome is WorkerOutcome.FAILED
    assert "tool-call limit" in (result.error or "")
    assert len(tools.calls) == 1


def test_result_statuses_round_trip_and_old_frames_default_to_unknown() -> None:
    result = WorkerResult(
        "job-1", WorkerOutcome.SUBMITTED, "Submitted", check_status=CheckStatus.FAILED,
        review_status=ReviewStatus.NOT_REVIEWED, cleanup_status=CleanupStatus.CLEAN,
    )
    assert decode_worker_message(encode_result(result)) == result
    old = json.loads(encode_result(result))
    for key in ("check_status", "review_status", "cleanup_status"):
        del old["payload"][key]
    restored = decode_worker_message(json.dumps(old))
    assert restored.check_status is CheckStatus.NOT_RUN
    assert restored.review_status is ReviewStatus.NOT_REVIEWED
    assert restored.cleanup_status is CleanupStatus.UNKNOWN
    old["payload"]["cleanup_status"] = "imaginary"
    with pytest.raises(ProtocolError, match="cleanup_status"):
        decode_worker_message(json.dumps(old))


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [(WorkerOutcome.SUBMITTED, JobStatus.COMPLETED), (WorkerOutcome.BLOCKED, JobStatus.FAILED)],
)
def test_service_persists_explicit_outcome_without_claiming_review(
    tmp_path: Path, outcome: WorkerOutcome, expected: JobStatus
) -> None:
    database = tmp_path / "jobs.db"
    jobs, events = JobStore(database), EventStore(database)
    service = NightShiftService(jobs, events)
    job = service.create(NightShiftJob("Fixture", "Fix it", "coding-worker"))
    service.transition(job.job_id, JobStatus.QUEUED, actor="user")

    class Backend:
        def run(self, task: WorkerTask, **_kwargs: object) -> WorkerResult:
            return WorkerResult(task.job_id, outcome, "Model report")

    result = service.run_local(job.job_id, Backend())
    assert result.outcome is outcome
    assert jobs.get(job.job_id).status is expected  # type: ignore[union-attr]
    payload = events.list(job_id=job.job_id)[-1].payload
    assert payload["outcome"] == outcome.value
    assert payload["check_status"] == "not_run"
    assert payload["review_status"] == "not_reviewed"
    assert payload["cleanup_status"] == "unknown"
