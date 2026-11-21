"""Issue a one-attempt guest TLS server identity with the live ISO's OpenSSL.

Private keys go straight to sealed Linux memfds. No key is passed through
Python bytes, command arguments, a log, an optical file or the target disk.
The reviewed boot owner still owns isolation, runtime provenance and teardown.
"""
from __future__ import annotations

import hashlib
import importlib
import os
import secrets
import ssl
import stat
import subprocess
import sys
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any

from night_shifts.finalization_tls_identity import FinalizationIdentityRefused, LocalPemIdentity
from night_shifts.maintenance_credentials_prototype import (
    CredentialPrototypeRefused, FinalizationPublicBootstrap, encode_finalization_bootstrap,
)
from night_shifts.maintenance_tls_prototype import FINALIZATION_OPERATION, SERVER_NAME, AttemptBinding
from night_shifts.serial_pipe_io import IOBudget

_OPENSSL = '/usr/bin/openssl'
_KEY_ARGS = ('genpkey', '-algorithm', 'EC', '-pkeyopt', 'ec_paramgen_curve:P-256')
_CA_EXT = (
    'basicConstraints=critical,CA:TRUE,pathlen:0', 'keyUsage=critical,keyCertSign,cRLSign',
    'subjectKeyIdentifier=hash', 'authorityKeyIdentifier=keyid:always',
)
_LEAF_EXT = (
    '[finalization_server]\n'
    'basicConstraints=critical,CA:FALSE\n'
    'keyUsage=critical,digitalSignature\n'
    'extendedKeyUsage=serverAuth\n'
    'subjectKeyIdentifier=hash\n'
    'authorityKeyIdentifier=keyid:always\n'
    f'subjectAltName=DNS:{SERVER_NAME}\n'
).encode('ascii')
_MAX_SLOT_BYTES = 4096


def _platform_guard() -> None:
    if sys.platform != 'linux' or any((os.getuid(), os.geteuid(), os.getgid(), os.getegid())):
        raise FinalizationIdentityRefused('guest_issuer_context')
    try:
        with Path('/proc/swaps').open('rb') as stream:
            if stream.read(4097).split() != [b'Filename', b'Type', b'Size', b'Used', b'Priority']:
                raise FinalizationIdentityRefused('guest_issuer_swap')
        info = Path(_OPENSSL).lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_gid != 0
                or info.st_mode & 0o7022 or not info.st_mode & stat.S_IXUSR):
            raise FinalizationIdentityRefused('guest_issuer_tool')
        # Only in the disposable guest process. Children inherit the core limit,
        # but Linux can reset their per-process dumpable attribute on exec.
        resource = importlib.import_module('resource')
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        ctypes = importlib.import_module('ctypes')
        if ctypes.CDLL(None, use_errno=True).prctl(4, 0, 0, 0, 0) != 0:  # PR_SET_DUMPABLE
            raise FinalizationIdentityRefused('guest_issuer_core_limit')
    except OSError:
        raise FinalizationIdentityRefused('guest_issuer_context') from None


class _Slot:
    """An anonymous private descriptor owned by this one-shot worker."""

    def __init__(self) -> None:
        native: Any = os
        # MFD_NOEXEC_SEAL is available in the reviewed ISO's Linux 6.8 ABI.
        noexec = getattr(native, 'MFD_NOEXEC_SEAL', 0x0008)
        self.fd: int = native.memfd_create('night-shift-tls', native.MFD_CLOEXEC | native.MFD_ALLOW_SEALING | noexec)
        try:
            native.fchmod(self.fd, 0o600)  # Before this descriptor can receive key bytes.
            info = os.fstat(self.fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 0 or info.st_uid != 0
                    or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size != 0 or os.get_inheritable(self.fd)):
                raise FinalizationIdentityRefused('guest_issuer_slot')
        except BaseException:
            os.close(self.fd)
            raise
        self.path = Path('/proc/self/fd') / str(self.fd)

    def __enter__(self) -> _Slot:
        return self

    def __exit__(self, *_: object) -> None:
        os.close(self.fd)

    def seal(self) -> None:
        fcntl = importlib.import_module('fcntl')
        native: Any = os
        if not 0 < os.fstat(self.fd).st_size <= _MAX_SLOT_BYTES:
            raise FinalizationIdentityRefused('guest_issuer_slot')
        native.fchmod(self.fd, 0o400)
        seals = fcntl.F_SEAL_SEAL | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_GROW | fcntl.F_SEAL_WRITE
        fcntl.fcntl(self.fd, fcntl.F_ADD_SEALS, seals)
        if fcntl.fcntl(self.fd, fcntl.F_GET_SEALS) & seals != seals:
            raise FinalizationIdentityRefused('guest_issuer_slot')

    def populate(self, raw: bytes) -> None:
        if not 0 < len(raw) <= _MAX_SLOT_BYTES or os.write(self.fd, raw) != len(raw):
            raise FinalizationIdentityRefused('guest_issuer_slot')
        self.seal()

    def public_pem(self) -> bytes:
        # Only called on public certificates, never on a private key slot.
        native: Any = os
        raw: bytes = native.pread(self.fd, _MAX_SLOT_BYTES + 1, 0)
        if not 0 < len(raw) <= _MAX_SLOT_BYTES:
            raise FinalizationIdentityRefused('guest_issuer_certificate')
        return raw


