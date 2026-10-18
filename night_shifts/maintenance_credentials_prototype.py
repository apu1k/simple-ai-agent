"""OFFLINE credential-boundary models and public-bootstrap codec only.

No key generation/storage, path discovery, ACL reading/writing, media authoring,
KVP/WMI access, serial adapter, VM operation, production integration or grants.
A valid record is PUBLIC DATA, not a provenance/authentication certificate.
The trusted acquisition path and private-key protection remain live blockers.
"""
from __future__ import annotations

import base64
import binascii
import hmac
import json
import re
import ssl
from dataclasses import dataclass, field
from typing import Any

from night_shifts.maintenance_tls_prototype import OPERATION, AttemptBinding
from night_shifts.ubuntu_preparation_control import AclRule, AclSnapshot

SYSTEM_SID = 'S-1-5-18'
ADMINS_SID = 'S-1-5-32-544'
FULL_CONTROL = 0x001F01FF
PUBLIC_ITEM_NAME = 'night-shift-inspect-tls-v1'
MAX_PUBLIC_RECORD_BYTES = 1000  # ASCII: below documented 1024-character KVP Data bound.
MAX_CA_DER_BYTES = 512


class CredentialPrototypeRefused(RuntimeError):
    """Fixed reason codes; no private material, raw record or exception text."""


def check_host_key_acl_model(
    snapshot: AclSnapshot, *, protected: bool, reparse: bool, links: int,
    directory: bool = False,
) -> None:
    """Check a proposed NEW secret-store ACL shape, NOT native access/provenance.

    Only SYSTEM/Administrators FullControl; no direct operator, VM or capability
    ACE. Directory rules explicitly inherit to children; leaf rules are explicit.
    The caller supplying facts cannot thereby attest a real protected file.
    Ancestor replacement, create-new, identity, sharing and real token checks
    are not implemented by this model. Never use it to repair existing ACLs.
    """
    if (type(snapshot) is not AclSnapshot or protected is not True or reparse is not False or
            type(links) is not int or links != 1 or type(directory) is not bool or
            snapshot.owner not in (SYSTEM_SID, ADMINS_SID) or
            type(snapshot.rules) is not tuple or len(snapshot.rules) != 2):
        raise CredentialPrototypeRefused('host_key_acl')
    remaining = {SYSTEM_SID, ADMINS_SID}
    flags = 3 if directory else 0
    for rule in snapshot.rules:
        if (type(rule) is not AclRule or rule.sid not in remaining or
                type(rule.mask) is not int or rule.mask != FULL_CONTROL or
                type(rule.flags) is not int or rule.flags != flags or
                type(rule.kind) is not int or rule.kind != 0):
            raise CredentialPrototypeRefused('host_key_acl')
        remaining.remove(rule.sid)


def _public_ca(der: bytes) -> None:
    """Parse exactly one bounded CA certificate in an in-memory OpenSSL store.

    This rejects private-key DER/public-key blobs and concatenated/trailing data.
    It does not authenticate the issuer/origin, attest key ownership, or replace
    real handshake chain/time/hostname/role validation and exact leaf pinning.
    """
    if type(der) is not bytes or not 1 <= len(der) <= MAX_CA_DER_BYTES:
        raise CredentialPrototypeRefused('public_certificate')
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    try:
        context.load_verify_locations(cadata=der)
        certificates = context.get_ca_certs(binary_form=True)
    except (ssl.SSLError, ValueError):
        raise CredentialPrototypeRefused('public_certificate') from None
    stats = context.cert_store_stats()
    if (stats['x509'] != 1 or stats['x509_ca'] != 1 or len(certificates) != 1 or
            not hmac.compare_digest(certificates[0], der)):
        raise CredentialPrototypeRefused('public_certificate')


@dataclass(frozen=True)
class PublicBootstrap:
    """Validated public record shape only; no live trust/authorization claim."""

    binding: AttemptBinding
    server_ca_der: bytes = field(repr=False)
    server_leaf_sha256: str

    def __post_init__(self) -> None:
        if (type(self.binding) is not AttemptBinding or
                type(self.server_leaf_sha256) is not str or
                re.fullmatch('[0-9a-f]{64}', self.server_leaf_sha256) is None):
            raise CredentialPrototypeRefused('bootstrap_schema')
        _public_ca(self.server_ca_der)


