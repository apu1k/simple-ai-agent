"""Isolated Windows host-store MARKER prototype; NOT a credential writer.

No production caller, deployment, key generation, media, WMI, serial or VM use.
Only the fixed NON-SECRET marker can be written. Native positive fixtures use
substituted ownership; they do not attest production/effective-token protection.
Failures retain new objects for review. No permission repair or fallback.
"""
from __future__ import annotations

import ctypes as c
import hashlib
import json
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

    def __init__(self, code: str, winerror: int | None = None, *,
                 comparison: MetadataComparison | None = None) -> None:
        self.code = code
        self.winerror = winerror
        self.comparison = comparison
        # Structured non-secret differences are opt-in, not raw exception text.
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
class MetadataComparison:
    """Bounded differences of supplied facts; NOT native attestation/authority."""

    object_label: str
    differences: tuple[tuple[str, object, object], ...]
    refusals: tuple[str, ...]
    directory_storage_bytes: tuple[int, int] | None
    expected_file_size: int | None
    archive_change: tuple[int, int] | None

    @property
    def matches(self) -> bool:
        return not self.differences and not self.refusals

    def as_dict(self) -> dict[str, Any]:
        return {
            'v': 1, 'scope': 'supplied_metadata_only', 'object': self.object_label,
            'match': self.matches, 'acceptance': False,
            'cols': ['field', 'before', 'after'],
            'differences': [list(row) for row in self.differences],
            'refused': list(self.refusals),
            'directory_storage_bytes': self.directory_storage_bytes,
            'expected_file_size': self.expected_file_size,
            'archive_change': self.archive_change,
        }

    def to_json(self) -> str:
        try:
            raw = json.dumps(self.as_dict(), ensure_ascii=True, sort_keys=True,
                             separators=(',', ':'), allow_nan=False)
        except (TypeError, ValueError, RecursionError):
            raise NativeStoreRefused('metadata_report_schema') from None
        if len(raw) > 3000 or len(raw.encode('utf-8')) > 3000:
            raise NativeStoreRefused('metadata_report_size')
        return raw


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


def _uint(value: object, bits: int) -> bool:
    return type(value) is int and 0 <= value < 1 << bits


def _sid(value: object) -> bool:
    return (type(value) is str and len(value) <= 184 and
            re.fullmatch(r'S-[0-9]+(?:-[0-9]+)+', value) is not None)


def _validate_metadata(value: Observation) -> None:
    if (type(value) is not Observation or type(value.identity) is not FileIdentity or
            not _uint(value.identity.volume, 32) or not _uint(value.identity.index, 64) or
            not _uint(value.attributes, 32) or not _uint(value.links, 32) or
            not _uint(value.size, 64) or type(value.protected) is not bool or
            type(value.acl) is not AclSnapshot or not _sid(value.acl.owner) or
            type(value.acl.rules) is not tuple or len(value.acl.rules) > 128):
        raise NativeStoreRefused('metadata_schema')
    for rule in value.acl.rules:
        if (type(rule) is not AclRule or not _sid(rule.sid) or not _uint(rule.mask, 32) or
                not _uint(rule.flags, 8) or not _uint(rule.kind, 8)):
            raise NativeStoreRefused('metadata_schema')


def _acl_digest(value: AclSnapshot) -> str:
    # Exact ordered ACE facts, not keys/content or unbounded raw SDDL in reports.
    raw = json.dumps([[r.sid, r.mask, r.flags, r.kind] for r in value.rules],
                     ensure_ascii=True, separators=(',', ':')).encode('ascii')
    return f'{len(value.rules)}:{hashlib.sha256(raw).hexdigest()}'


