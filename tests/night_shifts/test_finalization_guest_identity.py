"""Fixed guest issuance profile; Windows uses explicitly synthetic test slots."""
from __future__ import annotations

import hashlib
import os
import ssl
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID

from night_shifts.finalization_tls_identity import FinalizationIdentityRefused, guest_context
from night_shifts.guest import finalization_bootstrap as boot
from night_shifts.guest import finalization_guest_identity as issuer
from night_shifts.maintenance_credentials_prototype import encode_finalization_bootstrap
from night_shifts.maintenance_tls_prototype import SERVER_NAME, AttemptBinding
from night_shifts.serial_pipe_io import IOBudget, PipeIOError
from tests.night_shifts.test_authenticated_image_finalization import _BINDING
from tests.night_shifts.test_finalization_bootstrap_exchange import (
    identities, live_fixture, never_cancelled, unexpected,
)
from tests.night_shifts.test_maintenance_tls_prototype import material as material


@pytest.fixture
def synthetic_slots(tmp_path, monkeypatch):
    binary = (Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'Git/usr/bin/openssl.exe'
              if sys.platform == 'win32' else Path('/usr/bin/openssl'))
    if not binary.is_file():
        pytest.skip('no fixed OpenSSL test executable')
    paths = []
    calls = []

    class Slot:
        def __init__(self):
            self.path = tmp_path / (str(len(paths)) + '.pem')
            self.path.touch(exist_ok=False)
            paths.append(self.path)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.path.unlink()

        def populate(self, raw):
            self.path.write_bytes(raw)

        def public_pem(self):
            return self.path.read_bytes()

    def openssl(args, output, budget, *inputs):
        assert 'PRIVATE KEY' not in ' '.join(args)
        assert all(part.path.is_file() for part in inputs)
        calls.append(args[0])
        result = subprocess.run([str(binary), *args], stdin=subprocess.DEVNULL, capture_output=True,
                                timeout=min(5, budget.remaining()), check=False, cwd=tmp_path)
        assert result.returncode == 0, result.stderr.decode('utf-8', errors='replace')
        output.path.write_bytes(result.stdout)

    monkeypatch.setattr(issuer, '_platform_guard', lambda: None)
    monkeypatch.setattr(issuer, '_Slot', Slot)
    monkeypatch.setattr(issuer, '_openssl', openssl)
    return paths, calls


def test_fixed_openssl_profile_and_freshness(material, synthetic_slots):
    _, controller, _, _ = identities(material)
    paths, calls = synthetic_slots
    seen = []
    for _ in range(2):
        with issuer.new_guest_identity(_BINDING, IOBudget(10)) as (server, identity):
            assert sum(p.is_file() for p in paths) == 2
            assert len(encode_finalization_bootstrap(server)) <= 1000
            cert_pem = identity.certificate.read_bytes()
            leaf = x509.load_pem_x509_certificate(cert_pem)
            ca = x509.load_der_x509_certificate(server.server_ca_der)
            assert ca.extensions.get_extension_for_class(x509.BasicConstraints).value.path_length == 0
            assert leaf.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value == x509.ExtendedKeyUsage(
                [ExtendedKeyUsageOID.SERVER_AUTH])
            assert leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(
                x509.DNSName) == [SERVER_NAME]
            ca_key = ca.public_key()
            assert isinstance(ca_key, ec.EllipticCurvePublicKey) and ca_key.curve.name == 'secp256r1'
            ca_key.verify(leaf.signature, leaf.tbs_certificate_bytes, ec.ECDSA(hashes.SHA256()))
            der = ssl.PEM_cert_to_DER_cert(cert_pem.decode())
            assert hashlib.sha256(der).hexdigest() == server.server_leaf_sha256
            assert guest_context(identity, controller).verify_mode == ssl.CERT_REQUIRED
            seen.append((server.server_ca_der, server.server_leaf_sha256))
        assert all(not p.exists() for p in paths)
    assert len({entry[0] for entry in seen}) == len({entry[1] for entry in seen}) == 2
    assert calls == ['genpkey', 'req', 'genpkey', 'req', 'x509'] * 2


