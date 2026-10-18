"""Offline models/public records only; no key store, media, KVP or VM access.

All keys are synthetic and stay in test-process memory. The ACL facts below are
models, not substituted evidence for an actual Windows credential path.
"""
from __future__ import annotations

import base64
import json
import socket
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from night_shifts.maintenance_credentials_prototype import (
    ADMINS_SID, FULL_CONTROL, MAX_CA_DER_BYTES, MAX_PUBLIC_RECORD_BYTES,
    PUBLIC_ITEM_NAME, SYSTEM_SID, CredentialPrototypeRefused, PublicBootstrap,
    PublicBootstrapLatch, check_host_key_acl_model, decode_public_bootstrap,
    encode_public_bootstrap,
)
from night_shifts.maintenance_tls_prototype import AttemptBinding
from night_shifts.ubuntu_preparation_control import AclRule, AclSnapshot

VM_WORKER = (
    'S-1-15-3-1024-2268835264-3721307629-241982045-173645152-'
    '1490879176-104643441-2915960892-1612460704'
)
OPERATOR = 'S-1-5-21-1-2-3-1001'


def root_certificate(label, *, ca=True):
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, label)])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(hours=1))
        .add_extension(x509.BasicConstraints(ca=ca, path_length=0 if ca else None), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()), critical=False)
        .add_extension(x509.KeyUsage(
            digital_signature=True, content_commitment=False, key_encipherment=False,
            data_encipherment=False, key_agreement=False, key_cert_sign=ca, crl_sign=ca,
            encipher_only=None, decipher_only=None,
        ), critical=True).sign(key, hashes.SHA256())
    )
    return key, cert.public_bytes(serialization.Encoding.DER)


@pytest.fixture(scope='module')
def material():
    key, ca = root_certificate('synthetic root')
    _, other = root_certificate('other synthetic root')
    _, leaf = root_certificate('not a CA', ca=False)
    private = key.private_bytes(
        serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption(),
    )
    return {'ca': ca, 'other': other, 'leaf': leaf, 'private': private}


@pytest.fixture
def binding():
    return AttemptBinding(uuid4().hex, str(uuid4()))


def record(material, binding, **changes):
    value = PublicBootstrap(binding, material['ca'], 'a' * 64)
    fields = json.loads(encode_public_bootstrap(value))
    fields.update(changes)
    return json.dumps(fields, sort_keys=True, separators=(',', ':')).encode('ascii')


def decode(raw, binding, **origin):
    values = dict(observed_vm_id=binding.vm_id, item_name=PUBLIC_ITEM_NAME, item_source=1)
    values.update(origin)
    return decode_public_bootstrap(raw, binding, **values)


def model(*, owner=ADMINS_SID, rules=None):
    return AclSnapshot(owner, rules if rules is not None else (
        AclRule(SYSTEM_SID, FULL_CONTROL), AclRule(ADMINS_SID, FULL_CONTROL),
    ))


def check(snapshot, **metadata):
    values = dict(protected=True, reparse=False, links=1, directory=False)
    values.update(metadata)
    return check_host_key_acl_model(snapshot, **values)


@pytest.mark.parametrize('owner', [SYSTEM_SID, ADMINS_SID])
def test_admin_system_only_host_key_model(owner):
    assert check(model(owner=owner)) is None
    directory = model(owner=owner, rules=(
        AclRule(SYSTEM_SID, FULL_CONTROL, 3), AclRule(ADMINS_SID, FULL_CONTROL, 3),
    ))
    assert check(directory, directory=True) is None


@pytest.mark.parametrize('extra', [
    AclRule(OPERATOR, 0x120089), AclRule(VM_WORKER, 0x120089),
    AclRule(VM_WORKER, FULL_CONTROL), AclRule('S-1-5-83-0', FULL_CONTROL),
    AclRule('S-1-1-0', 0x120089), AclRule('S-1-5-32-578', FULL_CONTROL),
    AclRule('S-1-1-0', 1, kind=1),
])
def test_host_secret_model_does_not_accept_extra_readers_or_unreviewed_aces(extra):
    with pytest.raises(CredentialPrototypeRefused, match='^host_key_acl$'):
        check(model(rules=model().rules + (extra,)))