def compare_metadata(
    before: Observation, after: Observation, *, object_label: str = 'object',
    expected_file_size: int | None = None, allow_archive_change: bool = False,
) -> MetadataComparison:
    """Compare supplied metadata only; never acquire, repair or authorize use.

    A directory's storage length is not a content length. Its changes are
    RECORDED, not silently discarded, while file length stays strict. Native
    type/shape, security policy, provenance, byte checks and claims remain caller
    obligations. No existing failed receipt/fixture is reclassified by this API.
    """
    if (type(object_label) is not str or
            re.fullmatch(r'[a-z][a-z0-9_]{0,31}', object_label) is None or
            (expected_file_size is not None and not _uint(expected_file_size, 64)) or
            type(allow_archive_change) is not bool or
            (allow_archive_change and expected_file_size is None)):
        raise NativeStoreRefused('metadata_policy')
    _validate_metadata(before)
    _validate_metadata(after)
    differences: list[tuple[str, object, object]] = []
    refusals = []
    for label, value in (('before', before), ('after', after)):
        if value.identity.index == 0:
            refusals.append(label + '_zero_identity')
        if value.links != 1:
            refusals.append(label + '_multiple_links')
        if value.attributes & _REPARSE:
            refusals.append(label + '_reparse')
        if value.attributes & (_BAD_ATTRIBUTES & ~_REPARSE):
            refusals.append(label + '_unsupported_attributes')
    before_dir, after_dir = bool(before.attributes & _DIRECTORY), bool(after.attributes & _DIRECTORY)
    both_dirs = before_dir and after_dir
    if expected_file_size is not None:
        if before_dir or after_dir:
            refusals.append('controlled_write_not_regular')
        if before.size != 0:
            refusals.append('controlled_write_not_empty')
    if before.identity != after.identity:
        differences.append(('identity',
                            f'{before.identity.volume:08x}:{before.identity.index:016x}',
                            f'{after.identity.volume:08x}:{after.identity.index:016x}'))
    if before_dir != after_dir:
        differences.append(('kind', 'directory' if before_dir else 'file',
                            'directory' if after_dir else 'file'))
    archive_change = None
    attribute_delta = before.attributes ^ after.attributes
    if attribute_delta and allow_archive_change and not before_dir and not after_dir and not attribute_delta & ~0x20:
        archive_change = (before.attributes, after.attributes)
    elif attribute_delta:
        differences.append(('attributes', f'0x{before.attributes:08x}', f'0x{after.attributes:08x}'))
    if before.links != after.links:
        differences.append(('links', before.links, after.links))
    if before.acl.owner != after.acl.owner:
        differences.append(('owner', before.acl.owner, after.acl.owner))
    if before.acl.rules != after.acl.rules:
        differences.append(('acl', _acl_digest(before.acl), _acl_digest(after.acl)))
    if before.protected != after.protected:
        differences.append(('protected', before.protected, after.protected))
    if not both_dirs:
        expected = before.size if expected_file_size is None else expected_file_size
        if after.size != expected:
            differences.append(('file_size', before.size, after.size))
    report = MetadataComparison(
        object_label, tuple(differences), tuple(refusals),
        (before.size, after.size) if both_dirs and before.size != after.size else None,
        expected_file_size, archive_change,
    )
    report.to_json()  # Enforce complete-report bounds before returning diagnostics.
    return report


def _same(before: Observation, after: Observation, *, marker_written: bool = False,
          object_label: str = 'object') -> None:
    if type(marker_written) is not bool:
        raise NativeStoreRefused('metadata_policy')
    report = compare_metadata(
        before, after, object_label=object_label,
        expected_file_size=len(MARKER) if marker_written else None,
        allow_archive_change=marker_written,
    )
    if not report.matches:
        raise NativeStoreRefused('object_drift', comparison=report)


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
    for index, (handle, before) in enumerate(chain):
        _same(before, api.observe(handle), object_label=f'ancestor_{index}')
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
    labeled = [(f'ancestor_{index}', handle, value)
               for index, (handle, value) in enumerate(chain)]
    for label, handle, before in [*labeled, ('store', store, store_before), ('marker', leaf, leaf_before)]:
        _same(before, api.observe(handle), object_label=label)
    api.write_marker(leaf)
    _same(leaf_before, api.observe(leaf), marker_written=True, object_label='marker')
    store_after = api.observe(store)
    _same(store_before, store_after, object_label='store')
    for label, handle, before in labeled:
        _same(before, api.observe(handle), object_label=label)
    return MarkerResult(store_after.identity, leaf_before.identity, len(MARKER))
