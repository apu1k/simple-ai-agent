"""Offline finalization payload and isolated source import regressions."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.serialization import Encoding

from night_shifts import finalization_recovery_payload as payload
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
        import io
        import zipfile

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
