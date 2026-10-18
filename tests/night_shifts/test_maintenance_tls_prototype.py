"""Memory-only TLS tests with fresh synthetic credentials; no live transport.

Temporary keys are fixture material, not production credentials or evidence of
Windows private-key ACL confinement. No socket, pipe, VM or certificate store.
"""
from __future__ import annotations

import hashlib
import json
import socket
import ssl
import struct
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from night_shifts.maintenance_tls_prototype import (
    MAX_CIPHER_BYTES, MAX_FRAME_BYTES, MAX_MESSAGES, OPERATION, SERVER_NAME,
    AttemptBinding, OfflineTlsEndpoint, PrototypeRefused,
)


@dataclass
class Clock:
    now: float = 100.0

    def __call__(self) -> float:
        return self.now


def certificate(name, key, issuer_key, issuer=None, *, ca=False, server=False, expired=False):
    now = datetime.now(timezone.utc)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    builder = (
        x509.CertificateBuilder().subject_name(subject)
        .issuer_name(subject if ca else issuer.subject).public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=2) if expired else now - timedelta(minutes=5))
        .not_valid_after(now - timedelta(days=1) if expired else now + timedelta(hours=1))
        .add_extension(x509.BasicConstraints(ca=ca, path_length=0 if ca else None), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(issuer_key.public_key()), critical=False)
        .add_extension(x509.KeyUsage(
            digital_signature=True, content_commitment=False, key_encipherment=False,
            data_encipherment=False, key_agreement=False, key_cert_sign=ca, crl_sign=ca,
            encipher_only=None, decipher_only=None,
        ), critical=True)
    )
    if not ca:
        usage = ExtendedKeyUsageOID.SERVER_AUTH if server else ExtendedKeyUsageOID.CLIENT_AUTH
        builder = builder.add_extension(x509.ExtendedKeyUsage([usage]), critical=False)
    if server:
        builder = builder.add_extension(x509.SubjectAlternativeName([x509.DNSName(name)]), critical=False)
    return builder.sign(issuer_key, hashes.SHA256())


@pytest.fixture(scope='module')
def material():
    with tempfile.TemporaryDirectory(prefix='maintenance-tls-synthetic-') as directory:
        root = Path(directory)
        ca_key = ec.generate_private_key(ec.SECP256R1())
        ca = certificate('synthetic CA', ca_key, ca_key, ca=True)
        foreign_key = ec.generate_private_key(ec.SECP256R1())
        foreign_ca = certificate('foreign synthetic CA', foreign_key, foreign_key, ca=True)
        result = {'ca': ca, 'foreign_ca': foreign_ca}
        profiles = [
            ('server', True, ca, ca_key, SERVER_NAME, False),
            ('other_server', True, ca, ca_key, SERVER_NAME, False),
            ('wrong_hostname', True, ca, ca_key, 'wrong.invalid', False),
            ('foreign_server', True, foreign_ca, foreign_key, SERVER_NAME, False),
            ('expired_server', True, ca, ca_key, SERVER_NAME, True),
            ('client', False, ca, ca_key, 'synthetic controller', False),
            ('other_client', False, ca, ca_key, 'other synthetic controller', False),
            ('foreign_client', False, foreign_ca, foreign_key, 'foreign controller', False),
        ]
        for label, server, issuer, issuer_key, name, expired in profiles:
            key = ec.generate_private_key(ec.SECP256R1())
            cert = certificate(name, key, issuer_key, issuer, server=server, expired=expired)
            cert_path, key_path = root / (label + '.pem'), root / (label + '.key')
            cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
            key_path.write_bytes(key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption(),
            ))
            result[label] = (cert_path, key_path, cert)
        yield result


def pin(material, label):
    return hashlib.sha256(material[label][2].public_bytes(serialization.Encoding.DER)).hexdigest()


def contexts(material, *, server='server', client='client'):
    guest = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    controller = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    for context, label in ((guest, server), (controller, client)):
        context.minimum_version = context.maximum_version = ssl.TLSVersion.TLSv1_3
        context.verify_mode = ssl.CERT_REQUIRED
        context.verify_flags |= ssl.VERIFY_X509_STRICT
        context.options |= ssl.OP_NO_TICKET
        context.load_verify_locations(cadata=material['ca'].public_bytes(serialization.Encoding.PEM).decode())
        if label:
            context.load_cert_chain(*map(str, material[label][:2]))
    guest.num_tickets = 0
    return controller, guest


