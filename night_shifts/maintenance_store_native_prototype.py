"""Isolated Windows host-store MARKER prototype; NOT a credential writer.

No production caller, deployment, key generation, media, WMI, serial or VM use.
Only the fixed NON-SECRET marker can be written. Native positive fixtures use
substituted ownership; they do not attest production/effective-token protection.
Failures retain new objects for review. No permission repair or fallback.
"""
from __future__ import annotations

import ctypes as c
import os
import re
from contextlib import ExitStack
from dataclasses import dataclass
from typing import Any

from night_shifts.maintenance_credentials_prototype import (
    ADMINS_SID,
    SYSTEM_SID,
    CredentialPrototypeRefused,
    check_host_key_acl_model,
)
from night_shifts.ubuntu_preparation_control import AclRule, AclSnapshot

MARKER = b'NON-SECRET host-store native prototype marker v1\n'
_PRIVATE_SIDS = (SYSTEM_SID, ADMINS_SID)  # Never runtime-selectable.
_READ_CONTROL = 0x20000
_SYNCHRONIZE = 0x100000
_READ_ATTRIBUTES = 0x80
_DIRECTORY = 0x10
_REPARSE = 0x400
_BAD_ATTRIBUTES = _REPARSE | 0x200 | 0x800 | 0x1000 | 0x4000
_U32 = c.c_uint32
_PTR = c.c_void_p


class NativeStoreRefused(RuntimeError):
    """Fixed reason plus optional numeric Windows error; no raw OS/path text."""

    def __init__(self, code: str, winerror: int | None = None) -> None:
        self.code = code
        self.winerror = winerror
        super().__init__(code if winerror is None else f'{code}: win32={winerror}')


@dataclass(frozen=True)
class FileIdentity:
    volume: int
    index: int


@dataclass(frozen=True)
class Observation:
    identity: FileIdentity
    attributes: int
    links: int
    size: int
    acl: AclSnapshot
    protected: bool


@dataclass(frozen=True)
class MarkerResult:
    """Non-secret observations, NOT credential-use/inspection authorization."""

    store: FileIdentity
    marker: FileIdentity
    marker_bytes: int


class _Unicode(c.Structure):
    _fields_ = [('length', c.c_uint16), ('maximum', c.c_uint16), ('buffer', c.c_wchar_p)]


class _ObjectAttributes(c.Structure):
    _fields_ = [('length', _U32), ('root', _PTR), ('name', c.POINTER(_Unicode)),
                ('attributes', _U32), ('security', _PTR), ('qos', _PTR)]


class _StatusValue(c.Union):
    _fields_ = [('status', c.c_int32), ('pointer', _PTR)]


class _IoStatus(c.Structure):
    _fields_ = [('value', _StatusValue), ('information', c.c_size_t)]


class _FileTime(c.Structure):
    _fields_ = [('low', _U32), ('high', _U32)]


class _FileInfo(c.Structure):
    _fields_ = [('attributes', _U32), ('created', _FileTime), ('accessed', _FileTime),
                ('written', _FileTime), ('volume', _U32), ('size_high', _U32),
                ('size_low', _U32), ('links', _U32), ('index_high', _U32), ('index_low', _U32)]


class _AclSize(c.Structure):
    _fields_ = [('count', _U32), ('used', _U32), ('free', _U32)]


class _AceHeader(c.Structure):
    _fields_ = [('kind', c.c_ubyte), ('flags', c.c_ubyte), ('size', c.c_uint16)]


def _component(value: str) -> None:
    if (type(value) is not str or not 1 <= len(value) <= 120 or
            re.fullmatch(r'[A-Za-z0-9_ .()\-]+', value) is None or
            value in ('.', '..') or value.endswith((' ', '.')) or
            re.fullmatch(r'(?i)(?:CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])(?:\..*)?', value)):
        raise NativeStoreRefused('path_component')


def _path_parts(path: str) -> tuple[str, tuple[str, ...]]:
    # Validate BEFORE normalization: no UNC/device/relative/ADS/dot components.
    if (type(path) is not str or not 4 <= len(path) <= 240 or
            re.match(r'^[A-Za-z]:\\', path) is None):
        raise NativeStoreRefused('local_absolute_path')
    parts = tuple(path[3:].split('\\'))
    for part in parts:
        _component(part)
    return path[:3], parts


