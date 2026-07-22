from datetime import timedelta
from pathlib import Path

import pytest

from core.agent import Agent
from core.tool_registry import ToolRegistry, ToolSpec
from night_shifts.models import (
    ArtifactRecord,
    JobStatus,
    NightShiftEvent,
    NightShiftJob,
    ToolCallRecord,
    ToolCallStatus,
    utc_now,
)
from night_shifts.service import NightShiftService
from night_shifts.state_machine import InvalidJobTransition
from night_shifts.storage import ArtifactStore, EventStore, JobStore, ToolCallStore
from runtime.chat_store import ChatStore
from runtime.state import AgentState, ModelConfig


def stores(tmp_path: Path):
    database = tmp_path / "operations.sqlite3"
    return JobStore(database), EventStore(database), ToolCallStore(database), ArtifactStore(database)


def test_job_round_trip_transition_and_events(tmp_path: Path):
    jobs, events, _, _ = stores(tmp_path)
    service = NightShiftService(jobs, events)
    job = NightShiftJob(
        title="Implement cache",
        objective="Add bounded caching",
        worker_profile="coding-worker",
        repository_id="main-project",
        starting_revision="abc123",
        acceptance_criteria=("Tests pass", "Cache is bounded"),
    )

    service.create(job)
    queued = service.transition(job.job_id, JobStatus.QUEUED, actor="user")

    assert queued.status is JobStatus.QUEUED
    restored = jobs.get(job.job_id)
    assert restored == queued
    assert [event.event_type for event in events.list(job_id=job.job_id)] == [
        "job_created",
        "job_status_changed",
    ]


def test_invalid_transition_is_rejected_without_mutation(tmp_path: Path):
    jobs, events, _, _ = stores(tmp_path)
    service = NightShiftService(jobs, events)
    job = service.create(NightShiftJob("Title", "Objective", "coding-worker"))

    with pytest.raises(InvalidJobTransition):
        service.transition(job.job_id, JobStatus.RUNNING, actor="head")

    assert jobs.get(job.job_id).status is JobStatus.DRAFT
    assert len(events.list(job_id=job.job_id)) == 1


def test_cancellation_request_is_durable_and_audited(tmp_path: Path):
    jobs, events, _, _ = stores(tmp_path)
    service = NightShiftService(jobs, events)
    job = service.create(NightShiftJob("Title", "Objective", "coding-worker"))

    updated = service.request_cancellation(job.job_id, actor="user")

    assert updated.cancellation_requested is True
    assert jobs.get(job.job_id).cancellation_requested is True
    assert events.list(job_id=job.job_id)[-1].event_type == "cancellation_requested"


def test_tool_calls_are_redacted_truncated_completed_and_purged(tmp_path: Path):
    _, _, calls, _ = stores(tmp_path)
    now = utc_now()
    record = ToolCallRecord(
        tool_name="example",
        arguments={"path": ".", "token": "do-not-store", "nested": {"password": "hidden"}},
        agent_profile="head",
        session_id="chat-1",
        started_at=now,
        expires_at=now + timedelta(days=7),
    )

    calls.start(record)
    calls.complete(
        record.call_id,
        status=ToolCallStatus.SUCCESS,
        result="x" * 5000,
        completed_at=now + timedelta(milliseconds=25),
    )
    restored = calls.list_recent()[0]

    assert restored.arguments["token"] == "[REDACTED]"
    assert restored.arguments["nested"]["password"] == "[REDACTED]"
    assert restored.status is ToolCallStatus.SUCCESS
    assert restored.duration_ms == 25
    assert restored.result_preview.endswith("…[truncated]")
    assert calls.purge_expired(now=now + timedelta(days=8)) == 1
    assert calls.list_recent() == []


def test_agent_execution_writes_tool_audit_record(tmp_path: Path):
    _, _, calls, _ = stores(tmp_path)
    state = AgentState(
        cwd=tmp_path,
        model_config=ModelConfig(
            provider_key="test",
            provider_label="Test",
            model="fake",
            api_key=None,
            base_url=None,
            api_type="chat_completions",
        ),
        chat_store=ChatStore(tmp_path / "chats"),
        chat_session_id="chat-1",
        tool_call_store=calls,
    )
    registry = ToolRegistry()
    registry.register(ToolSpec("echo", lambda text: text, "Echo text", {"text": "Text"}))

    class FakeLLM:
        supports_native_tools = False
        api_type = "chat_completions"

    agent = Agent(
        "system",
        state,
        FakeLLM(),
        tool_registry=registry,
        agent_profile="coding-worker",
        job_id="job-1",
    )

    status, observation, error = agent._execute_one_tool_call("echo", {"text": "hello"})
    record = calls.list_recent(job_id="job-1")[0]

    assert (status, observation, error) == ("success", "hello", None)
    assert record.tool_name == "echo"
    assert record.agent_profile == "coding-worker"
    assert record.session_id == "chat-1"
    assert record.status is ToolCallStatus.SUCCESS


def test_events_and_artifact_metadata_round_trip(tmp_path: Path):
    _, events, _, artifacts = stores(tmp_path)
    event = NightShiftEvent(event_type="worker_message", actor="worker", payload={"message": "hi"})
    artifact = ArtifactRecord(job_id="job-1", kind="diff", path="artifacts/job-1/change.patch")

    events.append(event)
    artifacts.add(artifact)

    assert events.list()[0] == event
    assert artifacts.list("job-1") == [artifact]