def pair(material, *, server='server', client='client', controller_pin=None, guest_pin=None,
         controller_binding=None, guest_binding=None, clock=None, timeout=5.0, cancelled=lambda: False):
    clock = clock or Clock()
    controller_binding = controller_binding or AttemptBinding(uuid4().hex, str(uuid4()))
    guest_binding = guest_binding or controller_binding
    controller_context, guest_context = contexts(material, server=server, client=client)
    controller = OfflineTlsEndpoint(
        controller_context, controller_binding, role='controller',
        peer_sha256=controller_pin or pin(material, server), timeout_seconds=timeout,
        clock=clock, cancelled=cancelled,
    )
    guest = OfflineTlsEndpoint(
        guest_context, guest_binding, role='guest',
        peer_sha256=guest_pin or pin(material, client or 'client'), timeout_seconds=timeout,
        clock=clock, cancelled=cancelled,
    )
    return controller, guest


def move(source, destination, chunk=16384, trace=None):
    data = source.take_ciphertext(min(chunk, 16384))
    if data:
        if trace is not None:
            trace.extend(data)
        destination.feed_ciphertext(data)


def handshake(controller, guest, *, chunk=16384, trace=None):
    for _ in range(50000):
        controller.step()
        guest.step()
        move(controller, guest, chunk, trace)
        move(guest, controller, chunk, trace)
        if (controller.authenticated and guest.authenticated and
                not controller.pending_ciphertext and not guest.pending_ciphertext):
            return
    raise AssertionError('bounded memory fixture stalled')


def deliver(source, destination, payload, *, chunk=16384, trace=None):
    source.queue_message(payload)
    for _ in range(50000):
        source.step()
        move(source, destination, chunk, trace)
        move(destination, source, chunk, trace)
        received = destination.receive_message()
        if received is not None:
            return received
    raise AssertionError('bounded memory fixture stalled')


def envelope(endpoint, **changes):
    value = dict(
        version=1, attempt_id=endpoint._binding.attempt_id, vm_id=endpoint._binding.vm_id,
        operation=OPERATION, sender=endpoint._role, sequence=0, payload={'fixture': True},
    )
    value.update(changes)
    return value


def framed(value):
    body = json.dumps(value, separators=(',', ':')).encode()
    return struct.pack('!I', len(body)) + body


def hostile_bytes(source, destination, plain):
    # Model an authenticated hostile/malformed peer, bypassing OUR producer only.
    # It still uses real TLS; never insert plaintext into the receiving framer.
    assert source._tls.write(plain) == len(plain)
    for _ in range(50000):
        move(source, destination, 7)
        message = destination.receive_message()
        if message is not None:
            return message
        if not source.pending_ciphertext:
            return None
    raise AssertionError('bounded hostile fixture stalled')


def refused(endpoint, code):
    assert not endpoint.authenticated
    for action in (endpoint.step, endpoint.receive_message, endpoint.take_ciphertext):
        with pytest.raises(PrototypeRefused) as error:
            action()
        assert error.value.code == code
        assert str(error.value) == code


@pytest.mark.parametrize('chunk', [1, 7, 1024, 16384])
def test_mutual_tls_fragmented_bidirectional_exchange_and_hidden_payload(material, chunk):
    controller, guest = pair(material)
    trace = bytearray()
    handshake(controller, guest, chunk=chunk, trace=trace)
    marker = 'SYNTHETIC_PRIVATE_FRAME_' + uuid4().hex
    assert deliver(controller, guest, {'request': marker}, chunk=chunk, trace=trace) == {'request': marker}
    assert deliver(guest, controller, {'reply': marker}, chunk=chunk, trace=trace) == {'reply': marker}
    assert marker.encode() not in trace
    assert controller._tls.version() == guest._tls.version() == 'TLSv1.3'
    assert not controller._tls.session_reused and not guest._tls.session_reused
    assert deliver(controller, guest, {}) == {}


