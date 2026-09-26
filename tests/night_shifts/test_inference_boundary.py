"""Tests for trusted inference mediation and the bounded guest model loop."""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence

import pytest

from llm.base import LLMResponse, NativeToolCall
from night_shifts.contracts.inference import (
    InferenceMessage,
    InferenceRequest,
    InferenceResponse,
    InferenceToolCall,
)
from night_shifts.contracts.worker_tool import (
    WorkerToolCall,
    WorkerToolResult,
    WorkerToolSpec,
)
from night_shifts.executor import MediatedModelExecutor, ModelExecutorLimits
from night_shifts.guest.executor import MediatedModelExecutor as LegacyMediatedModelExecutor
from night_shifts.inference import (
    InferenceBoundaryError,
    InferenceLimits,
    LLMInferenceModel,
    TrustedInferenceGateway,
)
from night_shifts.protocol import WorkerOutcome, WorkerTask
from night_shifts.worker_capabilities import worker_tool_names


def _specs() -> tuple[WorkerToolSpec, ...]:
    schema = {"type": "object", "properties": {}, "additionalProperties": False}
    return tuple(
        WorkerToolSpec(name, f"Fixture tool: {name}", schema)
        for name in worker_tool_names("coding-worker")
    )


class QueueModel:
    def __init__(self, responses: Sequence[InferenceResponse]) -> None:
        self.responses = deque(responses)
        self.requests: list[tuple[Sequence[InferenceMessage], Sequence[WorkerToolSpec]]] = []

    def infer(
        self,
        messages: Sequence[InferenceMessage],
        tools: Sequence[WorkerToolSpec],
    ) -> InferenceResponse:
        self.requests.append((messages, tools))
        return self.responses.popleft()


class FakeTools:
    def available_tools(self) -> tuple[WorkerToolSpec, ...]:
        return _specs()

    def invoke(self, call: WorkerToolCall) -> WorkerToolResult:
        assert call.name == "write_artifact"
        return WorkerToolResult(
            call.name,
            '{"reference":"guest-artifact/report.txt","size_bytes":12}',
        )


def _request(job_id: str = "a" * 32, profile: str = "coding-worker") -> InferenceRequest:
    return InferenceRequest(
        job_id=job_id,
        worker_profile=profile,
        messages=(InferenceMessage("user", "Inspect the repository."),),
        tools=_specs(),
    )


def test_gateway_binds_job_profile_model_and_request_budget() -> None:
    model = QueueModel(
        [InferenceResponse("first"), InferenceResponse("second")]
    )
    gateway = TrustedInferenceGateway({"approved-model": lambda: model})
    client = gateway.create_client(
        job_id="a" * 32,
        worker_profile="coding-worker",
        model_id="approved-model",
        limits=InferenceLimits(max_requests=1),
    )

    assert client.infer(_request()).content == "first"
    with pytest.raises(InferenceBoundaryError, match="request limit"):
        client.infer(_request())
    with pytest.raises(InferenceBoundaryError, match="unknown trusted model"):
        gateway.create_client(
            job_id="a" * 32,
            worker_profile="coding-worker",
            model_id="task-selected-model",
        )


def test_gateway_rejects_identity_and_profile_tool_mismatches() -> None:
    model = QueueModel([InferenceResponse("unused")])
    gateway = TrustedInferenceGateway({"approved": lambda: model})
    client = gateway.create_client(
        job_id="a" * 32,
        worker_profile="coding-worker",
        model_id="approved",
    )

    with pytest.raises(InferenceBoundaryError, match="job does not match"):
        client.infer(_request(job_id="b" * 32))
    with pytest.raises(InferenceBoundaryError, match="tools do not match"):
        client.infer(
            InferenceRequest(
                job_id="a" * 32,
                worker_profile="coding-worker",
                messages=(InferenceMessage("user", "task"),),
                tools=(_specs()[0],),
            )
        )


def test_gateway_counts_tool_calls_and_arguments_toward_payload_limits() -> None:
    model = QueueModel(
        [
            InferenceResponse(
                tool_calls=(InferenceToolCall("call-1", "run_command", {"argv": ["git", "status"]}),)
            )
        ]
    )
    gateway = TrustedInferenceGateway({"approved": lambda: model})
    client = gateway.create_client(
        job_id="a" * 32,
        worker_profile="coding-worker",
        model_id="approved",
        limits=InferenceLimits(max_output_bytes=16),
    )

    with pytest.raises(InferenceBoundaryError, match="output exceeds"):
        client.infer(_request())