def _openssl(args: tuple[str, ...], output: _Slot, budget: IOBudget, *inputs: _Slot) -> None:
    # Only fixed local argv. Inherit only the descriptors this exact step needs.
    result = subprocess.run(
        [_OPENSSL, *args], stdin=subprocess.DEVNULL, stdout=output.fd, stderr=subprocess.DEVNULL,
        pass_fds=tuple(part.fd for part in inputs), close_fds=True, cwd='/',
        env={'LANG': 'C', 'LC_ALL': 'C', 'OPENSSL_CONF': '/dev/null'},
        timeout=min(5, budget.remaining()), check=False,
    )
    budget.remaining()
    if result.returncode != 0:
        raise FinalizationIdentityRefused('guest_issuer_command')
    output.seal()


def _serial() -> str:
    return hex(secrets.randbits(159) or 1)


def _der(slot: _Slot) -> bytes:
    return ssl.PEM_cert_to_DER_cert(slot.public_pem().decode('ascii').strip())


@contextmanager
def new_guest_identity(binding: AttemptBinding, budget: IOBudget) -> Iterator[
    tuple[FinalizationPublicBootstrap, LocalPemIdentity]
]:
    """Return public evidence and TLS-load handles, not teardown or key erasure."""
    if type(binding) is not AttemptBinding or binding.operation != FINALIZATION_OPERATION:
        raise FinalizationIdentityRefused('guest_issuer_context')
    budget.remaining()
    _platform_guard()
    budget.remaining()
    with ExitStack() as identity:
        try:
            key = identity.enter_context(_Slot())
            leaf = identity.enter_context(_Slot())
            with ExitStack() as scratch:
                ca_key, ca, csr, profile = (scratch.enter_context(_Slot()) for _ in range(4))
                profile.populate(_LEAF_EXT)
                _openssl(_KEY_ARGS, ca_key, budget)
                _openssl(('req', '-new', '-x509', '-sha256', '-days', '1', '-set_serial', _serial(),
                          '-config', '/dev/null', '-subj', '/CN=Night Shift Recovery CA', '-key', str(ca_key.path),
                          *(part for ext in _CA_EXT for part in ('-addext', ext))), ca, budget, ca_key)
                _openssl(_KEY_ARGS, key, budget)
                _openssl(('req', '-new', '-sha256', '-config', '/dev/null', '-subj', '/CN=' + SERVER_NAME,
                          '-key', str(key.path)), csr, budget, key)
                _openssl(('x509', '-req', '-sha256', '-days', '1', '-set_serial', _serial(),
                          '-in', str(csr.path), '-CA', str(ca.path), '-CAkey', str(ca_key.path),
                          '-extfile', str(profile.path), '-extensions', 'finalization_server'),
                         leaf, budget, csr, ca, ca_key, profile)
                public = FinalizationPublicBootstrap(binding, _der(ca), hashlib.sha256(_der(leaf)).hexdigest())
                encode_finalization_bootstrap(public)
        except (OSError, subprocess.SubprocessError, ValueError, CredentialPrototypeRefused):
            raise FinalizationIdentityRefused('guest_issuer_failed') from None
        budget.remaining()
        # The issuer signing key has been closed before this yield/publication.
        yield public, LocalPemIdentity(leaf.path, key.path)
