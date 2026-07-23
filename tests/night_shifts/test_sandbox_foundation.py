import json
import sqlite3
from pathlib import Path

import pytest

from night_shifts.models import (
    AgentPlan,
    NightShiftJob,
    SandboxRecord,
    SandboxSpec,
    SandboxStatus,
)
from night_shifts.protocol import WorkerTask, decode_task, encode_task
from night_shifts.storage import JobStore, SandboxStore


def test_agent_plan_defaults_to_flex_and_round_trips(tmp_path: Path):
    database = tmp_path / "operations.sqlite3"
    jobs = JobStore(database)
    default_job = NightShiftJob("Default", "Work", "coding-worker")
    normal_job = NightShiftJob(
        "Fast", "Work quickly", "coding-worker", plan=AgentPlan.NORMAL
    )

    jobs.create(default_job)
    jobs.create(normal_job)

    assert jobs.get(default_job.job_id).plan is AgentPlan.FLEX
    assert jobs.get(normal_job.job_id).plan is AgentPlan.NORMAL
    assert decode_task(encode_task(WorkerTask.from_job(normal_job))).plan is AgentPlan.NORMAL


def test_protocol_treats_missing_plan_as_flex_for_compatibility():
    message = {
        "version": 1,
        "kind": "task",
        "payload": {
            "job_id": "job-1",
            "objective": "Work",
            "worker_profile": "coding-worker",
        },
    }

    assert decode_task(json.dumps(message)).plan is AgentPlan.FLEX


def test_job_store_migrates_existing_database_with_flex_default(tmp_path: Path):
    database = tmp_path / "operations.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """CREATE TABLE jobs (
            job_id TEXT PRIMARY KEY, title TEXT NOT NULL, objective TEXT NOT NULL,
            worker_profile TEXT NOT NULL, repository_id TEXT, starting_revision TEXT,
            acceptance_criteria_json TEXT NOT NULL, budget_json TEXT NOT NULL,
            status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            cancellation_requested INTEGER NOT NULL, result_summary TEXT
            )"""
        )

    JobStore(database)

    with sqlite3.connect(database) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(jobs)")}
    assert "plan" in columns


def test_sandbox_record_and_policy_round_trip(tmp_path: Path):
    store = SandboxStore(tmp_path / "operations.sqlite3")
    sandbox = SandboxRecord(
        job_id="job-1",
        backend="hyperv",
        external_id="night-shift-job-1",
        status=SandboxStatus.RUNNING,
        spec=SandboxSpec(cpu_count=4, memory_mb=8192, disk_gb=40, network_enabled=False),
    )

    store.create(sandbox)

    assert store.get(sandbox.sandbox_id) == sandbox
    assert store.list(job_id="job-1") == [sandbox]
    assert store.list(job_id="other") == []


@pytest.mark.parametrize(
    "kwargs",
    [
        {"cpu_count": 0},
        {"memory_mb": 0},
        {"disk_gb": 0},
    ],
)
def test_sandbox_policy_rejects_non_positive_limits(kwargs: dict[str, int]):
    with pytest.raises(ValueError, match="must be positive"):
        SandboxSpec(**kwargs)
