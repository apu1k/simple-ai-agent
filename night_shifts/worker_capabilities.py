"""Fail-closed guest tool capabilities for each restricted worker profile.

These names describe tools implemented inside the disposable guest. They are
intentionally separate from the head runtime's host-side tool registry: sharing
similar intent does not make a host tool safe to pass into a worker VM.
"""

from __future__ import annotations

RUN_COMMAND_TOOL = "run_command"
WRITE_ARTIFACT_TOOL = "write_artifact"

SUPPORTED_WORKER_PROFILES = frozenset(
    {"coding-worker", "read-only-worker", "review-worker"}
)

_PROFILE_TOOLS: dict[str, tuple[str, ...]] = {
    "coding-worker": (RUN_COMMAND_TOOL, WRITE_ARTIFACT_TOOL),
    "read-only-worker": (WRITE_ARTIFACT_TOOL,),
    "review-worker": (RUN_COMMAND_TOOL, WRITE_ARTIFACT_TOOL),
}


def worker_tool_names(profile: str) -> tuple[str, ...]:
    """Return the immutable guest tool allowlist for a worker profile."""

    try:
        return _PROFILE_TOOLS[profile]
    except KeyError as exc:
        choices = ", ".join(sorted(SUPPORTED_WORKER_PROFILES))
        raise ValueError(
            f"Unknown worker profile {profile!r}. Expected one of: {choices}"
        ) from exc
