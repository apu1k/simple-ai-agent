"""Offline spawned-host-process tests; no VM, paid model or repository code."""

from __future__ import annotations

import threading
import time

import pytest

from night_shifts.contracts.inference import InferenceMessage, InferenceRequest, InferenceResponse
from night_shifts.contracts.worker_tool import WorkerToolSpec
from night_shifts.execution_policy import ExecutionPolicyBlocked
from night_shifts.inference import InferenceBoundaryError, TrustedInferenceGateway
from night_shifts.process_inference import ProcessInferenceModel, _decode
from night_shifts.worker_capabilities import worker_tool_names


class _CountingModel:
    def __init__(self) -> None:
        self.count = 0

    def infer(self, messages, tools):
        self.count += 1
        return InferenceResponse(content=f"turn {self.count}")


class _StalledModel:
    def infer(self, messages, tools):
        time.sleep(60)
        return InferenceResponse(content="late result MUST NOT win")


def _counting_factory():
    return _CountingModel()


def _stall_factory():
    return _StalledModel()


def _bad_factory():
    raise RuntimeError("provider secret must never cross the child pipe")


def _request(job_id: str = "job-a") -> InferenceRequest:
    return InferenceRequest(
        job_id=job_id,
        worker_profile="coding-worker",
        messages=(InferenceMessage("user", "fixture"),),
        tools=tuple(
            WorkerToolSpec(name, "fixture", {"type": "object"})
            for name in worker_tool_names("coding-worker")
        ),
    )


def test_spawned_inference_is_one_conversation_per_job_and_revoked_on_close() -> None:
    processes: list[ProcessInferenceModel] = []

    def model_factory():
        process = ProcessInferenceModel(_counting_factory, deadline=time.monotonic() + 15)
        processes.append(process)
        return process

    gateway = TrustedInferenceGateway({"approved": model_factory})
    a = gateway.create_client(job_id="job-a", worker_profile="coding-worker", model_id="approved")
    b = gateway.create_client(job_id="job-b", worker_profile="coding-worker", model_id="approved")
    try:
        assert a.infer(_request()).content == "turn 1"
        assert a.infer(_request()).content == "turn 2"
        assert b.infer(_request("job-b")).content == "turn 1"
        with pytest.raises(InferenceBoundaryError, match="job does not match"):
            b.infer(_request())
    finally:
        gateway.close_client(a)
        gateway.close_client(b)
    assert not any(process.alive for process in processes)
    with pytest.raises(InferenceBoundaryError, match="revoked"):
        a.infer(_request())


def test_cancel_terminates_hung_inference_and_no_late_success_survives() -> None:
    holder: list[ProcessInferenceModel] = []

    def factory():
        model = ProcessInferenceModel(_stall_factory, deadline=time.monotonic() + 15)
        holder.append(model)
        return model

    gateway = TrustedInferenceGateway({"approved": factory})
    client = gateway.create_client(job_id="job-a", worker_profile="coding-worker", model_id="approved")
    entered = threading.Event()
    results: list[object] = []

    def run() -> None:
        entered.set()
        try:
            results.append(client.infer(_request()))
        except Exception as exc:
            results.append(exc)

    thread = threading.Thread(target=run)  # Never a daemon workaround.
    thread.start()
    assert entered.wait(timeout=2)
    try:
        gateway.cancel_client(client)
        thread.join(timeout=3)
        assert not thread.is_alive()
        assert len(results) == 1 and isinstance(results[0], InferenceBoundaryError)
        assert not holder[0].alive
        with pytest.raises(InferenceBoundaryError, match="revoked"):
            client.infer(_request())
    finally:
        gateway.close_client(client)
        thread.join(timeout=3)


def test_monotonic_deadline_reaps_hung_child_without_late_reply() -> None:
    process = ProcessInferenceModel(_stall_factory, deadline=time.monotonic() + 4)
    try:
        with pytest.raises(InferenceBoundaryError, match="timed out"):
            process.infer(_request().messages, _request().tools)
        assert not process.alive
    finally:
        process.close()


def test_process_frame_rejects_duplicate_and_nonfinite_fields() -> None:
    for frame in (b'{"type":"ready","type":"result"}', b'{"usage":NaN}'):
        with pytest.raises(InferenceBoundaryError, match="malformed JSON"):
            _decode(frame, 128)
    with pytest.raises(InferenceBoundaryError, match="exceeds the limit"):
        _decode(b"{}" * 100, 32)


def test_initialization_failure_cannot_leak_child_or_exception_details() -> None:
    with pytest.raises(InferenceBoundaryError, match="failed to initialize") as exc:
        ProcessInferenceModel(_bad_factory, deadline=time.monotonic() + 15)
    assert "provider secret" not in str(exc.value)


def test_live_policy_requires_both_boundaries_and_rejects_strict_usd() -> None:
    from night_shifts.execution_policy import WorkerExecutionPolicy
    from night_shifts.models import JobBudget, NightShiftJob

    def policy(budget):
        return WorkerExecutionPolicy.snapshot(
            NightShiftJob(
                "fixture", "task", "coding-worker", repository_id="fixture",
                starting_revision="a" * 40, budget=budget,
            ),
            provider_id="approved", model_id="approved", image_sha256="f" * 64,
        )

    with pytest.raises(ExecutionPolicyBlocked, match="hard-cancellable"):
        policy(JobBudget()).require_live_guarantees(inference_cancellable=True)
    with pytest.raises(ExecutionPolicyBlocked, match="pricing"):
        policy(JobBudget(max_cost_usd=1.0)).require_live_guarantees(
            inference_cancellable=True, tool_cancellable=True,
        )
