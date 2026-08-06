#!/usr/bin/env python3
"""Version-1 serial loop for the restricted night-shift guest.

The loop validates one task against a root-owned workspace manifest, exposes
only the restricted command runner to an injected worker executor, emits
bounded structured events, writes exactly one result, and exits on channel
failure. The default executor fails closed until a reviewed model adapter is
configured in the guest image.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Callable, Protocol

from night_shifts.contracts.worker_tool import WorkerToolProvider
from night_shifts.guest.artifacts import ArtifactWriter
from night_shifts.guest.commands import RestrictedCommandRunner
from night_shifts.guest.tools import GuestWorkerTools
from night_shifts.models import NightShiftEvent
from night_shifts.protocol import (
    WorkerOutcome,
    WorkerResult,
    WorkerTask,
    decode_task,
    encode_event,
    encode_result,
)
from night_shifts.worker_capabilities import SUPPORTED_WORKER_PROFILES
from night_shifts.workspaces import WORKSPACE_ARTIFACTS, WORKSPACE_MANIFEST

MAX_FRAME_BYTES = 1024 * 1024
MAX_WORKER_EVENTS = 500


class GuestRuntimeError(RuntimeError):
    """Raised when task or workspace identity validation fails closed."""


@dataclass(frozen=True)
class WorkspaceIdentity:
    job_id: str
    repository_id: str
    starting_revision: str
    revision: str


EmitEvent = Callable[[str, dict[str, Any]], None]


class WorkerExecutor(Protocol):
    """Replaceable model boundary with access only to guest-safe tools."""

    def execute(
        self,
        task: WorkerTask,
        tools: WorkerToolProvider,
        emit_event: EmitEvent,
    ) -> WorkerResult: ...


class UnavailableWorkerExecutor:
    """Fail-closed placeholder used when no reviewed model adapter is installed."""

    def execute(
        self,
        task: WorkerTask,
        tools: WorkerToolProvider,
        emit_event: EmitEvent,
    ) -> WorkerResult:
        del tools
        emit_event("worker_executor_unavailable", {"profile": task.worker_profile})
        return WorkerResult(
            job_id=task.job_id,
            outcome=WorkerOutcome.FAILED,
            summary="The restricted guest has no configured worker executor.",
            error="A reviewed worker model adapter is required",
        )


def run_once(
    channel: BinaryIO,
    *,
    workspace_root: Path,
    executor: WorkerExecutor | None = None,
    require_root_owned_manifest: bool = True,
) -> None:
    """Consume one task and emit bounded events followed by exactly one result."""

    task = _read_task(channel)
    event_count = 0

    def emit(event_type: str, payload: dict[str, Any]) -> None:
        nonlocal event_count
        event_count += 1
        if event_count > MAX_WORKER_EVENTS:
            raise GuestRuntimeError("worker event limit exceeded")
        event = NightShiftEvent(
            job_id=task.job_id,
            event_type=event_type,
            actor="worker",
            payload=payload,
        )
        _write_frame(channel, encode_event(event))

    try:
        workspace, identity = _validate_task_workspace(
            task,
            workspace_root,
            require_root_owned_manifest=require_root_owned_manifest,
        )
        emit(
            "worker_started",
            {
                "profile": task.worker_profile,
                "repository_id": identity.repository_id,
                "revision": identity.revision,
            },
        )
        commands = RestrictedCommandRunner(workspace, task.worker_profile)
        artifacts = ArtifactWriter(workspace_root.resolve() / WORKSPACE_ARTIFACTS)
        tools = GuestWorkerTools(task.worker_profile, commands, artifacts)
        selected_executor = executor or UnavailableWorkerExecutor()
        result = selected_executor.execute(task, tools, emit)
        if result.job_id != task.job_id:
            raise GuestRuntimeError("worker executor returned a mismatched job ID")
    except Exception as exc:
        result = WorkerResult(
            job_id=task.job_id,
            outcome=WorkerOutcome.FAILED,
            summary="The restricted guest failed the task.",
            error=str(exc)[:2000] or exc.__class__.__name__,
        )
    _write_result(channel, task.job_id, result)


def _read_task(channel: BinaryIO) -> WorkerTask:
    frame = channel.readline(MAX_FRAME_BYTES + 2)
    if not frame:
        raise GuestRuntimeError("controller closed the channel before sending a task")
    if len(frame) > MAX_FRAME_BYTES or not frame.endswith(b"\n"):
        raise GuestRuntimeError("task frame is unterminated or exceeds the size limit")
    try:
        text = frame.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GuestRuntimeError("task frame is not valid UTF-8") from exc
    return decode_task(text)


def _write_frame(channel: BinaryIO, frame: str) -> None:
    encoded = frame.encode("utf-8") + b"\n"
    if len(encoded) > MAX_FRAME_BYTES:
        raise GuestRuntimeError("worker frame exceeds the size limit")
    view = memoryview(encoded)
    while view:
        written = channel.write(view)
        if written is None or written <= 0:
            raise GuestRuntimeError("controller closed the channel while writing")
        view = view[written:]
    channel.flush()


def _write_result(channel: BinaryIO, job_id: str, result: WorkerResult) -> None:
    try:
        _write_frame(channel, encode_result(result))
    except GuestRuntimeError as exc:
        if "exceeds the size limit" not in str(exc):
            raise
        fallback = WorkerResult(
            job_id=job_id,
            outcome=WorkerOutcome.FAILED,
            summary="The worker result exceeded the guest output limit.",
            error="worker result frame exceeds the size limit",
        )
        _write_frame(channel, encode_result(fallback))


def _validate_task_workspace(
    task: WorkerTask,
    workspace_root: Path,
    *,
    require_root_owned_manifest: bool,
) -> tuple[Path, WorkspaceIdentity]:
    if task.worker_profile not in SUPPORTED_WORKER_PROFILES:
        raise GuestRuntimeError(f"unsupported worker profile: {task.worker_profile!r}")
    if task.repository_id is None or task.starting_revision is None:
        raise GuestRuntimeError("repository ID and starting revision are required")
    root = workspace_root.resolve()
    manifest_path = root / WORKSPACE_MANIFEST
    workspace = root / "repository"
    identity = _load_identity(
        manifest_path,
        root=root,
        require_root_owner=require_root_owned_manifest,
    )
    if identity.job_id != task.job_id:
        raise GuestRuntimeError("task job ID does not match the workspace manifest")
    if identity.repository_id != task.repository_id:
        raise GuestRuntimeError("task repository does not match the workspace manifest")
    if identity.starting_revision != task.starting_revision:
        raise GuestRuntimeError("task revision does not match the workspace manifest")
    if workspace.is_symlink() or not workspace.is_dir() or workspace.resolve().parent != root:
        raise GuestRuntimeError("repository workspace is unavailable or escapes its root")
    return workspace, identity


def _load_identity(
    path: Path,
    *,
    root: Path,
    require_root_owner: bool,
) -> WorkspaceIdentity:
    try:
        root_status = root.stat()
        manifest_status = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(manifest_status.st_mode):
            raise GuestRuntimeError("workspace manifest must be a regular file")
        if os.name == "posix" and manifest_status.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise GuestRuntimeError("workspace manifest must not be group/world writable")
        if os.name == "posix" and root_status.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise GuestRuntimeError("workspace root must not be group/world writable")
        if require_root_owner and (root_status.st_uid != 0 or manifest_status.st_uid != 0):
            raise GuestRuntimeError("workspace root and manifest must be owned by root")
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GuestRuntimeError("workspace manifest is unavailable or invalid") from exc
    expected_fields = {"job_id", "repository_id", "starting_revision", "revision"}
    if not isinstance(value, dict) or set(value) != expected_fields:
        raise GuestRuntimeError("workspace manifest has an invalid shape")
    if not all(isinstance(value[key], str) and value[key] for key in value):
        raise GuestRuntimeError("workspace manifest fields must be non-empty strings")
    return WorkspaceIdentity(
        value["job_id"],
        value["repository_id"],
        value["starting_revision"],
        value["revision"],
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
        tty.setraw(descriptor, when=termios.TCSANOW)  # type: ignore[attr-defined]
        return os.fdopen(descriptor, "r+b", buffering=0)
    except Exception:
        os.close(descriptor)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial-device", default="/dev/ttyS0")
    parser.add_argument("--workspace-root", default="/workspace")
    arguments = parser.parse_args(argv)
    try:
        with _open_serial(arguments.serial_device) as channel:
            run_once(channel, workspace_root=Path(arguments.workspace_root))
    except Exception as exc:
        print(f"night-shift guest runtime failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
