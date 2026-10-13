"""Synthetic maintenance failures only; never boot, elevate or inspect a real disk."""
from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path

import pytest

from night_shifts import image_finalization as host
from night_shifts.maintenance_runner import validate_failure_diagnostics
from runtime import privileged_inspection as client
from runtime.privileged_host import PrivilegedHostError
from runtime.privileged_turn import INSPECTION_OPERATION, PrivilegedClaim

ID = 'a' * 32
VM_ID = '51434da9-9168-428a-8624-72a246ccc18d'
SECRET = 'PRIVATE_EXCEPTION_CANARY_NOT_FOR_RECEIPTS'


def diagnostics(identity=ID):
    return dict(version=1, id=identity, mode='inspect', phase='CHANNEL',
                channel_stage='security_query', code='win32_error', win32_error=5,
                vm_id=VM_ID, stop_observation='off_observed')


@pytest.mark.parametrize('field,value', [
    ('version', True), ('version', 2), ('id', '../other'), ('mode', 'execute'),
    ('phase', SECRET), ('channel_stage', SECRET), ('code', SECRET),
    ('win32_error', True), ('win32_error', -1), ('win32_error', 0x100000000),
    ('win32_error', 5.0), ('win32_error', SECRET), ('vm_id', SECRET),
    ('vm_id', True), ('vm_id', None), ('stop_observation', 'removed'),
    ('channel_stage', 'not_applicable'), ('phase', 'GUEST'),
])
def test_diagnostics_refuse_unbounded_or_inconsistent_values(field, value):
    data = diagnostics()
    data[field] = value
    with pytest.raises(ValueError):
        validate_failure_diagnostics(data)


def test_diagnostics_require_exact_identity_mode_and_schema():
    data = diagnostics()
    with pytest.raises(ValueError):
        validate_failure_diagnostics(data, identity='b' * 32)
    with pytest.raises(ValueError):
        validate_failure_diagnostics(data, mode='finalize')
    data['exception'] = SECRET
    with pytest.raises(ValueError):
        validate_failure_diagnostics(data)
    del data['exception']
    del data['code']
    with pytest.raises(ValueError):
        validate_failure_diagnostics(data)


def test_unknown_stop_and_nonchannel_failure_are_not_cleanup_success():
    data = diagnostics()
    data.update(phase='CREATE', channel_stage='not_applicable', code='operation_failed',
                win32_error=None, vm_id=None, stop_observation='unknown')
    assert validate_failure_diagnostics(data) == data
    assert 'vm_removed' not in data and 'unmounted_read_only' not in data


@pytest.fixture
def config(tmp_path, monkeypatch):
    source = tmp_path / 'source.vhdx'
    source.write_bytes(b'vhdxfileSYNTHETIC_NOT_A_DISK')
    iso = tmp_path / 'live.iso'
    iso.write_bytes(b'SYNTHETIC_NOT_BOOTABLE')
    root = tmp_path / 'empty-workspace'
    root.mkdir()
    monkeypatch.setattr('night_shifts.ubuntu_preparation_control._check_control_permissions', lambda p: None)
    return host.FinalizationConfig(source, host._digest(source), iso, host._digest(iso), root)


class FailedRunner:
    def __init__(self, mutation=None, raw=None):
        self.mutation = mutation
        self.raw = raw
        self.calls = 0

    def run(self, script, arguments):
        self.calls += 1
        args = dict(zip(arguments[::2], arguments[1::2], strict=True))
        data = diagnostics(args['-Identity'])
        if self.mutation:
            data.update(self.mutation)
        if self.raw != 'absent':
            raw = self.raw if isinstance(self.raw, bytes) else json.dumps(data).encode()
            Path(args['-FailureReceipt']).write_bytes(raw)
        raise RuntimeError('NS-MAINTENANCE-FAIL CHANNEL ' + SECRET)


def maintain(config, runner, failure_path=None):
    return host.run_image_maintenance(config, operator_authorized=True,
                                      iso_provenance_reviewed=True, evidence_preserved=True,
                                      runner=runner, failure_receipt_path=failure_path)


def test_valid_failure_is_retained_in_manifest_and_typed_exception(config, tmp_path):
    path = tmp_path / 'protected-failure-fixture.json'
    runner = FailedRunner()
    original = config.source.read_bytes()
    with pytest.raises(host.ImageMaintenanceError) as caught:
        maintain(config, runner, path)
    exc = caught.value
    state = json.loads(exc.manifest.read_bytes())
    assert state['status'] == 'maintenance_unknown' and state['accepted'] is False
    assert state['failure_diagnostics'] == exc.diagnostics
    assert exc.diagnostics['stop_observation'] == 'off_observed'
    assert exc.manifest.parent.joinpath('launch.claim').is_file()
    assert path.is_file() and config.source.read_bytes() == original and runner.calls == 1
    assert SECRET not in exc.manifest.read_text() and SECRET not in str(exc)


