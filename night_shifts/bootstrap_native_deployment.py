"""Memory-only validator deployment INPUT bundle; unwired, NOT an installer.

Stdlib only. Never import snapshotted code/codec, run the embedded interpreter,
write/extract files, grant approval or reuse an inspection installation/claim.
Independent provenance and future protected installation/lifetime policy remain
mandatory. Hashes and these ordinary Python objects confer no authority.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import stat
import zipfile
import zlib
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

MAX_BUNDLE_BYTES = 64 * 1024**2
MAX_RUNTIME_BYTES = 32 * 1024**2
MAX_EXPANDED_BYTES = 64 * 1024**2
MAX_ENTRY_BYTES = 32 * 1024**2
MAX_REVIEW_BYTES = 16384
_WINDOWS = os.name == 'nt'
CODE_FILES = (
    'bootstrap_daemon_asset.py', 'bootstrap_probe_seed.py',
    'bootstrap_native_deployment.py', 'bootstrap_native_provision.py', 'bootstrap_native_handoff.py',
    'bootstrap_native_media.py', 'bootstrap_native_media_store.py',
    'bootstrap_native_fixture.py', 'bootstrap_native_denials.py',
    'bootstrap_native_supervision.py', 'bootstrap_native_ram.py',
    'bootstrap_native_child_plan.py', 'bootstrap_native_owner.py',
    'bootstrap_native_capture.py', 'bootstrap_native_sequence.py',
    'guest/bootstrap_native_child.py', 'guest/bootstrap_native_worker.py',
    'guest/bootstrap_native_boot.py', 'guest/bootstrap_public_probe.py',
    'guest/bootstrap-public-probe.apparmor', 'guest/publish_public_bootstrap.py',
    'public_bootstrap_kvp.py', 'maintenance_credentials_prototype.py',
    'maintenance_tls_prototype.py', 'maintenance_store_native_prototype.py',
    'ubuntu_preparation_control.py', 'hyperv_image_preflight.py',
)
EMPTY_FILES = ('night_shifts/__init__.py', 'night_shifts/guest/__init__.py')
CODE_NAMES = tuple(sorted((*EMPTY_FILES, *('night_shifts/' + n for n in CODE_FILES))))
CODEC_FILES = (
    '__init__.py', 'dates.py', 'dr.py', 'eltorito.py', 'facade.py', 'headervd.py',
    'inode.py', 'inplaceeditor.py', 'isohybrid.py', 'path_table_record.py',
    'pycdlib.py', 'pycdlibexception.py', 'pycdlibio.py', 'rockridge.py',
    'udf.py', 'utils.py', 'py.typed',
)
CODEC_METADATA = 'pycdlib-1.21.0.dist-info/'
CODEC_NAMES = tuple(sorted((*('pycdlib/' + n for n in CODEC_FILES),
    *(CODEC_METADATA + n for n in ('METADATA', 'WHEEL', 'licenses/COPYING')))))
# CPython 3.14 x64 EMBEDDABLE profile, not a system/venv installation.
# A matching inventory/name is NOT publisher authentication or a version check.
RUNTIME_NAMES = tuple(sorted((
    'python.exe', 'pythonw.exe', 'python314.dll', 'python3.dll',
    'vcruntime140.dll', 'vcruntime140_1.dll', 'LICENSE.txt', 'pyexpat.pyd',
    'select.pyd', 'unicodedata.pyd', 'winsound.pyd', '_asyncio.pyd', '_bz2.pyd',
    '_ctypes.pyd', '_decimal.pyd', '_elementtree.pyd', '_hashlib.pyd', '_lzma.pyd',
    '_multiprocessing.pyd', '_overlapped.pyd', '_queue.pyd', '_remote_debugging.pyd',
    '_socket.pyd', '_sqlite3.pyd', '_ssl.pyd', '_uuid.pyd', '_wmi.pyd',
    '_zoneinfo.pyd', '_zstd.pyd', 'libcrypto-3.dll', 'libffi-8.dll',
    'libssl-3.dll', 'libtommath.dll', 'sqlite3.dll', 'python314.zip',
    'python314._pth', 'python.cat',
)))
_PTH = b'python314.zip\r\n.\r\n\r\n# Uncomment to run site.main() automatically\r\n#import site\r\n'
# Deliberate duplication: NO application import before deployment-input review.
# Cross-layer tests require these public-asset pins to remain synchronized.
PACKAGE_NAME = 'linux-cloud-tools-6.8.0-139_6.8.0-139.139_amd64.deb'
PUBLIC_PINS = {
    PACKAGE_NAME: (148096, 'd07e7f7804374bd33bb31ca51a46b23f497ef530cefef00244a4e92d01727f6c'),
    'COPYING': (496, 'fb5a425bd3b3cd6071a3a9aff9909a859e7c1158d54d32e07658398cd67eb6a0'),
    'GPL-2.0': (18729, 'f6b78c087c3ebdf0f3c13415070dd480a3f35d8fc76f3d02180a407c1c812f79'),
}
BUNDLE_NAMES = tuple(sorted(('manifest.json',
    *('payload/' + n for n in (*CODE_NAMES, *CODEC_NAMES)),
    *('runtime/' + n for n in RUNTIME_NAMES), 'inputs/runtime.zip',
    *('inputs/' + n for n in PUBLIC_PINS))))


class DeploymentBundleRefused(RuntimeError):
    """Fixed labels only; no OS/path/source/archive/exception payload text."""


@dataclass(frozen=True)
class ValidationDeploymentPins:
    """Independent review inputs, NOT provenance, installation/execution grants.

    Recovery is a reviewed input REFERENCE, not read here. No attempt/VM ID:
    Hyper-V must supply its actual new VM GUID before an installed immutable
    recipe can derive bound public-seed/CIDATA bytes.
    """

    code_tree_sha256: str
    codec_tree_sha256: str
    runtime_sha256: str
    runtime_bytes: int
    recovery_sha256: str
    recovery_bytes: int


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _digest(value: object) -> bool:
    return type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None


def _json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True) + '\n').encode('ascii')


def _inventory(files: dict[str, bytes]) -> dict[str, dict[str, str | int]]:
    return {name: {'bytes': len(raw), 'sha256': _sha(raw)} for name, raw in sorted(files.items())}


def _tree(files: dict[str, bytes]) -> str:
    return _sha(_json(_inventory(files)))


def _pins(pins: ValidationDeploymentPins) -> None:
    if (type(pins) is not ValidationDeploymentPins
            or any(not _digest(v) for v in (pins.code_tree_sha256, pins.codec_tree_sha256,
                                           pins.runtime_sha256, pins.recovery_sha256))
            or type(pins.runtime_bytes) is not int or not 0 < pins.runtime_bytes <= MAX_RUNTIME_BYTES
            or type(pins.recovery_bytes) is not int
            or not 20 * 2048 <= pins.recovery_bytes <= 8 * 1024**3 or pins.recovery_bytes % 2048):
        raise DeploymentBundleRefused('pins')


def _identity(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns, getattr(info, 'st_file_attributes', 0),
            getattr(info, 'st_birthtime_ns', -1))


def _open_identity(info: os.stat_result) -> tuple[int, ...]:
    # CPython's Windows path and descriptor stat providers can report different
    # ctime values for the SAME unchanged file. Do not round timestamps or drop
    # this check globally: bridge all OTHER fields (including birthtime), then
    # retain exact before/after ctime checks separately within EACH provider.
    value = _identity(info)
    return value[:6] + value[7:] if _WINDOWS else value


def _no_link(info: os.stat_result) -> None:
    if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
        raise DeploymentBundleRefused('snapshot_link')


def _read_snapshot(path: Path, maximum: int) -> bytes:
    """Ordinary-process checks; NOT privileged handle/ACL acquisition."""
    try:
        chain = (path, *path.parents)
        before = [p.lstat() for p in chain]
        for info in before:
            _no_link(info)
        first = before[0]
        if not stat.S_ISREG(first.st_mode) or first.st_nlink != 1 or not 0 <= first.st_size <= maximum:
            raise DeploymentBundleRefused('snapshot_shape')
        with path.open('rb') as stream:
            opened = os.fstat(stream.fileno())
            _no_link(opened)
            if _open_identity(opened) != _open_identity(first):
                raise DeploymentBundleRefused('snapshot_changed')
            raw = stream.read(maximum + 1)
            if _identity(os.fstat(stream.fileno())) != _identity(opened):
                raise DeploymentBundleRefused('snapshot_changed')
        if len(raw) != first.st_size or any(_identity(p.lstat()) != _identity(i) for p, i in zip(chain, before)):
            raise DeploymentBundleRefused('snapshot_changed')
        return raw
    except (OSError, ValueError):
        raise DeploymentBundleRefused('snapshot_read') from None


def _snapshots() -> tuple[dict[str, bytes], dict[str, bytes]]:
    root = Path(__file__).parent
    code = dict.fromkeys(EMPTY_FILES, b'')
    for name in CODE_FILES:
        raw = _read_snapshot(root / name, 128 * 1024)
        try:
            code['night_shifts/' + name] = raw.decode('utf-8').replace('\r\n', '\n').encode('utf-8')
        except UnicodeError:
            raise DeploymentBundleRefused('source_encoding') from None
    try:
        dist = metadata.distribution('pycdlib')  # Metadata only, NEVER import codec.
        if dist.version != '1.21.0':
            raise DeploymentBundleRefused('codec_version')
        codec: dict[str, bytes] = {}
        for name in CODEC_NAMES:
            location = dist.locate_file(name)
            # SimplePath also permits non-filesystem providers such as ZIP
            # paths. This profile requires actual absolute pathlib leaves;
            # do not coerce an arbitrary provider's string into a trusted path.
            if not isinstance(location, Path) or not location.is_absolute():
                raise DeploymentBundleRefused('codec_location')
            codec[name] = _read_snapshot(location, 1024 * 1024)
    except metadata.PackageNotFoundError:
        raise DeploymentBundleRefused('codec_unavailable') from None
    _codec(codec)
    return code, codec


def _codec(files: dict[str, bytes]) -> None:
    text = files[CODEC_METADATA + 'METADATA'].replace(b'\r\n', b'\n')
    header = text.split(b'\n\n', 1)[0].split(b'\n')
    wheel = files[CODEC_METADATA + 'WHEEL'].replace(b'\r\n', b'\n')
    if (header.count(b'Name: pycdlib') != 1 or header.count(b'Version: 1.21.0') != 1
            or sum(line.startswith(b'Name:') for line in header) != 1
            or sum(line.startswith(b'Version:') for line in header) != 1
            or any(line.startswith(b'Requires-Dist:') for line in header)
            or wheel.count(b'Root-Is-Purelib: true\n') != 1
            or wheel.count(b'Tag: py3-none-any\n') != 1
            or not files[CODEC_METADATA + 'licenses/COPYING']):
        raise DeploymentBundleRefused('codec_metadata')


def review_validation_deployment_sources() -> bytes:
    """In-memory source/codec inventory for INDEPENDENT human review.

    No runtime, package, ISO, code import, filesystem write or activation.
    Calling this then immediately trusting its hashes supplies no provenance.
    """
    code, codec = _snapshots()
    raw = _json({'version': 1, 'scope': 'local_deployment_source_consistency_only',
        'code_tree_sha256': _tree(code), 'codec_tree_sha256': _tree(codec),
        'files': _inventory({**code, **codec})})
    if len(raw) > MAX_REVIEW_BYTES:
        raise DeploymentBundleRefused('review_bound')
    return raw


def _checked_blob(raw: bytes, size: int, digest: str, label: str) -> None:
    if type(raw) is not bytes or len(raw) != size or _sha(raw) != digest:
        raise DeploymentBundleRefused(label)


def _unzip(raw: bytes, names: tuple[str, ...], maximum: int) -> dict[str, bytes]:
    """Only AFTER independent whole-input pin checks; NEVER extract to paths."""
    try:
        with zipfile.ZipFile(io.BytesIO(raw), 'r') as archive:
            infos = archive.infolist()
            if (archive.comment or len(infos) != len(names)
                    or tuple(sorted(i.filename for i in infos)) != names):
                raise DeploymentBundleRefused('archive_inventory')
            total = 0
            for info in infos:
                total += info.file_size
                kind = (info.external_attr >> 16) & 0o170000
                if (info.filename != info.orig_filename or info.flag_bits & ~0x800
                        or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                        or kind not in (0, stat.S_IFREG) or info.external_attr & 0x10
                        or info.create_system not in (0, 3) or info.extra or info.comment
                        or not 0 <= info.file_size <= MAX_ENTRY_BYTES or total > maximum):
                    raise DeploymentBundleRefused('archive_shape')
            files = {}
            for info in infos:
                with archive.open(info, 'r') as stream:
                    data = stream.read(info.file_size + 1)
                if len(data) != info.file_size:
                    raise DeploymentBundleRefused('archive_extent')
                files[info.filename] = data
            return files
    except DeploymentBundleRefused:
        raise
    except (OSError, ValueError, EOFError, RuntimeError, zipfile.BadZipFile, zlib.error):
        raise DeploymentBundleRefused('archive_refused') from None


def _runtime(raw: bytes, pins: ValidationDeploymentPins) -> dict[str, bytes]:
    _checked_blob(raw, pins.runtime_bytes, pins.runtime_sha256, 'runtime_pin')
    files = _unzip(raw, RUNTIME_NAMES, 48 * 1024**2)
    if files['python314._pth'] != _PTH:
        raise DeploymentBundleRefused('runtime_path')
    if any(not data for data in files.values()) or not files['python314.zip'].startswith(b'PK\x03\x04'):
        raise DeploymentBundleRefused('runtime_shape')
    for name, data in files.items():
        if name.endswith(('.exe', '.dll', '.pyd')):
            # Narrow PE/AMD64 wrong-input check, NOT a signature/version claim.
            offset = int.from_bytes(data[60:64], 'little')
            if (len(data) < 64 or not data.startswith(b'MZ') or not 64 <= offset <= len(data) - 6
                    or data[offset:offset + 6] != b'PE\x00\x00\x64\x86'):
                raise DeploymentBundleRefused('runtime_architecture')
    return files


def _public(files: dict[str, bytes]) -> None:
    for name, (size, digest) in PUBLIC_PINS.items():
        _checked_blob(files[name], size, digest, 'public_input_pin')


def _recipe(pins: ValidationDeploymentPins) -> dict[str, object]:
    return {'code_tree_sha256': pins.code_tree_sha256, 'codec_tree_sha256': pins.codec_tree_sha256,
        'runtime': {'sha256': pins.runtime_sha256, 'bytes': pins.runtime_bytes,
                    'profile': 'cpython-314-embeddable-amd64'},
        'recovery_reference': {'sha256': pins.recovery_sha256, 'bytes': pins.recovery_bytes,
                               'verified_here': False},
        'binding': 'derive-only-after-observed-fresh-off-vm-guid',
        'public_inputs': {name: {'bytes': size, 'sha256': digest}
                          for name, (size, digest) in PUBLIC_PINS.items()}}


def _manifest(files: dict[str, bytes], pins: ValidationDeploymentPins) -> bytes:
    return _json({'version': 1, 'purpose': 'native-validator-deployment-inputs',
        'scope': 'local_deployment_consistency_only', 'recipe': _recipe(pins), 'files': _inventory(files)})


def _zip(files: dict[str, bytes]) -> bytes:
    # Conservative pre-allocation bound, including central/local headers and EOCD.
    if sum(len(d) + 128 + 2 * len(n.encode('utf-8')) for n, d in files.items()) + 22 > MAX_BUNDLE_BYTES:
        raise DeploymentBundleRefused('bundle_bound')
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_STORED) as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100444 << 16
            archive.writestr(info, data)
    result = output.getvalue()
    if len(result) > MAX_BUNDLE_BYTES:
        raise DeploymentBundleRefused('bundle_bound')
    return result


def build_validation_deployment_bundle(
    runtime_zip: bytes, package: bytes, *, copying: bytes, gpl: bytes, pins: ValidationDeploymentPins,
) -> bytes:
    """Return a canonical INPUT archive in memory; no install/execution authority.

    Runtime/public pins precede parsing; independent source/codec tree pins
    precede serialization. Source-evidence/provenance review, recovery acquisition
    and all protected installer/runner policy are external requirements.
    """
    _pins(pins)
    public = {PACKAGE_NAME: package, 'COPYING': copying, 'GPL-2.0': gpl}
    _public(public)
    runtime = _runtime(runtime_zip, pins)
    code, codec = _snapshots()
    if _tree(code) != pins.code_tree_sha256 or _tree(codec) != pins.codec_tree_sha256:
        raise DeploymentBundleRefused('source_pin')
    files = {**{'payload/' + n: d for n, d in {**code, **codec}.items()},
             **{'runtime/' + n: d for n, d in runtime.items()},
             **{'inputs/' + n: d for n, d in public.items()}, 'inputs/runtime.zip': runtime_zip}
    return _zip({**files, 'manifest.json': _manifest(files, pins)})


def inspect_validation_deployment_bundle(
    bundle: bytes, *, expected_bundle_sha256: str, pins: ValidationDeploymentPins,
) -> bytes:
    """Pin FIRST, inspect without imports/execution, return bounded local review.

    Caller-computed hashes aren't provenance. The result isn't a receipt or a
    runnable complete deployment: no installer, helper or watchdog is supplied.
    """
    _pins(pins)
    if (type(bundle) is not bytes or not 0 < len(bundle) <= MAX_BUNDLE_BYTES
            or not _digest(expected_bundle_sha256) or _sha(bundle) != expected_bundle_sha256):
        raise DeploymentBundleRefused('bundle_pin')
    files = _unzip(bundle, BUNDLE_NAMES, MAX_EXPANDED_BYTES)
    manifest = files.pop('manifest.json')
    if manifest != _manifest(files, pins) or bundle != _zip({**files, 'manifest.json': manifest}):
        raise DeploymentBundleRefused('bundle_canonical')
    code = {name: files['payload/' + name] for name in CODE_NAMES}
    codec = {name: files['payload/' + name] for name in CODEC_NAMES}
    if _tree(code) != pins.code_tree_sha256 or _tree(codec) != pins.codec_tree_sha256:
        raise DeploymentBundleRefused('source_pin')
    if any(code[n] for n in EMPTY_FILES):
        raise DeploymentBundleRefused('package_initializer')
    _codec(codec)
    _public({name: files['inputs/' + name] for name in PUBLIC_PINS})
    runtime = _runtime(files['inputs/runtime.zip'], pins)
    if any(files['runtime/' + name] != data for name, data in runtime.items()):
        raise DeploymentBundleRefused('runtime_correspondence')
    # No reread/import of checkout or installed codec: independently reviewed
    # bundle/tree pins bind the carried snapshot, including all metadata/bytes.
    raw = _json({'version': 1, 'scope': 'local_deployment_consistency_only',
        'bundle_sha256': _sha(bundle), 'bundle_bytes': len(bundle),
        'manifest_sha256': _sha(manifest), 'file_count': len(files), 'recipe': _recipe(pins)})
    if len(raw) > MAX_REVIEW_BYTES:
        raise DeploymentBundleRefused('review_bound')
    return raw
