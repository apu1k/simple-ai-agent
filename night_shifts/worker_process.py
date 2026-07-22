"""Minimal phase-2 worker process for validating the JSONL protocol.

This is deliberately not the coding worker runtime. Until the restricted worker
is implemented, only the ``protocol-test-worker`` profile succeeds.
"""

from __future__ import annotations

import sys

from night_shifts.models import NightShiftEvent
from night_shifts.protocol import (
    ProtocolError,
    WorkerOutcome,
    WorkerResult,
    decode_task,
    encode_event,
    encode_result,
)

_PROTOCOL_TEST_PROFILE = "protocol-test-worker"


def _write(line: str) -> None:
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def main() -> int:
    line = sys.stdin.readline()
    if not line:
        print("Worker received no task", file=sys.stderr)
        return 2
    try:
        task = decode_task(line)
    except ProtocolError as exc:
        print(f"Invalid task: {exc}", file=sys.stderr)
        return 2

    _write(encode_event(NightShiftEvent(
        job_id=task.job_id,
        event_type="worker_started",
        actor="worker",
        payload={"profile": task.worker_profile},
    )))

    if task.worker_profile != _PROTOCOL_TEST_PROFILE:
        _write(encode_result(WorkerResult(
            job_id=task.job_id,
            outcome=WorkerOutcome.FAILED,
            summary="No restricted task executor is installed yet.",
            error=(
                f"Unsupported phase-2 worker profile: {task.worker_profile}. "
                "Implement the restricted worker runtime before executing real tasks."
            ),
        )))
        return 1

    _write(encode_event(NightShiftEvent(
        job_id=task.job_id,
        event_type="progress_updated",
        actor="worker",
        payload={"message": "Local process protocol validated", "progress": 1.0},
    )))
    _write(encode_result(WorkerResult(
        job_id=task.job_id,
        outcome=WorkerOutcome.SUCCESS,
        summary="Local worker process and structured protocol completed successfully.",
        metrics={"protocol_version": 1},
    )))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
