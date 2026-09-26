"""Host worker-only per-request SDK limits; head-agent clients remain unchanged."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class WorkerRequestLimits:
    max_output_tokens: int
    deadline_monotonic: float

    def __post_init__(self) -> None:
        if type(self.max_output_tokens) is not int or not 1 <= self.max_output_tokens <= 16_384:
            raise ValueError("worker maximum generation must be a bounded integer")
        if (type(self.deadline_monotonic) not in (float, int)
                or not math.isfinite(self.deadline_monotonic)):
            raise ValueError("worker deadline must be finite")

    def timeout(self, requested: float) -> float:
        remaining = self.deadline_monotonic - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("worker inference deadline expired before SDK dispatch")
        return min(requested, remaining)
