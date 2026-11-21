"""Author and read back the public-only automatic recovery seed in memory."""
from __future__ import annotations

import base64
import hashlib
import io
import json
from dataclasses import dataclass, field

from night_shifts.authenticated_image_finalization import request_digest
from night_shifts.finalization_recovery_payload import (
    RecoveryPayload, RecoveryPayloadRefused, _source, validate_recovery_payload,
)
from night_shifts.guest.finalization_recovery_entry import ENTRY
from night_shifts.maintenance_tls_prototype import FINALIZATION_OPERATION, AttemptBinding

MAX_ISO_BYTES = 2 * 1024 * 1024
_CATALOG = (
    ('user-data', 'USERDATA.;1'), ('meta-data', 'METADATA.;1'), ('recovery.zip', 'RECOVERY.ZIP;1'),
    ('request.json', 'REQUEST.JSN;1'), ('night-shift-protocol-test.service', 'PROTUNIT.SRV;1'),
)


class RecoveryIsoRefused(ValueError):
    """No media paths, contents or native diagnostics."""


@dataclass(frozen=True)
class RecoveryIso:
    raw: bytes = field(repr=False)
    sha256: str
    payload_sha256: str
    request_sha256: str


def _json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':')) + '\n').encode('ascii')


def _files(payload: RecoveryPayload, binding: AttemptBinding) -> dict[str, bytes]:
    if (type(payload) is not RecoveryPayload or type(binding) is not AttemptBinding
            or binding.operation != FINALIZATION_OPERATION):
        raise RecoveryIsoRefused('binding')
    try:
        entries = validate_recovery_payload(payload.raw, binding, expected_sha256=payload.sha256)
        entry = _source('guest/finalization_recovery_entry.py')
    except (RecoveryPayloadRefused, OSError, UnicodeError):
        raise RecoveryIsoRefused('payload') from None
    if request_digest(json.loads(entries['request.json']), binding) != payload.request_sha256:
        raise RecoveryIsoRefused('request_digest')
    argv = ['/usr/bin/env', '-i', 'LANG=C', 'LC_ALL=C', '/usr/bin/unshare', '--mount', '--net',
            '--propagation', 'private', '/usr/bin/python3.12', '-I', '-B', '-S', ENTRY,
            binding.attempt_id, binding.vm_id, payload.sha256]
    user_data = {'users': [], 'ssh_pwauth': False, 'ssh_deletekeys': False, 'ssh_genkeytypes': [],
                 'package_update': False, 'package_upgrade': False,
                 'write_files': [{'path': ENTRY, 'owner': 'root:root', 'permissions': '0400',
                                  'encoding': 'b64', 'content': base64.b64encode(entry).decode('ascii')}],
                 'runcmd': [argv]}
    return {'user-data': b'#cloud-config\n' + _json(user_data),
            'meta-data': _json({'instance-id': 'night-shift-finalize-' + binding.attempt_id}),
            'recovery.zip': payload.raw, 'request.json': entries['request.json'],
            'night-shift-protocol-test.service': entries['night-shift-protocol-test.service']}


def build_recovery_iso(payload: RecoveryPayload, binding: AttemptBinding) -> RecoveryIso:
    """No installer/autoinstall data, arbitrary commands, disk writes or VM calls."""
    files = _files(payload, binding)
    try:
        import pycdlib  # type: ignore[import-not-found]
        from pycdlib.pycdlibexception import PyCdlibException  # type: ignore[import-not-found]
    except ImportError:
        raise RecoveryIsoRefused('iso_dependency') from None
    iso = pycdlib.PyCdlib()
    iso.new(vol_ident='CIDATA', rock_ridge='1.09', joliet=3)
    try:
        for name, legacy in _CATALOG:
            data = files[name]
            iso.add_fp(io.BytesIO(data), len(data), iso_path='/' + legacy, rr_name=name, joliet_path='/' + name)
        output = io.BytesIO()
        iso.write_fp(output)
        raw = output.getvalue()
    except PyCdlibException:
        raise RecoveryIsoRefused('iso_build') from None
    finally:
        iso.close()
    pin = hashlib.sha256(raw).hexdigest()
    _readback(raw, pin, files)
    return RecoveryIso(raw, pin, payload.sha256, payload.request_sha256)


def verify_recovery_iso(raw: bytes, payload: RecoveryPayload, binding: AttemptBinding, *, expected_sha256: str) -> None:
    """Read-only verification against the separately held media and inputs."""
    _readback(raw, expected_sha256, _files(payload, binding))


def _readback(raw: bytes, pin: str, files: dict[str, bytes]) -> None:
    if type(raw) is not bytes or not 17 * 2048 <= len(raw) <= MAX_ISO_BYTES or hashlib.sha256(raw).hexdigest() != pin:
        raise RecoveryIsoRefused('iso_pin')
    pvd = raw[16 * 2048:16 * 2048 + 72]
    if pvd[:7] != b'\x01CD001\x01' or pvd[40:72].rstrip(b' ') != b'CIDATA':
        raise RecoveryIsoRefused('iso_label')
    try:
        import pycdlib  # type: ignore[import-not-found]
        from pycdlib.pycdlibexception import PyCdlibException  # type: ignore[import-not-found]
    except ImportError:
        raise RecoveryIsoRefused('iso_dependency') from None
    iso = pycdlib.PyCdlib()
    opened = False
    try:
        iso.open_fp(io.BytesIO(raw))
        opened = True
        if (not iso.has_rock_ridge() or not iso.has_joliet() or iso.has_udf()
                or iso.eltorito_boot_catalog is not None or iso.pvd.space_size * 2048 != len(raw)):
            raise RecoveryIsoRefused('iso_shape')
        for namespace in ('iso_path', 'rr_path', 'joliet_path'):
            wanted = {legacy if namespace == 'iso_path' else name: files[name] for name, legacy in _CATALOG}
            for record in iso.list_children(**{namespace: '/'}):
                if record.is_dot() or record.is_dotdot():
                    continue
                if record.is_symlink() or not record.is_file() or record.is_associated_file():
                    raise RecoveryIsoRefused('iso_inventory')
                name = (record.rock_ridge.name() if namespace == 'rr_path' and record.rock_ridge is not None
                        else record.file_identifier()).decode('utf-16-be' if namespace == 'joliet_path' else 'ascii')
                if name not in wanted or record.get_data_length() != len(wanted[name]):
                    raise RecoveryIsoRefused('iso_inventory')
                data = io.BytesIO()
                iso.get_file_from_iso_fp(data, **{namespace: '/' + name})
                if data.getvalue() != wanted.pop(name):
                    raise RecoveryIsoRefused('iso_contents')
            if wanted:
                raise RecoveryIsoRefused('iso_inventory')
    except (PyCdlibException, UnicodeError, OSError):
        raise RecoveryIsoRefused('iso_readback') from None
    finally:
        if opened:
            iso.close()
