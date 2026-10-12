"""Offline only: no UAC, real VHDX, serial pipe or VM."""
from __future__ import annotations

import copy
import hashlib
import io
import json
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from night_shifts import image_finalization as host
from night_shifts.inspection_bundle import bundle_bytes
from runtime import privileged_inspection as client
from runtime.privileged_host import PrivilegedHostError
from runtime.privileged_turn import INSPECTION_OPERATION, PrivilegedClaim, PrivilegedTurn
from runtime.tool_profiles import AgentProfile, profile_tool_names

ID = 'a' * 32
SID = 'S-1-5-21-1-2-3-1001'


def policy():
    files = {'helper.ps1': 'b' * 64, 'runtime/python.exe': 'b' * 64,
             'payload/night_shifts/inspection_worker.py': 'b' * 64,
             'payload/night_shifts/backends/hyperv_scripts/maintain_image_copy.ps1': 'b' * 64}
    files.update({f'payload/pycdlib/file{index}.py': 'b' * 64 for index in range(16)})
    return dict(version=1, operation=INSPECTION_OPERATION, operator_sid=SID,
                source=r'D:\NightShift\source.vhdx', source_sha256='c' * 64,
                recovery_iso=r'D:\NightShift\live.iso', recovery_iso_sha256='d' * 64,
                workspace=r'D:\NightShift\inspection', approved_until_unix=int(time.time()) + 3600,
                iso_provenance_reviewed=True, evidence_preserved=True, files=files,
                bundle_sha256='e' * 64, python_archive_sha256='f' * 64)


def result():
    data = policy()
    return dict(version=1, request_id=ID, operation=INSPECTION_OPERATION, status='inspected_not_accepted',
                accepted=False, gate_a='unrun',
                manifest=str(Path(data['workspace']) / (ID + '.control') / 'manifest.json'),
                receipt=dict(id=ID, mode='inspect', source_sha256=data['source_sha256'],
                             source_unchanged=True, vm_removed=True, copy_unattached=True,
                             pipe_acl_checked=True, copy_sha256='b' * 64,
                             vm_id='12345678-1234-1234-1234-123456789012', vm_config_retained=True,
                             guest=dict(version=1, id=ID, mode='inspect', status='success',
                                        unmounted_read_only=True, audit='inspection_only', diagnostics={})))


def claim():
    return PrivilegedClaim(ID, time.time() + 1800, INSPECTION_OPERATION)


def test_distinct_grants_are_mutually_exclusive_and_single_use():
    gate = PrivilegedTurn()
    gate.arm(INSPECTION_OPERATION)
    assert gate.armed_operation == INSPECTION_OPERATION
    with gate.turn('head'):
        with pytest.raises(PermissionError):
            gate.claim()
        assert gate.claim(INSPECTION_OPERATION).operation == INSPECTION_OPERATION
        with pytest.raises(PermissionError):
            gate.claim(INSPECTION_OPERATION)
    assert gate.status == 'disabled'
    gate.arm()
    gate.arm(INSPECTION_OPERATION)
    with gate.turn('coding-worker'), pytest.raises(PermissionError):
        gate.claim(INSPECTION_OPERATION)
    assert gate.armed_operation == INSPECTION_OPERATION
    gate.revoke()
    with gate.turn('head'), pytest.raises(PermissionError):
        gate.claim(INSPECTION_OPERATION)


@pytest.mark.parametrize('field,value', [('operation', 'finalize'), ('version', True),
    ('evidence_preserved', False), ('approved_until_unix', 0), ('source', r'\\server\disk.vhdx'),
    ('workspace', r'D:\NightShift\..\other'), ('source_sha256', 'self-selected')])
def test_policy_refuses_unapproved_or_unsafe_values(field, value):
    data = policy()
    data[field] = value
    with pytest.raises(PrivilegedHostError):
        client.validate_policy(data)


def test_valid_policy_and_bounded_result():
    client.validate_policy(policy())
    client.validate_result(result(), claim(), policy())


@pytest.mark.parametrize('field,value', [('mode', 'finalize'), ('source_unchanged', False),
    ('vm_removed', False), ('copy_unattached', False), ('pipe_acl_checked', False), ('vm_id', 'guess')])
