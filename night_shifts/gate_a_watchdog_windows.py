"""Win32 signal adapter for a separately hosted Gate A watchdog.

Only exact already-held handles. No process lookup by PID, handle delivery,
process creation, VM operation, privilege changes or CLI. The protected host
starter is responsible for handle provenance, rights, role and lifetime.
"""
from __future__ import annotations

import ctypes as c
import os

from night_shifts.gate_a_watchdog import MAX_WAIT_MS, StopReason, WatchdogRefused

_WAIT_TIMEOUT = 258
_REASONS = (StopReason.CANCELLED, StopReason.RUNTIME_EXITED, StopReason.WORKER_EXITED)


class WindowsWatchSignals:
    """Borrow four distinct non-inheritable handles owned by the watchdog host.

    The protected starter retains them until Run returns and must supply local,
    non-aliased manual-reset events (cancel initially per request state, armed
    initially clear), and process handles with SYNCHRONIZE and QUERY_LIMITED_
    INFORMATION rights. Only the watchdog may signal armed. A non-inheritable
    handle is not by itself authenticated delivery. Polling never interprets
    exit codes or process IDs as work or cleanup results.
    """

    def __init__(self, *, cancelled: int, runtime: int, worker: int, armed: int) -> None:
        handles = (cancelled, runtime, worker, armed)
        if (os.name != 'nt' or c.sizeof(c.c_void_p) != 8
                or any(type(h) is not int or not 0 < h < 2**63 for h in handles)
                or len(set(handles)) != len(handles)):
            raise WatchdogRefused('signal_handles')
        self._kernel = c.WinDLL('kernel32', use_last_error=True)
        signatures = {
            'GetHandleInformation': ([c.c_void_p, c.POINTER(c.c_uint32)], c.c_int),
            'GetProcessId': ([c.c_void_p], c.c_uint32),
            'WaitForSingleObject': ([c.c_void_p, c.c_uint32], c.c_uint32),
            'WaitForMultipleObjects': ([c.c_uint32, c.POINTER(c.c_void_p), c.c_int, c.c_uint32], c.c_uint32),
            'SetEvent': ([c.c_void_p], c.c_int),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self._kernel, name)
            function.argtypes, function.restype = arguments, result
        for handle in handles:
            flags = c.c_uint32()
            if not self._kernel.GetHandleInformation(handle, c.byref(flags)) or flags.value & 1:
                raise WatchdogRefused('signal_handles')
        runtime_id = self._kernel.GetProcessId(runtime)
        worker_id = self._kernel.GetProcessId(worker)
        if (not runtime_id or not worker_id or runtime_id == worker_id
                or os.getpid() in (runtime_id, worker_id)
                or self._kernel.WaitForSingleObject(armed, 0) != _WAIT_TIMEOUT):
            raise WatchdogRefused('signal_handles')
        self._wait_handles = (c.c_void_p * 3)(cancelled, runtime, worker)
        self._armed, self._arm_attempted = armed, False

    def wait(self, milliseconds: int) -> StopReason | None:
        if type(milliseconds) is not int or not 0 <= milliseconds <= MAX_WAIT_MS:
            raise WatchdogRefused('signal_wait_bound')
        result = self._kernel.WaitForMultipleObjects(len(self._wait_handles), self._wait_handles, False, milliseconds)
        if result == _WAIT_TIMEOUT:
            return None
        if not 0 <= result < len(_REASONS):
            raise WatchdogRefused('signal_unknown')
        return _REASONS[result]

    def arm(self) -> None:
        if self._arm_attempted:
            raise WatchdogRefused('signal_arm')
        self._arm_attempted = True  # never try again even if delivery was uncertain
        if not self._kernel.SetEvent(self._armed):
            raise WatchdogRefused('signal_arm')
