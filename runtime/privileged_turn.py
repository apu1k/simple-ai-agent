"""Volatile, UI-armed authority for one head-agent turn and one fixed operation.

This gate is not a Windows privilege boundary: the separately protected helper
and UAC enforce that boundary. No model tool can arm this gate.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from threading import Lock
from typing import Callable, Iterator
from uuid import uuid4

ARM_SECONDS = 120
TURN_SECONDS = 1800
_context: ContextVar[str | None] = ContextVar('privileged_turn', default=None)


@dataclass(frozen=True)
class PrivilegedClaim:
    request_id: str
    deadline_unix: float


class PrivilegedTurn:
    """Thread-safe, single-use grant; never serialized or restored on restart."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic,
                 wall_clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._wall_clock = wall_clock
        self._lock = Lock()
        self._armed_until = 0.0
        self._turn: str | None = None
        self._deadline = 0.0
        self._used = False

    def arm(self) -> None:
        with self._lock:
            if self._turn is not None:
                raise RuntimeError('Cannot arm privileged operations during an active turn')
            self._armed_until = self._clock() + ARM_SECONDS

    def revoke(self) -> None:
        """Prevent new operations; already-running read-only work has its own deadline."""
        with self._lock:
            self._armed_until = 0.0
            self._deadline = 0.0
            self._used = True

    @property
    def status(self) -> str:
        with self._lock:
            now = self._clock()
            if self._turn is not None:
                if now >= self._deadline:
                    return 'expired'
                return 'consumed' if self._used else 'active (one read-only collection)'
            return 'armed for next turn' if now < self._armed_until else 'disabled'

    @contextmanager
    def turn(self, profile: str) -> Iterator[None]:
        if profile != 'head':
            # Workers neither inherit nor consume head authority.
            token = _context.set(None)
            try:
                yield
            finally:
                _context.reset(token)
            return
        identity = uuid4().hex
        with self._lock:
            if self._turn is not None:
                raise RuntimeError('Concurrent head turns are not permitted')
            enabled = self._clock() < self._armed_until
            self._armed_until = 0.0
            self._turn = identity
            self._deadline = self._clock() + TURN_SECONDS if enabled else 0.0
            self._used = not enabled
        token = _context.set(identity)
        try:
            yield
        finally:
            _context.reset(token)
            with self._lock:
                self._turn = None
                self._deadline = 0.0
                self._used = True

    def claim(self) -> PrivilegedClaim:
        """Consume before validation/UAC: failure or cancellation never refunds."""
        with self._lock:
            now = self._clock()
            if (_context.get() is None or _context.get() != self._turn
                    or self._used or now >= self._deadline):
                raise PermissionError('Enable privileged Hyper-V evidence in settings for the next turn')
            self._used = True
            return PrivilegedClaim(uuid4().hex, self._wall_clock() + self._deadline - now)
