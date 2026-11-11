"""Memory-only setup packet for an independently reviewed protected bootstrap.

No file access, approval, compilation, installation, discovery or execution. The
packet and its hashes are DATA, not authority. Never elevate checkout code.
"""
from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import dataclass
from typing import cast

from night_shifts import bootstrap_native_install_request as request

SCOPE = 'observed_setup_references_not_authorization'
LEAF = 'native-validator-bootstrap'
ANCHORS = ('', 'approval', 'approval/claims', 'imports', 'imports/claims', 'launch', 'launch/scratch')
MAGIC = b'NVSU0001'
MAX_PACKET_BYTES = 129 * 1024**2
PACKET_NAMES = tuple(sorted(('request.json', 'reviewed-profile.cs', 'approval/approval.json',
    'imports/provision-request.json', *('imports/' + n for n in request.IMPORT_NAMES),
    *('launch/' + n for n in request.LAUNCH_NAMES))))


class SetupRefused(RuntimeError):
    """Fixed consistency labels; never an installation/execution grant."""


@dataclass(frozen=True)
class SetupPacket:
    """Immutable local bytes. Observed digest MUST NOT be promoted to approval."""

    packet: bytes
    sha256: str
    guardian_profile: bytes


def _references(value: object) -> tuple[dict[str, object], str, str, int, dict[str, int]]:
    root = request._fields(value, ('version', 'scope', 'operator_sid', 'parent', 'indices'))
    request._number(root['version'], 1, 1)
    if root['scope'] != SCOPE or type(root['scope']) is not str:
        raise SetupRefused('references_scope')
    parent = request._fields(root['parent'], ('path', 'identity'))
    path = request._path(parent['path'], 150)
    volume, parent_index = request._identity(parent['identity'])
    indices = request._fields(root['indices'], ANCHORS)
    checked = {name: request._number(indices[name], 1, 2**64 - 1) for name in ANCHORS}
    if len(set((parent_index, *checked.values()))) != len(ANCHORS) + 1:
        raise SetupRefused('references_alias')
    setup = path + '\\' + LEAF
    profile = {'version': 1, 'scope': request.GUARDIAN_PROFILE_SCOPE,
        'operator_sid': root['operator_sid'], 'approval_anchor': {'path': setup + '\\approval',
        'identity': {'volume': volume, 'index': checked['approval']}}, 'launch_root': setup + '\\launch'}
    request.build_validation_guardian_profile(profile)  # canonical SID/path bounds
    return profile, setup, cast(str, root['operator_sid']), volume, checked


def setup_guardian_profile(references: object) -> bytes:
    """Build non-circular profile DATA from separately observed/reviewed anchors."""
    try:
        profile, *_ = _references(references)
        return request.build_validation_guardian_profile(profile)
    except request.InstallRequestRefused:
        raise SetupRefused('references') from None


def prepare_validation_setup_packet(references: object, raw: bytes, *, expected_bytes: int,
                                    expected_sha256: str, import_files: object,
                                    launch_files: object) -> SetupPacket:
    """Verify fixed request/leaf pins, then frame ONE bounded deterministic packet.

    Inputs must be independently reviewed, including the finished executable pins
    and effective platform/load closure. Nothing here proves that an executable
    contains the emitted profile, or authorizes installation of the policy.
    """
    try:
        _, setup, sid, volume, indices = _references(references)
        bound = request.bind_validation_install_request(raw, expected_bytes=expected_bytes,
                                                        expected_sha256=expected_sha256)
        value = json.loads(raw)
        if value['operator_sid'] != sid:
            raise SetupRefused('operator_binding')
        for field, name in (('launch_anchor', 'launch'), ('import_anchor', 'imports')):
            anchor = value[field]
            if anchor['path'] != setup + '\\' + name or anchor['identity'] != {'volume': volume, 'index': indices[name]}:
                raise SetupRefused('anchor_binding')
        if value['launch_anchor']['scratch_identity'] != {'volume': volume, 'index': indices['launch/scratch']}:
            raise SetupRefused('scratch_binding')
        # Source/output must be entirely outside the setup tree, not merely
        # disjoint from its launch/import siblings. All observed anchors are distinct.
        reserved = {(volume, index) for index in indices.values()}
        parent = cast(dict[str, object], cast(dict[str, object], references)['parent'])
        reserved.add(request._identity(parent['identity']))
        for name in ('source', 'output_parent'):
            place = value['provision'][name]
            path = place['path'].lower()
            if (path == setup.lower() or path.startswith(setup.lower() + '\\')
                    or setup.lower().startswith(path + '\\') or request._identity(place['identity']) in reserved):
                raise SetupRefused('setup_overlap')
        files: dict[str, bytes] = {'request.json': raw, 'reviewed-profile.cs': setup_guardian_profile(references),
            'imports/provision-request.json': bound.worker_request,
            'approval/approval.json': request._json({
                'version': 1, 'scope': 'protected_native_validator_install_approval_once', 'operation': request.OPERATION,
                'operator_sid': sid, 'budget_seconds': value['budget_seconds'], 'expires_unix': value['expires_unix'],
                'request_bytes': len(raw), 'request_sha256': expected_sha256})}
        for supplied, field, prefix, names in ((import_files, 'import_anchor', 'imports/', request.IMPORT_NAMES),
                                               (launch_files, 'launch_anchor', 'launch/', request.LAUNCH_NAMES)):
            if type(supplied) is not dict or set(supplied) != set(names):
                raise SetupRefused('inventory')
            supplied = cast(dict[str, object], supplied)
            for pin in value[field]['files']:
                data = supplied[pin['name']]
                if (type(data) is not bytes or len(data) != pin['bytes']
                        or hashlib.sha256(data).hexdigest() != pin['sha256']):
                    raise SetupRefused('leaf_pin')
                files[prefix + pin['name']] = data
        total = 12 + sum(6 + len(name) + len(data) for name, data in files.items())
        if total > MAX_PACKET_BYTES or tuple(sorted(files)) != PACKET_NAMES:
            raise SetupRefused('packet_bound')
        pieces = [MAGIC, struct.pack('<I', len(PACKET_NAMES))]
        for name in PACKET_NAMES:
            encoded = name.encode('ascii')
            data = files[name]
            pieces.extend((struct.pack('<H', len(encoded)), encoded, struct.pack('<I', len(data)), data))
        packet = b''.join(pieces)
        return SetupPacket(packet, hashlib.sha256(packet).hexdigest(), files['reviewed-profile.cs'])
    except request.InstallRequestRefused:
        raise SetupRefused('request_or_references') from None
