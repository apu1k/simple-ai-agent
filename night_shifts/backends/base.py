"""Backend-independent worker execution contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable

from night_shifts.models import NightShiftEvent
from night_shifts.protocol import WorkerResult, WorkerTask


class WorkerBackend(ABC):
    """Execute one task in an isolated worker environment."""

    @abstractmethod
    def run(
        self,
        task: WorkerTask,
        *,
        timeout_seconds: float,
        cancellation_requested: Callable[[], bool] | None = None,
        on_event: Callable[[NightShiftEvent], None] | None = None,
    ) -> WorkerResult:
        """Run a task until a result, cancellation, failure, or timeout."""
