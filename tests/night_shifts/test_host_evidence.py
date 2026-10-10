"""Synthetic files/fake queries only, not actual VM or Windows ACL evidence."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from night_shifts import host_evidence as module


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    source = tmp_path / 'source.vhdx'
    source.write_bytes(b'vhdxfilefixture')
    iso = tmp_path / 'live.iso'
    iso.write_bytes(b'fixture ISO')
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    monkeypatch.setattr(module, '_check_control_permissions', lambda path: None)
    monkeypatch.setattr(module.shutil, 'disk_usage', lambda path: SimpleNamespace(free=50 * 1024**3))
    return source, iso, hashlib.sha256(iso.read_bytes()).hexdigest(), workspace


class FakeRunner:
    def __init__(self, source, iso, failure=None):
        self.calls = []
        self.failure = failure
        self.facts = {'version': 1, 'blockers': [], 'source_references': [],
                      'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                      'recovery_iso_sha256': hashlib.sha256(iso.read_bytes()).hexdigest()}

    def run(self, script, arguments):
        self.calls.append((script.name, arguments))
        if self.failure:
            raise RuntimeError('PRIVATE_EXCEPTION_CANARY')
        return json.dumps(self.facts)


def test_snapshot_never_writes_or_authorizes_launch(inputs):
    source, iso, digest, workspace = inputs
    before = {p: p.read_bytes() for p in (source, iso)}
    runner = FakeRunner(source, iso)
    report = module.collect_host_evidence(*inputs, runner=runner)
    assert report['status'] == 'snapshot_ready_for_review'
    assert report['launch_authorized'] is False and report['guest_audited'] is False
    assert report['vm_create_start_permissions_attested'] is False
    assert runner.calls[0][0] == 'collect_host_evidence.ps1'
    assert list(workspace.iterdir()) == []
    assert all(p.read_bytes() == data for p, data in before.items())


@pytest.mark.parametrize('fault', ['running', 'attached', 'iso-digest', 'permissions', 'private-acl', 'free-space', 'workspace-missing', 'workspace-not-empty', 'missing-hash'])
def test_blockers_never_repair_or_launch(inputs, monkeypatch, fault):
    source, iso, digest, workspace = inputs
    runner = FakeRunner(source, iso)
    if fault == 'running':
        runner.facts['source_references'] = [{'name': 'fixture', 'id': 'fixture-guid', 'state': 'Running'}]
    elif fault == 'attached':
        runner.facts['blockers'] = ['source_vhd_unsuitable']
        runner.facts['source_sha256'] = None
    elif fault == 'iso-digest':
        runner.facts['recovery_iso_sha256'] = '0' * 64
    elif fault == 'permissions':
        runner.failure = True
    elif fault == 'private-acl':
        def deny(path):
            raise RuntimeError('PRIVATE_EXCEPTION_CANARY')
        monkeypatch.setattr(module, '_check_control_permissions', deny)
    elif fault == 'free-space':
        monkeypatch.setattr(module.shutil, 'disk_usage', lambda path: SimpleNamespace(free=1))
    elif fault == 'workspace-missing':
        workspace.rmdir()
    elif fault == 'workspace-not-empty':
        (workspace / 'retained').write_bytes(b'evidence')
    else:
        runner.facts['source_sha256'] = None
    report = module.collect_host_evidence(*inputs, runner=runner)
    assert report['status'] == 'blocked' and report['launch_authorized'] is False
    assert 'PRIVATE_EXCEPTION_CANARY' not in json.dumps(report)
    assert not (workspace / 'launch.claim').exists()
    if fault == 'workspace-missing':
        assert not workspace.exists()
    if fault == 'workspace-not-empty':
        assert (workspace / 'retained').read_bytes() == b'evidence'


def test_invalid_pinned_iso_digest_refused_before_host_query(inputs):
    source, iso, _, workspace = inputs
    runner = FakeRunner(source, iso)
    with pytest.raises(ValueError, match='reviewed'):
        module.collect_host_evidence(source, iso, 'not-a-digest', workspace, runner=runner)
    assert not runner.calls


def test_query_script_has_no_host_mutations():
    source = (Path(module.__file__).parent / 'backends/hyperv_scripts/collect_host_evidence.ps1').read_text()
    for command in ('Start-VM', 'Stop-VM', 'New-VM', 'Remove-VM', 'Set-VM', 'Mount-VHD', 'Dismount-VHD', 'Set-Acl', 'New-Item', 'Remove-Item'):
        assert command not in source
    assert "[IO.File]::Open($SourceDisk, 'Open', 'Read', 'Read')" in source
    assert '$references = @(Read-References)' in source