@pytest.mark.parametrize('mutation,raw', [
    ({'id': 'b' * 32}, None), ({'mode': 'finalize'}, None),
    ({'phase': 'BOOT', 'channel_stage': 'not_applicable'}, None),
    ({'exception': SECRET}, None), ({'win32_error': True}, None),
    (None, b'not JSON'), (None, b'x' * 4097), (None, 'absent'),
])
def test_bad_or_missing_receipt_does_not_infer_off_or_expose_raw_data(config, mutation, raw):
    runner = FailedRunner(mutation, raw)
    with pytest.raises(host.ImageMaintenanceError) as caught:
        maintain(config, runner)
    assert caught.value.diagnostics is None
    state = json.loads(caught.value.manifest.read_bytes())
    assert state['failure_phase'] == 'CHANNEL' and 'failure_diagnostics' not in state
    assert SECRET not in caught.value.manifest.read_text() and runner.calls == 1


def failed_facts():
    return dict(version=1, request_id=ID, operation=INSPECTION_OPERATION,
                status='blocked_or_outcome_unknown', accepted=False, gate_a='unrun',
                manifest=str(Path(r'D:\NightShift\fixture') / (ID + '.control') / 'manifest.json'),
                failure_diagnostics=diagnostics())


def claim():
    return PrivilegedClaim(ID, 9999999999, INSPECTION_OPERATION)


def test_client_returns_validated_diagnostics_without_success_or_retry(monkeypatch, tmp_path):
    policy = {'workspace': r'D:\NightShift\fixture'}
    monkeypatch.setattr(client, 'load_inspection_policy', lambda: (tmp_path, tmp_path / 'pwsh.exe', policy, 'f' * 64))
    monkeypatch.setattr(client, '_elevate', lambda *args: 'helper_failed')
    envelope = dict(version=1, request_id=ID, operation=INSPECTION_OPERATION,
                    policy_sha256='f' * 64, status='blocked_or_outcome_unknown', result=failed_facts())
    monkeypatch.setattr(client, '_bounded_json', lambda p: copy.deepcopy(envelope))
    answer = client.inspect_installed_copy(claim())
    assert answer['status'] == 'blocked_or_outcome_unknown'
    assert answer['failure_diagnostics']['stop_observation'] == 'off_observed'
    assert answer['retry_authorized'] is False and answer['accepted'] is False
    assert answer['gate_a'] == 'unrun' and 'receipt' not in answer['failure_diagnostics']
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('field,value', [
    ('version', True), ('request_id', uuid.uuid4().hex), ('operation', 'finalize'),
    ('status', 'inspected_not_accepted'), ('accepted', True), ('gate_a', 'passed'),
    ('manifest', 'D:/unbound/manifest.json'),
])
def test_client_failure_facts_are_request_operation_and_manifest_bound(field, value):
    data = failed_facts()
    data[field] = value
    with pytest.raises(PrivilegedHostError):
        client.validate_failure_result(data, claim(), {'workspace': r'D:\NightShift\fixture'})


def test_client_failure_diagnostics_cannot_change_operation_or_contain_raw_errors():
    data = failed_facts()
    data['failure_diagnostics']['mode'] = 'finalize'
    with pytest.raises(PrivilegedHostError):
        client.validate_failure_result(data, claim(), {'workspace': r'D:\NightShift\fixture'})
    data = failed_facts()
    data['failure_diagnostics']['exception'] = SECRET
    with pytest.raises(PrivilegedHostError):
        client.validate_failure_result(data, claim(), {'workspace': r'D:\NightShift\fixture'})


def test_timeout_without_failure_receipt_keeps_unknown(monkeypatch, tmp_path):
    monkeypatch.setattr(client, 'load_inspection_policy', lambda: (tmp_path, tmp_path / 'pwsh.exe', {}, 'f' * 64))
    monkeypatch.setattr(client, '_elevate', lambda *args: 'deadline_outcome_unknown')
    monkeypatch.setattr(client, '_bounded_json', lambda p: pytest.fail('cannot read nonexistent completion'))
    answer = client.inspect_installed_copy(claim())
    assert answer['status'] == 'deadline_outcome_unknown' and 'failure_diagnostics' not in answer
    assert answer['retry_authorized'] is False and answer['accepted'] is False
