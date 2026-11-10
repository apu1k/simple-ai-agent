"""Explicit UNELEVATED Windows build adapter. No installation or executable run.

Only the fixed recipe's compiler can be launched as root. Its resource helper
and config MUST be pinned/held too. The fixed job concurrency cap is not an
executable allowlist; trusted compiler/helper/load behavior remains a prerequisite.
Trusted Windows/.NET and builder-runtime/load policy are EXTERNAL prerequisites,
not inferred from pins.
No import-time native calls, fallback, create-then-assign or permission repair.
"""
from __future__ import annotations

import ctypes as c
import math
import os
import platform
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from night_shifts import bootstrap_native_build as build
from night_shifts import bootstrap_native_build_owner as owner
from night_shifts import maintenance_store_native_prototype as native

_U = c.c_uint32
_P = c.c_void_p


class BuildNativeRefused(RuntimeError):
    """Fixed-label native build refusal; never an approval or retry grant."""


def _require(ok: object, label: str) -> None:
    if not ok:
        raise BuildNativeRefused(label)


class _Window:
    def __init__(self, deadline: float, cancelled: Callable[[], bool]) -> None:
        self.deadline, self.cancelled = deadline, cancelled
        self.last = -math.inf

    def seconds(self) -> float:
        value = time.monotonic()
        _require(type(value) in (int, float) and math.isfinite(value) and self.last <= value <= 1e15,
                 'native_build_clock')
        self.last = value
        return value

    def check(self) -> None:
        _require(self.seconds() < self.deadline, 'native_build_deadline')
        cancelled = self.cancelled()
        _require(type(cancelled) is bool and not cancelled, 'native_build_cancelled')


class _Security(c.Structure):
    _fields_ = [('size', _U), ('descriptor', _P), ('inherit', c.c_int)]


class _Basic(c.Structure):
    _fields_ = [('process_time', c.c_int64), ('job_time', c.c_int64), ('flags', _U),
                ('minimum', c.c_size_t), ('maximum', c.c_size_t), ('active', _U),
                ('affinity', c.c_size_t), ('priority', _U), ('scheduling', _U)]


class _Limits(c.Structure):
    _fields_ = [('basic', _Basic), ('io', c.c_uint64 * 6), ('process_memory', c.c_size_t),
                ('job_memory', c.c_size_t), ('peak_process', c.c_size_t), ('peak_job', c.c_size_t)]


class _Accounting(c.Structure):
    _fields_ = [('times', c.c_int64 * 4), ('faults', _U), ('total', _U), ('active', _U), ('terminated', _U)]


class _Startup(c.Structure):
    _fields_ = [('size', _U), ('reserved', c.c_wchar_p), ('desktop', c.c_wchar_p), ('title', c.c_wchar_p),
                ('x', _U), ('y', _U), ('width', _U), ('height', _U), ('xchars', _U), ('ychars', _U),
                ('fill', _U), ('flags', _U), ('show', c.c_uint16), ('reserved_bytes', c.c_uint16),
                ('reserved_pointer', _P), ('input', _P), ('output', _P), ('error', _P)]


class _StartupEx(c.Structure):
    _fields_ = [('startup', _Startup), ('attributes', _P)]


class _ProcessInfo(c.Structure):
    _fields_ = [('process', _P), ('thread', _P), ('pid', _U), ('tid', _U)]


class _Owned(native._Handle):
    def __init__(self, api: _Windows, value: int, kind: str) -> None:
        super().__init__(api, value)
        self.kind = kind


