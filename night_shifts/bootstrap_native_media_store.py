"""Unwired Windows validation-media store candidate; NEVER run checkout elevated.

Fixed public media only, no credentials/VM/policy/installer/receipt operation.
A separately reviewed deployment must pin this code/runtime, plan and inputs,
provision the private anchor/recovery.iso, authorize one attempt and supervise
its VM independently. Local objects/hashes are consistency data, not grants.
"""
from __future__ import annotations

import ctypes as c
import hashlib
import json
import re
from dataclasses import dataclass, field
from time import monotonic as _now

from night_shifts import maintenance_store_native_prototype as native
from night_shifts.bootstrap_native_media import NativeValidationMedia, build_native_validation_iso
from night_shifts.maintenance_tls_prototype import AttemptBinding

MAX_RECOVERY_BYTES = 8 * 1024**3
MAX_REVIEW_BYTES = 8192
CHUNK_BYTES = 65536
_GUID_ROOT = r'\\\\\?\\Volume\{[0-9a-fA-F-]{36}\}\\'


class MediaStoreRefused(RuntimeError):
    """Fixed labels only; never OS/path/source/image/exception text."""


class MediaStoreUnknown(MediaStoreRefused):
    """Incomplete local operation, NOT rollback, VM cleanup or retry consent."""


@dataclass(frozen=True)
class ValidationMediaPlan:
    """Forgeable review inputs; only an installed policy may give them authority."""

    binding: AttemptBinding
    anchor_identity: native.FileIdentity
    recovery_sha256: str
    recovery_bytes: int
    seed_sha256: str
    cidata_sha256: str


@dataclass(frozen=True)
class HeldMediaPaths:
    """Volume-GUID paths for a FUTURE runner, valid only during the held lifetime."""

    recovery_iso: str
    cidata_iso: str
    review: str


class _Budget:
    def __init__(self, deadline: float) -> None:
        now = _now()
        # Ordered comparisons reject NaN/infinity and enormous integers without
        # converting arbitrary integers to floats (which can overflow).
        if type(deadline) not in (int, float) or not now < deadline <= now + 900:
            raise MediaStoreRefused('deadline')
        self.deadline = deadline

    def check(self) -> None:
        if _now() >= self.deadline:
            raise MediaStoreRefused('deadline')


def _digest(value: object) -> bool:
    return type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None


def _anchor_parts(path: str) -> tuple[str, tuple[str, ...]]:
    try:
        return native._path_parts(path)
    except native.NativeStoreRefused:
        raise MediaStoreRefused('anchor_path') from None


def _plan(plan: ValidationMediaPlan) -> None:
    if (type(plan) is not ValidationMediaPlan or type(plan.binding) is not AttemptBinding
            or type(plan.anchor_identity) is not native.FileIdentity
            or type(plan.anchor_identity.volume) is not int
            or not 0 <= plan.anchor_identity.volume < 2**32
            or type(plan.anchor_identity.index) is not int
            or not 0 < plan.anchor_identity.index < 2**64
            or type(plan.recovery_bytes) is not int
            or not 20 * 2048 <= plan.recovery_bytes <= MAX_RECOVERY_BYTES
            or plan.recovery_bytes % 2048
            or any(not _digest(v) for v in (plan.recovery_sha256, plan.seed_sha256, plan.cidata_sha256))):
        raise MediaStoreRefused('plan')


def _render(plan: ValidationMediaPlan, support_zip: bytes) -> tuple[NativeValidationMedia, bytes]:
    _plan(plan)
    try:
        media = build_native_validation_iso(plan.binding, support_zip, expected_seed_sha256=plan.seed_sha256)
        if media.sha256 != plan.cidata_sha256:
            raise MediaStoreRefused('cidata_pin')
        # The nested descriptor remains explicitly local-only, never a receipt.
        value = {'version': 1, 'purpose': 'native-validation-media-set',
            'scope': 'local_media_set_consistency_only',
            'attempt_id': plan.binding.attempt_id, 'vm_id': plan.binding.vm_id,
            'anchor_identity': {'volume': plan.anchor_identity.volume, 'index': plan.anchor_identity.index},
            'files': {'recovery.iso': {'role': 'externally-reviewed-boot-iso',
                'sha256': plan.recovery_sha256, 'bytes': plan.recovery_bytes},
                'cidata.iso': {'role': 'nonbootable-secondary-data',
                    'sha256': media.sha256, 'bytes': media.size_bytes}},
            'cidata_review': json.loads(media.review_bytes())}
        raw = (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True) + '\n').encode('ascii')
        if len(raw) > MAX_REVIEW_BYTES:
            raise MediaStoreRefused('review_bound')
        return media, raw
    except MediaStoreRefused:
        raise
    except BaseException:
        raise MediaStoreUnknown('review_render_unknown') from None


