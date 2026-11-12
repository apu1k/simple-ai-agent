"""Cancellation-only native pipe lease for the EXISTING approved command channel.

No command/data frames, elevation, child PID lookup, retry or deadline renewal.
The protected client must independently bind the server PID AND creation time,
use anonymous SQOS, and observe its exact process handle. The UI/app remains a
trusted approval participant, not a sandbox against a compromised caller.
"""
from __future__ import annotations

import ctypes as c
import os
import re
from threading import Event, Thread
from uuid import uuid4

from runtime.privileged_host import PrivilegedHostError
from runtime.privileged_turn import PrivilegedClaim, PrivilegedTurn

PREFIX = '\\\\.\\pipe\\AiAgentCommandLease-v1-'


class _Security(c.Structure):
    _fields_ = [('size', c.c_uint32), ('descriptor', c.c_void_p), ('inherit', c.c_int)]


class _Pipe:
    def __init__(self, name: str, sid: str) -> None:
        if os.name != 'nt' or c.sizeof(c.c_void_p) != 8 or not re.fullmatch(r'S-1-5-21-\d+-\d+-\d+-\d+', sid):
            raise PrivilegedHostError('Native same-account command lifetime required')
        self.k = c.WinDLL('kernel32', use_last_error=True)
        self.a = c.WinDLL('advapi32', use_last_error=True)
        signatures = {
            'CreateNamedPipeW': ([c.c_wchar_p, c.c_uint32, c.c_uint32, c.c_uint32, c.c_uint32, c.c_uint32, c.c_uint32, c.POINTER(_Security)], c.c_void_p),
            'ConnectNamedPipe': ([c.c_void_p, c.c_void_p], c.c_int),
            'GetHandleInformation': ([c.c_void_p, c.POINTER(c.c_uint32)], c.c_int),
            'GetCurrentProcess': ([], c.c_void_p),
            'GetProcessTimes': ([c.c_void_p, *([c.POINTER(c.c_uint64)] * 4)], c.c_int),
            'CloseHandle': ([c.c_void_p], c.c_int),
            'LocalFree': ([c.c_void_p], c.c_void_p),
        }
        for key, (args, result) in signatures.items():
            fn = getattr(self.k, key)
            fn.argtypes, fn.restype = args, result
        convert = self.a.ConvertStringSecurityDescriptorToSecurityDescriptorW
        convert.argtypes = [c.c_wchar_p, c.c_uint32, c.POINTER(c.c_void_p), c.POINTER(c.c_uint32)]
        convert.restype = c.c_int
        self.handle: int | None = None
        self.connected = False
        descriptor, count = c.c_void_p(), c.c_uint32()
        try:
            sddl = f'O:{sid}G:{sid}D:P(A;;GA;;;SY)(A;;GA;;;BA)(A;;GA;;;{sid})'
            if not convert(sddl, 1, c.byref(descriptor), c.byref(count)):
                raise PrivilegedHostError('Command lifetime descriptor unavailable')
            security = _Security(c.sizeof(_Security), descriptor, 0)
            # FIRST_PIPE_INSTANCE, outbound byte pipe, NOWAIT, REJECT_REMOTE.
            # The one-way endpoint transports NO bytes; closing only subtracts
            # lifetime. It is not a command or a transferable approval channel.
            h = self.k.CreateNamedPipeW(name, 0x80002, 9, 1, 512, 512, 0, c.byref(security))
            if h in (None, c.c_void_p(-1).value):
                raise PrivilegedHostError('Command lifetime name collision or creation refused')
            self.handle = h
            flags = c.c_uint32()
            if not self.k.GetHandleInformation(h, c.byref(flags)) or flags.value != 0:
                raise PrivilegedHostError('Command lifetime inheritance unknown')
            times = [c.c_uint64() for _ in range(4)]
            if not self.k.GetProcessTimes(self.k.GetCurrentProcess(), *(c.byref(t) for t in times)) or times[0].value < 1:
                raise PrivilegedHostError('Command lifetime owner identity unknown')
            self.created = str(times[0].value)
        except BaseException:
            self.close()
            raise
        finally:
            if descriptor.value and self.k.LocalFree(descriptor):
                self.close()
                raise PrivilegedHostError('Command lifetime descriptor release unknown')

    def poll(self) -> None:
        if self.connected:
            return
        if self.k.ConnectNamedPipe(self.handle, None):
            self.connected = True
            return
        error = c.get_last_error()
        if error in (535, 232):  # connected, or already disconnected; never reconnect
            self.connected = True
        elif error != 536:  # nonblocking listening; all other states terminal
            raise PrivilegedHostError('Command lifetime connection unavailable')

    def close(self) -> None:
        old, self.handle = self.handle, None
        if old is not None and not self.k.CloseHandle(old):
            raise PrivilegedHostError('Command lifetime close unknown')


class CommandLifetime:
    """Own one non-inheritable server until completion, revocation or app death.

    Monitor reads grant liveness only; it cannot approve, execute or refresh a
    deadline. Process death closes the OS endpoint even if Python never unwinds.
    A stuck monitor/uncertain close never becomes a successful client result.
    """

    def __init__(self, gate: PrivilegedTurn, claim: PrivilegedClaim, sid: str) -> None:
        name = PREFIX + claim.request_id + '-' + uuid4().hex
        self._pipe = _Pipe(name, sid)
        try:
            self.binding = dict(version=1, pipe=name, owner_pid=os.getpid(), owner_created=self._pipe.created)
            self._stop = Event()
            self._failed = False
            self._gate, self._claim = gate, claim
            self._thread = Thread(target=self._watch, name='approved-command-lifetime', daemon=True)
        except BaseException:
            self._pipe.close()
            raise

    def _watch(self) -> None:
        try:
            while not self._stop.is_set() and not self._gate.execution_cancelled(self._claim):
                self._pipe.poll()
                self._stop.wait(0.1)
        except BaseException:
            self._failed = True
        finally:
            try:
                self._pipe.close()
            except BaseException:
                self._failed = True

    def __enter__(self) -> CommandLifetime:
        try:
            self._thread.start()
        except BaseException:
            self._pipe.close()
            raise
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        self._thread.join(2)
        if self._thread.is_alive() or self._failed:
            raise PrivilegedHostError('Command lifetime outcome unknown; preserve protected receipts')
