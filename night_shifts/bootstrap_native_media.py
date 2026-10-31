"""Fixed validation CIDATA ISO in MEMORY ONLY; no paths, mounting or execution.

Data-only secondary media, not a bootable recovery ISO, publication installer,
protected deployment, authorization or native evidence. Exact bytes/descriptor
are local consistency observations; later authority must independently review
and read-lock the complete recovery+CIDATA set and own its VM/watchdog/evidence.
"""
from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass, field
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from night_shifts.bootstrap_native_handoff import NativeValidationHandoff, render_native_validation_handoff
from night_shifts.guest.bootstrap_native_boot import _json
from night_shifts.maintenance_tls_prototype import AttemptBinding

SECTOR_BYTES = 2048
MAX_MEDIA_BYTES = 2 * 1024 * 1024
MAX_DESCRIPTOR_BYTES = 4096
PYCDLIB_VERSION = '1.21.0'
_LAYOUT = (
    ('meta-data', '/METADATA.;1'), ('network-config', '/NETCFG.;1'),
    ('support.zip', '/SUPPORT.ZIP;1'), ('user-data', '/USERDATA.;1'),
    ('validator.zip', '/VALIDATR.ZIP;1'),
)
_DATE = b'2000010100000000\x00'  # UTC, 2000-01-01. Not a wall-clock observation.
_NO_DATE = b'0000000000000000\x00'  # Expiration unspecified, not already expired.
_DIR_DATE = bytes((100, 1, 1, 0, 0, 0, 0))
_TF_FIELDS = ('creation_time', 'access_time', 'modification_time', 'attribute_change_time',
              'backup_time', 'expiration_time', 'effective_time')


class NativeMediaRefused(RuntimeError):
    """Fixed labels only; never source/image/parser bytes or external paths."""


class NativeMediaUnknown(NativeMediaRefused):
    """Local build/inspection incomplete, not rollback or execution/VM evidence."""


@dataclass(frozen=True)
class LocalMediaFile:
    name: str
    iso9660_name: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class NativeValidationMedia:
    """Forgeable local data, NOT a media approval, signature or runtime receipt."""

    binding: AttemptBinding
    image: bytes = field(repr=False)
    sha256: str
    size_bytes: int
    seed_sha256: str
    payload_sha256: str
    bootstrap_sha256: str
    policy_sha256: str
    files: tuple[LocalMediaFile, ...]

    def review_bytes(self) -> bytes:
        """Bounded descriptor for later review; NEVER serialize the raw image."""
        if (type(self.binding) is not AttemptBinding or type(self.image) is not bytes
                or not 20 * SECTOR_BYTES <= len(self.image) <= MAX_MEDIA_BYTES
                or type(self.size_bytes) is not int or self.size_bytes != len(self.image)
                or hashlib.sha256(self.image).hexdigest() != self.sha256
                or any(not _digest(value) for value in (self.sha256, self.seed_sha256,
                    self.payload_sha256, self.bootstrap_sha256, self.policy_sha256))
                or type(self.files) is not tuple or len(self.files) != len(_LAYOUT)):
            raise NativeMediaRefused('descriptor_context')
        table: dict[str, object] = {}
        for item, (name, alias) in zip(self.files, _LAYOUT, strict=True):
            if (type(item) is not LocalMediaFile or item.name != name or item.iso9660_name != alias
                    or type(item.size_bytes) is not int or not 0 < item.size_bytes <= MAX_MEDIA_BYTES
                    or not _digest(item.sha256)):
                raise NativeMediaRefused('descriptor_context')
            table[name] = {'iso9660_name': alias, 'bytes': item.size_bytes, 'sha256': item.sha256}
        raw = _json({'version': 1, 'purpose': 'native-validation-cidata-only',
            'scope': 'local_media_consistency_only', 'attempt_id': self.binding.attempt_id,
            'vm_id': self.binding.vm_id, 'image': {'sha256': self.sha256, 'bytes': self.size_bytes,
                'volume_label': 'CIDATA', 'logical_block_bytes': SECTOR_BYTES, 'bootable': False},
            'inputs': {'seed_sha256': self.seed_sha256, 'payload_sha256': self.payload_sha256,
                'bootstrap_sha256': self.bootstrap_sha256, 'policy_sha256': self.policy_sha256}, 'files': table})
        if len(raw) > MAX_DESCRIPTOR_BYTES:
            raise NativeMediaRefused('descriptor_bound')
        return raw


class _BoundedBuffer(io.BytesIO):
    def __init__(self, limit: int) -> None:
        super().__init__()
        self._limit = limit

    def write(self, data: Any, /) -> int:
        if self.tell() + len(data) > self._limit:
            raise NativeMediaRefused('buffer_bound')
        return super().write(data)


def _digest(value: object) -> bool:
    return type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None


