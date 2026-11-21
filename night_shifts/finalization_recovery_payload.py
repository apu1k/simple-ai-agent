"""Public-only, deterministic payload for the automatic recovery boot.

An independently reviewed launcher must pin the complete optical media and
payload before boot/import. No cloud-init activator, key generation, process
start, extraction to disk, installation or image write occurs here.
"""
from __future__ import annotations

import hashlib
import io
import json
import stat
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from night_shifts.authenticated_image_finalization import FinalizationRefused, request_digest
from night_shifts.bootstrap_daemon_asset import DAEMON_BYTES, DAEMON_SHA256, DaemonAssetRefused, extract_reviewed_daemon
from night_shifts.bootstrap_probe_seed import COPYING_SHA256, GPL_SHA256, PACKAGE_SHA256, SOURCE_NOTICE
from night_shifts.finalization_tls_identity import (
    ControllerPublicTrust, FinalizationIdentityRefused, decode_controller_trust, encode_controller_trust,
)
from night_shifts.maintenance_tls_prototype import AttemptBinding

MAX_ENTRY_BYTES = 128 * 1024
MAX_PAYLOAD_BYTES = 512 * 1024
_SOURCES = (
    'authenticated_image_finalization.py', 'bounded_tls_pipe.py', 'finalization_tls_identity.py',
    'guest/bounded_tls_serial.py', 'guest/finalization_bootstrap.py', 'guest/finalization_guest_identity.py',
    'guest/finalize_image_copy.py', 'guest/protocol_test_bootstrap.py', 'guest/publish_public_bootstrap.py',
    'guest/review_protocol_test_target.py', 'guest/serial_device_io.py', 'hyperv_image_preflight.py',
    'maintenance_credentials_prototype.py', 'maintenance_tls_prototype.py', 'public_bootstrap_kvp.py',
    'serial_pipe_io.py', 'ubuntu_preparation_control.py',
)
_EMPTY = ('night_shifts/__init__.py', 'night_shifts/guest/__init__.py')
_UNIT = 'night-shift-protocol-test.service'
_BOOTSTRAP = 'night_shifts/guest/protocol_test_bootstrap.py'
_DATA = ('COPYING', 'GPL-2.0', 'SOURCE.txt', 'controller.json', 'hv_kvp_daemon', _UNIT, 'request.json')
_NAMES = tuple(sorted((*_EMPTY, *('night_shifts/' + name for name in _SOURCES), *_DATA, 'manifest.json')))
_NOTICE = (
    b'AUTOMATIC FINALIZATION RECOVERY PAYLOAD. Only public controller trust is present.\n'
    + SOURCE_NOTICE[SOURCE_NOTICE.index(b'hv_kvp_daemon:'):SOURCE_NOTICE.index(b'The fixed parser-test CA')]
)


class RecoveryPayloadRefused(ValueError):
    """Fixed errors, not raw input or native paths."""


@dataclass(frozen=True)
class RecoveryPayload:
    raw: bytes = field(repr=False)
    sha256: str
    request_sha256: str


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True) + '\n').encode('ascii')


def _manifest(entries: dict[str, bytes], binding: AttemptBinding, request_sha256: str) -> bytes:
    return _json({'version': 1, 'operation': binding.operation, 'attempt_id': binding.attempt_id,
                  'vm_id': binding.vm_id, 'request_sha256': request_sha256,
                  'files': {name: {'bytes': len(raw), 'sha256': _sha(raw)} for name, raw in entries.items()}})