def render_validation_media_set_review(plan: ValidationMediaPlan, support_zip: bytes) -> bytes:
    """Memory-only descriptor for independent review; no file opens/writes/grants."""
    return _render(plan, support_zip)[1]


class _Windows(native._Windows):
    """Reuse existing native handle/ACL primitives, NEVER its marker-write API.

    The specialized leaf opens use FILE_SHARE_READ, not the marker's exclusive
    share mode. All acquisition is relative to held no-delete directory handles.
    """

    def leaf(self, parent: native._Handle, name: str, *, create: bool) -> native._Handle:
        if name not in ('recovery.iso', 'cidata.iso', 'review.json') or (create and name == 'recovery.iso'):
            raise MediaStoreRefused('leaf_name')
        buffer = c.create_unicode_buffer(name)
        text = native._Unicode(len(name) * 2, (len(name) + 1) * 2, c.cast(buffer, c.c_wchar_p))
        descriptor = native._PTR()
        if create and not self.a.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                native._sddl(directory=False), 1, c.byref(descriptor), None):
            raise MediaStoreUnknown('creation_descriptor_unknown')
        try:
            attrs = native._ObjectAttributes(c.sizeof(native._ObjectAttributes), parent.value,
                c.pointer(text), 0x1040, descriptor, None)  # DONT_REPARSE, CASE_INSENSITIVE
            output, status = native._PTR(), native._IoStatus()
            access = 0x120080 | (0xC0000000 if create else 0x80000000)
            result = self.n.NtCreateFile(c.byref(output), access, c.byref(attrs), c.byref(status),
                None, 0, 0 if create else 1, 2 if create else 1, 0x200060, None, 0)
            # FILE_CREATE or FILE_OPEN only; synchronous, non-directory,
            # OPEN_REPARSE_POINT. Writer is exclusive; final reader shares READ
            # only, so compatible readers work but data writers/deleters cannot.
            if result != 0:
                if output.value:
                    self._close(native._Handle(self, int(output.value)))
                raise MediaStoreRefused('leaf_create_refused' if create else 'leaf_open_refused')
            handle = native._Handle(self, int(output.value or 0))
            if not handle.value or status.information != (2 if create else 1):
                self._close(handle)
                raise MediaStoreUnknown('leaf_disposition_unknown')
            return handle
        finally:
            if descriptor:
                self.k.LocalFree(descriptor)

    @staticmethod
    def _close(handle: native._Handle) -> None:
        try:
            handle.__exit__()
        except BaseException:
            raise MediaStoreUnknown('handle_close_unknown') from None

    def final_name(self, handle: native._Handle) -> str:
        output = c.create_unicode_buffer(512)
        count = self.k.GetFinalPathNameByHandleW(handle.value, output, len(output), 1)
        if not 0 < count < len(output) or re.match(_GUID_ROOT, output.value) is None:
            raise MediaStoreRefused('volume_guid_path')
        return str(output.value)

    def write(self, handle: native._Handle, data: bytes, budget: _Budget) -> None:
        budget.check()
        buffer, count = c.create_string_buffer(data), native._U32()
        if (not self.k.WriteFile(handle.value, buffer, len(data), c.byref(count), None)
                or count.value != len(data)):
            raise MediaStoreUnknown('write_unknown')  # Never retry a short/failed write.
        budget.check()
        if not self.k.FlushFileBuffers(handle.value):
            raise MediaStoreUnknown('flush_unknown')
        budget.check()

    def verify_bytes(self, handle: native._Handle, size: int, digest: str,
                     expected: bytes | None, budget: _Budget) -> None:
        budget.check()
        if not self.k.SetFilePointerEx(handle.value, 0, None, 0):
            raise MediaStoreUnknown('seek_unknown')
        result, total = hashlib.sha256(), 0
        buffer, count = c.create_string_buffer(CHUNK_BYTES), native._U32()
        while total < size:
            budget.check()
            requested = min(CHUNK_BYTES, size - total)
            if not self.k.ReadFile(handle.value, buffer, requested, c.byref(count), None):
                raise MediaStoreUnknown('read_unknown')
            if not 0 < count.value <= requested:
                raise MediaStoreRefused('read_extent')
            chunk = buffer.raw[:count.value]
            if expected is not None and chunk != expected[total:total + count.value]:
                raise MediaStoreRefused('file_bytes')
            result.update(chunk)
            total += count.value
        budget.check()
        if not self.k.ReadFile(handle.value, buffer, 1, c.byref(count), None):
            raise MediaStoreUnknown('read_unknown')
        if count.value != 0 or result.hexdigest() != digest:
            raise MediaStoreRefused('file_digest')
        budget.check()


