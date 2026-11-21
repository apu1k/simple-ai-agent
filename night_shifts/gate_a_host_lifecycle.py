"""Protected-owner composition for the two fixed Gate A Hyper-V actions.

Not an installed launcher. The caller must already hold the claim, exact fresh
VM, workspace, and approved media/disk leases. The fixed action runner must
pin code and live outside the runtime; never wire this to a general shell tool.
"""
from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from pathlib import PureWindowsPath
from threading import Condition
from typing import Protocol

from night_shifts.gate_a_watchdog import (
    CLEANUP_RESERVE_NS, MAX_RECEIPT_BYTES, MAX_WINDOW_NS, GateAWatchdog, StopReason,
    TeardownTarget, WatchdogRefused, WatchResult, WatchSignals, _unique,
)

_START = 'start_gate_a_vm.ps1'
_RECONCILE = 'reconcile_gate_a_vm.ps1'
_START_SETTLE_NS = 10_000_000_000
_MIN_RECONCILE_NS = 20_000_000_000
_DRIVE_PATH = re.compile(r'[A-Za-z]:\\[A-Za-z0-9_ .()\-]+(?:\\[A-Za-z0-9_ .()\-]+)*')
_RESERVED = re.compile(r'(?:CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])(?:\..*)?', re.IGNORECASE)


class PinnedGateAActions(Protocol):
    def run(self, fixed_script: str, args: tuple[str, ...], *, deadline_ns: int, stdout_limit: int) -> bytes:
        """Run only pinned installed Gate A actions with literal argv.

        Independently enforce the absolute deadline and capture bound, no
        profiles, ambient module resolution or elevation of checkout code.
        Return stdout only after observed successful exit of the exact process,
        with no residual job processes. Never retry on failure or timeout.
        """


def _local_path(value: str) -> PureWindowsPath:
    if (type(value) is not str or len(value) > 200 or _DRIVE_PATH.fullmatch(value) is None
            or any(part.startswith(' ') or part.endswith((' ', '.')) or _RESERVED.fullmatch(part)
                   for part in value[3:].split('\\'))):
        raise WatchdogRefused('held_path')
    return PureWindowsPath(value)


def _start_outcome(raw: bytes, target: TeardownTarget) -> bool:
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_RECEIPT_BYTES:
        raise WatchdogRefused('start_unknown')
    try:
        item = json.loads(raw.decode('ascii'), object_pairs_hook=_unique)
    except (ValueError, RecursionError):
        raise WatchdogRefused('start_unknown') from None
    expected = {'version': 1, 'operation': target.operation, 'id': target.attempt_id, 'vm_id': target.vm_id}
    if (type(item) is not dict or item.keys() != expected.keys() | {'state'}
            or any(type(item[k]) is not type(v) or item[k] != v for k, v in expected.items())
            or type(item['state']) is not str or item['state'] not in ('running_observed', 'not_started')):
        raise WatchdogRefused('start_unknown')
    return item['state'] == 'running_observed'