def _context(binding: AttemptBinding, seed_sha256: str) -> None:
    if type(binding) is not AttemptBinding or not _digest(seed_sha256):
        raise NativeMediaRefused('context')


def _library() -> tuple[Any, Any]:
    try:
        if version('pycdlib') != PYCDLIB_VERSION:
            raise NativeMediaRefused('library_version')
        import pycdlib  # type: ignore[import-not-found]  # optional pinned development dependency
        from pycdlib import dates  # type: ignore[import-not-found]
        return pycdlib, dates
    except (ImportError, PackageNotFoundError):
        raise NativeMediaRefused('library_unavailable') from None


def _render(binding: AttemptBinding, seed: bytes, seed_sha256: str) -> NativeValidationHandoff:
    _context(binding, seed_sha256)
    try:
        result = render_native_validation_handoff(binding, seed, expected_seed_sha256=seed_sha256)
        if tuple(sorted(result.files())) != tuple(name for name, _ in _LAYOUT):
            raise NativeMediaRefused('file_inventory')
        return result
    except NativeMediaRefused:
        raise
    except Exception:
        raise NativeMediaRefused('handoff_refused') from None


def _date(dates: Any, *, long: bool = False) -> Any:
    value = dates.VolumeDescriptorDate() if long else dates.DirectoryRecordDate()
    value.parse(_DATE if long else _DIR_DATE)
    return value


def _normalize_directories(iso: Any, dates: Any) -> None:
    # This narrow adapter is intentionally tied to pycdlib 1.21.0. No process-
    # global clock/TZ monkeypatch, dependency fallback or permissive ABI repair.
    if len(iso.svds) != 1:
        raise NativeMediaRefused('author_profile')
    for volume in (iso.pvd, *iso.svds):
        root = volume.root_directory_record()
        if len(root.children) != len(_LAYOUT) + 2:
            raise NativeMediaRefused('author_profile')
        for record in (root, *root.children):
            record.date = _date(dates)
            if record.rock_ridge is None:
                continue
            for area in (record.rock_ridge.dr_entries, record.rock_ridge.ce_entries):
                if area is None or area.tf_record is None:
                    continue
                tf = area.tf_record
                for name in _TF_FIELDS:
                    if getattr(tf, name, None) is not None:
                        setattr(tf, name, _date(dates, long=bool(tf.time_flags & 128)))


def _shape(raw: bytes) -> None:
    if (not 20 * SECTOR_BYTES <= len(raw) <= MAX_MEDIA_BYTES or len(raw) % SECTOR_BYTES
            or any(raw[:16 * SECTOR_BYTES])):
        raise NativeMediaRefused('image_shape')
    for sector, tag in ((16, 1), (17, 2), (18, 255)):
        if raw[sector * SECTOR_BYTES:sector * SECTOR_BYTES + 7] != bytes((tag,)) + b'CD001\x01':
            raise NativeMediaRefused('image_shape')
    pvd = raw[16 * SECTOR_BYTES:17 * SECTOR_BYTES]
    if (pvd[40:72] != b'CIDATA'.ljust(32, b' ')
            or int.from_bytes(pvd[80:84], 'little') != len(raw) // SECTOR_BYTES
            or pvd[80:84] != pvd[84:88][::-1]
            or int.from_bytes(pvd[128:130], 'little') != SECTOR_BYTES
            or pvd[128:130] != pvd[130:132][::-1]):
        raise NativeMediaRefused('image_shape')


def _canonical_image(files: dict[str, bytes]) -> bytes:
    library, dates = _library()
    iso = library.PyCdlib()
    initialized = False
    try:
        iso.new(vol_ident='CIDATA', sys_ident='AI_AGENT_NATIVE', app_ident_str='AI_AGENT_NATIVE_VALIDATION',
                rock_ridge='1.09', joliet=3)
        initialized = True
        buffers: list[io.BytesIO] = []
        for name, alias in _LAYOUT:
            stream = io.BytesIO(files[name])
            buffers.append(stream)  # Keep every source alive until serialization.
            iso.add_fp(stream, len(files[name]), iso_path=alias, rr_name=name, joliet_path='/' + name,
                       file_mode=0o100444, creation_time=946684800.0)
        iso.force_consistency()
        _normalize_directories(iso, dates)
        with _BoundedBuffer(MAX_MEDIA_BYTES) as output:
            iso.write_fp(output)
            data = bytearray(output.getvalue())
        _shape(bytes(data))
        # 1.21.0 serializes VD modification time afresh, ignoring the date object.
        # Freeze ONLY known ISO9660/SVD date fields on our newly authored bytes.
        # Expiration is unspecified. No untrusted ISO is ever normalized/repaired.
        for sector in (16, 17):
            start = sector * SECTOR_BYTES
            data[start + 813:start + 881] = _DATE + _DATE + _NO_DATE + _DATE
        return bytes(data)
    except NativeMediaRefused:
        raise
    except BaseException:
        raise NativeMediaUnknown('image_build_unknown') from None
    finally:
        if initialized:
            try:
                iso.close()
            except BaseException:
                raise NativeMediaUnknown('image_close_unknown') from None