@pytest.mark.parametrize('rules', [
    (), (AclRule(SYSTEM_SID, FULL_CONTROL),),
    (AclRule(SYSTEM_SID, FULL_CONTROL), AclRule(SYSTEM_SID, FULL_CONTROL)),
    (AclRule(SYSTEM_SID, 0x10000000), AclRule(ADMINS_SID, FULL_CONTROL)),
    (AclRule(SYSTEM_SID, FULL_CONTROL, 16), AclRule(ADMINS_SID, FULL_CONTROL)),
    (AclRule(SYSTEM_SID, FULL_CONTROL, 8), AclRule(ADMINS_SID, FULL_CONTROL)),
    (AclRule(SYSTEM_SID, FULL_CONTROL, kind=1), AclRule(ADMINS_SID, FULL_CONTROL)),
    (AclRule(SYSTEM_SID, FULL_CONTROL, False), AclRule(ADMINS_SID, FULL_CONTROL)),
])
def test_host_secret_model_requires_exact_supported_acl_shape(rules):
    with pytest.raises(CredentialPrototypeRefused, match='^host_key_acl$'):
        check(model(rules=rules))


@pytest.mark.parametrize('metadata', [
    {'protected': False}, {'protected': 1}, {'reparse': True}, {'links': 2},
    {'links': True}, {'directory': True}, {'directory': 'yes'},
])
def test_host_secret_metadata_model_fails_closed(metadata):
    with pytest.raises(CredentialPrototypeRefused, match='^host_key_acl$'):
        check(model(), **metadata)


def test_untrusted_key_owner_refused():
    with pytest.raises(CredentialPrototypeRefused, match='^host_key_acl$'):
        check(model(owner=OPERATOR))


def test_retained_media_style_acl_is_not_a_secret_store_model():
    # A synthetic representation of the reviewed media's extra capability/user
    # grants, NOT a read of or permission change to the retained ISO.
    media = model(rules=(
        AclRule(VM_WORKER, 0x120089), AclRule('S-1-5-83-1-1-2-3-4', 0x120089),
        AclRule(ADMINS_SID, FULL_CONTROL, 16), AclRule(VM_WORKER, FULL_CONTROL, 16),
        AclRule(SYSTEM_SID, FULL_CONTROL, 16), AclRule(OPERATOR, FULL_CONTROL, 16),
    ))
    with pytest.raises(CredentialPrototypeRefused, match='^host_key_acl$'):
        check(media)


def test_public_record_roundtrip_and_documented_transport_size(material, binding):
    value = PublicBootstrap(binding, material['ca'], 'a' * 64)
    raw = encode_public_bootstrap(value)
    assert len(material['ca']) <= MAX_CA_DER_BYTES
    assert len(raw) <= MAX_PUBLIC_RECORD_BYTES < 1024
    assert len((raw.decode('ascii') + '\0').encode('utf-16-le')) <= 2048
    assert decode(raw, binding) == value
    assert set(json.loads(raw)) == {
        'version', 'attempt_id', 'vm_id', 'operation', 'server_ca_der_b64', 'server_leaf_sha256',
    }
    assert 'PRIVATE' not in raw.decode('ascii')
    assert 'server_ca_der=' not in repr(value)