class _Windows(native._Windows):
    def __init__(self) -> None:
        _require(os.name == 'nt' and c.sizeof(_P) == 8 and platform.machine().lower() in ('amd64', 'x86_64'),
                 'native_build_windows_x64')
        super().__init__()
        k, a = self.k, self.a
        for name, args, result in (
            ('GetCurrentProcess', [], _P), ('GetCurrentThread', [], _P),
            ('GetWindowsDirectoryW', [c.c_wchar_p, _U], _U),
            ('GetHandleInformation', [_P, c.POINTER(_U)], c.c_int),
            ('GetFileInformationByHandleEx', [_P, c.c_int, _P, _U], c.c_int),
            ('FindFirstFileNameW', [c.c_wchar_p, _U, c.POINTER(_U), c.c_wchar_p], _P),
            ('FindNextFileNameW', [_P, c.POINTER(_U), c.c_wchar_p], c.c_int),
            ('FindClose', [_P], c.c_int),
            ('CreateJobObjectW', [c.POINTER(_Security), c.c_wchar_p], _P),
            ('SetInformationJobObject', [_P, c.c_int, _P, _U], c.c_int),
            ('QueryInformationJobObject', [_P, c.c_int, _P, _U, _P], c.c_int),
            ('InitializeProcThreadAttributeList', [_P, _U, _U, c.POINTER(c.c_size_t)], c.c_int),
            ('UpdateProcThreadAttribute', [_P, _U, c.c_size_t, _P, c.c_size_t, _P, _P], c.c_int),
            ('DeleteProcThreadAttributeList', [_P], None),
            ('CreateProcessW', [c.c_wchar_p, c.c_wchar_p, c.POINTER(_Security), c.POINTER(_Security),
                                c.c_int, _U, _P, c.c_wchar_p, c.POINTER(_StartupEx), c.POINTER(_ProcessInfo)], c.c_int),
            ('IsProcessInJob', [_P, _P, c.POINTER(c.c_int)], c.c_int),
            ('ResumeThread', [_P], _U), ('WaitForSingleObject', [_P, _U], _U),
            ('GetExitCodeProcess', [_P, c.POINTER(_U)], c.c_int), ('TerminateJobObject', [_P, _U], c.c_int),
        ):
            self._bind(k, name, args, result)
        self._bind(a, 'OpenProcessToken', [_P, _U, c.POINTER(_P)], c.c_int)
        self._bind(a, 'OpenThreadToken', [_P, _U, c.c_int, c.POINTER(_P)], c.c_int)
        self._bind(a, 'GetTokenInformation', [_P, c.c_int, _P, _U, c.POINTER(_U)], c.c_int)

    def free_local(self, pointer: _P) -> None:
        value, pointer.value = pointer.value, None
        if value:
            _require(not self.k.LocalFree(value), 'native_build_local_release')

    def close(self, handle: native._Handle) -> None:
        value, handle.value = handle.value, 0
        _require(bool(value) and self.k.CloseHandle(value), 'native_build_close')

    def operator(self) -> str:
        token, thread = _P(), _P()
        if self.a.OpenThreadToken(self.k.GetCurrentThread(), 8, True, c.byref(thread)):
            self.close(native._Handle(self, int(thread.value or 0)))
            raise BuildNativeRefused('native_build_impersonation')
        _require(c.get_last_error() == 1008, 'native_build_thread_token')
        _require(self.a.OpenProcessToken(self.k.GetCurrentProcess(), 8, c.byref(token)), 'native_build_token')
        try:
            elevation, used = _U(), _U()
            _require(self.a.GetTokenInformation(token, 20, c.byref(elevation), 4, c.byref(used))
                     and used.value == 4 and elevation.value == 0, 'native_build_must_be_unelevated')
            size = _U()
            probe = self.a.GetTokenInformation(token, 1, None, 0, c.byref(size))
            _require(not probe and c.get_last_error() == 122 and 8 <= size.value <= 4096, 'native_build_user')
            buffer = c.create_string_buffer(size.value)
            _require(self.a.GetTokenInformation(token, 1, buffer, len(buffer), c.byref(size)), 'native_build_user')
            sid = self.sid_text(c.cast(buffer, c.POINTER(_P))[0])
            _require(sid.startswith('S-1-5-21-'), 'native_build_account')
            return sid
        finally:
            self.close(native._Handle(self, int(token.value or 0)))

    def descriptor(self, sid: str, directory: bool, *, kernel_object: bool = False) -> _P:
        _require(not kernel_object or not directory, 'native_build_descriptor_kind')
        flags = 'OICI' if directory else ''
        # FILE_ALL_ACCESS is not PROCESS/THREAD_ALL_ACCESS. GA is mapped by
        # the kernel object type; the trusted principal set stays identical.
        rights = 'GA' if kernel_object else 'FA'
        text = f'O:{sid}G:{sid}D:P(A;{flags};{rights};;;{sid})(A;{flags};{rights};;;SY)(A;{flags};{rights};;;BA)'
        output = _P()
        _require(self.a.ConvertStringSecurityDescriptorToSecurityDescriptorW(text, 1, c.byref(output), None),
                 'native_build_descriptor')
        return output

    def relative_build(self, parent: native._Handle, name: str, *, directory: bool, create: bool = False,
                       sid: str = '', writable: bool = False) -> native._Handle:
        native._component(name)
        buffer = c.create_unicode_buffer(name)
        text = native._Unicode(len(name) * 2, (len(name) + 1) * 2, c.cast(buffer, c.c_wchar_p))
        descriptor = self.descriptor(sid, directory) if create else _P()
        output, status = _P(), native._IoStatus()
        try:
            attributes = native._ObjectAttributes(c.sizeof(native._ObjectAttributes), parent.value,
                                                   c.pointer(text), 0x1040, descriptor, None)
            access = (0x1200a7 if create else 0x1200a1) if directory else (0xc0120080 if writable else 0x80120080)
            result = self.n.NtCreateFile(c.byref(output), access, c.byref(attributes), c.byref(status), None,
                                         0, 3 if directory else 1, 2 if create else 1,
                                         0x200020 | (1 if directory else 0x40), None, 0)
            _require(result == 0 and output.value not in (None, c.c_void_p(-1).value)
                     and status.information == (2 if create else 1), 'native_build_relative_open')
            self.free_local(descriptor)
            handle = native._Handle(self, int(output.value or 0))
            output.value = None
            return handle
        finally:
            unknown = False
            if output.value and output.value != c.c_void_p(-1).value:
                try:
                    self.close(native._Handle(self, output.value))
                except BaseException:
                    unknown = True
            try:
                self.free_local(descriptor)
            except BaseException:
                unknown = True
            _require(not unknown, 'native_build_open_release')

    def require_case_insensitive(self, handle: native._Handle) -> None:
        flags = _U()
        _require(self.k.GetFileInformationByHandleEx(handle.value, 23, c.byref(flags), 4)
                 and flags.value == 0, 'native_build_case_sensitive_directory')

    def aliases(self, path: str) -> tuple[str, ...]:
        # Called only with a fixed selected tool path under held ancestry, or
        # by ordinary fixture input observation. No alias grants authorization.
        native._path_parts(path)
        size, buffer = _U(1024), c.create_unicode_buffer(1024)
        handle = self.k.FindFirstFileNameW(path, 0, c.byref(size), buffer)
        _require(handle not in (None, c.c_void_p(-1).value), 'native_build_alias_query')
        result: list[str] = []
        try:
            for _ in range(8):
                relative = str(buffer.value)
                _require(relative.startswith('\\') and not relative.startswith('\\\\')
                         and 1 < len(relative) <= 237, 'native_build_alias_extent')
                full = path[:2] + relative
                native._path_parts(full)
                _require(full.lower() not in {name.lower() for name in result}, 'native_build_alias_duplicate')
                result.append(full)
                size.value = len(buffer)
                if not self.k.FindNextFileNameW(handle, c.byref(size), buffer):
                    _require(c.get_last_error() == 38, 'native_build_alias_query')
                    return tuple(sorted(result, key=str.lower))
            raise BuildNativeRefused('native_build_alias_bound')
        finally:
            _require(self.k.FindClose(handle), 'native_build_alias_close')

    def final_name(self, handle: native._Handle) -> str:
        buffer = c.create_unicode_buffer(512)
        size = self.k.GetFinalPathNameByHandleW(handle.value, buffer, len(buffer), 1)
        _require(0 < size < len(buffer), 'native_build_final_name')
        return str(buffer.value)

    def names(self, handle: native._Handle) -> set[str]:
        buffer = c.create_string_buffer(65536)
        names: set[str] = set()
        aliases: set[str] = set()
        for page in range(16):
            c.memset(buffer, 0, len(buffer))
            if not self.k.GetFileInformationByHandleEx(handle.value, 11 if page == 0 else 10, buffer, len(buffer)):
                _require(c.get_last_error() == 18, 'native_build_directory_query')
                return names
            raw, offset = buffer.raw, 0
            while True:
                _require(0 <= offset <= len(raw) - 104, 'native_build_directory_extent')
                next_offset = int.from_bytes(raw[offset:offset + 4], 'little')
                size = int.from_bytes(raw[offset + 60:offset + 64], 'little')
                _require(2 <= size <= 240 and size % 2 == 0 and offset + 104 + size <= len(raw), 'native_build_directory_extent')
                name = raw[offset + 104:offset + 104 + size].decode('utf-16le')
                if name not in ('.', '..'):
                    native._component(name)
                    _require(name.lower() not in aliases and len(names) < 512, 'native_build_directory_alias')
                    names.add(name)
                    aliases.add(name.lower())
                if not next_offset:
                    break
                _require(next_offset % 8 == 0 and next_offset >= 104 + size
                         and next_offset <= len(raw) - offset - 104, 'native_build_directory_extent')
                offset += next_offset
        raise BuildNativeRefused('native_build_directory_bound')