def _zip(entries: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_STORED) as archive:
        for name, raw in sorted(entries.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100444 << 16
            archive.writestr(info, raw)
    return output.getvalue()


def _asset(raw: bytes, size: int, expected: str) -> None:
    if type(raw) is not bytes or len(raw) != size or _sha(raw) != expected:
        raise RecoveryPayloadRefused('payload_asset')


def _source(name: str) -> bytes:
    path = Path(__file__).parent / name
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not 0 < info.st_size <= MAX_ENTRY_BYTES:
        raise RecoveryPayloadRefused('payload_source')
    with path.open('rb') as stream:
        raw = stream.read(MAX_ENTRY_BYTES + 1)
    if len(raw) != info.st_size:
        raise RecoveryPayloadRefused('payload_source')
    text = raw.decode('utf-8').replace('\r\n', '\n')
    if '\r' in text or '\x00' in text:
        raise RecoveryPayloadRefused('payload_source')
    return text.encode('utf-8')


def build_recovery_payload(trust: ControllerPublicTrust, *, artifacts: dict[str, str],
                           daemon_package: bytes, copying: bytes, gpl: bytes) -> RecoveryPayload:
    """Render only fixed repo assets and reviewed payload fingerprints in memory."""
    if type(trust) is not ControllerPublicTrust or type(artifacts) is not dict or len(artifacts) > 32:
        raise RecoveryPayloadRefused('payload_inputs')
    try:
        _asset(copying, 496, COPYING_SHA256)
        _asset(gpl, 18729, GPL_SHA256)
        controller = encode_controller_trust(trust)
        binding = trust.binding
        entries = {name: b'' for name in _EMPTY}
        entries.update({'night_shifts/' + name: _source(name) for name in _SOURCES})
        unit = _source('guest/' + _UNIT)
        request = {'version': 1, 'id': binding.attempt_id, 'mode': 'finalize', 'artifacts': dict(artifacts),
                   'payload': {'bootstrap': _sha(entries[_BOOTSTRAP]), 'unit': _sha(unit)}}
        digest = request_digest(request, binding)
        entries.update({'COPYING': copying, 'GPL-2.0': gpl, 'SOURCE.txt': _NOTICE, 'controller.json': controller,
                        'hv_kvp_daemon': extract_reviewed_daemon(daemon_package), _UNIT: unit,
                        'request.json': _json(request)})
        raw = _zip({**entries, 'manifest.json': _manifest(entries, binding, digest)})
        payload_sha = _sha(raw)
        validate_recovery_payload(raw, binding, expected_sha256=payload_sha)
        return RecoveryPayload(raw, payload_sha, digest)
    except (DaemonAssetRefused, FinalizationIdentityRefused, FinalizationRefused, OSError, UnicodeError):
        raise RecoveryPayloadRefused('payload_inputs') from None


def validate_recovery_payload(raw: bytes, binding: AttemptBinding, *, expected_sha256: str) -> dict[str, bytes]:
    """Offline readback only; equality with a caller's digest is NOT provenance."""
    if (type(raw) is not bytes or not 0 < len(raw) <= MAX_PAYLOAD_BYTES or type(binding) is not AttemptBinding
            or type(expected_sha256) is not str or _sha(raw) != expected_sha256):
        raise RecoveryPayloadRefused('payload_digest')
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            infos = archive.infolist()
            if tuple(info.filename for info in infos) != _NAMES:
                raise RecoveryPayloadRefused('payload_inventory')
            entries: dict[str, bytes] = {}
            for info in infos:
                if (info.compress_type != zipfile.ZIP_STORED or info.flag_bits
                        or not 0 <= info.file_size <= MAX_ENTRY_BYTES or info.compress_size != info.file_size):
                    raise RecoveryPayloadRefused('payload_shape')
                entries[info.filename] = archive.read(info)
        if _zip(entries) != raw or any(entries[name] for name in _EMPTY):
            raise RecoveryPayloadRefused('payload_shape')
        _asset(entries['hv_kvp_daemon'], DAEMON_BYTES, DAEMON_SHA256)
        _asset(entries['COPYING'], 496, COPYING_SHA256)
        _asset(entries['GPL-2.0'], 18729, GPL_SHA256)
        if entries['SOURCE.txt'] != _NOTICE or PACKAGE_SHA256.encode('ascii') not in entries['SOURCE.txt']:
            raise RecoveryPayloadRefused('payload_asset')
        decode_controller_trust(entries['controller.json'], binding)
        request: dict[str, Any] = json.loads(entries['request.json'].decode('ascii'))
        digest = request_digest(request, binding)
        if (_json(request) != entries['request.json']
                or request['payload'] != {'bootstrap': _sha(entries[_BOOTSTRAP]), 'unit': _sha(entries[_UNIT])}):
            raise RecoveryPayloadRefused('payload_request')
        manifest = entries.pop('manifest.json')
        if manifest != _manifest(entries, binding, digest):
            raise RecoveryPayloadRefused('payload_manifest')
        return entries
    except (zipfile.BadZipFile, FinalizationIdentityRefused, FinalizationRefused, UnicodeError, RecursionError):
        raise RecoveryPayloadRefused('payload_refused') from None
    except ValueError as exc:
        if type(exc) is RecoveryPayloadRefused:
            raise
        raise RecoveryPayloadRefused('payload_refused') from None
