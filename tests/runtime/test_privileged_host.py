"""Protected-helper validation with synthetic files/ACLs and mocked elevation."""
import hashlib
import json
import os
import time
from pathlib import Path

import pytest

from night_shifts.ubuntu_preparation_control import AclRule, AclSnapshot
from runtime import privileged_host as module
from runtime.privileged_turn import PrivilegedClaim


@pytest.fixture
def install(tmp_path, monkeypatch):
    root = tmp_path / 'install'
    root.mkdir()
    (root / 'receipts').mkdir()
    (root / 'helper.ps1').write_bytes(b'fixed helper')
    (root / 'collector.ps1').write_bytes(b'fixed collector')
    powershell = tmp_path / 'system' / 'powershell.exe'
    powershell.parent.mkdir()
    powershell.write_bytes(b'fixed executable')
    source = tmp_path / 'source.vhdx'
    source.write_bytes(b'vhdxfilefixture')
    iso = tmp_path / 'recovery.iso'
    iso.write_bytes(b'fixture iso')
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    policy = {'version': 1, 'operator_sid': 'operator', 'source': str(source),
              'recovery_iso': str(iso), 'workspace': str(workspace),
              'recovery_iso_sha256': hashlib.sha256(iso.read_bytes()).hexdigest(),
              'helper_sha256': hashlib.sha256((root / 'helper.ps1').read_bytes()).hexdigest(),
              'collector_sha256': hashlib.sha256((root / 'collector.ps1').read_bytes()).hexdigest()}
    (root / 'policy.json').write_text(json.dumps(policy))
    acl = AclSnapshot(module.ADMINS, (AclRule(module.ADMINS, 0x1f01ff),
                                    AclRule('operator', 0x1200a9)))
    monkeypatch.setattr(module, '_read_acl', lambda path: acl)
    monkeypatch.setattr(module, '_current_user_sid', lambda: 'operator')
    monkeypatch.setattr(module, '_windows_paths', lambda: (root, powershell))
    return root, powershell, policy


def test_only_protected_pinned_code_is_selected(install):
    root, executable, policy = install
    assert module.load_policy() == (root, executable, policy)


@pytest.mark.parametrize('fault', ['code', 'schema', 'owner', 'write', 'ancestor',
                                  'delete_child', 'operator', 'hardlink', 'symlink', 'input-link'])
def test_unsafe_install_rejected_without_elevation(install, monkeypatch, fault):
    root, _, policy = install
    if fault == 'code':
        (root / 'helper.ps1').write_bytes(b'changed')
    elif fault == 'schema':
        policy['command'] = 'Remove-VM'
        (root / 'policy.json').write_text(json.dumps(policy))
    elif fault == 'owner':
        monkeypatch.setattr(module, '_read_acl', lambda p: AclSnapshot('operator', (AclRule(module.ADMINS, 0x1f01ff),)))
    elif fault in ('write', 'ancestor', 'delete_child'):
        target = root.parent if fault == 'ancestor' else root
        mask = 0x40 if fault == 'delete_child' else (0x10000 if fault == 'ancestor' else 0x2)
        def acl(path):
            rules = [AclRule(module.ADMINS, 0x1f01ff)]
            if path == target:
                rules.append(AclRule('operator', mask))
            return AclSnapshot(module.ADMINS, tuple(rules))
        monkeypatch.setattr(module, '_read_acl', acl)
    elif fault == 'operator':
        monkeypatch.setattr(module, '_current_user_sid', lambda: 'someone-else')
    elif fault == 'hardlink':
        os.link(root / 'helper.ps1', root / 'alias.ps1')
    else:
        path = root / 'helper.ps1' if fault == 'symlink' else Path(policy['source'])
        target = path.with_name('target' + path.suffix)
        path.rename(target)
        try:
            path.symlink_to(target)
        except OSError:
            pytest.skip('OS denies creation of test symlinks')
    monkeypatch.setattr(module, '_elevate', lambda *a: pytest.fail('must not elevate'))
    with pytest.raises((module.PrivilegedHostError, ValueError)):
        module.collect_installed_evidence(PrivilegedClaim('a' * 32, time.time() + 30))


def test_system_servicing_hardlinks_are_allowed_only_for_os_binary(install):
    _, executable, _ = install
    os.link(executable, executable.with_name('winsxs-alias.exe'))
    module.load_policy()
    with pytest.raises(module.PrivilegedHostError):
        module._assert_protected(executable)


@pytest.mark.parametrize('outcome', ['uac_cancelled', 'deadline_outcome_unknown'])
def test_cancel_timeout_no_retry_no_receipt_assumption(install, monkeypatch, outcome):
    calls = []
    def elevate(*args):
        calls.append(args)
        return outcome
    monkeypatch.setattr(module, '_elevate', elevate)
    result = module.collect_installed_evidence(PrivilegedClaim('a' * 32, time.time() + 30))
    assert result['status'] == outcome and result['launch_authorized'] is False
    assert len(calls) == 1
    assert list((install[0] / 'receipts').iterdir()) == []