class _Resources:
    def __init__(self) -> None:
        self.handles: list[native._Handle] = []

    def own(self, handle: native._Handle) -> native._Handle:
        self.handles.append(handle)
        return handle

    def close(self) -> None:
        handles, self.handles = self.handles, []
        failed = False
        for handle in reversed(handles):
            try:
                handle.__exit__()  # _Handle clears its value BEFORE CloseHandle.
            except BaseException:
                failed = True
        if failed:
            raise MediaStoreUnknown('handle_close_unknown') from None


@dataclass(frozen=True)
class _Directory:
    handle: native._Handle = field(repr=False)
    before: native.Observation
    private: bool
    path: str


@dataclass(frozen=True)
class _File:
    handle: native._Handle = field(repr=False)
    before: native.Observation
    path: str
    size: int
    digest: str
    expected: bytes | None = field(repr=False)


def _same(before: native.Observation, after: native.Observation, *, written: int | None = None) -> None:
    comparison = native.compare_metadata(before, after, expected_file_size=written,
                                         allow_archive_change=written is not None)
    if not comparison.matches:
        raise MediaStoreRefused('metadata_drift')


def _directories(api: _Windows, directories: list[_Directory], budget: _Budget) -> None:
    for entry in directories:
        budget.check()
        after = api.observe(entry.handle)
        if entry.private:
            native._check_private(after, directory=True)
        else:
            native._check_ancestor(after)
        _same(entry.before, after)
        if api.final_name(entry.handle).casefold() != entry.path.casefold():
            raise MediaStoreRefused('directory_path_drift')


def _file_metadata(api: _Windows, entry: _File) -> None:
    after = api.observe(entry.handle)
    native._check_private(after, directory=False)
    _same(entry.before, after)
    if after.size != entry.size or api.final_name(entry.handle).casefold() != entry.path.casefold():
        raise MediaStoreRefused('file_metadata')


class HeldValidationMedia:
    """Explicit single handle lifetime, no finalizer, reopen, retry or receipt.

    Keep this object open through future VM use AND independently confirmed VM
    absence. These handles are NOT a VM watchdog; controller death releases them.
    Any verify failure is terminal and attempts all closes. No partial path set
    is returned. Ordinary Python callers can fabricate state; trust is external.
    """

    def __init__(self, api: _Windows, resources: _Resources, directories: list[_Directory],
                 files: tuple[_File, _File, _File], budget: _Budget) -> None:
        self._api, self._resources = api, resources
        self._directories, self._files, self._budget = directories, files, budget
        self._usable = True

    def verify(self) -> None:
        if not self._usable:
            raise MediaStoreRefused('held_set_terminal')
        try:
            _directories(self._api, self._directories, self._budget)
            for entry in self._files:
                self._budget.check()
                _file_metadata(self._api, entry)
                self._api.verify_bytes(entry.handle, entry.size, entry.digest, entry.expected, self._budget)
                _file_metadata(self._api, entry)
            # No success after a late chain/ACL/identity/deadline change.
            _directories(self._api, self._directories, self._budget)
            for entry in self._files:
                self._budget.check()
                _file_metadata(self._api, entry)
            self._budget.check()
        except BaseException as error:
            self.close()
            if isinstance(error, MediaStoreRefused):
                raise
            raise MediaStoreUnknown('held_verification_unknown') from None

    def checked_paths(self) -> HeldMediaPaths:
        self.verify()
        return HeldMediaPaths(*(entry.path for entry in self._files))

    def close(self) -> None:
        self._usable = False
        self._resources.close()  # One attempt per handle, including uncertain close.

    def __enter__(self) -> HeldValidationMedia:
        if not self._usable:
            raise MediaStoreRefused('held_set_terminal')
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def _acquire_directories(api: _Windows, resources: _Resources, anchor_path: str,
                         plan: ValidationMediaPlan, budget: _Budget) -> list[_Directory]:
    drive, parts = _anchor_parts(anchor_path)
    budget.check()
    handle = resources.own(api.root(drive))  # Fixed local NTFS, volume-GUID root.
    before = api.observe(handle)
    native._check_ancestor(before)
    root = api.final_name(handle)
    if re.fullmatch(_GUID_ROOT, root) is None:
        raise MediaStoreRefused('volume_guid_root')
    directories = [_Directory(handle, before, False, root)]
    path = root.rstrip('\\')
    volume = before.identity.volume
    for index, part in enumerate(parts):
        budget.check()
        private = index == len(parts) - 1
        handle = resources.own(api.relative(handle, part, directory=True, create=False, writable=private))
        observed = api.observe(handle)
        if observed.identity.volume != volume:
            raise MediaStoreRefused('volume_changed')
        if private:
            native._check_private(observed, directory=True)
        else:
            native._check_ancestor(observed)
        path += '\\' + part
        directories.append(_Directory(handle, observed, private, path))
    if directories[-1].before.identity != plan.anchor_identity:
        raise MediaStoreRefused('anchor_identity')
    _directories(api, directories, budget)
    return directories


