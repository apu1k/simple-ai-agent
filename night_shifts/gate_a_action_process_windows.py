"""Private Win32 execution primitive for installed Gate A's fixed actions.

No elevation or VM authority. Closing the job bounds the action client, not
an admitted Hyper-V provider operation. Only the action's terminal receipt can
settle that operation for the owner.
"""
from __future__ import annotations

import ctypes as c
import os
import subprocess
import time
from contextlib import ExitStack
from typing import Any

from night_shifts.bootstrap_native_build_windows import _Accounting, _Limits, _ProcessInfo, _Security, _StartupEx
from night_shifts.gate_a_watchdog import MAX_RECEIPT_BYTES, WatchdogRefused
from night_shifts.maintenance_store_native_prototype import _Windows

_P, _U = c.c_void_p, c.c_uint32
_INVALID = c.c_void_p(-1).value
_JOB_FLAGS = 0x2008  # KILL_ON_JOB_CLOSE | ACTIVE_PROCESS


def _require(ok: object, label: str) -> None:
    if not ok:
        raise WatchdogRefused(label)


class _WindowsGateAProcess(_Windows):
    def __init__(self, *, require_protected_owner: bool) -> None:
        _require(os.name == 'nt' and c.sizeof(_P) == 8, 'action_windows_x64')
        super().__init__()
        self.protected = require_protected_owner
        for name, args, result in (
            ('GetSystemDirectoryW', [c.c_wchar_p, _U], _U),
            ('GetComputerNameW', [c.c_wchar_p, c.POINTER(_U)], c.c_int),
            ('GetCurrentProcess', [], _P),
            ('IsProcessInJob', [_P, _P, c.POINTER(c.c_int)], c.c_int),
            ('CreateJobObjectW', [c.POINTER(_Security), c.c_wchar_p], _P),
            ('SetInformationJobObject', [_P, c.c_int, _P, _U], c.c_int),
            ('QueryInformationJobObject', [_P, c.c_int, _P, _U, _P], c.c_int),
            ('CreatePipe', [c.POINTER(_P), c.POINTER(_P), c.POINTER(_Security), _U], c.c_int),
            ('SetHandleInformation', [_P, _U, _U], c.c_int),
            ('PeekNamedPipe', [_P, _P, _U, _P, c.POINTER(_U), _P], c.c_int),
            ('InitializeProcThreadAttributeList', [_P, _U, _U, c.POINTER(c.c_size_t)], c.c_int),
            ('UpdateProcThreadAttribute', [_P, _U, c.c_size_t, _P, c.c_size_t, _P, _P], c.c_int),
            ('DeleteProcThreadAttributeList', [_P], None),
            ('CreateProcessW', [c.c_wchar_p, c.c_wchar_p, c.POINTER(_Security), c.POINTER(_Security),
                                c.c_int, _U, _P, c.c_wchar_p, c.POINTER(_StartupEx), c.POINTER(_ProcessInfo)], c.c_int),
            ('ResumeThread', [_P], _U), ('WaitForSingleObject', [_P, _U], _U),
            ('GetExitCodeProcess', [_P, c.POINTER(_U)], c.c_int),
        ):
            self._bind(self.k, name, args, result)
        if self.protected:
            self.require_admin()
            in_job = c.c_int()
            _require(self.k.IsProcessInJob(self.k.GetCurrentProcess(), None, c.byref(in_job)) and not in_job.value,
                     'action_owner_not_independent')

    def system_identity(self) -> tuple[str, str]:
        system, computer, size = c.create_unicode_buffer(512), c.create_unicode_buffer(256), _U(256)
        count = self.k.GetSystemDirectoryW(system, len(system))
        _require(0 < count < len(system) and self.k.GetComputerNameW(computer, c.byref(size))
                 and 0 < size.value < len(computer), 'action_system_identity')
        return system.value, computer.value

    def _close(self, handle: c.c_void_p | int) -> None:
        _require(self.k.CloseHandle(handle), 'action_close_unknown')

    def _free(self, sd: c.c_void_p) -> None:
        _require(not self.k.LocalFree(sd), 'action_descriptor_unknown')

    def _security(self, stack: ExitStack) -> tuple[_Security, _Security]:
        sd = _P()
        if self.protected:
            # No access/ownership granted to the unelevated operator SID.
            _require(self.a.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                'O:BAG:BAD:P(A;;GA;;;SY)(A;;GA;;;BA)', 1, c.byref(sd), None), 'action_descriptor')
            stack.callback(self._free, sd)
        return _Security(c.sizeof(_Security), sd, 0), _Security(c.sizeof(_Security), sd, 1)

    def _job(self, security: _Security, stack: ExitStack) -> int:
        job = self.k.CreateJobObjectW(c.byref(security), None)
        _require(job, 'action_job_create')
        stack.callback(self._close, job)
        limits, observed = _Limits(), _Limits()
        limits.basic.flags, limits.basic.active = _JOB_FLAGS, 1
        _require(self.k.SetInformationJobObject(job, 9, c.byref(limits), c.sizeof(limits))
                 and self.k.QueryInformationJobObject(job, 9, c.byref(observed), c.sizeof(observed), None)
                 and observed.basic.flags == _JOB_FLAGS and observed.basic.active == 1, 'action_job_limits')
        return int(job)

    def _attributes(self, job: int, inherited: Any, stack: ExitStack) -> Any:
        size = c.c_size_t()
        probe = self.k.InitializeProcThreadAttributeList(None, 2, 0, c.byref(size))
        _require(not probe and c.get_last_error() == 122 and 0 < size.value <= 4096, 'action_attributes')
        attributes, jobs = c.create_string_buffer(size.value), (_P * 1)(job)
        _require(self.k.InitializeProcThreadAttributeList(attributes, 2, 0, c.byref(size)), 'action_attributes')

        def delete(attributes: Any, *_keep_values: object) -> None:
            self.k.DeleteProcThreadAttributeList(attributes)

        # These value buffers must remain live until DeleteProcThreadAttributeList.
        stack.callback(delete, attributes, jobs, inherited)
        _require(self.k.UpdateProcThreadAttribute(attributes, 0, 0x2000d, jobs, c.sizeof(jobs), None, None)
                 and self.k.UpdateProcThreadAttribute(attributes, 0, 0x20002, inherited, c.sizeof(inherited), None, None),
                 'action_atomic_containment')
        return attributes

    @staticmethod
    def _remaining(deadline_ns: int) -> int:
        remaining = deadline_ns - time.monotonic_ns()
        _require(remaining > 0, 'action_deadline')
        return remaining

    def _collect(self, job: int, process: int, reader: c.c_void_p, *, deadline_ns: int, limit: int) -> bytes:
        output, record, code = bytearray(), _Accounting(), _U()
        exited = eof = False
        while True:
            self._remaining(deadline_ns)
            available = _U()
            if not eof:
                if not self.k.PeekNamedPipe(reader, None, 0, None, c.byref(available), None):
                    _require(c.get_last_error() == 109, 'action_pipe_read')  # ERROR_BROKEN_PIPE / EOF
                    eof = True
                elif available.value:
                    count = min(int(available.value), limit - len(output) + 1)
                    buffer, read = c.create_string_buffer(count), _U()
                    _require(self.k.ReadFile(reader, buffer, count, c.byref(read), None)
                             and 0 < read.value <= count, 'action_pipe_read')
                    output.extend(buffer.raw[:read.value])
                    _require(len(output) <= limit, 'action_output_bound')
                    continue
            if exited:
                # Windows can account an atomically assigned process more than
                # once in the cumulative total. Require exact root exit and
                # an empty job, with the native single-active-process cap.
                _require(self.k.QueryInformationJobObject(job, 1, c.byref(record), c.sizeof(record), None)
                         and record.total >= 1 and record.active <= 1, 'action_job_accounting')
                if eof and record.active == 0:
                    _require(output and self.k.GetExitCodeProcess(process, c.byref(code)) and code.value == 0,
                             'action_process_failed')
                    self._remaining(deadline_ns)
                    return bytes(output)
            remaining = self._remaining(deadline_ns)
            if not exited:
                result = self.k.WaitForSingleObject(process, min(10, remaining // 1_000_000))
                _require(result in (0, 258), 'action_wait_unknown')
                exited = result == 0
            elif remaining >= 1_000_000:
                time.sleep(0.001)

    def capture(self, argv: tuple[str, ...], *, cwd: str, environment: dict[str, str],
                deadline_ns: int, limit: int) -> bytes:
        """Private spawn boundary. The installed owner passes fixed argv only."""
        text = subprocess.list2cmdline(argv)
        _require(len(text) < 30_000 and '\x00' not in text and 0 < limit <= MAX_RECEIPT_BYTES, 'action_command_extent')
        block = ''.join(f'{k}={v}\0' for k, v in sorted(environment.items(), key=lambda p: p[0].upper())) + '\0'
        env = c.create_unicode_buffer(block)
        self._remaining(deadline_ns)
        with ExitStack() as stack:
            security, inheritable = self._security(stack)
            job = self._job(security, stack)
            reader, writer, info = _P(), _P(), _ProcessInfo()
            with ExitStack() as child_io:
                _require(self.k.CreatePipe(c.byref(reader), c.byref(writer), c.byref(inheritable), 4096), 'action_pipe')
                stack.callback(self._close, reader)
                child_io.callback(self._close, writer)
                _require(self.k.SetHandleInformation(reader, 1, 0), 'action_pipe_flags')
                stdin = self.k.CreateFileW('NUL', 0x80000000, 3, c.byref(inheritable), 3, 0x80, None)
                _require(stdin not in (None, _INVALID), 'action_stdin')
                child_io.callback(self._close, stdin)
                inherited = (_P * 2)(stdin, writer.value)
                attrs = self._attributes(job, inherited, child_io)
                si = _StartupEx()
                si.startup.size, si.attributes = c.sizeof(si), c.cast(attrs, _P)
                si.startup.flags = 0x100  # STARTF_USESTDHANDLES
                si.startup.input, si.startup.output, si.startup.error = stdin, writer.value, writer.value
                self._remaining(deadline_ns)
                _require(self.k.CreateProcessW(argv[0], c.create_unicode_buffer(text), c.byref(security), c.byref(security),
                                              True, 0x08080404, env, cwd, c.byref(si), c.byref(info)),
                         'action_atomic_process')
                if info.process:
                    stack.callback(self._close, int(info.process))
                if info.thread:
                    stack.callback(self._close, int(info.thread))
                _require(info.process and info.thread, 'action_process_handles')
            # Parent copies of writers are closed before the child can run.
            member = c.c_int()
            _require(self.k.IsProcessInJob(info.process, job, c.byref(member)) and member.value == 1,
                     'action_job_membership')
            self._remaining(deadline_ns)
            _require(self.k.ResumeThread(info.thread) == 1, 'action_resume')
            output = self._collect(job, int(info.process), reader, deadline_ns=deadline_ns, limit=limit)
        self._remaining(deadline_ns)
        return output
