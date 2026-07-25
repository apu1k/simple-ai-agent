#!/usr/bin/env python3
"""Minimal, standard-library-only serial worker for Phase 3 host validation.

This program deliberately recognizes only fixed protocol-test objectives. It is
not a general worker and must never execute task text or repository code.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, BinaryIO

PROTOCOL_VERSION = 1
MAX_FRAME_BYTES = 1024 * 1024
SUCCESS_OBJECTIVE = "phase3-protocol-success"
_SLEEP_OBJECTIVE = re.compile(r"^phase3-protocol-sleep:([0-9]+(?:\.[0-9]+)?)$")


def _write_frame(channel: BinaryIO, kind: str, payload: dict[str, Any]) -> None:
    frame = json.dumps(
        {"version": PROTOCOL_VERSION, "kind": kind, "payload": payload},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    channel.write(frame + b"\n")
    channel.flush()


def _read_frame(channel: BinaryIO) -> dict[str, Any]:
    frame = channel.readline(MAX_FRAME_BYTES + 2)
    if not frame:
        raise ValueError("controller closed the serial channel before sending a task")
    if len(frame) > MAX_FRAME_BYTES or not frame.endswith(b"\n"):
        raise ValueError("task frame is unterminated or exceeds the size limit")
    try:
        envelope = json.loads(frame.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("task frame is not valid UTF-8 JSON") from exc
    if not isinstance(envelope, dict):
        raise ValueError("task envelope must be an object")
    if envelope.get("version") != PROTOCOL_VERSION or envelope.get("kind") != "task":
        raise ValueError("unsupported task protocol envelope")
    payload = envelope.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("task payload must be an object")
    for field in ("job_id", "objective", "worker_profile"):
        if not isinstance(payload.get(field), str) or not payload[field]:
            raise ValueError(f"task {field} must be a non-empty string")
    return payload


def _event(job_id: str, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_id": uuid.uuid4().hex,
        "job_id": job_id,
        "event_type": event_type,
        "actor": "worker",
        "payload": payload,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def run_once(channel: BinaryIO, *, sleep: Callable[[float], None] = time.sleep) -> None:
    """Read one task and emit bounded events plus exactly one result."""

    task = _read_frame(channel)
    job_id = task["job_id"]
    objective = task["objective"]
    _write_frame(channel, "event", _event(job_id, "protocol_test_started", {}))

    if objective == SUCCESS_OBJECTIVE:
        _write_frame(
            channel,
            "event",
            _event(job_id, "protocol_test_echo", {"objective": objective}),
        )
        outcome = "success"
        summary = "Phase 3 guest serial protocol validation succeeded."
        error = None
    else:
        match = _SLEEP_OBJECTIVE.fullmatch(objective)
        if match is None:
            outcome = "failed"
            summary = "The Phase 3 guest rejected an unsupported test objective."
            error = "Only fixed Phase 3 protocol-test objectives are accepted"
        else:
            delay = min(float(match.group(1)), 86_400.0)
            _write_frame(
                channel,
                "event",
                _event(job_id, "protocol_test_sleeping", {"seconds": delay}),
            )
            sleep(delay)
            outcome = "success"
            summary = "Phase 3 guest completed its controlled delay."
            error = None

    _write_frame(
        channel,
        "result",
        {
            "job_id": job_id,
            "outcome": outcome,
            "summary": summary,
            "error": error,
            "checks": [],
            "artifacts": [],
            "metrics": {},
        },
    )


def _open_serial(path: str) -> BinaryIO:
    import fcntl
    import termios
    import tty

    descriptor = os.open(path, os.O_RDWR | os.O_NOCTTY)  # type: ignore[attr-defined]
    try:
        fcntl.flock(  # type: ignore[attr-defined]
            descriptor,
            fcntl.LOCK_EX | fcntl.LOCK_NB,  # type: ignore[attr-defined]
        )
        tty.setraw(  # type: ignore[attr-defined]
            descriptor,
            when=termios.TCSANOW,  # type: ignore[attr-defined]
        )
        return os.fdopen(descriptor, "r+b", buffering=0)
    except Exception:
        os.close(descriptor)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial-device", default="/dev/ttyS0")
    arguments = parser.parse_args(argv)
    try:
        with _open_serial(arguments.serial_device) as channel:
            run_once(channel)
            while channel.read(4096):
                pass
    except Exception as exc:
        print(f"night-shift protocol bootstrap failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
