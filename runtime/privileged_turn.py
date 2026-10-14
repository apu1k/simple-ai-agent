"""Volatile head-turn authorization and live, per-request UI approvals.

This is a trusted-app workflow, not an OS security boundary. Windows UAC and
protected launchers provide elevation. No model tool may arm or approve it.
"""
from __future__ import annotations

import hashlib
import json
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from threading import Event, Lock
from typing import Callable, Iterator
from uuid import uuid4

ARM_SECONDS = 120
TURN_SECONDS = 1800
EVIDENCE_OPERATION = 'collect_host_evidence'
INSPECTION_OPERATION = 'inspect_image_copy'
ELEVATED_OPERATION = 'elevated_commands'
OPERATIONS = frozenset((EVIDENCE_OPERATION, INSPECTION_OPERATION, ELEVATED_OPERATION))
_context: ContextVar[str | None] = ContextVar('privileged_turn', default=None)


@dataclass(frozen=True)
class PrivilegedClaim:
    request_id: str
    deadline_unix: float
    operation: str = EVIDENCE_OPERATION


@dataclass(frozen=True)
class PendingPrivilege:
    id: str
    claim: PrivilegedClaim
    review_json: str
    review_sha256: str

    @property
    def path(self) -> str:
        return self.claim.operation


class PrivilegedTurn:
    """Never serialized/restored. Unified turns allow separately approved calls.

    Legacy operation-specific arms remain for API compatibility, not UI settings.
    Their one-attempt budgets are unchanged. Fixed helpers also retain their own
    independent installed policy/claim constraints.
    """

    def __init__(self, *, clock: Callable[[], float] = time.monotonic,
                 wall_clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._wall_clock = wall_clock
        self._lock = Lock()
        self._armed_until = 0.0
        self._turn: str | None = None
        self._deadline = 0.0
        self._used = False
        self._operation = EVIDENCE_OPERATION
        self._fixed_used: set[str] = set()
        self._claims: dict[str, PrivilegedClaim] = {}
        self._requests: dict[str, PendingPrivilege] = {}
        self._decisions: dict[str, str] = {}
        self._events: dict[str, Event] = {}

    @property
    def armed_operation(self) -> str | None:
        with self._lock:
            return self._operation if self._turn is None and self._clock() < self._armed_until else None

    def arm(self, operation: str = EVIDENCE_OPERATION) -> None:
        if operation not in OPERATIONS:
            raise ValueError('Unknown privileged operation')
        with self._lock:
            if self._turn is not None:
                raise RuntimeError('Cannot arm privileged operations during an active turn')
            self._operation = operation
            self._armed_until = self._clock() + ARM_SECONDS

    def _invalidate(self) -> None:
        for identity, event in self._events.items():
            self._decisions[identity] = 'expired'
            event.set()

    def revoke(self) -> None:
        with self._lock:
            self._armed_until = 0.0
            self._deadline = 0.0
            self._used = True
            self._invalidate()

    @property
    def status(self) -> str:
        with self._lock:
            now = self._clock()
            if self._turn is not None:
                if now >= self._deadline:
                    return 'expired'
                if self._operation == ELEVATED_OPERATION:
                    return 'active (each elevated request requires pending approval and UAC)'
                if self._used:
                    return 'consumed'
                return ('active (one inspection-only attempt)' if self._operation == INSPECTION_OPERATION
                        else 'active (one read-only collection)')
            if now >= self._armed_until:
                return 'disabled'
            return ('inspection armed for next turn' if self._operation == INSPECTION_OPERATION
                    else 'armed for next turn')

    @contextmanager
    def turn(self, profile: str) -> Iterator[None]:
        if profile != 'head':
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
            self._fixed_used.clear()
            self._claims.clear()
            self._requests.clear()
            self._decisions.clear()
            self._events.clear()
        token = _context.set(identity)
        try:
            yield
        finally:
            _context.reset(token)
            with self._lock:
                self._invalidate()
                self._turn = None
                self._deadline = 0.0
                self._used = True

    def claim(self, operation: str = EVIDENCE_OPERATION) -> PrivilegedClaim:
        """Register before validation/UAC; fixed attempts are never refunded."""
        with self._lock:
            now = self._clock()
            unified = self._operation == ELEVATED_OPERATION
            if (operation not in OPERATIONS or _context.get() is None or _context.get() != self._turn
                    or self._used or now >= self._deadline
                    or (not unified and operation != self._operation)
                    or (unified and operation != ELEVATED_OPERATION and operation in self._fixed_used)):
                raise PermissionError('Enable elevated commands for the next turn')
            if not unified:
                self._used = True
            elif operation != ELEVATED_OPERATION:
                self._fixed_used.add(operation)
            claim = PrivilegedClaim(uuid4().hex, self._wall_clock() + self._deadline - now, operation)
            self._claims[claim.request_id] = claim
            return claim

    def _live(self, claim: PrivilegedClaim) -> bool:
        return (self._turn is not None and self._clock() < self._deadline
                and self._claims.get(claim.request_id) == claim)

    def submit(self, claim: PrivilegedClaim, details: dict) -> PendingPrivilege:
        review = json.dumps(details, sort_keys=True, ensure_ascii=True, indent=2, allow_nan=False)
        if len(review.encode('utf-8')) > 65536:
            raise ValueError('Oversized approval request')
        request = PendingPrivilege('E' + claim.request_id, claim, review,
                                   hashlib.sha256(review.encode('utf-8')).hexdigest())
        with self._lock:
            if _context.get() != self._turn or not self._live(claim) or request.id in self._requests:
                raise PermissionError('Approval request is not live or was already submitted')
            self._requests[request.id] = request
            self._decisions[request.id] = 'pending'
            self._events[request.id] = Event()
        return request

    def pending(self) -> dict[str, PendingPrivilege]:
        with self._lock:
            if self._clock() >= self._deadline:
                self._invalidate()
            return {key: request for key, request in self._requests.items()
                    if self._decisions[key] == 'pending'}

    def decide(self, identity: str, *, accept: bool) -> str:
        """UI only. Exactly one decision; no resurrecting old approvals."""
        with self._lock:
            request = self._requests.get(identity)
            if request is None or self._decisions.get(identity) != 'pending':
                raise ValueError('Request is no longer pending')
            decision = 'accepted' if accept else 'rejected'
            if not self._live(request.claim):
                decision = 'expired'
            self._decisions[identity] = decision
            self._events[identity].set()
            return decision

    def wait(self, request: PendingPrivilege) -> str:
        while True:
            with self._lock:
                if self._requests.get(request.id) != request or not self._live(request.claim):
                    return 'expired'
                decision = self._decisions[request.id]
                event = self._events[request.id]
                if decision != 'pending':
                    return decision
            event.wait(0.2)

    def require_accepted(self, request: PendingPrivilege) -> None:
        with self._lock:
            if (_context.get() != self._turn or not self._live(request.claim)
                    or self._requests.get(request.id) != request
                    or self._decisions.get(request.id) != 'accepted'):
                raise PermissionError('Approval expired or was not accepted')
            # Single handoff; duplicate execution with this approval is denied.
            self._decisions[request.id] = 'handed_off'