def _audit_views(raw: bytes, files: dict[str, bytes]) -> None:
    library, _ = _library()
    iso = library.PyCdlib()
    opened = False
    try:
        iso.open_fp(io.BytesIO(raw))
        opened = True
        if (not iso.has_rock_ridge() or not iso.has_joliet() or iso.has_udf()
                or iso.eltorito_boot_catalog is not None or len(iso.svds) != 1):
            raise NativeMediaRefused('namespace_profile')
        for namespace in ('iso_path', 'rr_path', 'joliet_path'):
            expected = {alias[1:] if namespace == 'iso_path' else name: (name, files[name]) for name, alias in _LAYOUT}
            seen: set[str] = set()
            for index, record in enumerate(iso.list_children(**{namespace: '/'})):
                if index >= len(_LAYOUT) + 2:
                    raise NativeMediaRefused('namespace_inventory')
                if record.is_dot() or record.is_dotdot():
                    continue
                if record.is_symlink() or record.is_associated_file() or not record.is_file():
                    raise NativeMediaRefused('namespace_entry')
                if namespace == 'rr_path':
                    if record.rock_ridge is None:
                        raise NativeMediaRefused('namespace_entry')
                    name = record.rock_ridge.name().decode('utf-8')
                    px = record.rock_ridge.dr_entries.px_record
                    if px is None or (px.posix_file_mode, px.posix_user_id, px.posix_group_id, px.posix_file_links) != (0o100444, 0, 0, 1):
                        raise NativeMediaRefused('namespace_entry')
                else:
                    name = record.file_identifier().decode('utf-16-be' if namespace == 'joliet_path' else 'ascii')
                if name not in expected or name in seen:
                    raise NativeMediaRefused('namespace_inventory')
                seen.add(name)
                _, content = expected[name]
                if record.get_data_length() != len(content):
                    raise NativeMediaRefused('namespace_content')
                with _BoundedBuffer(len(content)) as output:
                    iso.get_file_from_iso_fp(output, **{namespace: '/' + name})
                    if output.getvalue() != content:
                        raise NativeMediaRefused('namespace_content')
            if seen != set(expected):
                raise NativeMediaRefused('namespace_inventory')
    except NativeMediaRefused:
        raise
    except BaseException:
        raise NativeMediaUnknown('image_inspection_unknown') from None
    finally:
        if opened:
            try:
                iso.close()
            except BaseException:
                raise NativeMediaUnknown('image_close_unknown') from None


def _record(binding: AttemptBinding, image: bytes, handoff: NativeValidationHandoff) -> NativeValidationMedia:
    files = handoff.files()
    result = NativeValidationMedia(binding, image, hashlib.sha256(image).hexdigest(), len(image),
        handoff.seed_sha256, handoff.payload_sha256, handoff.bootstrap_sha256, handoff.policy_sha256,
        tuple(LocalMediaFile(name, alias, len(files[name]), hashlib.sha256(files[name]).hexdigest())
              for name, alias in _LAYOUT))
    result.review_bytes()  # Bound only; no write, publication or acceptance API.
    return result


def build_native_validation_iso(
    binding: AttemptBinding, support_zip: bytes, *, expected_seed_sha256: str,
) -> NativeValidationMedia:
    """Build/inspect data-only secondary ISO bytes; never create a file or VM."""
    handoff = _render(binding, support_zip, expected_seed_sha256)
    raw = _canonical_image(handoff.files())
    _audit_views(raw, handoff.files())
    return _record(binding, raw, handoff)


def inspect_native_validation_iso(
    binding: AttemptBinding, support_zip: bytes, *, expected_seed_sha256: str,
    image: bytes, expected_image_sha256: str,
) -> NativeValidationMedia:
    """Verify external full-image pin AND current exact canonical media snapshot.

    Only byte-identical known canonical media reaches the third-party ISO parser.
    No stale images, metadata/padding changes or self-rehashed alternate contents
    are normalized or salvaged. This is not source/publisher/boot provenance.
    """
    _context(binding, expected_seed_sha256)
    if (not _digest(expected_image_sha256) or type(image) is not bytes
            or not 20 * SECTOR_BYTES <= len(image) <= MAX_MEDIA_BYTES
            or hashlib.sha256(image).hexdigest() != expected_image_sha256):
        raise NativeMediaRefused('image_digest')
    handoff = _render(binding, support_zip, expected_seed_sha256)
    canonical = _canonical_image(handoff.files())
    if image != canonical:
        raise NativeMediaRefused('image_not_canonical')
    _shape(image)
    _audit_views(image, handoff.files())
    return _record(binding, image, handoff)
