"""One-shot VM lifetime supervision for a future protected Windows owner.

No launcher, authorization, filesystem claim, process/VM creation or CLI. Run
outside the runtime and work processes. The protected starter must bind the
exact, fresh VM and hold the private workspace and permanent attempt claim.
The watchdog never treats process exit or a guest result as host cleanup.
"""
from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from threading import Lock
from typing import Protocol

_NS = 1_000_000_000
MAX_WINDOW_NS = 900 * _NS
CLEANUP_RESERVE_NS = 30 * _NS
MAX_WAIT_MS = 250
MAX_RECEIPT_BYTES = 1024
_VM_ID = re.compile(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}')


class WatchdogRefused(ValueError):
    """Fixed local label; no subprocess output, identities or paths."""


@dataclass(frozen=True)
class TeardownTarget:
    operation: str
    attempt_id: str
    vm_id: str

    def __post_init__(self) -> None:
        if (type(self.operation) is not str or self.operation not in ('finalization', 'smoke')
                or type(self.attempt_id) is not str or re.fullmatch('[0-9a-f]{32}', self.attempt_id) is None
                or type(self.vm_id) is not str or _VM_ID.fullmatch(self.vm_id) is None
                or self.vm_id == '00000000-0000-0000-0000-000000000000'):
            raise WatchdogRefused('target')

    @property
    def remove_smoke_disk(self) -> bool:
        return self.operation == 'smoke'


@dataclass(frozen=True)
class HostCleanup:
    """Parsed local host-action facts, not a protected receipt or Gate A pass."""

    target: TeardownTarget
    disk_retained: bool


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise WatchdogRefused('receipt')
        result[key] = value
    return result


def validate_cleanup_receipt(target: TeardownTarget, raw: bytes) -> HostCleanup:
    """Accept only exact success facts from the pinned host action's output."""
    if type(target) is not TeardownTarget or type(raw) is not bytes or not 0 < len(raw) <= MAX_RECEIPT_BYTES:
        raise WatchdogRefused('receipt')
    try:
        item = json.loads(raw.decode('ascii'), object_pairs_hook=_unique)
    except (ValueError, RecursionError):
        raise WatchdogRefused('receipt') from None
    retained = not target.remove_smoke_disk
    expected = {'version': 1, 'operation': target.operation, 'id': target.attempt_id, 'vm_id': target.vm_id,
                'vm_absent': True, 'disk_unattached_and_unreferenced': True, 'disk_retained': retained}
    if not retained:
        expected['disk_absent'] = True
    if (type(item) is not dict or item.keys() != expected.keys()
            or any(type(item[key]) is not type(value) or item[key] != value for key, value in expected.items())):
        raise WatchdogRefused('receipt')
    return HostCleanup(target, retained)


class StopReason(Enum):
    CANCELLED = 'cancelled'
    RUNTIME_EXITED = 'runtime_exited'
    WORKER_EXITED = 'worker_exited'
    DEADLINE = 'deadline'
    SIGNAL_UNKNOWN = 'signal_unknown'


_SIGNAL_REASONS = (StopReason.CANCELLED, StopReason.RUNTIME_EXITED, StopReason.WORKER_EXITED)


class WatchSignals(Protocol):
    def wait(self, milliseconds: int) -> StopReason | None:
        """Wait on exact local handles; None means only that this wait elapsed."""

    def arm(self) -> None:
        """Acknowledge the watchdog is watching; not an authorization to Start-VM."""


class ProtectedLifecycle(Protocol):
    def seal(self, target: TeardownTarget, *, deadline_ns: int) -> bool:
        """Permanently close start/mutation admission and prove prior writes settled.

        The starter must serialize this transition with lifecycle admission,
        including any in-flight Hyper-V operation. Killing a client process does
        not prove provider-side settlement. A mere callback success is not the
        live proof; this seam is for a protected implementation, not the runtime.
        """

    def reconcile_once(self, target: TeardownTarget, *, deadline_ns: int) -> bytes:
        """Run only pinned reconcile_gate_a_vm.ps1 in the held workspace.

        The protected owner supplies its already held root, the exact target,
        the fixed disk policy, and bounded, successful host-action stdout only.
        Never return output from a failed/timed-out command or invoke it twice.
        """