def _check_shape(value: Observation, *, directory: bool) -> None:
    if (value.attributes & _BAD_ATTRIBUTES or bool(value.attributes & _DIRECTORY) != directory or
            value.links != 1 or value.identity.index == 0):
        raise NativeStoreRefused('object_shape')


def _check_private(value: Observation, *, directory: bool) -> None:
    _check_shape(value, directory=directory)
    try:
        check_host_key_acl_model(value.acl, protected=value.protected, reparse=False,
                                 links=value.links, directory=directory)
    except CredentialPrototypeRefused:
        raise NativeStoreRefused('private_security') from None


def _check_ancestor(value: Observation) -> None:
    _check_shape(value, directory=True)
    if value.acl.owner not in _PRIVATE_SIDS or not value.acl.rules:
        raise NativeStoreRefused('ancestor_security')
    # General read/execute and creation of unrelated siblings are acceptable on
    # ancestors, NOT delete-child, ACL/owner mutation, write-EA/attributes or
    # generic write/all. The anchor itself must pass the strict private profile.
    harmless = 0x1200A9 | 0x00000002 | 0x00000004 | 0x80000000 | 0x20000000
    for rule in value.acl.rules:
        if rule.kind not in (0, 1) or rule.flags & ~0x1F:
            raise NativeStoreRefused('ancestor_security')
        if rule.flags & 8:  # inherit-only does not grant access to this object
            continue
        if rule.kind == 0 and rule.sid not in _PRIVATE_SIDS and rule.mask & ~harmless:
            raise NativeStoreRefused('ancestor_security')


class _Handle:
    def __init__(self, api: _Windows, value: int) -> None:
        self.api = api
        self.value = value

    def __enter__(self) -> _Handle:
        return self

    def __exit__(self, *_: Any) -> None:
        if self.value:
            value, self.value = self.value, 0
            if not self.api.k.CloseHandle(value):
                raise NativeStoreRefused('close_handle', c.get_last_error())