class GateAHostLifecycle:
    """Single local owner of VM writes after preparation. No write authority in the worker.

    Host starts watch() on an independent thread in its protected process and
    admits start_once() only through this same object. The worker should wait
    for a positive start readback. A permanent host claim precedes this state.
    """

    def __init__(self, target: TeardownTarget, *, held_workspace_root: str, held_boot_asset: str,
                 actions: PinnedGateAActions, deadline_ns: int, clock: Callable[[], int] = time.monotonic_ns) -> None:
        if type(target) is not TeardownTarget or type(deadline_ns) is not int or not 0 < deadline_ns < 2**63:
            raise WatchdogRefused('host_binding')
        workspace, boot = _local_path(held_workspace_root), _local_path(held_boot_asset)
        if (boot.suffix.lower() != ('.iso' if target.operation == 'finalization' else '.vhdx')
                or boot == workspace or workspace / target.attempt_id in boot.parents):
            raise WatchdogRefused('held_path')
        self._target, self._deadline, self._clock = target, deadline_ns, clock
        self._actions = actions
        self._binding = ('-Operation', target.operation, '-Identity', target.attempt_id,
                         '-VmId', target.vm_id, '-WorkspaceRoot', held_workspace_root)
        self._work_until = deadline_ns - CLEANUP_RESERVE_NS
        self._start_args = self._binding + ('-BootAsset', held_boot_asset, '-WorkUntilNanoseconds', str(self._work_until))
        self._changed = Condition()
        self._last = 0
        self._bad_clock = False
        self._watching = self._armed = self._sealed = self._can_reconcile = self._reconcile_used = False
        self._start_state = 'unadmitted'
        if not 0 < deadline_ns - self._now() <= MAX_WINDOW_NS:
            raise WatchdogRefused('host_window')

    def _now(self) -> int:
        # Call under _changed (or during initialization). Bad time never reopens admission.
        if not self._bad_clock:
            try:
                value = self._clock()
                if type(value) is int and self._last <= value < 2**63:
                    self._last = value
                    return value
            except Exception:
                pass
        self._bad_clock = True
        raise WatchdogRefused('clock_unknown')

    def _arm(self, signals: WatchSignals) -> None:
        with self._changed:
            if self._armed or self._sealed or self._now() >= self._work_until:
                raise WatchdogRefused('arm_closed')
            signals.arm()
            self._armed = True

    def watch(self, signals: WatchSignals) -> WatchResult:
        with self._changed:
            if self._watching:
                raise WatchdogRefused('one_shot')
            self._watching = True
        host = self

        class OwnedSignals:
            def arm(self) -> None:
                host._arm(signals)

            def wait(self, milliseconds: int) -> StopReason | None:
                return signals.wait(milliseconds)

        return GateAWatchdog(self._target, OwnedSignals(), self, deadline_ns=self._deadline, clock=self._clock).run()

    def start_once(self) -> bool:
        """Return True only for a settled Start-VM with an exact Running readback."""
        with self._changed:
            if (not self._armed or self._sealed or self._start_state != 'unadmitted'
                    or self._now() >= self._work_until):
                raise WatchdogRefused('start_closed')
            self._start_state = 'pending'  # before crossing the process/VM boundary
        settled = False
        try:
            running = _start_outcome(self._actions.run(_START, self._start_args, deadline_ns=self._work_until,
                                                       stdout_limit=MAX_RECEIPT_BYTES), self._target)
            with self._changed:
                if self._now() >= self._work_until:
                    raise WatchdogRefused('start_unknown')
                settled = True
                # A stop racing a settled start must not let new worker work proceed.
                return running and not self._sealed
        except Exception:
            raise WatchdogRefused('start_unknown') from None
        finally:
            with self._changed:
                self._start_state = 'settled' if settled else 'unknown'
                self._changed.notify_all()

    def _same_attempt(self, target: TeardownTarget, deadline_ns: int) -> bool:
        return type(target) is TeardownTarget and self._target == target and self._deadline == deadline_ns

    def seal(self, target: TeardownTarget, *, deadline_ns: int) -> bool:
        with self._changed:
            if not self._same_attempt(target, deadline_ns) or self._sealed:
                raise WatchdogRefused('seal_closed')
            self._sealed = True  # irrevocable; even unknown results forbid later admission
            now = self._now()
            settle_by = min(now + _START_SETTLE_NS, deadline_ns - _MIN_RECONCILE_NS)
            if self._start_state == 'pending':
                # Neither client death nor a newly returned VM status proves a queued
                # provider mutation settled. Wait only for the fixed action's terminal receipt.
                while self._start_state == 'pending':
                    remaining = settle_by - self._now()
                    if remaining <= 0 or not self._changed.wait(remaining / 1_000_000_000):
                        return False
                if self._now() >= settle_by:
                    return False
            self._can_reconcile = self._start_state in ('unadmitted', 'settled') and self._now() < deadline_ns
            return self._can_reconcile

    def reconcile_once(self, target: TeardownTarget, *, deadline_ns: int) -> bytes:
        with self._changed:
            if (not self._same_attempt(target, deadline_ns) or not self._can_reconcile
                    or self._reconcile_used or self._now() >= self._deadline):
                raise WatchdogRefused('reconcile_closed')
            self._reconcile_used = True
        args = self._binding + (('-RemoveSmokeDisk',) if target.remove_smoke_disk else ())
        return self._actions.run(_RECONCILE, args, deadline_ns=deadline_ns, stdout_limit=MAX_RECEIPT_BYTES)
