"""Strict TLS contexts for the fixed finalization attempt, not key provisioning.

The caller owns fresh, protected PEM material and must hold the backing objects
stable while SSL loads them. This module does not create paths, attest storage,
trust a certificate store, or accept credentials from the serial wire.
"""
from __future__ import annotations

import re
import ssl
from dataclasses import dataclass, field
from pathlib import Path

from night_shifts.maintenance_credentials_prototype import CredentialPrototypeRefused, _public_ca
from night_shifts.maintenance_tls_prototype import FINALIZATION_OPERATION, AttemptBinding


class FinalizationIdentityRefused(RuntimeError):
    """Fixed labels only; never paths, keys or provider messages."""


@dataclass(frozen=True)
class ControllerPublicTrust:
    """Only the per-attempt public controller trust destined for reviewed media."""

    binding: AttemptBinding
    ca_der: bytes = field(repr=False)
    leaf_sha256: str

    def __post_init__(self) -> None:
        if (type(self.binding) is not AttemptBinding or self.binding.operation != FINALIZATION_OPERATION
                or type(self.leaf_sha256) is not str or re.fullmatch('[0-9a-f]{64}', self.leaf_sha256) is None):
            raise FinalizationIdentityRefused('controller_public_trust')
        try:
            _public_ca(self.ca_der)
        except CredentialPrototypeRefused:
            raise FinalizationIdentityRefused('controller_public_trust') from None


@dataclass(frozen=True)
class LocalPemIdentity:
    """Paths from the protected local credential owner only; never a media input."""

    certificate: Path = field(repr=False)
    key: Path = field(repr=False)


def _context(identity: LocalPemIdentity, peer_ca_der: bytes, *, guest: bool) -> ssl.SSLContext:
    if (type(identity) is not LocalPemIdentity or not isinstance(identity.certificate, Path)
            or not isinstance(identity.key, Path) or not identity.certificate.is_absolute()
            or not identity.key.is_absolute() or identity.certificate == identity.key):
        raise FinalizationIdentityRefused('local_identity')
    try:
        _public_ca(peer_ca_der)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER if guest else ssl.PROTOCOL_TLS_CLIENT)
        context.minimum_version = context.maximum_version = ssl.TLSVersion.TLSv1_3
        context.verify_mode = ssl.CERT_REQUIRED
        context.verify_flags = ssl.VERIFY_X509_STRICT | ssl.VERIFY_X509_TRUSTED_FIRST
        context.options |= ssl.OP_NO_TICKET
        context.hostname_checks_common_name = False
        context.load_verify_locations(cadata=peer_ca_der)
        if guest:
            context.num_tickets = 0
        # Supplying a password prevents an encrypted PEM from prompting at boot.
        # A protected owner supplies unencrypted, short-lived, private material.
        context.load_cert_chain(identity.certificate, identity.key, password=b'')
    except (OSError, ValueError, CredentialPrototypeRefused):
        raise FinalizationIdentityRefused('tls_identity_load') from None
    return context


def controller_context(identity: LocalPemIdentity, guest_ca_der: bytes) -> ssl.SSLContext:
    return _context(identity, guest_ca_der, guest=False)


def guest_context(identity: LocalPemIdentity, trust: ControllerPublicTrust) -> ssl.SSLContext:
    if type(trust) is not ControllerPublicTrust:
        raise FinalizationIdentityRefused('controller_public_trust')
    trust.__post_init__()
    return _context(identity, trust.ca_der, guest=True)