def test_no_socket_opened_by_memory_prototype(material, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('no socket permitted in memory prototype')
    monkeypatch.setattr(socket, 'socket', forbidden)
    controller, guest = pair(material)
    handshake(controller, guest)
    assert deliver(controller, guest, {'fixture': True}) == {'fixture': True}


@pytest.mark.parametrize('kwargs', [
    {'client': None}, {'client': 'foreign_client'}, {'client': 'server'},
    {'server': 'foreign_server'}, {'server': 'wrong_hostname'}, {'server': 'expired_server'},
])
def test_standard_certificate_validation_cannot_be_replaced_by_a_pin(material, kwargs):
    controller, guest = pair(material, **kwargs)
    with pytest.raises(PrototypeRefused, match='^tls_failure$'):
        handshake(controller, guest)


@pytest.mark.parametrize('side', ['controller', 'guest'])
def test_same_ca_different_leaf_fails_exact_peer_pin(material, side):
    if side == 'controller':
        controller, guest = pair(material, server='other_server', controller_pin=pin(material, 'server'))
        failed = controller
    else:
        controller, guest = pair(material, client='other_client', guest_pin=pin(material, 'client'))
        failed = guest
    with pytest.raises(PrototypeRefused, match='^peer_identity$'):
        handshake(controller, guest)
    refused(failed, 'peer_identity')


@pytest.mark.parametrize('action', ['queue', 'receive'])
def test_no_application_message_before_authentication(material, action):
    controller, _ = pair(material)
    with pytest.raises(PrototypeRefused, match='^not_authenticated$'):
        controller.queue_message({'fixture': True}) if action == 'queue' else controller.receive_message()
    refused(controller, 'not_authenticated')


def test_plaintext_injection_has_no_fallback(material):
    _, guest = pair(material)
    guest.feed_ciphertext(b'{"PRIVATE_CANARY":"not TLS"}\n')
    with pytest.raises(PrototypeRefused, match='^tls_failure$'):
        guest.step()
    refused(guest, 'tls_failure')


@pytest.mark.parametrize('tamper', [True, False])
def test_modified_or_replayed_tls_record_is_rejected(material, tamper):
    controller, guest = pair(material)
    handshake(controller, guest)
    controller.queue_message({'fixture': True})
    controller.step()
    wire = controller.take_ciphertext()
    assert wire and not controller.pending_ciphertext
    if tamper:
        wire = wire[:-1] + bytes([wire[-1] ^ 1])
    else:
        guest.feed_ciphertext(wire)
        assert guest.receive_message() == {'fixture': True}
    guest.feed_ciphertext(wire)
    with pytest.raises(PrototypeRefused, match='^tls_failure$'):
        guest.receive_message()
    refused(guest, 'tls_failure')


@pytest.mark.parametrize('changes', [
    {'attempt_id': 'b' * 32}, {'vm_id': '00000000-0000-4000-8000-000000000001'},
    {'operation': 'finalize'}, {'sender': 'guest'}, {'version': True},
    {'payload': []}, {'extra_field': 'PRIVATE_CANARY'},
])
def test_authenticated_frame_cannot_change_binding_or_schema(material, changes):
    controller, guest = pair(material)
    handshake(controller, guest)
    with pytest.raises(PrototypeRefused, match='^frame_binding$'):
        hostile_bytes(controller, guest, framed(envelope(controller, **changes)))
    refused(guest, 'frame_binding')


@pytest.mark.parametrize('sequence', [True, -1, 1])
def test_wrong_or_boolean_sequence_rejected(material, sequence):
    controller, guest = pair(material)
    handshake(controller, guest)
    with pytest.raises(PrototypeRefused, match='^frame_sequence$'):
        hostile_bytes(controller, guest, framed(envelope(controller, sequence=sequence)))


def test_application_replay_in_a_new_tls_record_is_rejected(material):
    controller, guest = pair(material)
    handshake(controller, guest)
    data = framed(envelope(controller))
    assert hostile_bytes(controller, guest, data) == {'fixture': True}
    with pytest.raises(PrototypeRefused, match='^frame_sequence$'):
        hostile_bytes(controller, guest, data)
    refused(guest, 'frame_sequence')


def test_two_individually_valid_but_different_attempts_refuse_each_other(material):
    controller, guest = pair(material, guest_binding=AttemptBinding(uuid4().hex, str(uuid4())))
    handshake(controller, guest)
    with pytest.raises(PrototypeRefused, match='^frame_binding$'):
        deliver(controller, guest, {'fixture': True})


@pytest.mark.parametrize('body', [
    b'not-json', b'\xff', b'{"version":1,"version":1}', b'{"payload":NaN}',
    json.dumps({'nested': [[[[[[[[[[True]]]]]]]]]]}).encode(),
])
def test_malformed_duplicate_nonfinite_or_deep_json_refused(material, body):
    controller, guest = pair(material)
    handshake(controller, guest)
    with pytest.raises(PrototypeRefused, match='^frame_value$'):
        hostile_bytes(controller, guest, struct.pack('!I', len(body)) + body)


@pytest.mark.parametrize('size', [0, MAX_FRAME_BYTES + 1, 2 ** 32 - 1])
def test_oversized_or_zero_declared_size_rejected_before_body(material, size):
    controller, guest = pair(material)
    handshake(controller, guest)
    with pytest.raises(PrototypeRefused, match='^frame_size$'):
        hostile_bytes(controller, guest, struct.pack('!I', size))


@pytest.mark.parametrize('payload', [
    {'value': float('nan')}, {'value': float('inf')}, {'value': 2 ** 63},
    {'value': b'not JSON'}, {1: 'not a text key'}, {'value': 'x' * (MAX_FRAME_BYTES + 1)},
    {'x' * (MAX_FRAME_BYTES + 1): True}, {str(i): 'x' * 1024 for i in range(32)},
])
def test_outgoing_json_work_and_values_are_bounded(material, payload):
    controller, guest = pair(material)
    handshake(controller, guest)
    with pytest.raises(PrototypeRefused, match='^frame_value$'):
        controller.queue_message(payload)
    refused(controller, 'frame_value')


def test_exact_serialized_size_checked_after_unicode_escaping(material):
    controller, guest = pair(material)
    handshake(controller, guest)
    with pytest.raises(PrototypeRefused, match='^frame_size$'):
        controller.queue_message({'value': '\u2603' * 10000})


def test_write_backpressure_and_message_count_are_fail_closed(material):
    controller, guest = pair(material)
    handshake(controller, guest)
    controller.queue_message({'first': True})
    with pytest.raises(PrototypeRefused, match='^write_busy$'):
        controller.queue_message({'second': True})
    refused(controller, 'write_busy')
    controller, guest = pair(material)
    handshake(controller, guest)
    controller._tx_sequence = MAX_MESSAGES
    with pytest.raises(PrototypeRefused, match='^message_limit$'):
        controller.queue_message({})


def test_input_and_cumulative_handshake_buffer_bounds(material):
    controller, _ = pair(material)
    with pytest.raises(PrototypeRefused, match='^cipher_buffer$'):
        controller.feed_ciphertext(b'x' * (MAX_CIPHER_BYTES + 1))
    refused(controller, 'cipher_buffer')
    _, guest = pair(material)
    # Model prior consumed handshake bytes; pending BIO remains empty.
    guest._handshake_input = MAX_CIPHER_BYTES
    with pytest.raises(PrototypeRefused, match='^handshake_buffer$'):
        guest.feed_ciphertext(b'x')


@pytest.mark.parametrize('limit', [0, -1, 16385, True])
def test_cipher_drain_is_bounded(material, limit):
    controller, _ = pair(material)
    with pytest.raises(PrototypeRefused, match='^cipher_buffer$'):
        controller.take_ciphertext(limit)


def test_eof_during_handshake_and_truncated_encrypted_frame(material):
    _, guest = pair(material)
    guest.feed_eof()
    with pytest.raises(PrototypeRefused, match='^tls_failure$'):
        guest.step()
    controller, guest = pair(material)
    handshake(controller, guest)
    assert hostile_bytes(controller, guest, struct.pack('!I', 100) + b'{') is None
    guest.feed_eof()
    with pytest.raises(PrototypeRefused) as error:
        guest.receive_message()
    assert error.value.code in ('tls_failure', 'truncated_frame')
    refused(guest, error.value.code)


def test_feed_after_eof_and_close_are_terminal(material):
    controller, _ = pair(material)
    controller.feed_eof()
    with pytest.raises(PrototypeRefused, match='^input_closed$'):
        controller.feed_ciphertext(b'x')
    refused(controller, 'input_closed')
    controller, _ = pair(material)
    controller.close()
    controller.close()
    refused(controller, 'closed')


@pytest.mark.parametrize('timeout', [0, -1, 901, float('inf'), float('nan'), True, 10 ** 1000])
def test_invalid_execution_budget_refused(material, timeout):
    with pytest.raises(PrototypeRefused, match='^configuration$'):
        pair(material, timeout=timeout)


def test_deadline_and_cancel_are_cooperative_terminal_checks(material):
    clock = Clock()
    controller, guest = pair(material, clock=clock, timeout=1)
    handshake(controller, guest)
    clock.now += 1
    with pytest.raises(PrototypeRefused, match='^deadline$'):
        controller.queue_message({})
    refused(controller, 'deadline')
    stopped = [False]
    controller, guest = pair(material, cancelled=lambda: stopped[0])
    handshake(controller, guest)
    stopped[0] = True
    with pytest.raises(PrototypeRefused, match='^cancelled$'):
        guest.receive_message()
    refused(guest, 'cancelled')


def test_late_provider_write_cannot_release_partial_success_ciphertext(material):
    controller, guest = pair(material, timeout=1)
    handshake(controller, guest)
    controller.queue_message({'fixture': True})
    controller._clock = iter([100.0, 102.0]).__next__
    with pytest.raises(PrototypeRefused, match='^deadline$'):
        controller.step()
    refused(controller, 'deadline')


def test_late_receive_never_returns_a_buffered_message(material):
    controller, guest = pair(material, timeout=1)
    handshake(controller, guest)
    controller.queue_message({'fixture': True})
    controller.step()
    move(controller, guest)
    guest._clock = iter([100.0, 100.0, 102.0]).__next__
    with pytest.raises(PrototypeRefused, match='^deadline$'):
        guest.receive_message()
    refused(guest, 'deadline')


@pytest.mark.parametrize('setting', ['hostname', 'strict', 'verify', 'tickets', 'version', 'post_auth', 'sni'])
def test_unsafe_contexts_refused_without_tls_exchange(material, setting):
    controller_context, guest_context = contexts(material)
    context, role, peer = controller_context, 'controller', pin(material, 'server')
    if setting == 'hostname':
        context.check_hostname = False
    elif setting == 'strict':
        context.verify_flags &= ~ssl.VERIFY_X509_STRICT
    elif setting == 'verify':
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    elif setting == 'tickets':
        context, role, peer = guest_context, 'guest', pin(material, 'client')
        context.num_tickets = 2
    elif setting == 'version':
        context.minimum_version = ssl.TLSVersion.TLSv1_2
    elif setting == 'post_auth':
        context.post_handshake_auth = True
    else:
        context, role, peer = guest_context, 'guest', pin(material, 'client')
        context.sni_callback = lambda *args: None
    with pytest.raises(PrototypeRefused, match='^configuration$'):
        OfflineTlsEndpoint(context, AttemptBinding(uuid4().hex, str(uuid4())), role=role, peer_sha256=peer)


def test_tls_secret_key_logging_is_refused_before_handshake(material, tmp_path):
    context, _ = contexts(material)
    log = tmp_path / 'synthetic-no-traffic.log'
    context.keylog_filename = str(log)
    with pytest.raises(PrototypeRefused, match='^configuration$'):
        OfflineTlsEndpoint(context, AttemptBinding(uuid4().hex, str(uuid4())),
                           role='controller', peer_sha256=pin(material, 'server'))
    # Some OpenSSL builds emit a fixed non-secret comment when the log is opened.
    assert b'CLIENT_RANDOM' not in log.read_bytes() and b'TRAFFIC_SECRET' not in log.read_bytes()


def test_changed_context_is_refused_before_application_data(material):
    controller, guest = pair(material)
    handshake(controller, guest)
    controller._context.check_hostname = False
    with pytest.raises(PrototypeRefused, match='^configuration$'):
        controller.queue_message({'PRIVATE_CANARY': True})
    refused(controller, 'configuration')


@pytest.mark.parametrize('attempt,vm', [
    ('A' * 32, '00000000-0000-4000-8000-000000000001'),
    ('a', '00000000-0000-4000-8000-000000000001'),
    ('a' * 32, 'NOT_A_VM'), ('a' * 32, '00000000-0000-0000-0000-000000000000'),
])
def test_noncanonical_or_null_binding_refused(attempt, vm):
    with pytest.raises(ValueError, match='^invalid prototype binding$'):
        AttemptBinding(attempt, vm)
