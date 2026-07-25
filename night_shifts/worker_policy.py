"""Fail-closed command policy for restricted night-shift workers.

This module decides which structured argv vectors a worker may request. It does
not invoke a shell and is only one layer of enforcement: the guest OS must also
confine the process, filesystem, network, resources, and lifetime.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Sequence


class WorkerPolicyError(ValueError):
    """Raised when a worker requests a command outside its profile policy."""


@dataclass(frozen=True)
class ApprovedCommand:
    """A normalized command plus host-enforced execution limits."""

    argv: tuple[str, ...]
    timeout_seconds: int
    max_output_bytes: int


_PROFILE_COMMANDS: dict[str, frozenset[str]] = {
    "coding-worker": frozenset({"git", "pytest", "ruff", "mypy", "python"}),
    "read-only-worker": frozenset(),
    "review-worker": frozenset({"git", "pytest", "ruff", "mypy", "python"}),
}

_GIT_OPTIONS: dict[str, frozenset[str]] = {
    "status": frozenset({"--short", "--porcelain", "--branch"}),
    "diff": frozenset({"--check", "--stat", "--name-only", "--cached", "--no-ext-diff"}),
    "log": frozenset({"--oneline", "--decorate", "--no-decorate", "--stat"}),
    "show": frozenset({"--stat", "--name-only", "--oneline", "--no-ext-diff"}),
    "rev-parse": frozenset({"HEAD", "--show-toplevel"}),
}
_TEST_OPTIONS = frozenset({"-q", "-x", "--quiet", "--disable-warnings"})
_RUFF_OPTIONS = frozenset({"--quiet", "--no-cache"})
_MYPY_OPTIONS = frozenset({"--no-incremental", "--pretty"})
_REVISION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/~-]{0,199}")
_MAX_ARGUMENTS = 128
_MAX_ARGUMENT_BYTES = 16 * 1024


def approve_worker_command(
    profile: str,
    argv: Sequence[str],
    *,
    timeout_seconds: int = 300,
    max_output_bytes: int = 1024 * 1024,
) -> ApprovedCommand:
    """Validate one argv vector against a worker profile's narrow allowlist."""

    allowed = _PROFILE_COMMANDS.get(profile)
    if allowed is None:
        raise WorkerPolicyError(f"unknown worker profile: {profile!r}")
    if not argv or not all(isinstance(item, str) and item for item in argv):
        raise WorkerPolicyError("command argv must contain non-empty strings")
    if len(argv) > _MAX_ARGUMENTS or sum(len(item.encode("utf-8")) for item in argv) > _MAX_ARGUMENT_BYTES:
        raise WorkerPolicyError("command argv exceeds the policy limit")
    if timeout_seconds <= 0 or timeout_seconds > 1800:
        raise WorkerPolicyError("command timeout must be between 1 and 1800 seconds")
    if max_output_bytes <= 0 or max_output_bytes > 4 * 1024 * 1024:
        raise WorkerPolicyError("command output limit must be between 1 byte and 4 MiB")

    executable = argv[0]
    if executable not in allowed:
        raise WorkerPolicyError(f"{executable!r} is not allowed for {profile}")
    if executable == "git":
        _validate_git(argv)
    elif executable == "pytest":
        _validate_targets(argv[1:], _TEST_OPTIONS)
    elif executable == "ruff":
        if len(argv) < 2 or argv[1] != "check":
            raise WorkerPolicyError("ruff is restricted to the 'check' subcommand")
        _validate_targets(argv[2:], _RUFF_OPTIONS)
    elif executable == "mypy":
        _validate_targets(argv[1:], _MYPY_OPTIONS)
    elif executable == "python":
        if len(argv) < 3 or tuple(argv[1:3]) != ("-m", "compileall"):
            raise WorkerPolicyError("python is restricted to '-m compileall'")
        _validate_targets(argv[3:], frozenset({"-q", "-f"}))

    return ApprovedCommand(tuple(argv), timeout_seconds, max_output_bytes)


def _validate_git(argv: Sequence[str]) -> None:
    if len(argv) < 2 or argv[1] not in _GIT_OPTIONS:
        raise WorkerPolicyError("git subcommand is not allowed")
    subcommand = argv[1]
    arguments = list(argv[2:])
    if subcommand == "rev-parse":
        if not arguments or any(item not in _GIT_OPTIONS[subcommand] for item in arguments):
            raise WorkerPolicyError("git rev-parse arguments are not allowed")
        return

    paths = False
    revision_seen = False
    for argument in arguments:
        if argument == "--":
            paths = True
        elif paths:
            _validate_relative_target(argument)
        elif argument in _GIT_OPTIONS[subcommand]:
            continue
        elif subcommand in {"log", "show"} and not revision_seen and _REVISION.fullmatch(argument):
            revision_seen = True
        else:
            raise WorkerPolicyError(f"git {subcommand} argument is not allowed: {argument!r}")


def _validate_targets(arguments: Sequence[str], options: frozenset[str]) -> None:
    for argument in arguments:
        if argument in options:
            continue
        if argument.startswith("-"):
            raise WorkerPolicyError(f"command option is not allowed: {argument!r}")
        _validate_relative_target(argument.split("::", 1)[0])


def _validate_relative_target(value: str) -> None:
    if not value or "\x00" in value or "\\" in value:
        raise WorkerPolicyError("command target must be a non-empty POSIX relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise WorkerPolicyError(f"command target escapes the workspace: {value!r}")
