"""Application service that owns job mutation and lifecycle events."""

from __future__ import annotations

from dataclasses import replace

from night_shifts.backends.base import WorkerBackend
from night_shifts.models import JobStatus, NightShiftEvent, NightShiftJob, utc_now
from night_shifts.protocol import WorkerOutcome, WorkerResult, WorkerTask
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
        result_summary: str | None = None,
    ) -> NightShiftJob:
        job = self._require(job_id)
        validate_transition(job.status, target)
        previous = job.status
        updated = replace(
            job,
            status=target,
            updated_at=utc_now(),
            result_summary=result_summary if result_summary is not None else job.result_summary,
        )
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

    def run_local(self, job_id: str, backend: WorkerBackend) -> WorkerResult:
        """Execute one queued job through a backend and persist its final state."""
        job = self._require(job_id)
        if job.cancellation_requested:
            self.transition(job_id, JobStatus.CANCELLED, actor="orchestrator")
            return WorkerResult(
                job_id=job_id,
                outcome=WorkerOutcome.CANCELLED,
                summary="Job was cancelled before worker startup.",
            )

        self.transition(job_id, JobStatus.PROVISIONING, actor="orchestrator")
        running = self.transition(job_id, JobStatus.RUNNING, actor="orchestrator")
        try:
            result = backend.run(
                WorkerTask.from_job(running),
                timeout_seconds=running.budget.timeout_seconds,
                cancellation_requested=lambda: self._require(job_id).cancellation_requested,
            )
        except Exception as exc:
            result = WorkerResult(
                job_id=job_id,
                outcome=WorkerOutcome.FAILED,
                summary="Worker backend raised an exception.",
                error=str(exc),
            )

        if result.job_id != job_id:
            result = WorkerResult(
                job_id=job_id,
                outcome=WorkerOutcome.FAILED,
                summary="Worker backend returned a result for a different job.",
                error=f"Expected job {job_id!r}, received {result.job_id!r}",
            )

        target = {
            WorkerOutcome.SUCCESS: JobStatus.COMPLETED,
            WorkerOutcome.CANCELLED: JobStatus.CANCELLED,
            WorkerOutcome.TIMED_OUT: JobStatus.FAILED,
            WorkerOutcome.FAILED: JobStatus.FAILED,
        }[result.outcome]
        self.transition(
            job_id,
            target,
            actor="orchestrator",
            payload={"outcome": result.outcome.value, "error": result.error},
            result_summary=result.summary,
        )
        return result

    def _require(self, job_id: str) -> NightShiftJob:
        job = self.jobs.get(job_id)
        if job is None:
            raise KeyError(f"Unknown night-shift job: {job_id}")
        return job
