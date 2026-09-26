"""Offline host-loop composition and independent cleanup attempts (no real VM)."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import replace

import pytest

from night_shifts.contracts.inference import InferenceMessage, InferenceRequest, InferenceResponse
from night_shifts.contracts.worker_tool import WorkerToolSpec
from night_shifts.execution_policy import WorkerExecutionPolicy
from night_shifts.inference import InferenceBoundaryError, TrustedInferenceGateway
from night_shifts.job_execution import HostJobExecution
from night_shifts.models import JobBudget, NightShiftJob, SandboxRecord
from night_shifts.process_inference import ProcessInferenceModel
from night_shifts.protocol import CleanupStatus, WorkerOutcome, WorkerTask
from night_shifts.tool_session import SandboxToolSession
from night_shifts.worker_capabilities import worker_tool_names


class _AnswerModel:
    def infer(self, messages, tools):
        return InferenceResponse("submitted for review")


def _answer_factory():
    return _AnswerModel()


class _Pipe:
    def __init__(self, actions, *, fail_close=False):
        self.actions = actions
        self.fail_close = fail_close
        self.response = b""

    def send(self, frame, *, timeout_seconds):
        value = json.loads(frame)
        ids = {key: value[key] for key in ("job_id", "sandbox_id", "session_id")}
        if value["type"] == "hello":
            payload = {"version": 1, "type": "hello_ack", **ids}
        else:
            payload = {
                "version": 1, "type": "response", **ids,
                "request_id": value["request_id"], "ok": True, "payload": {},
            }
        self.response = json.dumps(payload).encode() + b"\n"

    def receive(self, *, max_bytes, timeout_seconds):
        return self.response

    def close(self):
        self.actions.append("tool session")
        if self.fail_close:
            raise RuntimeError("private error not for model result")


def _components(*, fail_close=False):
    job = NightShiftJob(
        "fixture", "inspect", "coding-worker", repository_id="fixture",
        starting_revision="a" * 40,
    )
    policy = WorkerExecutionPolicy.snapshot(
        job, image_sha256="f" * 64, provider_id="fixture-provider",
        model_id="fixture-model",
    )
    sandbox_id = "c" * 32
    sandbox = SandboxRecord(
        job_id=job.job_id, backend="hyperv", sandbox_id=sandbox_id,
        external_id=f"night-shift-{sandbox_id}",
    )
    actions = []
    transport = _Pipe(actions, fail_close=fail_close)
    session = SandboxToolSession(
        sandbox, job.worker_profile,
        tuple(WorkerToolSpec(name, "fixture", {"type": "object"})
              for name in worker_tool_names(job.worker_profile)),
        transport, deadline=time.monotonic() + 15,
    )
    session.start()
    session.load_chunk(b"fixture", offset=0, final=True)
    return policy, session, actions


def test_host_loop_closes_child_and_session_but_does_not_claim_vm_cleanup():
    policy, session, actions = _components()
    processes = []

    def factory():
        process = ProcessInferenceModel(_answer_factory, deadline=time.monotonic() + 15)
        processes.append(process)
        return process

    gateway = TrustedInferenceGateway({policy.model_id: factory})
    client = gateway.create_client(
        job_id=policy.job_id, worker_profile=policy.worker_profile,
        model_id=policy.model_id, limits=policy.inference_limits(),
    )
    result = HostJobExecution(
        policy, gateway, client, session, deadline=time.monotonic() + 15,
        cancellation_requested=lambda: False,
    ).run(WorkerTask(
        policy.job_id, "inspect", policy.worker_profile, repository_id=policy.repository_id,
        starting_revision=policy.base_revision,
    ), lambda _name, _data: None)
    assert result.outcome is WorkerOutcome.SUBMITTED
    assert result.cleanup_status is CleanupStatus.UNKNOWN
    assert actions == ["tool session"]
    assert not processes[0].alive


def test_event_and_each_cleanup_failure_do_not_skip_other_cleanup():
    policy, session, actions = _components(fail_close=True)

    class FailingModel(_AnswerModel):
        def close(self):
            actions.append("inference child")
            raise RuntimeError("secret provider exception")

    gateway = TrustedInferenceGateway({policy.model_id: FailingModel})
    client = gateway.create_client(
        job_id=policy.job_id, worker_profile=policy.worker_profile,
        model_id=policy.model_id,
    )
    result = HostJobExecution(
        policy, gateway, client, session, deadline=time.monotonic() + 15,
        cancellation_requested=lambda: False,
    ).run(WorkerTask(
        policy.job_id, "inspect", policy.worker_profile, repository_id=policy.repository_id,
        starting_revision=policy.base_revision,
    ), lambda _name, _data: (_ for _ in ()).throw(RuntimeError("event store unavailable")))
    assert result.outcome is WorkerOutcome.FAILED
    assert result.cleanup_status is CleanupStatus.FAILED
    assert result.error == "tool session cleanup failed; inference child cleanup failed"
    assert actions == ["tool session", "inference child"]
    assert "secret" not in (result.error or "")


def test_inference_model_mismatch_cannot_dispatch_and_is_cleaned_up() -> None:
    policy, session, actions = _components()
    model_calls = []

    class WrongModel:
        def infer(self, messages, tools):
            model_calls.append("unapproved model call")
            return InferenceResponse("bad")

    gateway = TrustedInferenceGateway({"different-model": WrongModel})
    client = gateway.create_client(
        job_id=policy.job_id, worker_profile=policy.worker_profile,
        model_id="different-model",
    )
    result = HostJobExecution(
        policy, gateway, client, session, deadline=time.monotonic() + 15,
        cancellation_requested=lambda: False,
    ).run(WorkerTask(
        policy.job_id, "inspect", policy.worker_profile,
        repository_id=policy.repository_id, starting_revision=policy.base_revision,
    ), lambda _name, _data: None)
    assert result.outcome is WorkerOutcome.FAILED
    assert result.metrics["usage"]["unknown"] is True
    assert not model_calls
    assert actions == ["tool session"]
    with pytest.raises(InferenceBoundaryError, match="revoked"):
        client.infer(InferenceRequest(
            policy.job_id, policy.worker_profile, (InferenceMessage("user", "x"),), (),
        ))


def test_invalid_deadline_still_closes_both_resources() -> None:
    policy, session, actions = _components()
    gateway = TrustedInferenceGateway({policy.model_id: _AnswerModel})
    client = gateway.create_client(
        job_id=policy.job_id, worker_profile=policy.worker_profile,
        model_id=policy.model_id,
    )
    result = HostJobExecution(
        policy, gateway, client, session, deadline=float("nan"),
        cancellation_requested=lambda: False,
    ).run(WorkerTask(
        policy.job_id, "inspect", policy.worker_profile,
        repository_id=policy.repository_id, starting_revision=policy.base_revision,
    ), lambda _name, _data: None)
    assert result.outcome is WorkerOutcome.FAILED
    assert result.error == "invalid monotonic job deadline"
    assert actions == ["tool session"]


def test_policy_session_mismatch_closes_both_resources() -> None:
    policy, session, actions = _components()
    changed = replace(policy, job_id="another-job")
    gateway = TrustedInferenceGateway({changed.model_id: _AnswerModel})
    client = gateway.create_client(
        job_id=changed.job_id, worker_profile=changed.worker_profile,
        model_id=changed.model_id,
    )
    result = HostJobExecution(
        changed, gateway, client, session, deadline=time.monotonic() + 15,
        cancellation_requested=lambda: False,
    ).run(WorkerTask(
        changed.job_id, "inspect", changed.worker_profile,
        repository_id=changed.repository_id, starting_revision=changed.base_revision,
    ), lambda _name, _data: None)
    assert result.outcome is WorkerOutcome.FAILED
    assert "identity" in (result.error or "")
    assert actions == ["tool session"]
    with pytest.raises(InferenceBoundaryError, match="revoked"):
        client.infer(InferenceRequest(
            changed.job_id, changed.worker_profile, (InferenceMessage("user", "x"),), (),
        ))


def test_tool_budget_mismatch_blocks_model_and_still_closes_session() -> None:
    policy, session, actions = _components()
    strict = replace(policy, budget=JobBudget(max_command_seconds=2))
    gateway = TrustedInferenceGateway({policy.model_id: _AnswerModel})
    client = gateway.create_client(
        job_id=policy.job_id, worker_profile=policy.worker_profile,
        model_id=policy.model_id,
    )
    result = HostJobExecution(
        strict, gateway, client, session, deadline=time.monotonic() + 15,
        cancellation_requested=lambda: False,
    ).run(WorkerTask(
        policy.job_id, "inspect", policy.worker_profile, repository_id=policy.repository_id,
        starting_revision=policy.base_revision,
    ), lambda _name, _data: None)
    assert result.outcome is WorkerOutcome.FAILED
    assert "command limit" in (result.error or "")
    assert actions == ["tool session"]


def test_interrupted_inference_is_cancelled_and_child_is_reaped() -> None:
    class StalledModel:
        def infer(self, messages, tools):
            time.sleep(60)
            return InferenceResponse("late response")

    # Spawn needs a top-level factory, so reuse the other process fixture.
    from test_process_inference import _stall_factory

    policy, session, actions = _components()
    cancelled = threading.Event()
    processes = []

    def factory():
        process = ProcessInferenceModel(
            _stall_factory, deadline=time.monotonic() + 15,
            cancellation_requested=cancelled.is_set,
        )
        processes.append(process)
        return process

    gateway = TrustedInferenceGateway({policy.model_id: factory})
    client = gateway.create_client(
        job_id=policy.job_id, worker_profile=policy.worker_profile,
        model_id=policy.model_id,
    )
    reports = []

    def run():
        reports.append(HostJobExecution(
            policy, gateway, client, session, deadline=time.monotonic() + 15,
            cancellation_requested=cancelled.is_set,
        ).run(WorkerTask(
            policy.job_id, "inspect", policy.worker_profile,
            repository_id=policy.repository_id, starting_revision=policy.base_revision,
        ), lambda _name, _data: None))

    worker = threading.Thread(target=run)
    worker.start()
    try:
        time.sleep(0.1)
        cancelled.set()
        worker.join(timeout=4)
        assert not worker.is_alive()
        assert len(reports) == 1 and reports[0].outcome is WorkerOutcome.CANCELLED
        assert reports[0].metrics["usage"]["unknown"] is True
        assert actions == ["tool session"]
        assert not processes[0].alive
    finally:
        cancelled.set()
        gateway.close_client(client)
        session.cancel()
        worker.join(timeout=4)


def test_task_identity_rejected_before_inference():
    policy, session, _ = _components()
    gateway = TrustedInferenceGateway({policy.model_id: _AnswerModel})
    client = gateway.create_client(
        job_id=policy.job_id, worker_profile=policy.worker_profile,
        model_id=policy.model_id,
    )
    try:
        execution = HostJobExecution(
            policy, gateway, client, session, deadline=time.monotonic() + 15,
            cancellation_requested=lambda: False,
        )
        result = execution.run(WorkerTask(
            "other-job", "inspect", policy.worker_profile, repository_id="fixture",
            starting_revision=policy.base_revision,
        ), lambda _name, _data: None)
        assert result.job_id == policy.job_id
        assert result.outcome is WorkerOutcome.FAILED
        assert "identity" in (result.error or "")
        assert result.cleanup_status is CleanupStatus.UNKNOWN
    finally:
        session.cancel()
        gateway.close_client(client)
