"""Stable contracts shared by night-shift modules."""

from night_shifts.contracts.channel import WorkerChannel
from night_shifts.contracts.sandbox import SandboxProvider

__all__ = ["SandboxProvider", "WorkerChannel"]