def test_partial_issuance_closes_every_slot_without_retry(synthetic_slots, monkeypatch):
    paths, calls = synthetic_slots
    real = issuer._openssl

    def fail(args, output, budget, *inputs):
        if args[0] == 'req':
            raise OSError('PRIVATE_CANARY')
        real(args, output, budget, *inputs)

    monkeypatch.setattr(issuer, '_openssl', fail)
    with pytest.raises(FinalizationIdentityRefused, match='^guest_issuer_failed$') as error:
        with issuer.new_guest_identity(_BINDING, IOBudget(5)):
            pytest.fail('issued after failure')
    assert 'CANARY' not in str(error.value)
    assert calls == ['genpkey'] and len(paths) == 6 and all(not p.exists() for p in paths)


def test_wrong_binding_or_expired_request_refused_before_native_action(monkeypatch):
    monkeypatch.setattr(issuer, '_platform_guard', unexpected)
    inspect = AttemptBinding(_BINDING.attempt_id, _BINDING.vm_id)
    with pytest.raises(FinalizationIdentityRefused, match='^guest_issuer_context$'):
        with issuer.new_guest_identity(inspect, IOBudget(3)):
            pytest.fail('inspection could issue finalization key')
    with pytest.raises(PipeIOError, match='^deadline$'):
        with issuer.new_guest_identity(_BINDING, IOBudget(3, deadline=time.monotonic() - 1)):
            pytest.fail('expired request could start OpenSSL')


def test_live_checks_and_key_close_precede_publication(material, monkeypatch, synthetic_slots):
    _, controller, _, _ = identities(material)
    live_fixture(monkeypatch)
    paths, calls = synthetic_slots
    advertised = []
    expires = time.monotonic() + 10
    real_issue = issuer.new_guest_identity

    @contextmanager
    def observe_issue(binding, budget):
        with real_issue(binding, budget) as credentials:
            assert not advertised
            yield credentials

    def publish(public, *, deadline, cancelled):
        assert all(not path.exists() for path in paths)
        assert deadline == expires and not cancelled()
        assert public.binding == controller.binding
        advertised.append(public)

    def serve(context, binding, *, peer_sha256, deadline, cancelled):
        assert len(advertised) == 1 and deadline == expires and not cancelled()
        assert binding == _BINDING and peer_sha256 == controller.leaf_sha256
        return context.verify_mode == ssl.CERT_REQUIRED

    monkeypatch.setattr(boot, 'new_guest_identity', observe_issue)
    monkeypatch.setattr(boot, 'publish_finalization_bootstrap', publish)
    monkeypatch.setattr(boot, 'connect_and_serve_once', serve)
    assert boot.serve_fresh_guest_once(controller, deadline=expires, cancelled=never_cancelled)
    assert len(calls) == 5
    live_fixture(monkeypatch, 'swap')
    monkeypatch.setattr(boot, 'new_guest_identity', unexpected)
    with pytest.raises(boot.FinalizationRefused, match='^unverified_recovery_boot$'):
        boot.serve_fresh_guest_once(controller, deadline=expires, cancelled=never_cancelled)


@pytest.mark.skipif(sys.platform != 'linux', reason='native sealed memfd and OpenSSL on Linux only')
def test_native_ram_issuance_child():
    if os.getuid() != 0 or not Path('/usr/bin/openssl').is_file() or len(Path('/proc/swaps').read_text().splitlines()) != 1:
        pytest.skip('native fixture requires disposable root Linux with no swap and fixed OpenSSL')
    # Limit core dumps only inside this disposable child. No VM/native pool I/O.
    code = '''
import os, stat
from night_shifts.guest.finalization_guest_identity import new_guest_identity
from night_shifts.maintenance_tls_prototype import AttemptBinding, FINALIZATION_OPERATION
from night_shifts.serial_pipe_io import IOBudget
binding = AttemptBinding('1' * 32, '51434da9-9168-428a-8624-72a246ccc18d', FINALIZATION_OPERATION)
with new_guest_identity(binding, IOBudget(10)) as (public, identity):
    assert public.server_leaf_sha256
    for path in (identity.certificate, identity.key):
        assert 'memfd:' in os.readlink(path)
        info = path.stat()
        assert stat.S_IMODE(info.st_mode) == 0o400 and info.st_nlink == 0
    fd = os.open(identity.key, os.O_WRONLY)
    try:
        try:
            os.write(fd, b'seal-test')
            raise AssertionError('sealed key was writable')
        except PermissionError:
            pass
    finally:
        os.close(fd)
assert not identity.key.exists()
'''
    result = subprocess.run([sys.executable, '-B', '-c', code], capture_output=True, timeout=15, check=False)
    assert result.returncode == 0, result.stderr.decode('utf-8', errors='replace')
