"""Deterministic public-only support ZIP, in memory; NOT boot media or a grant.

No CLI, output paths, downloads, key generation, installation or guest execution.
The future protected author/launcher must pin this complete snapshot before using
it. Its internal manifest detects inconsistency, not publisher provenance.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import stat
import zipfile
from pathlib import Path

from night_shifts.bootstrap_daemon_asset import (
    DAEMON_BYTES, DAEMON_SHA256, PACKAGE_SHA256, extract_reviewed_daemon,
)
from night_shifts.maintenance_credentials_prototype import (
    PUBLIC_ITEM_NAME, PublicBootstrap, decode_public_bootstrap,
)
from night_shifts.maintenance_tls_prototype import AttemptBinding
from night_shifts.public_bootstrap_kvp import canonical_public_bytes

MAX_SEED_BYTES = 512 * 1024
MAX_ENTRY_BYTES = 128 * 1024
COPYING_SHA256 = 'fb5a425bd3b3cd6071a3a9aff9909a859e7c1158d54d32e07658398cd67eb6a0'
GPL_SHA256 = 'f6b78c087c3ebdf0f3c13415070dd480a3f35d8fc76f3d02180a407c1c812f79'
SOURCE_FILES = (
    'bootstrap_daemon_asset.py', 'bootstrap_probe_seed.py',
    'guest/bootstrap_public_probe.py', 'guest/bootstrap-public-probe.apparmor',
    'guest/publish_public_bootstrap.py', 'public_bootstrap_kvp.py',
    'maintenance_credentials_prototype.py', 'maintenance_tls_prototype.py',
    'ubuntu_preparation_control.py', 'hyperv_image_preflight.py',
)
EMPTY_FILES = ('night_shifts/__init__.py', 'night_shifts/guest/__init__.py')
DATA_FILES = ('hv_kvp_daemon', 'public.json', 'COPYING', 'GPL-2.0', 'SOURCE.txt')
ENTRY_NAMES = tuple(sorted((*EMPTY_FILES, *('night_shifts/' + n for n in SOURCE_FILES),
                            *DATA_FILES, 'manifest.json')))
SOURCE_NOTICE = (
    'PUBLIC PLUMBING PROBE ONLY. No private key exists in this seed.\n'
    'hv_kvp_daemon: Ubuntu linux 6.8.0-139.139, GPL-2.0-only.\n'
    'Package SHA256: ' + PACKAGE_SHA256 + '\n'
    'Source: https://snapshot.ubuntu.com/ubuntu/20260915T000000Z/pool/main/l/linux/\n'
    'linux_6.8.0.orig.tar.gz SHA256 '
    '26512115972bdf017a4ac826cc7d3e9b0ba397d4f85cd330e4e4ff54c78061c8\n'
    'linux_6.8.0-139.139.diff.gz SHA256 '
    'c18cf1db6c7ed0ad5cf7d651de117b415f17e05baaeefb13a4a2306e94e9ae57\n'
    'linux_6.8.0-139.139.dsc SHA256 '
    '40fb1a41e084f8f923cbea43fe2ffc491e7bd3c247672018f0aa97ef3e352558\n'
    'Source/license review: docs/night_shift_kvp_runtime_review.md.\n'
    'Retain authenticated source alongside any later reviewed local media.\n'
    'This source pointer is NOT a legal distribution-compliance approval.\n'
    'The fixed parser-test CA has a deliberately INVALID signature; the leaf pin\n'
    'is a fixed sentinel. Neither can authenticate a TLS peer. No key is made.\n'
).encode('ascii')
# Manually encoded parser fixture: P-256 public generator point, dummy (1,1)
# ECDSA signature. NOT a signed certificate or a production trust anchor.
_PUBLIC_CA = base64.b64decode(
    'MIIBGDCB/qADAgECAgEBMAoGCCqGSM49BAMCMCsxKTAnBgNVBAMMIE5pZ2h0IHNoaWZ0'
    'IFBVQkxJQyBQTFVNQklORyBPTkxZMB4XDTIwMDEwMTAwMDAwMFoXDTQ5MDEwMTAwMDAw'
    'MFowKzEpMCcGA1UEAwwgTmlnaHQgc2hpZnQgUFVCTElDIFBMVU1CSU5HIE9OTFkwWTAT'
    'BgcqhkjOPQIBBggqhkjOPQMBBwNCAARrF9Hy4SxCR/i85uVjpEDydwN9gS3rM6D0oTlF'
    '2JjClk/jQuL+Gn+bjufrSnwPnhYrzjNXazFezsu2QGg3v1H1oxMwETAPBgNVHRMBAf8E'
    'BTADAQH/MAoGCCqGSM49BAMCAwkAMAYCAQECAQE=', validate=True,
)


class ProbeSeedRefused(RuntimeError):
    """Fixed labels only; no archive, source or public payload text."""


def synthetic_public_value(binding: AttemptBinding) -> PublicBootstrap:
    """Fixed public parser fixture; no signature/key possession/TLS claim."""
    if type(binding) is not AttemptBinding:
        raise ProbeSeedRefused('binding')
    return PublicBootstrap(binding, _PUBLIC_CA, '0' * 64)


def _json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True) + '\n').encode('ascii')


def _manifest(entries: dict[str, bytes], binding: AttemptBinding) -> bytes:
    return _json({'version': 1, 'purpose': 'public-plumbing-only',
                  'attempt_id': binding.attempt_id, 'vm_id': binding.vm_id,
                  'files': {name: {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
                            for name, raw in sorted(entries.items())}})


def _zip(entries: dict[str, bytes]) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_STORED) as archive:
        for name, raw in sorted(entries.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100444 << 16
            archive.writestr(info, raw)
    return stream.getvalue()


def _pinned(data: bytes, size: int, digest: str) -> None:
    if type(data) is not bytes or len(data) != size or hashlib.sha256(data).hexdigest() != digest:
        raise ProbeSeedRefused('asset_digest')


def build_public_probe_seed(
    binding: AttemptBinding, package: bytes, *, copying: bytes, gpl: bytes,
) -> bytes:
    """Return a fixed-inventory data ZIP; no media files, filesystem extraction.

    Code is snapshotted from this checkout, not authenticated by this function.
    No arbitrary certificate, leaf pin, filename, command or extra payload API.
    Caller must separately re-establish provenance and pin all reviewed code,
    license/source inputs and the returned digest at its deployment boundary.
    """
    public = canonical_public_bytes(synthetic_public_value(binding))
    _pinned(copying, 496, COPYING_SHA256)
    _pinned(gpl, 18729, GPL_SHA256)
    daemon = extract_reviewed_daemon(package)
    entries = {name: b'' for name in EMPTY_FILES}
    source = Path(__file__).resolve().parent
    for name in SOURCE_FILES:
        path = source / name
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or not 0 < info.st_size <= MAX_ENTRY_BYTES):
            raise ProbeSeedRefused('source_shape')
        raw = path.read_bytes()
        if len(raw) != info.st_size:
            raise ProbeSeedRefused('source_changed')
        # Freeze canonical UTF-8/LF, independent of Windows checkout line ends.
        entries['night_shifts/' + name] = raw.decode('utf-8').replace('\r\n', '\n').encode('utf-8')
    entries.update({'hv_kvp_daemon': daemon, 'public.json': public,
                    'COPYING': copying, 'GPL-2.0': gpl, 'SOURCE.txt': SOURCE_NOTICE})
    entries['manifest.json'] = _manifest(entries, binding)
    result = _zip(entries)
    validate_public_probe_seed(result, binding, expected_sha256=hashlib.sha256(result).hexdigest())
    return result


def validate_public_probe_seed(
    raw: bytes, binding: AttemptBinding, *, expected_sha256: str,
) -> dict[str, bytes]:
    """Bounded consistency check against an EXTERNALLY trusted full-seed pin.

    Passing the digest of an untrusted ZIP here does not establish provenance.
    The future launcher must verify before importing code from that ZIP. Never
    extractall; the guest writes only the pinned daemon to one create-new path.
    """
    if (type(binding) is not AttemptBinding or type(raw) is not bytes
            or not 0 < len(raw) <= MAX_SEED_BYTES or type(expected_sha256) is not str
            or len(expected_sha256) != 64 or hashlib.sha256(raw).hexdigest() != expected_sha256):
        raise ProbeSeedRefused('seed_digest')
    try:
        with zipfile.ZipFile(io.BytesIO(raw), 'r') as archive:
            infos = archive.infolist()
            if tuple(info.filename for info in infos) != ENTRY_NAMES:
                raise ProbeSeedRefused('seed_inventory')
            entries: dict[str, bytes] = {}
            for info in infos:
                if (info.compress_type != zipfile.ZIP_STORED or info.flag_bits
                        or info.date_time != (1980, 1, 1, 0, 0, 0) or info.extra or info.comment
                        or info.create_system != 3 or info.external_attr != 0o100444 << 16
                        or not 0 <= info.file_size <= MAX_ENTRY_BYTES):
                    raise ProbeSeedRefused('seed_shape')
                entries[info.filename] = archive.read(info)
            manifest = entries.pop('manifest.json')
            if manifest != _manifest(entries, binding):
                raise ProbeSeedRefused('seed_manifest')
            # Also reject prepended/trailing data and noncanonical local headers.
            if _zip({**entries, 'manifest.json': manifest}) != raw:
                raise ProbeSeedRefused('seed_shape')
        if any(entries[name] for name in EMPTY_FILES):
            raise ProbeSeedRefused('seed_shape')
        _pinned(entries['hv_kvp_daemon'], DAEMON_BYTES, DAEMON_SHA256)
        _pinned(entries['COPYING'], 496, COPYING_SHA256)
        _pinned(entries['GPL-2.0'], 18729, GPL_SHA256)
        if (entries['SOURCE.txt'] != SOURCE_NOTICE
                or entries['public.json'] != canonical_public_bytes(synthetic_public_value(binding))):
            raise ProbeSeedRefused('seed_public')
        # Reuse the production-candidate codec, never accept an arbitrary record.
        decode_public_bootstrap(entries['public.json'], binding, observed_vm_id=binding.vm_id,
                                item_name=PUBLIC_ITEM_NAME, item_source=1)
        return entries
    except (zipfile.BadZipFile, ValueError, KeyError, RuntimeError) as error:
        if isinstance(error, ProbeSeedRefused):
            raise
        raise ProbeSeedRefused('seed_shape') from None