class _Windows:
    """Small handle-based layer; no subprocess, ACL repair or fallback."""

    def __init__(self) -> None:
        if os.name != 'nt':
            raise NativeStoreRefused('windows_required')
        self.k = c.WinDLL('kernel32', use_last_error=True)
        self.a = c.WinDLL('advapi32', use_last_error=True)
        self.n = c.WinDLL('ntdll', use_last_error=True)
        self._bind(self.k, 'CreateFileW', [c.c_wchar_p, _U32, _U32, _PTR, _U32, _U32, _PTR], _PTR)
        self._bind(self.k, 'CloseHandle', [_PTR], c.c_int)
        self._bind(self.k, 'GetFileType', [_PTR], _U32)
        self._bind(self.k, 'GetFileInformationByHandle', [_PTR, c.POINTER(_FileInfo)], c.c_int)
        self._bind(self.k, 'GetDriveTypeW', [c.c_wchar_p], _U32)
        self._bind(self.k, 'GetFinalPathNameByHandleW', [_PTR, c.c_wchar_p, _U32, _U32], _U32)
        self._bind(self.k, 'GetVolumeInformationByHandleW',
                   [_PTR, c.c_wchar_p, _U32, _PTR, _PTR, _PTR, c.c_wchar_p, _U32], c.c_int)
        self._bind(self.k, 'LocalFree', [_PTR], _PTR)
        self._bind(self.k, 'WriteFile', [_PTR, _PTR, _U32, c.POINTER(_U32), _PTR], c.c_int)
        self._bind(self.k, 'ReadFile', [_PTR, _PTR, _U32, c.POINTER(_U32), _PTR], c.c_int)
        self._bind(self.k, 'FlushFileBuffers', [_PTR], c.c_int)
        self._bind(self.k, 'SetFilePointerEx', [_PTR, c.c_int64, _PTR, _U32], c.c_int)
        self._bind(self.a, 'ConvertStringSecurityDescriptorToSecurityDescriptorW',
                   [c.c_wchar_p, _U32, c.POINTER(_PTR), _PTR], c.c_int)
        self._bind(self.a, 'GetSecurityInfo',
                   [_PTR, c.c_int, _U32, c.POINTER(_PTR), _PTR, c.POINTER(_PTR), _PTR,
                    c.POINTER(_PTR)], _U32)
        self._bind(self.a, 'GetSecurityDescriptorControl',
                   [_PTR, c.POINTER(c.c_uint16), c.POINTER(_U32)], c.c_int)
        self._bind(self.a, 'GetAclInformation', [_PTR, _PTR, _U32, c.c_int], c.c_int)
        self._bind(self.a, 'GetAce', [_PTR, _U32, c.POINTER(_PTR)], c.c_int)
        self._bind(self.a, 'IsValidSid', [_PTR], c.c_int)
        self._bind(self.a, 'GetLengthSid', [_PTR], _U32)
        self._bind(self.a, 'ConvertSidToStringSidW', [_PTR, c.POINTER(_PTR)], c.c_int)
        self._bind(self.a, 'ConvertStringSidToSidW', [c.c_wchar_p, c.POINTER(_PTR)], c.c_int)
        self._bind(self.a, 'CheckTokenMembership', [_PTR, _PTR, c.POINTER(c.c_int)], c.c_int)
        self._bind(self.n, 'NtCreateFile',
                   [c.POINTER(_PTR), _U32, c.POINTER(_ObjectAttributes), c.POINTER(_IoStatus),
                    _PTR, _U32, _U32, _U32, _U32, _PTR, _U32], c.c_int32)
        self._bind(self.n, 'RtlNtStatusToDosError', [c.c_int32], _U32)

    @staticmethod
    def _bind(library: Any, name: str, arguments: list[Any], result: Any) -> None:
        function = getattr(library, name)
        function.argtypes, function.restype = arguments, result

    def require_admin(self) -> None:
        sid = _PTR()
        if not self.a.ConvertStringSidToSidW(ADMINS_SID, c.byref(sid)):
            raise NativeStoreRefused('token_query', c.get_last_error())
        try:
            member = c.c_int()
            if not self.a.CheckTokenMembership(None, sid, c.byref(member)):
                raise NativeStoreRefused('token_query', c.get_last_error())
            if not member.value:
                raise NativeStoreRefused('enabled_administrator_required')
        finally:
            self.k.LocalFree(sid)

    def sid_text(self, sid: Any) -> str:
        if not sid or not self.a.IsValidSid(sid):
            raise NativeStoreRefused('invalid_sid')
        output = _PTR()
        if not self.a.ConvertSidToStringSidW(sid, c.byref(output)):
            raise NativeStoreRefused('sid_query', c.get_last_error())
        try:
            return str(c.wstring_at(output))
        finally:
            self.k.LocalFree(output)

    def security(self, handle: _Handle) -> tuple[AclSnapshot, bool]:
        owner, dacl, descriptor = _PTR(), _PTR(), _PTR()
        error = self.a.GetSecurityInfo(handle.value, 1, 5, c.byref(owner), None,
                                       c.byref(dacl), None, c.byref(descriptor))
        if error:
            raise NativeStoreRefused('security_query', int(error))
        try:
            if not descriptor or not owner or not dacl:
                raise NativeStoreRefused('missing_security')
            control, revision = c.c_uint16(), _U32()
            if not self.a.GetSecurityDescriptorControl(descriptor, c.byref(control), c.byref(revision)):
                raise NativeStoreRefused('security_control', c.get_last_error())
            if not control.value & 4:
                raise NativeStoreRefused('missing_dacl')
            size = _AclSize()
            if not self.a.GetAclInformation(dacl, c.byref(size), c.sizeof(size), 2):
                raise NativeStoreRefused('acl_query', c.get_last_error())
            if not 1 <= size.count <= 128 or not 8 <= size.used <= 65536:
                raise NativeStoreRefused('acl_bounds')
            rules = []
            for index in range(size.count):
                ace = _PTR()
                if not self.a.GetAce(dacl, index, c.byref(ace)) or not ace.value:
                    raise NativeStoreRefused('ace_query', c.get_last_error())
                header = _AceHeader.from_address(ace.value)
                if header.kind not in (0, 1) or header.size < 16:
                    raise NativeStoreRefused('unsupported_ace')
                # Bound the SID's subauthority array before asking Windows to
                # inspect it. Only simple ACCESS_ALLOWED/DENIED ACEs are parsed.
                subauthorities = c.c_ubyte.from_address(ace.value + 9).value
                if subauthorities > 15 or 16 + 4 * subauthorities != header.size:
                    raise NativeStoreRefused('ace_sid_bounds')
                sid = _PTR(ace.value + 8)
                if not self.a.IsValidSid(sid) or self.a.GetLengthSid(sid) + 8 != header.size:
                    raise NativeStoreRefused('ace_sid_bounds')
                rules.append(AclRule(self.sid_text(sid), _U32.from_address(ace.value + 4).value,
                                     header.flags, header.kind))
            return AclSnapshot(self.sid_text(owner), tuple(rules)), bool(control.value & 0x1000)
        finally:
            self.k.LocalFree(descriptor)

    def observe(self, handle: _Handle) -> Observation:
        info = _FileInfo()
        if self.k.GetFileType(handle.value) != 1:
            raise NativeStoreRefused('not_disk_file')
        if not self.k.GetFileInformationByHandle(handle.value, c.byref(info)):
            raise NativeStoreRefused('file_query', c.get_last_error())
        acl, protected = self.security(handle)
        return Observation(FileIdentity(info.volume, (info.index_high << 32) | info.index_low),
                           info.attributes, info.links, (info.size_high << 32) | info.size_low,
                           acl, protected)

    def root(self, drive: str) -> _Handle:
        if self.k.GetDriveTypeW(drive) != 3:
            raise NativeStoreRefused('fixed_local_volume_required')
        value = self.k.CreateFileW(drive, _READ_CONTROL | _READ_ATTRIBUTES | _SYNCHRONIZE | 0x20,
                                   3, None, 3, 0x02200000, None)
        if value in (None, c.c_void_p(-1).value):
            raise NativeStoreRefused('root_open', c.get_last_error())
        handle = _Handle(self, value)
        try:
            name = c.create_unicode_buffer(128)
            length = self.k.GetFinalPathNameByHandleW(value, name, len(name), 1)  # volume GUID
            if (not 0 < length < len(name) or
                    re.fullmatch(r'\\\\\?\\Volume\{[0-9a-fA-F-]{36}\}\\', name.value) is None):
                raise NativeStoreRefused('volume_root_identity')
            filesystem = c.create_unicode_buffer(32)
            if not self.k.GetVolumeInformationByHandleW(value, None, 0, None, None, None,
                                                       filesystem, len(filesystem)):
                raise NativeStoreRefused('volume_query', c.get_last_error())
            if filesystem.value != 'NTFS':
                raise NativeStoreRefused('ntfs_required')
            return handle
        except BaseException:
            handle.__exit__()
            raise

    def relative(self, parent: _Handle, name: str, *, directory: bool,
                 create: bool, sddl: str | None = None, writable: bool = False) -> _Handle:
        _component(name)
        if create != (sddl is not None):
            raise NativeStoreRefused('creation_descriptor_required')
        buffer = c.create_unicode_buffer(name)
        text = _Unicode(len(name) * 2, (len(name) + 1) * 2, c.cast(buffer, c.c_wchar_p))
        descriptor = _PTR()
        if sddl is not None and not self.a.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                sddl, 1, c.byref(descriptor), None):
            raise NativeStoreRefused('creation_descriptor', c.get_last_error())
        try:
            # OBJ_CASE_INSENSITIVE | OBJ_DONT_REPARSE. Child names are single
            # components relative to held directory handles, not re-resolved paths.
            attributes = _ObjectAttributes(c.sizeof(_ObjectAttributes), parent.value,
                                           c.pointer(text), 0x1040, descriptor, None)
            output, status = _PTR(), _IoStatus()
            access = _READ_CONTROL | _READ_ATTRIBUTES | _SYNCHRONIZE | (0x20 if directory else 0)
            if writable:
                access |= 6 if directory else 0xC0000000
            # Held directories permit read/write sharing but NO delete. The
            # marker leaf uses share mode zero for data/delete access. Windows
            # can still allow metadata-only opens; DACL protection is separate.
            # Conflicts refuse, never relax.
            sharing = 3 if directory else 0
            options = 0x00200000 | 0x20 | (1 if directory else 0x40)
            result = self.n.NtCreateFile(c.byref(output), access, c.byref(attributes),
                                         c.byref(status), None, 0, sharing,
                                         2 if create else 1, options, None, 0)
            if result != 0:
                if output.value:
                    _Handle(self, output.value).__exit__()
                raise NativeStoreRefused('relative_create' if create else 'relative_open',
                                         int(self.n.RtlNtStatusToDosError(result)))
            handle = _Handle(self, int(output.value or 0))
            if not handle.value or status.information != (2 if create else 1):
                handle.__exit__()
                raise NativeStoreRefused('unexpected_create_disposition')
            return handle
        finally:
            if descriptor:
                self.k.LocalFree(descriptor)

    def write_marker(self, handle: _Handle) -> None:
        payload = c.create_string_buffer(MARKER)
        count = _U32()
        if not self.k.WriteFile(handle.value, payload, len(MARKER), c.byref(count), None):
            raise NativeStoreRefused('marker_write', c.get_last_error())
        if count.value != len(MARKER):
            raise NativeStoreRefused('marker_short_write')
        if not self.k.FlushFileBuffers(handle.value):
            raise NativeStoreRefused('marker_flush', c.get_last_error())
        if not self.k.SetFilePointerEx(handle.value, 0, None, 0):
            raise NativeStoreRefused('marker_seek', c.get_last_error())
        output = c.create_string_buffer(len(MARKER) + 1)
        if not self.k.ReadFile(handle.value, output, len(output), c.byref(count), None):
            raise NativeStoreRefused('marker_read', c.get_last_error())
        if count.value != len(MARKER) or output.raw[:count.value] != MARKER:
            raise NativeStoreRefused('marker_mismatch')


