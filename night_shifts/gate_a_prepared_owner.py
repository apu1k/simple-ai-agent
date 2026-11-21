"""Supervise the start, exchange lifetime and teardown of an already prepared VM.

This is the installed owner's post-preparation entry point, not a launcher
installer or runtime tool. The owner must already hold the permanent claim,
reviewed inputs, an Off VM recorded by GUID, and exact process/event handles.
It must publish the host outcome separately from any guest audit or reply.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from threading import Event, Lock, Thread
from typing import Protocol

from night_shifts.gate_a_action_process_windows import _WindowsGateAProcess
from night_shifts.gate_a_fixed_actions import GateAActionSnapshot, WindowsPinnedGateAActions
from night_shifts.gate_a_host_lifecycle import GateAHostLifecycle
from night_shifts.gate_a_watchdog import StopReason, TeardownTarget, WatchdogRefused, WatchResult, WatchSignals
from night_shifts.gate_a_watchdog_windows import WindowsOwnerSignals


class _OwnerSignals(WatchSignals, Protocol):
    def release_worker(self) -> None: ...
    def request_cancel(self) -> None: ...


@dataclass(frozen=True)
class PreparedGateAOutcome:
    worker_signalled: bool
    host_cleanup: WatchResult


def _supervise(lifecycle: GateAHostLifecycle, signals: _OwnerSignals, *, deadline_ns: int) -> PreparedGateAOutcome:
    armed, stopped, released = Event(), Event(), Event()
    signal_lock = Lock()

    class _HostSignals:
        def wait(self, milliseconds: int) -> StopReason | None:
            return signals.wait(milliseconds)

        def arm(self) -> None:
            signals.arm()
            armed.set()

    def release() -> None:
        with signal_lock:
            if stopped.is_set():
                raise WatchdogRefused('owner_stopped')
            signals.release_worker()
            released.set()

    def cancel_if_live() -> None:
        with signal_lock:
            if not stopped.is_set():
                try:
                    if signals.wait(0) is None:
                        signals.request_cancel()
                except Exception:
                    # The watchdog observes its own signals and time; a failed
                    # early wake never widens admission or grants a retry.
                    pass

    def starter() -> None:
        armed.wait()  # also woken by watch() unwinding before it ever arms
        if stopped.is_set():
            return
        try:
            if lifecycle.start_once() and lifecycle.release_worker_once(release):
                return
        except Exception:
            pass  # lifecycle retains the settlement state; no second action
        cancel_if_live()

    controller = Thread(target=starter, name='gate-a-fixed-start', daemon=True)
    started = False
    try:
        try:
            controller.start()
            started = True
        except RuntimeError:
            cancel_if_live()
        result = lifecycle.watch(_HostSignals())
    finally:
        with signal_lock:
            stopped.set()  # no event signals from controller after we release borrowed handles
        armed.set()
        if started:
            controller.join(max(0, deadline_ns - time.monotonic_ns()) / 1_000_000_000)
    if controller.is_alive():
        result = WatchResult(result.stop_reason, None, 'controller_lifetime_unknown')
    return PreparedGateAOutcome(released.is_set(), result)


def supervise_prepared_windows_gate_a(
    target: TeardownTarget, *, held_workspace_root: str, held_boot_asset: str, deadline_ns: int,
    start: GateAActionSnapshot, reconcile: GateAActionSnapshot,
    cancelled: int, runtime: int, worker: int, armed: int, worker_gate: int,
) -> PreparedGateAOutcome:
    """Run inside the independent protected host, not in the runtime/worker.

    The worker must already be waiting on worker_gate (wait-only access) and
    independently observe cancellation and the original work cutoff. It has
    no VM mutation authority. Missing or untrusted preparation/handle evidence
    must be refused by the owner before it calls here, never guessed from PIDs.
    """
    _WindowsGateAProcess(require_protected_owner=True)  # reject a general-command job or ordinary process before arming
    actions = WindowsPinnedGateAActions(target, held_workspace_root=held_workspace_root,
                                        held_boot_asset=held_boot_asset, deadline_ns=deadline_ns,
                                        start=start, reconcile=reconcile)
    host = GateAHostLifecycle(target, held_workspace_root=held_workspace_root, held_boot_asset=held_boot_asset,
                              actions=actions, deadline_ns=deadline_ns)
    signals = WindowsOwnerSignals(cancelled=cancelled, runtime=runtime, worker=worker, armed=armed, worker_gate=worker_gate)
    return _supervise(host, signals, deadline_ns=deadline_ns)