def encode_public_bootstrap(value: PublicBootstrap) -> bytes:
    if type(value) is not PublicBootstrap:
        raise CredentialPrototypeRefused('bootstrap_schema')
    # No private-key/credential field or arbitrary file/payload input exists.
    raw = json.dumps({
        'version': 1, 'attempt_id': value.binding.attempt_id, 'vm_id': value.binding.vm_id,
        'operation': OPERATION,
        'server_ca_der_b64': base64.b64encode(value.server_ca_der).decode('ascii'),
        'server_leaf_sha256': value.server_leaf_sha256,
    }, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')
    if len(raw) > MAX_PUBLIC_RECORD_BYTES:
        raise CredentialPrototypeRefused('bootstrap_size')
    return raw


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate bootstrap key')
        result[key] = value
    return result


def _constant(_: str) -> None:
    raise ValueError('invalid bootstrap constant')


def decode_public_bootstrap(
    raw: bytes, expected: AttemptBinding, *, observed_vm_id: str,
    item_name: str, item_source: int,
) -> PublicBootstrap:
    """Check data from a FUTURE independently trusted exact-VM acquisition path.

    Merely passing matching arguments is NOT WMI attestation. No query is made.
    A live adapter must obtain VM association/name/source itself, not from a
    pipe message, worker task, untrusted XML or guest-selected lookup target.
    """
    if (type(expected) is not AttemptBinding or type(observed_vm_id) is not str or
            observed_vm_id != expected.vm_id or item_name != PUBLIC_ITEM_NAME or
            type(item_source) is not int or item_source != 1):
        raise CredentialPrototypeRefused('bootstrap_origin')
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_PUBLIC_RECORD_BYTES:
        raise CredentialPrototypeRefused('bootstrap_size')
    try:
        value = json.loads(raw.decode('ascii'), object_pairs_hook=_unique, parse_constant=_constant)
    except (ValueError, TypeError, RecursionError):
        raise CredentialPrototypeRefused('bootstrap_schema') from None
    fields = {'version', 'attempt_id', 'vm_id', 'operation',
              'server_ca_der_b64', 'server_leaf_sha256'}
    if (type(value) is not dict or set(value) != fields or
            type(value['version']) is not int or value['version'] != 1 or
            value['attempt_id'] != expected.attempt_id or value['vm_id'] != expected.vm_id or
            value['operation'] != OPERATION or type(value['server_ca_der_b64']) is not str):
        raise CredentialPrototypeRefused('bootstrap_schema')
    encoded = value['server_ca_der_b64']
    if not 4 <= len(encoded) <= 4 * ((MAX_CA_DER_BYTES + 2) // 3):
        raise CredentialPrototypeRefused('public_certificate')
    try:
        der = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise CredentialPrototypeRefused('public_certificate') from None
    if base64.b64encode(der).decode('ascii') != encoded:
        raise CredentialPrototypeRefused('public_certificate')
    return PublicBootstrap(expected, der, value['server_leaf_sha256'])


class PublicBootstrapLatch:
    """Freeze one model record; identical polling is okay, changes fail forever.

    This is not a permanent attempt claim or a way to authorize discovery.
    Recreating this object does not prove a fresh/authorized VM or boot epoch.
    """

    def __init__(self, binding: AttemptBinding) -> None:
        if type(binding) is not AttemptBinding:
            raise CredentialPrototypeRefused('bootstrap_schema')
        self._binding = binding
        self._value: PublicBootstrap | None = None
        self._failure: str | None = None

    def observe(self, raw: bytes, *, observed_vm_id: str,
                item_name: str, item_source: int) -> PublicBootstrap:
        if self._failure is not None:
            raise CredentialPrototypeRefused(self._failure)
        try:
            value = decode_public_bootstrap(
                raw, self._binding, observed_vm_id=observed_vm_id,
                item_name=item_name, item_source=item_source,
            )
            if self._value is not None and value != self._value:
                raise CredentialPrototypeRefused('bootstrap_changed')
        except CredentialPrototypeRefused as error:
            self._failure = str(error)
            self._value = None
            raise CredentialPrototypeRefused(self._failure) from None
        if self._value is None:
            self._value = value
        return self._value

    def close(self) -> None:
        if self._failure is None:
            self._failure = 'closed'
        self._value = None
