"""Restricted subprocess execution for the Linux guest worker runtime."""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from night_shifts.worker_policy import ApprovedCommand, approve_worker_command


class WorkerExecutionError(RuntimeError):
    """Raised when the guest cannot safely start or control an approved command."""


@dataclass(frozen=True)
class CommandResult:
    argv: tuple[str, ...]
    return_code: int
    output: str
    duration_seconds: float
    timed_out: bool = False
    output_truncated: bool = False


_SAFE_ENVIRONMENT = {
    "HOME": "/nonexistent",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "PATH": "/usr/local/bin:/usr/bin:/bin",
    "PYTHONNOUSERSITE": "1",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_ASKPASS": "/bin/false",
}


class RestrictedCommandRunner:
    """Execute policy-approved argv in one fixed repository workspace.

    The reviewed guest image must additionally confine this process with its
    service account, mount namespace, cgroup, seccomp policy, and network policy.
    """

    def __init__(
        self,
        workspace: Path,
        profile: str,
        *,
        environment: Mapping[str, str] | None = None,
        termination_grace_seconds: float = 0.5,
    ) -> None:
        resolved = workspace.resolve()
        if not resolved.is_dir():
            raise WorkerExecutionError("worker workspace is unavailable")
        if termination_grace_seconds <= 0 or termination_grace_seconds > 5:
            raise ValueError("termination grace period must be between 0 and 5 seconds")
        self._workspace = resolved
        self._profile = profile
        self._environment = dict(_SAFE_ENVIRONMENT if environment is None else environment)
        self._termination_grace_seconds = termination_grace_seconds

    def run(
        self,
        argv: Sequence[str],
        *,
        timeout_seconds: int = 300,
        max_output_bytes: int = 1024 * 1024,
    ) -> CommandResult:
        approved = approve_worker_command(
            self._profile,
            argv,
            timeout_seconds=timeout_seconds,
            max_output_bytes=max_output_bytes,
        )
        started = time.monotonic()
        try:
            process = subprocess.Popen(
                approved.argv,
                cwd=self._workspace,
                env=self._environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                shell=False,
                close_fds=True,
                start_new_session=True,
            )
        except OSError as exc:
            raise WorkerExecutionError(f"approved command could not start: {exc}") from exc

        output = bytearray()
        output_exceeded = threading.Event()
        reader = threading.Thread(
            target=_read_bounded_output,
            args=(process, approved, output, output_exceeded),
            daemon=True,
        )
        reader.start()
        deadline = started + approved.timeout_seconds
        timed_out = False
        while process.poll() is None:
            if output_exceeded.is_set():
                self._terminate(process)
                break
            if time.monotonic() >= deadline:
                timed_out = True
                self._terminate(process)
                break
            time.sleep(0.01)

        try:
            process.wait(timeout=self._termination_grace_seconds)
        except subprocess.TimeoutExpired:
            self._kill(process)
            process.wait(timeout=self._termination_grace_seconds)
        if process.stdout is not None:
            process.stdout.close()
        reader.join(timeout=self._termination_grace_seconds)
        duration = time.monotonic() - started
        return CommandResult(
            argv=approved.argv,
            return_code=process.returncode,
            output=bytes(output).decode("utf-8", errors="replace"),
            duration_seconds=duration,
            timed_out=timed_out,
            output_truncated=output_exceeded.is_set(),
        )

    def _terminate(self, process: subprocess.Popen[bytes]) -> None:
        try:
            kill_process_group = getattr(os, "killpg", None)
            if os.name == "posix" and kill_process_group is not None:
                kill_process_group(process.pid, signal.SIGTERM)
            else:
                process.terminate()
        except ProcessLookupError:
            return

    @staticmethod
    def _kill(process: subprocess.Popen[bytes]) -> None:
        try:
            kill_process_group = getattr(os, "killpg", None)
            if os.name == "posix" and kill_process_group is not None:
                kill_process_group(process.pid, getattr(signal, "SIGKILL", 9))
            else:
                process.kill()
        except ProcessLookupError:
            return


def _read_bounded_output(
    process: subprocess.Popen[bytes],
    approved: ApprovedCommand,
    output: bytearray,
    output_exceeded: threading.Event,
) -> None:
    if process.stdout is None:
        return
    while True:
        chunk = process.stdout.read(64 * 1024)
        if not chunk:
            return
        remaining = approved.max_output_bytes - len(output)
        if remaining > 0:
            output.extend(chunk[:remaining])
        if len(chunk) > remaining:
            output_exceeded.set()
            return