def _sddl(*, directory: bool) -> str:
    flags = 'OICI' if directory else ''
    return f'O:BAG:BAD:P(A;{flags};FA;;;SY)(A;{flags};FA;;;BA)'


def _same(before: Observation, after: Observation, *, marker_written: bool = False) -> None:
    # ARCHIVE may be set during a write; it does not weaken this protection.
    # Conservative: even a directory-length change refuses this prototype.
    if (before.identity != after.identity or before.links != after.links or
            before.acl != after.acl or before.protected != after.protected or
            (before.attributes & ~0x20) != (after.attributes & ~0x20) or
            after.size != (len(MARKER) if marker_written else before.size)):
        raise NativeStoreRefused('object_drift')


def probe_new_store(anchor_path: str, attempt_id: str) -> MarkerResult:
    """Create ONLY a fresh marker store beneath an EXISTING strict host anchor.

    No private bytes accepted/generated. Anchor provisioning/path pinning, native
    effective-token access, crypto runtime and deployment are separate gates. No
    production caller/authorization. Never repair, reopen an old store or retry.
    """
    drive, parts = _path_parts(anchor_path)
    if type(attempt_id) is not str or re.fullmatch('[0-9a-f]{32}', attempt_id) is None:
        raise NativeStoreRefused('attempt_id')
    api = _Windows()
    api.require_admin()
    with ExitStack() as stack:
        chain: list[tuple[_Handle, Observation]] = []
        handle = stack.enter_context(api.root(drive))
        baseline = api.observe(handle)
        _check_ancestor(baseline)
        chain.append((handle, baseline))
        for index, part in enumerate(parts):
            final = index == len(parts) - 1
            handle = stack.enter_context(api.relative(handle, part, directory=True, create=False,
                                                     writable=final))
            observed = api.observe(handle)
            if observed.identity.volume != baseline.identity.volume:
                raise NativeStoreRefused('volume_changed')
            if final:
                _check_private(observed, directory=True)
            else:
                _check_ancestor(observed)
            chain.append((handle, observed))
        return _probe_on_anchor(api, stack, chain, attempt_id)


