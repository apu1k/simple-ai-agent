"""Offline finalization payload and isolated source import regressions."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import zipfile
from dataclasses import replace
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.serialization import Encoding

from night_shifts import finalization_recovery_payload as payload
from night_shifts.finalization_recovery_iso import RecoveryIsoRefused, build_recovery_iso, verify_recovery_iso
from night_shifts.guest.finalization_recovery_entry import ENTRY, RecoveryEntryRefused, parse_context, pin_archive
from night_shifts.finalization_tls_identity import (
    ControllerPublicTrust, FinalizationIdentityRefused, decode_controller_trust, encode_controller_trust,
)
from night_shifts.maintenance_tls_prototype import FINALIZATION_OPERATION, AttemptBinding
from tests.night_shifts.test_authenticated_image_finalization import _BINDING
from tests.night_shifts.test_maintenance_tls_prototype import material as material
from tests.night_shifts.test_maintenance_tls_prototype import pin


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture
def trust(material):
    return ControllerPublicTrust(_BINDING, material['ca'].public_bytes(Encoding.DER), pin(material, 'client'))


@pytest.fixture
def assets(monkeypatch):
    daemon, copying, gpl = b'DAEMON_TEST_ONLY', b'c' * 496, b'g' * 18729
    package = b'PACKAGE_TEST_ONLY'

    def extract(raw):
        assert raw == package
        return daemon

    monkeypatch.setattr(payload, 'extract_reviewed_daemon', extract)
    for name, content in [('DAEMON_SHA256', daemon), ('COPYING_SHA256', copying), ('GPL_SHA256', gpl)]:
        monkeypatch.setattr(payload, name, sha(content))
    monkeypatch.setattr(payload, 'DAEMON_BYTES', len(daemon))
    return {'daemon_package': package, 'copying': copying, 'gpl': gpl}


@pytest.fixture
def built(trust, assets):
    return payload.build_recovery_payload(trust, artifacts={}, **assets)


@pytest.mark.parametrize('change', ['private', 'duplicate', 'base64', 'attempt', 'vm', 'operation', 'version'])
def test_public_trust_refuses_noncanonical_or_wrong_binding(trust, change):
    raw = encode_controller_trust(trust)
    assert decode_controller_trust(raw, trust.binding) == trust
    value = json.loads(raw)
    if change == 'duplicate':
        modified = raw.replace(b'{', b'{"version":1,', 1)
    else:
        attrs = {'private': {'key': 'PRIVATE_CANARY'}, 'base64': {'ca_der_b64': 'private!'},
                 'attempt': {'attempt_id': 'e' * 32}, 'vm': {'vm_id': 'wrong'},
                 'operation': {'operation': 'inspect_image_copy'}, 'version': {'version': True}}
        modified = payload._json(value | attrs[change])
    with pytest.raises(FinalizationIdentityRefused, match='^controller_public_trust$') as error:
        decode_controller_trust(modified, trust.binding)
    assert 'CANARY' not in str(error.value)


def test_build_is_deterministic_and_imports_in_isolation(trust, assets, built, tmp_path):
    assert built == payload.build_recovery_payload(trust, artifacts={}, **assets)
    files = payload.validate_recovery_payload(built.raw, trust.binding, expected_sha256=built.sha256)
    assert files['controller.json'] == encode_controller_trust(trust)
    assert not ({'user-data', 'meta-data', 'ca-key.pem', 'client-key.pem'} & files.keys())
    assert b'BEGIN PRIVATE KEY' not in built.raw
    assert files['night_shifts/__init__.py'] == files['night_shifts/guest/__init__.py'] == b''
    zip_path = (tmp_path / 'guest.zip').resolve()
    zip_path.write_bytes(built.raw)
    result = subprocess.run([sys.executable, '-I', '-B', '-S', '-c',
                             'import sys; sys.path.insert(0, sys.argv[1]); '
                             'from night_shifts.guest.finalization_bootstrap import serve_fresh_guest_once; '
                             'assert callable(serve_fresh_guest_once); '
                             'assert sys.modules["night_shifts"].__file__.startswith(sys.argv[1])',
                             str(zip_path)], capture_output=True, timeout=10, check=False)
    assert result.returncode == 0, result.stderr.decode('utf-8', errors='replace')


@pytest.mark.parametrize('change,reason', [
    ('pin', 'payload_digest'), ('trailing', 'payload_shape'), ('inventory', 'payload_inventory'),
    ('daemon', 'payload_asset'), ('request', 'payload_request'), ('manifest', 'payload_manifest'),
    ('wrong_vm', 'payload_refused'),
])
def test_payload_refuses_substitution_even_when_rehashed(trust, built, change, reason):
    raw = built.raw
    binding = trust.binding
    if change == 'trailing':
        raw += b'injected'
    elif change == 'wrong_vm':
        binding = AttemptBinding(trust.binding.attempt_id, 'de85a5dc-75ba-4537-ab3b-2d89d4c5254f',
                                 FINALIZATION_OPERATION)
    elif change != 'pin':
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            files = {name: archive.read(name) for name in archive.namelist()}
        if change == 'inventory':
            files['unexpected.key'] = b'canary'
        elif change == 'daemon':
            files['hv_kvp_daemon'] = b'not-the-reviewed-daemon'
        elif change == 'request':
            request = json.loads(files['request.json'])
            request['payload']['unit'] = '0' * 64
            files['request.json'] = payload._json(request)
        else:
            files['manifest.json'] = b'{}\n'
        raw = payload._zip(files)
    with pytest.raises(payload.RecoveryPayloadRefused, match='^' + reason + '$'):
        payload.validate_recovery_payload(raw, binding, expected_sha256='0' * 64 if change == 'pin' else sha(raw))


def test_builder_refuses_non_profile_artifact_or_license(trust, assets):
    with pytest.raises(payload.RecoveryPayloadRefused, match='^payload_inputs$'):
        payload.build_recovery_payload(trust, artifacts={'etc/shadow': 'a' * 64}, **assets)
    with pytest.raises(payload.RecoveryPayloadRefused, match='^payload_asset$'):
        payload.build_recovery_payload(trust, artifacts={}, **(assets | {'gpl': b'unpinned'}))


def test_configured_sources_are_bounded_and_fixed():
    assert all(not Path(name).is_absolute() and '..' not in Path(name).parts for name in payload._SOURCES)
    assert len(payload._NAMES) == len(set(payload._NAMES))


def test_seed_readback_and_fixed_cloud_init_entry(trust, built):
    pycdlib = pytest.importorskip('pycdlib')
    iso = build_recovery_iso(built, trust.binding)
    assert iso.sha256 == sha(iso.raw) and iso.request_sha256 == built.request_sha256
    verify_recovery_iso(iso.raw, built, trust.binding, expected_sha256=iso.sha256)
    image = pycdlib.PyCdlib()
    image.open_fp(io.BytesIO(iso.raw))
    try:
        data = io.BytesIO()
        image.get_file_from_iso_fp(data, rr_path='/user-data')
    finally:
        image.close()
    prefix, value = data.getvalue().split(b'\n', 1)
    assert prefix == b'#cloud-config'
    user_data = json.loads(value)
    assert 'autoinstall' not in user_data and user_data['users'] == []
    [command] = user_data['runcmd']
    assert command == ['/usr/bin/env', '-i', 'LANG=C', 'LC_ALL=C', '/usr/bin/unshare', '--mount', '--net',
                       '--propagation', 'private', '/usr/bin/python3.12', '-I', '-B', '-S', ENTRY,
                       trust.binding.attempt_id, trust.binding.vm_id, built.sha256]
    [source] = user_data['write_files']
    assert source['owner'] == 'root:root' and source['permissions'] == '0400' and source['path'] == ENTRY
    entry = base64.b64decode(source['content'], validate=True)
    assert entry == payload._source('guest/finalization_recovery_entry.py')
    compile(entry, ENTRY, 'exec')


def test_seed_refuses_request_fingerprint_substitution(trust, built):
    with pytest.raises(RecoveryIsoRefused, match='^request_digest$'):
        build_recovery_iso(replace(built, request_sha256='0' * 64), trust.binding)


def test_seed_refuses_media_substitution_or_appended_data(trust, built):
    pytest.importorskip('pycdlib')
    iso = build_recovery_iso(built, trust.binding)
    with pytest.raises(RecoveryIsoRefused, match='^iso_pin$'):
        verify_recovery_iso(iso.raw[:-1] + b'X', built, trust.binding, expected_sha256=iso.sha256)
    raw = iso.raw + b'\0' * 2048
    with pytest.raises(RecoveryIsoRefused, match='^iso_shape$'):
        verify_recovery_iso(raw, built, trust.binding, expected_sha256=sha(raw))


def test_guest_checks_pin_before_parsing_and_does_not_extract(built, monkeypatch):
    entries = pin_archive(built.raw, expected_sha256=built.sha256)
    assert set(entries) == {'controller.json', 'request.json', 'night-shift-protocol-test.service', 'hv_kvp_daemon'}
    assert entries['hv_kvp_daemon'] == b'DAEMON_TEST_ONLY'

    def no_parse(*args, **kwargs):
        pytest.fail('attempted zip parse before checking the trusted pin')

    monkeypatch.setattr(zipfile, 'ZipFile', no_parse)
    with pytest.raises(RecoveryEntryRefused, match='^payload_pin$'):
        pin_archive(built.raw + b'change', expected_sha256=built.sha256)


@pytest.mark.parametrize('bad', [0, 1, 2])
def test_guest_entry_arguments_are_exact(trust, built, bad):
    valid = [trust.binding.attempt_id, trust.binding.vm_id, built.sha256]
    assert parse_context(*valid) == tuple(valid)
    valid[bad] = '../../not-an-attempt'
    with pytest.raises(RecoveryEntryRefused, match='^binding$'):
        parse_context(*valid)