def test_matching_receipt_integrates_existing_collector_without_launch(install, monkeypatch):
    root, _, policy = install
    claim = PrivilegedClaim('a' * 32, time.time() + 30)
    facts = {'version': 1, 'source_references': [], 'blockers': [],
             'source_sha256': hashlib.sha256(Path(policy['source']).read_bytes()).hexdigest(),
             'recovery_iso_sha256': policy['recovery_iso_sha256']}
    receipt = {'version': 1, 'request_id': claim.request_id, 'status': 'completed',
               'helper_sha256': policy['helper_sha256'], 'collector_sha256': policy['collector_sha256'],
               'host': facts}
    (root / 'receipts' / (claim.request_id + '.result.json')).write_text(json.dumps(receipt))
    monkeypatch.setattr(module, '_elevate', lambda *args: 'completed')
    from night_shifts import host_evidence
    monkeypatch.setattr(host_evidence, '_check_control_permissions', lambda path: None)
    report = module.collect_installed_evidence(claim)
    assert report['status'] == 'snapshot_ready_for_review'
    assert report['launch_authorized'] is False
    assert report['privileged_request_id'] == claim.request_id
    assert list(Path(policy['workspace']).iterdir()) == []


@pytest.mark.parametrize('fault', ['identity', 'code', 'oversized', 'missing'])
def test_bad_receipt_not_accepted(install, monkeypatch, fault):
    root, _, policy = install
    claim = PrivilegedClaim('a' * 32, time.time() + 30)
    receipt = {'version': 1, 'request_id': claim.request_id, 'status': 'completed',
               'helper_sha256': policy['helper_sha256'], 'collector_sha256': policy['collector_sha256']}
    if fault == 'identity':
        receipt['request_id'] = 'b' * 32
    if fault == 'code':
        receipt['helper_sha256'] = '0' * 64
    path = root / 'receipts' / (claim.request_id + '.result.json')
    if fault != 'missing':
        path.write_text(' ' * 65537 if fault == 'oversized' else json.dumps(receipt))
    monkeypatch.setattr(module, '_elevate', lambda *args: 'completed')
    with pytest.raises((module.PrivilegedHostError, ValueError)):
        module.collect_installed_evidence(claim)


def test_receipt_runner_cannot_select_new_script_or_inputs(install):
    _, _, policy = install
    runner = module._ReceiptRunner(policy, {'version': 1})
    args = ('-SourceDisk', policy['source'], '-RecoveryIso', policy['recovery_iso'])
    assert json.loads(runner.run(Path('collect_host_evidence.ps1'), args)) == {'version': 1}
    with pytest.raises(module.PrivilegedHostError):
        runner.run(Path('evil.ps1'), args)
    with pytest.raises(module.PrivilegedHostError):
        runner.run(Path('collect_host_evidence.ps1'), ('-SourceDisk', 'other', '-RecoveryIso', policy['recovery_iso']))


@pytest.mark.parametrize('fault', [None, 'identity', 'phase', 'version', 'oversized', 'malformed', 'unsafe'])
def test_phase_hints_are_bounded_protected_identity_checked_and_display_only(install, monkeypatch, fault):
    root, _, _ = install
    request_id = 'a' * 32
    record = {'version': 1, 'request_id': request_id, 'phase': 'iso_hash'}
    if fault == 'identity':
        record['request_id'] = 'b' * 32
    elif fault == 'phase':
        record['phase'] = 'SUCCESS; arbitrary injected label'
    elif fault == 'version':
        record['version'] = True
    path = root / 'receipts' / (request_id + '.phase-iso_hash.json')
    path.write_text(' ' * 65537 if fault == 'oversized' else ('{' if fault == 'malformed' else json.dumps(record)))
    if fault == 'unsafe':
        monkeypatch.setattr(module, '_read_acl', lambda p: AclSnapshot('operator', (AclRule(module.ADMINS, 0x1f01ff),)))
    result = module._observed_phase(root, request_id)
    assert result == ('Hashing recovery ISO' if fault is None else
                      'Collecting host evidence (fresh hashing may take several minutes)')
    assert 'SUCCESS' not in result
    assert len(list((root / 'receipts').iterdir())) == 1


def test_old_installation_needs_no_upgrade_for_generic_elapsed_progress(install):
    assert module._observed_phase(install[0], 'a' * 32).startswith('Collecting host evidence')


def test_fixed_helper_has_containment_deadline_and_protected_receipts():
    scripts = Path(__file__).resolve().parents[2] / 'scripts'
    helper = (scripts / 'privileged_host_helper.ps1').read_text()
    installer = (scripts / 'install_privileged_host_helper.ps1').read_text()
    assert "'CreateNew'" in helper and "'.start.json'" in helper
    assert '0x08000004' in helper and 'limits.Basic.Flags = 0x2000' in helper
    assert 'AssignProcessToJobObject' in helper and 'TerminateJobObject' in helper
    assert '$remaining -le 0' in helper and '$remaining -gt 1800' in helper
    assert '$directory.Create($security)' in installer
    assert '$security.SetOwner($admins)' in installer
    assert 'ReadAndExecute' in installer
    assert 'ReadAllBytes($helperSource)' in installer
    for command in ('Start-VM', 'Stop-VM', 'New-VM', 'Remove-VM', 'Mount-VHD', 'Dismount-VHD'):
        assert command not in helper
        assert command not in installer