def _probe_on_anchor(api: _Windows, stack: ExitStack,
                     chain: list[tuple[_Handle, Observation]], attempt_id: str) -> MarkerResult:
    # Internal fixture seam, NOT an independently trusted anchor-acquisition API.
    anchor = chain[-1][0]
    for handle, before in chain:
        _same(before, api.observe(handle))
    store = stack.enter_context(api.relative(anchor, 'native-probe-' + attempt_id,
                                             directory=True, create=True,
                                             sddl=_sddl(directory=True), writable=True))
    store_before = api.observe(store)
    _check_private(store_before, directory=True)
    leaf = stack.enter_context(api.relative(store, 'probe.bin', directory=False, create=True,
                                            sddl=_sddl(directory=False), writable=True))
    leaf_before = api.observe(leaf)
    _check_private(leaf_before, directory=False)
    if leaf_before.size != 0:
        raise NativeStoreRefused('new_file_not_empty')
    # Reattest every held handle before even the non-secret marker is written.
    for handle, before in [*chain, (store, store_before), (leaf, leaf_before)]:
        _same(before, api.observe(handle))
    api.write_marker(leaf)
    _same(leaf_before, api.observe(leaf), marker_written=True)
    store_after = api.observe(store)
    _same(store_before, store_after)
    for handle, before in chain:
        _same(before, api.observe(handle))
    return MarkerResult(store_after.identity, leaf_before.identity, len(MARKER))
