"""Application service that owns job mutation and lifecycle events."""

from __future__ import annotations

from dataclasses import replace

from night_shifts.models import JobStatus, NightShiftEvent, NightShiftJob, utc_now
from night_shifts.state_machine import validate_transition
from night_shifts.storage import EventStore, JobStore


class NightShiftService:
    """Coordinate durable job state with an append-only event trail."""

    def __init__(self, jobs: JobStore, events: EventStore):
        self.jobs = jobs
        self.events = events

    def create(self, job: NightShiftJob, *, actor: str = "head") -> NightShiftJob:
        self.jobs.create(job)
        self.events.append(NightShiftEvent(
            job_id=job.job_id,
            event_type="job_created",
            actor=actor,
            payload={"status": job.status.value, "worker_profile": job.worker_profile},
        ))
        return job

    def transition(
        self,
        job_id: str,
        target: JobStatus,
        *,
        actor: str,
        payload: dict | None = None,
    ) -> NightShiftJob:
        job = self._require(job_id)
        validate_transition(job.status, target)
        previous = job.status
        updated = replace(job, status=target, updated_at=utc_now())
        self.jobs.update(updated)
        self.events.append(NightShiftEvent(
            job_id=job_id,
            event_type="job_status_changed",
            actor=actor,
            payload={"from": previous.value, "to": target.value, **(payload or {})},
        ))
        return updated

    def request_cancellation(self, job_id: str, *, actor: str) -> NightShiftJob:
        job = self._require(job_id)
        if job.status in {JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.REJECTED, JobStatus.MERGED}:
            raise ValueError(f"Cannot request cancellation for terminal job {job_id}")
        updated = replace(job, cancellation_requested=True, updated_at=utc_now())
        self.jobs.update(updated)
        self.events.append(NightShiftEvent(
            job_id=job_id,
            event_type="cancellation_requested",
            actor=actor,
            payload={"status": job.status.value},
        ))
        return updated

    def _require(self, job_id: str) -> NightShiftJob:
        job = self.jobs.get(job_id)
        if job is None:
            raise KeyError(f"Unknown night-shift job: {job_id}")
        return job
