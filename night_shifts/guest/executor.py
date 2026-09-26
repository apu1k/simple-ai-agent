"""Compatibility import for the historical guest-mediated worker loop.

The current host-managed worker should import from night_shifts.executor. The
legacy guest runtime remains available and uses the same injected boundaries.
"""

from night_shifts.executor import EmitEvent, MediatedModelExecutor, ModelExecutorLimits

__all__ = ["EmitEvent", "MediatedModelExecutor", "ModelExecutorLimits"]
