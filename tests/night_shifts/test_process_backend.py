import json
import sys
from pathlib import Path

import pytest

from night_shifts.backends import ProcessWorkerBackend
from night_shifts.models import JobBudget, JobStatus, NightShiftJob
from night_shifts.protocol import (
    ProtocolError,
    WorkerOutcome,
    WorkerResult,
    WorkerTask,
    decode_task,
    decode_worker_message,
    encode_result,
    encode_task,
)
from night_shifts.service import NightShiftService
from night_shifts.storage import EventStore, JobStore


def test_protocol_round_trips_task_and_result():
    task = WorkerTask(
        job_id="job-1",
        objective="Validate protocol",
        worker_profile="protocol-test-worker",
        acceptance_criteria=("Completes",),
    )
    result = WorkerResult(
        job_id="job-1",
        outcome=WorkerOutcome.SUCCESS,
        summary="done",
        checks=({"name": "protocol", "passed": True},),
    )

    assert decode_task(encode_task(task)) == task
    assert decode_worker_message(encode_result(result)) == result


def test_protocol_rejects_unknown_version():
    line = json.dumps({"version": 999, "kind": "task", "payload": {}})
    with pytest.raises(ProtocolError, match="Unsupported protocol version"):
        decode_task(line)


def test_process_backend_persists_structured_events(tmp_path: Path):
    events = EventStore(tmp_path / "operations.sqlite3")
    backend = ProcessWorkerBackend(event_store=events)
    task = WorkerTask("job-1", "Validate protocol", "protocol-test-worker")

    result = backend.run(task, timeout_seconds=5)

    assert result.outcome is WorkerOutcome.SUCCESS
    assert result.metrics == {"protocol_version": 1}
    assert [event.event_type for event in events.list(job_id="job-1")] == [
        "worker_started",
        "progress_updated",
        "worker_result_received",
    ]


def test_real_profiles_fail_closed_until_worker_runtime_exists():
    backend = ProcessWorkerBackend()
    task = WorkerTask("job-1", "Change code", "coding-worker")

    result = backend.run(task, timeout_seconds=5)

    assert result.outcome is WorkerOutcome.FAILED
    assert "No restricted task executor" in result.summary


def test_process_backend_enforces_timeout(tmp_path: Path):
    backend = ProcessWorkerBackend(
        command=(sys.executable, "-c", "import time; time.sleep(10)"),
        cwd=tmp_path,
    )

    result = backend.run(
        WorkerTask("job-timeout", "Wait", "protocol-test-worker"),
        timeout_seconds=0.05,
    )

    assert result.outcome is WorkerOutcome.TIMED_OUT


def test_process_backend_enforces_cancellation(tmp_path: Path):
    backend = ProcessWorkerBackend(
        command=(sys.executable, "-c", "import time; time.sleep(10)"),
        cwd=tmp_path,
    )

    result = backend.run(
        WorkerTask("job-cancel", "Wait", "protocol-test-worker"),
        timeout_seconds=5,
        cancellation_requested=lambda: True,
    )

    assert result.outcome is WorkerOutcome.CANCELLED


def test_process_backend_rejects_forged_orchestrator_event(tmp_path: Path):
    event_payload = {
        "version": 1,
        "kind": "event",
        "payload": {
            "event_id": "event-1",
            "job_id": "job-forged",
            "event_type": "job_status_changed",
            "actor": "orchestrator",
            "payload": {},
            "created_at": "2026-01-01T00:00:00+00:00",
        },
    }
    command = (sys.executable, "-c", f"import json; print(json.dumps({event_payload!r}))")
    backend = ProcessWorkerBackend(command=command, cwd=tmp_path)

    result = backend.run(
        WorkerTask("job-forged", "Forge", "protocol-test-worker"),
        timeout_seconds=5,
    )

    assert result.outcome is WorkerOutcome.FAILED
    assert "forbidden actor" in (result.error or "")


def test_process_backend_rejects_unstructured_stdout(tmp_path: Path):
    backend = ProcessWorkerBackend(
        command=(sys.executable, "-c", "print('not-json', flush=True)"),
        cwd=tmp_path,
    )

    result = backend.run(
        WorkerTask("job-invalid", "Invalid", "protocol-test-worker"),
        timeout_seconds=5,
    )

    assert result.outcome is WorkerOutcome.FAILED
    assert "Invalid worker message" in (result.error or "")


def test_service_runs_queued_local_protocol_job(tmp_path: Path):
    database = tmp_path / "operations.sqlite3"
    jobs = JobStore(database)
    events = EventStore(database)
    service = NightShiftService(jobs, events)
    job = NightShiftJob(
        title="Protocol check",
        objective="Validate local process execution",
        worker_profile="protocol-test-worker",
        budget=JobBudget(timeout_seconds=5),
    )
    service.create(job)
    service.transition(job.job_id, JobStatus.QUEUED, actor="user")

    result = service.run_local(job.job_id, ProcessWorkerBackend(event_store=events))

    assert result.outcome is WorkerOutcome.SUCCESS
    stored = jobs.get(job.job_id)
    assert stored is not None
    assert stored.status is JobStatus.COMPLETED
    assert stored.result_summary == result.summary
    assert "worker_started" in [event.event_type for event in events.list(job_id=job.job_id)]