def test_gateway_rejects_unauthorized_model_tool_calls() -> None:
    model = QueueModel(
        [
            InferenceResponse(
                tool_calls=(InferenceToolCall("call-1", "publish_branch", {}),)
            )
        ]
    )
    gateway = TrustedInferenceGateway({"approved": lambda: model})
    client = gateway.create_client(
        job_id="a" * 32,
        worker_profile="coding-worker",
        model_id="approved",
    )

    with pytest.raises(InferenceBoundaryError, match="unauthorized tool"):
        client.infer(_request())


def test_mediated_executor_runs_bounded_tool_loop_and_collects_artifacts() -> None:
    model = QueueModel(
        [
            InferenceResponse(
                tool_calls=(
                    InferenceToolCall(
                        "call-1",
                        "write_artifact",
                        {"name": "report.txt", "kind": "report", "content": "done"},
                    ),
                )
            ),
            InferenceResponse("Completed the bounded task."),
        ]
    )
    gateway = TrustedInferenceGateway({"approved": lambda: model})
    client = gateway.create_client(
        job_id="a" * 32,
        worker_profile="coding-worker",
        model_id="approved",
    )
    events: list[tuple[str, dict]] = []
    executor = MediatedModelExecutor(client)

    result = executor.execute(
        WorkerTask(
            job_id="a" * 32,
            objective="Produce a report.",
            worker_profile="coding-worker",
            acceptance_criteria=("Write a report artifact.",),
            repository_id="example",
            starting_revision="deadbeef",
        ),
        FakeTools(),
        lambda name, payload: events.append((name, payload)),
    )

    assert LegacyMediatedModelExecutor is MediatedModelExecutor
    assert result.outcome is WorkerOutcome.SUBMITTED
    assert result.summary == "Completed the bounded task."
    assert result.artifacts == ("guest-artifact/report.txt",)
    assert result.metrics == {
        "inference_turns": 2, "tool_calls": 1, "tool_errors": 0,
        "usage": {
            "input_tokens": None, "output_tokens": None,
            "cached_input_tokens": None, "reasoning_output_tokens": None,
            "unknown_requests": 2,
        },
    }
    assert [name for name, _ in events] == [
        "worker_inference_requested",
        "worker_inference_completed",
        "worker_tool_completed",
        "worker_inference_requested",
        "worker_inference_completed",
    ]
    second_messages = model.requests[1][0]
    assert second_messages[-2].tool_calls[0].call_id == "call-1"
    assert second_messages[-1].tool_call_id == "call-1"


def test_mediated_executor_fails_closed_at_turn_limit() -> None:
    response = InferenceResponse(
        tool_calls=(InferenceToolCall("call-1", "write_artifact", {}),)
    )

    class RepeatingClient:
        def infer(self, request: InferenceRequest) -> InferenceResponse:
            del request
            return response

    result = MediatedModelExecutor(
        RepeatingClient(),
        limits=ModelExecutorLimits(max_turns=1),
    ).execute(
        WorkerTask(
            job_id="a" * 32,
            objective="Never finish.",
            worker_profile="coding-worker",
            repository_id="example",
            starting_revision="deadbeef",
        ),
        FakeTools(),
        lambda _name, _payload: None,
    )

    assert result.outcome is WorkerOutcome.FAILED
    assert "turn limit" in (result.error or "")


class FakeNativeLLM:
    supports_native_tools = True
    supports_native_tool_outputs = False
    api_type = "chat_completions"

    def __init__(self) -> None:
        self.messages: list[dict] = []
        self.tools: list[dict] = []

    def chat(self, messages: list[dict], tools=None, tool_choice=None):
        self.messages = messages
        self.tools = tools or []
        assert tool_choice == "auto"
        return LLMResponse(
            content=None,
            tool_calls=[NativeToolCall("native-1", "run_command", {"argv": ["git", "status"]})],
        )

    def submit_tool_outputs(self, tool_outputs):
        raise NotImplementedError


def test_llm_adapter_keeps_provider_client_on_trusted_host_boundary() -> None:
    client = FakeNativeLLM()
    model = LLMInferenceModel(client)

    response = model.infer((InferenceMessage("user", "task"),), _specs())

    assert response.tool_calls[0].name == "run_command"
    assert tuple(tool["function"]["name"] for tool in client.tools) == worker_tool_names(
        "coding-worker"
    )
    assert client.messages == [{"role": "user", "content": "task"}]
