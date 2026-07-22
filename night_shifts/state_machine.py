"""Validated lifecycle transitions for night-shift jobs."""

from night_shifts.models import JobStatus


class InvalidJobTransition(ValueError):
    """Raised when a caller requests an invalid lifecycle transition."""


_ALLOWED: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.DRAFT: frozenset({JobStatus.QUEUED, JobStatus.CANCELLED}),
    JobStatus.QUEUED: frozenset({JobStatus.PROVISIONING, JobStatus.CANCELLED, JobStatus.FAILED}),
    JobStatus.PROVISIONING: frozenset({JobStatus.RUNNING, JobStatus.CANCELLED, JobStatus.FAILED}),
    JobStatus.RUNNING: frozenset({
        JobStatus.WAITING_FOR_INPUT,
        JobStatus.PAUSED,
        JobStatus.COMPLETED,
        JobStatus.CANCELLED,
        JobStatus.FAILED,
    }),
    JobStatus.WAITING_FOR_INPUT: frozenset({JobStatus.RUNNING, JobStatus.CANCELLED, JobStatus.FAILED}),
    JobStatus.PAUSED: frozenset({JobStatus.RUNNING, JobStatus.CANCELLED, JobStatus.FAILED}),
    JobStatus.COMPLETED: frozenset({JobStatus.AWAITING_REVIEW}),
    JobStatus.AWAITING_REVIEW: frozenset({
        JobStatus.REVISION_REQUESTED,
        JobStatus.REJECTED,
        JobStatus.APPROVED,
    }),
    JobStatus.REVISION_REQUESTED: frozenset({JobStatus.QUEUED, JobStatus.CANCELLED}),
    JobStatus.APPROVED: frozenset({JobStatus.PUBLISHED}),
    JobStatus.PUBLISHED: frozenset({JobStatus.MERGED}),
    JobStatus.FAILED: frozenset(),
    JobStatus.CANCELLED: frozenset(),
    JobStatus.REJECTED: frozenset(),
    JobStatus.MERGED: frozenset(),
}


def allowed_transitions(status: JobStatus) -> frozenset[JobStatus]:
    return _ALLOWED[status]


def validate_transition(current: JobStatus, target: JobStatus) -> None:
    if target not in allowed_transitions(current):
        raise InvalidJobTransition(f"Cannot transition night-shift job from {current.value} to {target.value}")