def test_success_requires_native_cleanup_and_pipe_evidence(field, value):
    facts = result()
    facts['receipt'][field] = value
    with pytest.raises(PrivilegedHostError):
        client.validate_result(facts, claim(), policy())


def test_unknown_result_does_not_claim_cleanup_or_retry(monkeypatch, tmp_path):
    monkeypatch.setattr(client, 'load_inspection_policy', lambda: (tmp_path, tmp_path / 'powershell.exe', policy(), 'f' * 64))
    calls = []
    monkeypatch.setattr(client, '_elevate', lambda *args: calls.append(args) or 'deadline_outcome_unknown')
    answer = client.inspect_installed_copy(claim())
    assert answer['status'] == 'deadline_outcome_unknown'
    assert answer['retry_authorized'] is False and answer['accepted'] is False
    assert len(calls) == 1 and not list(tmp_path.iterdir())


def test_protected_receipt_binding_and_success(monkeypatch, tmp_path):
    monkeypatch.setattr(client, 'load_inspection_policy', lambda: (tmp_path, tmp_path / 'powershell.exe', policy(), 'f' * 64))
    monkeypatch.setattr(client, '_elevate', lambda *args: 'completed')
    envelope = dict(version=1, request_id=ID, operation=INSPECTION_OPERATION,
                    policy_sha256='f' * 64, status='completed', result=result())
    monkeypatch.setattr(client, '_bounded_json', lambda path: copy.deepcopy(envelope))
    assert client.inspect_installed_copy(claim())['status'] == 'inspected_not_accepted'
    envelope['policy_sha256'] = 'a' * 64
    with pytest.raises(PrivilegedHostError):
        client.inspect_installed_copy(claim())


def test_wrong_grant_and_worker_profile_cannot_inspect(monkeypatch):
    monkeypatch.setattr(client, 'load_inspection_policy', lambda: pytest.fail('must not load/elevate'))
    with pytest.raises(PrivilegedHostError):
        client.inspect_installed_copy(PrivilegedClaim(ID, time.time() + 1800))
    from tools.system.privileged_inspection import inspect_privileged_image_copy
    assert inspect_privileged_image_copy(SimpleNamespace(privileged_turn=PrivilegedTurn())).startswith('Error:')
    assert 'inspect_privileged_image_copy' in profile_tool_names(AgentProfile.HEAD)
    assert all('inspect_privileged_image_copy' not in profile_tool_names(p) for p in AgentProfile if p != AgentProfile.HEAD)


def test_bundle_excludes_app_secrets_and_provider_imports():
    raw = bundle_bytes()
    assert raw == bundle_bytes()
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = set(archive.namelist())
        assert archive.read('night_shifts/__init__.py') == b''
        assert not any(name.startswith(('core/', 'runtime/', 'llm/')) or '.env' in name for name in entries)
        manifest = json.loads(archive.read('manifest.json'))
        assert set(manifest) == entries - {'manifest.json'}
        assert all(hashlib.sha256(archive.read(name)).hexdigest() == digest for name, digest in manifest.items())


def test_fresh_space_refusal_precedes_output_creation(tmp_path, monkeypatch):
    root = tmp_path / 'empty'
    root.mkdir()
    disk = tmp_path / 'source.vhdx'
    disk.write_bytes(b'vhdxfileFIXTURE')
    iso = tmp_path / 'live.iso'
    iso.write_bytes(b'FIXTURE')
    config = host.FinalizationConfig(disk, host._digest(disk), iso, host._digest(iso), root)
    monkeypatch.setattr(host.shutil, 'disk_usage', lambda path: SimpleNamespace(free=0))
    with pytest.raises(Exception, match='insufficient fresh workspace space'):
        host.run_image_maintenance(config, operator_authorized=True, iso_provenance_reviewed=True, evidence_preserved=True)
    assert not list(root.iterdir())


def test_native_inspection_records_guid_before_start_and_checks_connected_pipe():
    script = Path(__file__).resolve().parents[2] / 'night_shifts/backends/hyperv_scripts/maintain_image_copy.ps1'
    text = script.read_text()
    assert text.index('$vmRecord =') < text.index('Start-VM -VM $vm')
    assert text.index('MaintenancePipeSecurity]::Read') < text.index('$pipe.WriteAsync')
    assert 'inspection.claim.json' in (script.parents[3] / 'scripts/privileged_inspection_helper.ps1').read_text()