def test_public_codec_does_not_open_a_socket(material, binding, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('no socket allowed for public-record codec')
    monkeypatch.setattr(socket, 'socket', forbidden)
    value = decode(record(material, binding), binding)
    assert value.server_ca_der == material['ca']


@pytest.mark.parametrize('origin', [
    {'observed_vm_id': '00000000-0000-4000-8000-000000000001'},
    {'observed_vm_id': '00000000-0000-0000-0000-000000000000'},
    {'item_name': 'unreviewed-key'}, {'item_source': 0}, {'item_source': 2},
    {'item_source': 4}, {'item_source': True}, {'item_source': '1'},
])
def test_origin_metadata_model_must_match_exact_expected_guest_item(material, binding, origin):
    with pytest.raises(CredentialPrototypeRefused, match='^bootstrap_origin$'):
        decode(record(material, binding), binding, **origin)


@pytest.mark.parametrize('changes', [
    {'version': True}, {'version': 2}, {'attempt_id': 'b' * 32},
    {'vm_id': '00000000-0000-4000-8000-000000000001'}, {'operation': 'finalize'},
    {'private_key': 'PRIVATE_CANARY'}, {'path': 'PRIVATE_CANARY'},
    {'server_ca_der_b64': []}, {'server_leaf_sha256': 'A' * 64},
    {'server_leaf_sha256': ''}, {'server_leaf_sha256': True},
])
def test_public_schema_rejects_substitution_secret_fields_and_bad_pins(material, binding, changes):
    with pytest.raises(CredentialPrototypeRefused) as error:
        decode(record(material, binding, **changes), binding)
    assert 'PRIVATE_CANARY' not in str(error.value)


@pytest.mark.parametrize('raw', [
    b'', b'x' * (MAX_PUBLIC_RECORD_BYTES + 1), bytearray(b'{}'),
])
def test_public_input_type_and_size_bounds(binding, raw):
    with pytest.raises(CredentialPrototypeRefused, match='^bootstrap_size$'):
        decode(raw, binding)


@pytest.mark.parametrize('raw', [
    b'\xff', b'not JSON', b'{"version":1,"version":1}', b'{"version":NaN}',
    b'[]', b'[' * 450 + b'0' + b']' * 450,
])
def test_malformed_nonascii_duplicate_or_nonfinite_public_records(binding, raw):
    with pytest.raises(CredentialPrototypeRefused, match='^bootstrap_schema$'):
        decode(raw, binding)


@pytest.mark.parametrize('encoded', ['!!!!', 'YWJj\n', 'YWJj-', '\u2603', 'x' * 688])
def test_public_base64_is_strict_and_bounded(material, binding, encoded):
    with pytest.raises(CredentialPrototypeRefused, match='^public_certificate$'):
        decode(record(material, binding, server_ca_der_b64=encoded), binding)


@pytest.mark.parametrize('kind', ['private', 'leaf', 'trailing', 'concatenated', 'oversized', 'pem'])
def test_only_one_public_ca_certificate_der_is_accepted(material, binding, kind):
    if kind in ('private', 'leaf'):
        der = material[kind]
    elif kind == 'trailing':
        der = material['ca'] + b'garbage'
    elif kind == 'concatenated':
        der = material['ca'] + material['other']
    elif kind == 'oversized':
        der = b'x' * (MAX_CA_DER_BYTES + 1)
    else:
        der = b'-----BEGIN CERTIFICATE-----\nnot DER\n-----END CERTIFICATE-----'
    encoded = base64.b64encode(der).decode('ascii')
    # The complete record bound may reject a concatenated/oversized value before
    # certificate parsing. Both are fail-closed; no transport fallback occurs.
    with pytest.raises(CredentialPrototypeRefused) as error:
        decode(record(material, binding, server_ca_der_b64=encoded), binding)
    assert str(error.value) in ('bootstrap_size', 'public_certificate')


def test_no_private_material_or_generic_payload_input_to_encoder(material):
    with pytest.raises(CredentialPrototypeRefused, match='^bootstrap_schema$'):
        encode_public_bootstrap({'private_key': material['private']})


def test_latch_identical_poll_is_idempotent_but_different_leaf_is_terminal(material, binding):
    latch = PublicBootstrapLatch(binding)
    raw = record(material, binding)
    args = dict(observed_vm_id=binding.vm_id, item_name=PUBLIC_ITEM_NAME, item_source=1)
    first = latch.observe(raw, **args)
    assert latch.observe(raw, **args) is first
    with pytest.raises(CredentialPrototypeRefused, match='^bootstrap_changed$'):
        latch.observe(record(material, binding, server_leaf_sha256='b' * 64), **args)
    with pytest.raises(CredentialPrototypeRefused, match='^bootstrap_changed$'):
        latch.observe(raw, **args)


def test_latch_changed_root_is_not_rediscovered_or_retrusted(material, binding):
    latch = PublicBootstrapLatch(binding)
    args = dict(observed_vm_id=binding.vm_id, item_name=PUBLIC_ITEM_NAME, item_source=1)
    raw = record(material, binding)
    latch.observe(raw, **args)
    changed = encode_public_bootstrap(PublicBootstrap(binding, material['other'], 'a' * 64))
    with pytest.raises(CredentialPrototypeRefused, match='^bootstrap_changed$'):
        latch.observe(changed, **args)
    latch.close()
    with pytest.raises(CredentialPrototypeRefused, match='^bootstrap_changed$'):
        latch.observe(raw, **args)


def test_latch_first_failure_or_close_is_terminal(material, binding):
    latch = PublicBootstrapLatch(binding)
    args = dict(observed_vm_id=binding.vm_id, item_name=PUBLIC_ITEM_NAME, item_source=1)
    with pytest.raises(CredentialPrototypeRefused, match='^bootstrap_origin$'):
        latch.observe(record(material, binding), **{**args, 'item_source': 0})
    with pytest.raises(CredentialPrototypeRefused, match='^bootstrap_origin$'):
        latch.observe(record(material, binding), **args)
    other = PublicBootstrapLatch(binding)
    other.close()
    other.close()
    with pytest.raises(CredentialPrototypeRefused, match='^closed$'):
        other.observe(record(material, binding), **args)
