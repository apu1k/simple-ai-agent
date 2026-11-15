"""Transport-neutral runtime events; importing a client never loads providers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


class EventHistoryExpired(ValueError):
    """Fetch a snapshot rather than replaying this cursor."""


@dataclass(frozen=True)
class RuntimeEvent:
    sequence: int
    kind: str
    text: str = ""
    role: str = ""
    run_id: str | None = None
    messages: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class RunInfo:
    run_id: str
    user_text: str
    status: Literal["running", "completed", "failed"] = "running"
    reply: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class RuntimeSnapshot:
    sequence: int
    messages: tuple[tuple[str, str], ...]
    run: RunInfo | None
    progress: str
    closed: bool

    @property
    def processing(self) -> bool:
        return self.run is not None and self.run.status == "running"