@dataclass(frozen=True)
class WatchResult:
    stop_reason: StopReason
    cleanup: HostCleanup | None
    cleanup_unknown: str | None


class GateAWatchdog:
    """Watch once under the original absolute host deadline and cleanup reserve.

    Both the lifecycle gate and host action must be bounded independently of
    this loop. The clock is system-wide Windows monotonic time in nanoseconds;
    a protected starter passes the original deadline, not a renewed duration.
    The in-memory one-shot guard does not replace a permanent host claim.
    """

    def __init__(self, target: TeardownTarget, signals: WatchSignals, lifecycle: ProtectedLifecycle, *,
                 deadline_ns: int, clock: Callable[[], int] = time.monotonic_ns) -> None:
        if type(target) is not TeardownTarget or type(deadline_ns) is not int or not 0 < deadline_ns < 2**63:
            raise WatchdogRefused('window')
        self._target, self._signals, self._lifecycle = target, signals, lifecycle
        self._clock, self._deadline = clock, deadline_ns
        self._work_until = deadline_ns - CLEANUP_RESERVE_NS
        self._last = 0
        self._clock_bad = False
        if deadline_ns - self._now() > MAX_WINDOW_NS:
            raise WatchdogRefused('window')
        self._used, self._lock = False, Lock()

    def _now(self) -> int:
        if not self._clock_bad:
            try:
                now = self._clock()
                if type(now) is int and self._last <= now < 2**63:
                    self._last = now
                    return now
            except Exception:
                pass
            self._clock_bad = True
        raise WatchdogRefused('clock_unknown')

    def _wait(self, milliseconds: int) -> StopReason | None:
        reason = self._signals.wait(milliseconds)
        if reason is not None and (type(reason) is not StopReason or reason not in _SIGNAL_REASONS):
            raise WatchdogRefused('signal_unknown')
        return reason

    def _watch(self) -> StopReason:
        try:
            if self._now() >= self._work_until:
                return StopReason.DEADLINE
            reason = self._wait(0)
            if self._now() >= self._work_until:
                return StopReason.DEADLINE
            if reason is not None:
                return reason
            self._signals.arm()
            while (before := self._now()) < self._work_until:
                remaining_ms = (self._work_until - before) // 1_000_000
                reason = self._wait(max(1, min(MAX_WAIT_MS, remaining_ms)))
                after = self._now()
                if after >= self._work_until:
                    break
                if reason is not None:
                    return reason
                if after <= before:
                    return StopReason.SIGNAL_UNKNOWN
            return StopReason.DEADLINE
        except Exception:
            # A signal failure withdraws work admission and still attempts safe
            # reconciliation, but only if the original cleanup window is known.
            return StopReason.SIGNAL_UNKNOWN

    def _cleanup_window_open(self) -> bool:
        try:
            return self._now() < self._deadline
        except WatchdogRefused:
            return False

    def run(self) -> WatchResult:
        with self._lock:
            if self._used:
                raise WatchdogRefused('one_shot')
            self._used = True
        reason = self._watch()
        if not self._cleanup_window_open():
            return WatchResult(reason, None, 'window_unknown_or_expired')
        try:
            if self._lifecycle.seal(self._target, deadline_ns=self._deadline) is not True:
                return WatchResult(reason, None, 'lifecycle_unknown')
        except Exception:
            return WatchResult(reason, None, 'lifecycle_unknown')
        if not self._cleanup_window_open():
            return WatchResult(reason, None, 'window_unknown_or_expired')
        try:
            data = self._lifecycle.reconcile_once(self._target, deadline_ns=self._deadline)
            observed = validate_cleanup_receipt(self._target, data)
        except Exception:
            return WatchResult(reason, None, 'reconciliation_unknown')
        if not self._cleanup_window_open():
            return WatchResult(reason, None, 'window_unknown_or_expired')
        return WatchResult(reason, observed, None)