@dataclass(eq=False)
class _Job:
    handle: native._Handle
    attempted: bool = False
    closed: bool = False
    root_exited: bool = False
    empty: bool = False
    code: int | None = None
    observed_total: int = 0
    observed_peak_active: int = 0


class _WindowsBuildKernel:
    def __init__(self, window: _Window) -> None:
        self.window = window
        self.api: _Windows | None = None
        self.sid = ''
        self.recipe: build.ValidatorBuildRecipe | None = None
        self.prepared = False
        self.jobs: list[_Job] = []
        self.created = self.finished = 0
        self.process_jobs: dict[int, _Job] = {}

    def cancelled(self) -> bool:
        return self.window.cancelled()

    def _api(self) -> _Windows:
        _require(self.api is not None, 'native_build_host_first')
        assert self.api is not None
        return self.api

    def require_unelevated_host(self, recipe: build.ValidatorBuildRecipe) -> None:
        _require(self.api is None and self.recipe is None, 'native_build_host_once')
        self.window.check()
        api = _Windows()
        sid = api.operator()
        buffer = c.create_unicode_buffer(512)
        count = api.k.GetWindowsDirectoryW(buffer, len(buffer))
        _require(0 < count < len(buffer) and str(buffer.value).lower() == dict(recipe.environment)['SystemRoot'].lower(),
                 'native_build_windows_root')
        self.api, self.sid, self.recipe = api, sid, recipe

    def prepare(self, recipe: build.ValidatorBuildRecipe) -> owner._BuildInputs:
        from night_shifts.bootstrap_native_build_stage import _BuildStage
        _require(recipe is self.recipe and not self.prepared, 'native_build_prepare_once')
        self.prepared = True
        return _BuildStage(self._api(), self.sid, recipe, self.window,
                           lambda: self.finished, lambda: not any(job.attempted and not job.closed for job in self.jobs)).acquire()

    def new_job(self) -> object:
        api = self._api()
        _require(self.prepared and len(self.jobs) < 2 and all(job.closed for job in self.jobs), 'native_build_job_order')
        self.window.check()
        descriptor = api.descriptor(self.sid, False, kernel_object=True)
        raw = 0
        try:
            security = _Security(c.sizeof(_Security), descriptor, 0)
            raw = api.k.CreateJobObjectW(c.byref(security), None)
            _require(raw, 'native_build_job_create')
            limits = _Limits()
            limits.basic.flags, limits.basic.active = 0x2008, build.BUILD_ACTIVE_PROCESS_LIMIT
            _require(api.k.SetInformationJobObject(raw, 9, c.byref(limits), c.sizeof(limits)), 'native_build_job_limits')
            actual, flags = _Limits(), _U()
            _require(api.k.QueryInformationJobObject(raw, 9, c.byref(actual), c.sizeof(actual), None)
                     and actual.basic.flags == 0x2008 and actual.basic.active == build.BUILD_ACTIVE_PROCESS_LIMIT
                     and api.k.GetHandleInformation(raw, c.byref(flags)) and flags.value == 0, 'native_build_job_readback')
            api.free_local(descriptor)
            job = _Job(native._Handle(api, raw))
            self.jobs.append(job)
            raw = 0
            return job
        finally:
            try:
                if raw:
                    api.close(native._Handle(api, raw))
            finally:
                api.free_local(descriptor)

    def _job(self, value: object) -> _Job:
        _require(type(value) is _Job and any(value is job for job in self.jobs), 'native_build_job_identity')
        assert isinstance(value, _Job)
        _require(not value.closed and value.handle.value, 'native_build_job_closed')
        return value

    def _handle(self, value: object, kind: str) -> _Owned:
        _require(type(value) is _Owned and value.kind == kind and value.value, 'native_build_handle')
        assert isinstance(value, _Owned)
        return value

    def create_suspended(self, job: object, command: tuple[str, ...], cwd: str,
                         environment: tuple[tuple[str, str], ...]) -> owner._CompilerChild:
        api, state = self._api(), self._job(job)
        recipe = self.recipe
        _require(recipe is not None and not state.attempted and self.created < 2, 'native_build_create_order')
        assert recipe is not None
        _require(command == recipe.commands[self.created] and cwd == recipe.working_directory
                 and environment == recipe.environment, 'native_build_fixed_command')
        self.window.check()
        state.attempted = True
        self.created += 1
        text = subprocess.list2cmdline(command)
        _require(len(text) < 8192 and '\0' not in text, 'native_build_command_bound')
        block = ''.join(key + '=' + value + '\0' for key, value in sorted(environment, key=lambda item: item[0].lower())) + '\0'
        env = c.create_unicode_buffer(block)
        size, info, ready = c.c_size_t(), _ProcessInfo(), False
        descriptor = _P()
        attributes: Any = None
        try:
            probe = api.k.InitializeProcThreadAttributeList(None, 1, 0, c.byref(size))
            _require(not probe and c.get_last_error() == 122 and 1 <= size.value <= 4096, 'native_build_attributes')
            attributes = c.create_string_buffer(size.value)
            _require(api.k.InitializeProcThreadAttributeList(attributes, 1, 0, c.byref(size)), 'native_build_attributes')
            ready = True
            jobs = (_P * 1)(state.handle.value)
            _require(api.k.UpdateProcThreadAttribute(attributes, 0, 0x2000d, jobs, c.sizeof(jobs), None, None),
                     'native_build_atomic_job_required')
            descriptor = api.descriptor(self.sid, False, kernel_object=True)
            security = _Security(c.sizeof(_Security), descriptor, 0)
            startup = _StartupEx()
            startup.startup.size, startup.attributes = c.sizeof(_StartupEx), c.cast(attributes, _P)
            # No inherited console, file/pipe handles or capture buffers. Both
            # success banners and compiler diagnostics are intentionally discarded.
            startup.startup.flags = 0x100
            _require(api.k.CreateProcessW(command[0], c.create_unicode_buffer(text), c.byref(security), c.byref(security),
                                          False, 0x08080404, env, cwd, c.byref(startup), c.byref(info)),
                     'native_build_atomic_create')
            _require(info.process and info.thread and info.process != info.thread and info.pid and info.tid,
                     'native_build_process_info')
            if ready:
                ready = False
                api.k.DeleteProcThreadAttributeList(attributes)
            api.free_local(descriptor)
            process, thread = _Owned(api, int(info.process), 'process'), _Owned(api, int(info.thread), 'thread')
            self.process_jobs[id(process)] = state
            answer = owner._CompilerChild(process, thread, int(info.pid))
            info.process = info.thread = None
            return answer
        finally:
            unknown = False
            for value in (info.thread, info.process):
                if value:
                    try:
                        api.close(native._Handle(api, int(value)))
                    except BaseException:
                        unknown = True
            if ready:
                ready = False
                api.k.DeleteProcThreadAttributeList(attributes)
            try:
                api.free_local(descriptor)
            except BaseException:
                unknown = True
            _require(not unknown, 'native_build_create_release')

    def member(self, process: object, job: object) -> bool:
        output = c.c_int()
        _require(self._api().k.IsProcessInJob(self._handle(process, 'process').value,
                                            self._job(job).handle.value, c.byref(output)), 'native_build_membership')
        return bool(output.value)

    def resume(self, thread: object) -> int:
        return int(self._api().k.ResumeThread(self._handle(thread, 'thread').value))

    def wait(self, process: object, milliseconds: int) -> int:
        _require(type(milliseconds) is int and 0 <= milliseconds <= 100, 'native_build_wait_bound')
        handle = self._handle(process, 'process')
        # Cooperative cumulative accounting, not a native total-creation quota
        # or pre-execution identity check. Native concurrency remains hard-capped.
        self.active(self.process_jobs[id(handle)])
        result = int(self._api().k.WaitForSingleObject(handle.value, milliseconds))
        self.active(self.process_jobs[id(handle)])
        if result == 0:
            self.process_jobs[id(handle)].root_exited = True
        return result

    def exit_code(self, process: object) -> int:
        handle, code = self._handle(process, 'process'), _U()
        _require(self._api().k.GetExitCodeProcess(handle.value, c.byref(code)), 'native_build_exit_code')
        self.process_jobs[id(handle)].code = int(code.value)
        return int(code.value)

    def active(self, job: object) -> int:
        state, result = self._job(job), _Accounting()
        _require(self._api().k.QueryInformationJobObject(state.handle.value, 1, c.byref(result), c.sizeof(result), None),
                 'native_build_accounting')
        # Basic accounting can include helpers still being removed after exit;
        # it is not the native limit's instantaneous enforcement counter. Keep
        # the separately set/read-back active limit unchanged, and bound these
        # observations by the fixed cumulative extent (including the root).
        _require(1 <= result.total <= build.BUILD_TOTAL_PROCESS_LIMIT
                 and result.active <= result.total, 'native_build_process_extent')
        state.observed_total = max(state.observed_total, int(result.total))
        state.observed_peak_active = max(state.observed_peak_active, int(result.active))
        state.empty = result.active == 0
        return int(result.active)

    def stop(self, job: object) -> None:
        _require(self._api().k.TerminateJobObject(self._job(job).handle.value, 124), 'native_build_stop')

    def pause(self, milliseconds: int) -> None:
        _require(type(milliseconds) is int and 1 <= milliseconds <= 20, 'native_build_pause_bound')
        time.sleep(milliseconds / 1000)

    def close(self, handle: object) -> None:
        if type(handle) is _Job:
            state = self._job(handle)
            state.closed = True  # disarm even if CloseHandle outcome is unknown
            self._api().close(state.handle)
            if state.root_exited and state.empty and state.code == 0:
                self.finished += 1
        else:
            _require(type(handle) is _Owned, 'native_build_handle')
            assert isinstance(handle, _Owned)
            self._api().close(handle)