def _read_file(api: _Windows, resources: _Resources, parent: _Directory, name: str,
               size: int, digest: str, expected: bytes | None, budget: _Budget,
               written: native.Observation | None = None) -> _File:
    budget.check()
    handle = resources.own(api.leaf(parent.handle, name, create=False))
    before = api.observe(handle)
    native._check_private(before, directory=False)
    if before.identity.volume != parent.before.identity.volume or before.size != size:
        raise MediaStoreRefused('file_shape')
    if written is not None:
        _same(written, before)  # Reject replacement during writer-to-reader handoff.
    entry = _File(handle, before, parent.path.rstrip('\\') + '\\' + name, size, digest, expected)
    _file_metadata(api, entry)
    api.verify_bytes(handle, size, digest, expected, budget)
    _file_metadata(api, entry)
    return entry


def _write_file(api: _Windows, resources: _Resources, directories: list[_Directory], name: str,
                data: bytes, budget: _Budget) -> _File:
    parent = directories[-1]
    _directories(api, directories, budget)
    writer = resources.own(api.leaf(parent.handle, name, create=True))
    before = api.observe(writer)
    native._check_private(before, directory=False)
    if before.identity.volume != parent.before.identity.volume or before.size != 0:
        raise MediaStoreRefused('new_file_shape')
    _directories(api, directories, budget)
    api.write(writer, data, budget)
    after = api.observe(writer)
    native._check_private(after, directory=False)
    _same(before, after, written=len(data))
    # The exclusive writer cannot coexist with a read-sharing-only reader.
    # Close once, then reopen RELATIVE to the protected held parent, requiring
    # the SAME identity/security and exact bytes before returning anything.
    # No untrusted writer is authorized in this interval; no output is used in it.
    _Windows._close(writer)
    return _read_file(api, resources, parent, name, len(data), hashlib.sha256(data).hexdigest(),
                      data, budget, written=after)


def materialize_validation_media(
    anchor_path: str, plan: ValidationMediaPlan, support_zip: bytes, *,
    expected_review_sha256: str, deadline: float,
) -> HeldValidationMedia:
    """Create a NEW media directory, return three held read-sharing-only files.

    Existing strict BA/SYSTEM anchor contains recovery.iso. Child directory is
    validation-media-<attempt_id>; outputs only cidata.iso and review.json. All
    reviewed pins are checked before writes; recovery is hashed under its lock
    before the directory claim. Retain partial artifacts on EVERY failure. No
    recovery copy, mkdir parents, reuse/truncate/replace/repair/delete or VM call.
    Blocking kernel/codec calls need an independent protected process watchdog;
    this original monotonic budget is cooperative and is never refreshed.
    """
    budget = _Budget(deadline)
    _anchor_parts(anchor_path)  # Validate without native I/O.
    if not _digest(expected_review_sha256):
        raise MediaStoreRefused('review_pin')
    media, review = _render(plan, support_zip)
    if hashlib.sha256(review).hexdigest() != expected_review_sha256:
        raise MediaStoreRefused('review_pin')
    budget.check()
    resources = _Resources()
    try:
        api = _Windows()
        api.require_admin()
        directories = _acquire_directories(api, resources, anchor_path, plan, budget)
        anchor = directories[-1]
        recovery = _read_file(api, resources, anchor, 'recovery.iso', plan.recovery_bytes,
                              plan.recovery_sha256, None, budget)
        _directories(api, directories, budget)
        child_name = 'validation-media-' + plan.binding.attempt_id
        budget.check()
        handle = resources.own(api.relative(anchor.handle, child_name, directory=True,
            create=True, sddl=native._sddl(directory=True), writable=True))
        observed = api.observe(handle)
        native._check_private(observed, directory=True)
        if observed.identity.volume != plan.anchor_identity.volume:
            raise MediaStoreRefused('volume_changed')
        directories.append(_Directory(handle, observed, True, anchor.path + '\\' + child_name))
        _directories(api, directories, budget)
        _file_metadata(api, recovery)
        cidata = _write_file(api, resources, directories, 'cidata.iso', media.image, budget)
        _file_metadata(api, recovery)
        descriptor = _write_file(api, resources, directories, 'review.json', review, budget)
        if len({entry.before.identity for entry in (recovery, cidata, descriptor)}) != 3:
            raise MediaStoreRefused('file_identity_alias')
        result = HeldValidationMedia(api, resources, directories, (recovery, cidata, descriptor), budget)
        result.verify()
        return result
    except BaseException as error:
        resources.close()  # Attempt every close; close uncertainty overrides success/refusal.
        if isinstance(error, MediaStoreRefused):
            raise
        raise MediaStoreUnknown('materialization_unknown') from None
