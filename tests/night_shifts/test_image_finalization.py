"""Synthetic files/fake Hyper-V only; NOT native ACL, Linux or boot evidence."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import pytest
import yaml

from night_shifts import image_finalization as host
from night_shifts import image_publication as publication
from night_shifts.guest import finalize_image_copy as guest
from night_shifts.ubuntu_preparation_control import PreparationError

IDENTITY = 'a' * 32
SECRET = 'PRIVATE_CANARY_MUST_NOT_BE_REPORTED'


def request(mode='inspect', artifacts=None):
    return {'version': 1, 'id': IDENTITY, 'mode': mode, 'artifacts': artifacts or {},
            'payload': {'bootstrap': 'b' * 64, 'unit': 'c' * 64}}


@pytest.mark.parametrize('name', ['/etc/shadow', '../etc/shadow', 'etc/passwd',
                                  'root/.ssh/id_ed25519', 'etc/systemd/system/../../passwd'])
def test_cleanup_profile_cannot_delete_arbitrary_paths(name):
    with pytest.raises(guest.FinalizationError):
        guest.validate_request(request('finalize', {name: 'd' * 64}))


@pytest.mark.parametrize('field,value', [('version', True), ('mode', 'execute'),
                                        ('id', 'vm-name-from-a-task'), ('payload', {}),
                                        ('artifacts', {'root/nsdiag027-backup': SECRET})])
def test_request_refuses_unknown_operations_and_unpinned_artifacts(field, value):
    data = request()
    data[field] = value
    with pytest.raises(guest.FinalizationError):
        guest.validate_request(data)


def test_profile_accepts_only_explicit_code_artifacts():
    profile = {'etc/systemd/system/debug-shell.service.d/override.conf': 'd' * 64,
               'root/nsdiag027-unit-backup': 'e' * 64}
    assert guest.validate_request(request('finalize', profile))['artifacts'] == profile


@pytest.fixture
def config(tmp_path, monkeypatch):
    source = tmp_path / 'diagnostic.vhdx'
    source.write_bytes(b'vhdxfile' + b'SYNTHETIC_NOT_A_DISK')
    iso = tmp_path / 'live.iso'
    iso.write_bytes(b'SYNTHETIC_NOT_BOOTABLE')
    root = tmp_path / 'new-workspace'
    root.mkdir()
    # Explicit ACL model only for these fake-host tests. Production still uses
    # the native Windows ACL reader; choosing a fake runner does not bypass it.
    monkeypatch.setattr('night_shifts.ubuntu_preparation_control._check_control_permissions', lambda path: None)
    return host.FinalizationConfig(source, host._digest(source), iso, host._digest(iso), root)


class FakeRunner:
    def __init__(self, failure=None):
        self.failure = failure
        self.calls = []

    def run(self, script, arguments):
        self.calls.append((script.name, arguments))
        if self.failure == 'host':
            raise RuntimeError(SECRET)
        args = dict(zip(arguments[::2], arguments[1::2], strict=True))
        identity, mode = args['-Identity'], args['-Mode']
        copy = Path(args['-Workspace']) / 'working-copy.vhdx'
        copy.write_bytes(b'vhdxfileSYNTHETIC_FINAL_COPY')
        data = {'id': identity, 'mode': mode, 'source_sha256': args['-SourceSha256'],
                'source_unchanged': True, 'copy_sha256': host._digest(copy),
                'vm_removed': True, 'vm_id': 'fixture-guid',
                'guest': {'version': 1, 'id': identity, 'mode': mode,
                          'status': 'success', 'unmounted_read_only': True, 'audit': 'pass'}}
        if self.failure == 'identity':
            data['guest']['id'] = 'f' * 32
        if self.failure == 'cleanup':
            data['vm_removed'] = False
        return json.dumps(data)


def run(config, runner):
    return host.run_image_maintenance(config, operator_authorized=True,
                                      iso_provenance_reviewed=True, evidence_preserved=True, runner=runner)


@pytest.mark.parametrize('missing', ['operator_authorized', 'iso_provenance_reviewed', 'evidence_preserved'])
def test_requires_all_separate_authorizations_before_effects(config, missing):
    runner = FakeRunner()
    flags = dict(operator_authorized=True, iso_provenance_reviewed=True, evidence_preserved=True)
    flags[missing] = False
    with pytest.raises(PreparationError, match='authorization'):
        host.run_image_maintenance(config, runner=runner, **flags)
    assert runner.calls == []
    assert list(config.workspace_root.iterdir()) == []


def test_media_is_lf_checksums_and_runcmd_not_an_installer(config, tmp_path):
    files = host.media_files(config, IDENTITY)
    cloud = yaml.safe_load(files['user-data'])
    assert 'autoinstall' not in cloud and 'storage' not in cloud
    assert cloud['users'] == [] and cloud['package_update'] is False
    invocation = cloud['runcmd'][0][2]
    assert 'sha256sum -c -- SHA256SUMS' in invocation and 'timeout ' in invocation
    assert 'chroot' not in invocation and 'mkfs' not in invocation
    assert all(b'\r' not in value for value in files.values())
    for line in files['SHA256SUMS'].decode().splitlines():
        digest, name = line.split('  ')
        assert hashlib.sha256(files[name]).hexdigest() == digest
    pycdlib = pytest.importorskip('pycdlib')
    path = tmp_path / 'maintenance.iso'
    digest = host._write_media(path, files)
    assert host._digest(path) == digest
    iso = pycdlib.PyCdlib()
    iso.open(str(path))
    try:
        for name, expected in files.items():
            output = io.BytesIO()
            iso.get_file_from_iso_fp(output, rr_path='/' + name)
            assert output.getvalue() == expected
        assert iso.eltorito_boot_catalog is None  # data-only seed, not bootable
    finally:
        iso.close()
    with pytest.raises(FileExistsError):
        host._write_media(path, files)


def test_success_preserves_source_and_never_accepts_an_image(config):
    pytest.importorskip('pycdlib')
    original = config.source.read_bytes()
    runner = FakeRunner()
    manifest = run(config, runner)
    data = json.loads(manifest.read_text())
    assert data['status'] == 'inspected_not_accepted' and data['accepted'] is False
    assert config.source.read_bytes() == original
    assert runner.calls[0][0] == 'maintain_image_copy.ps1'
    assert (manifest.parent / 'launch.claim').is_file()
    with pytest.raises(PreparationError, match='not empty'):
        run(config, runner)
    assert len(runner.calls) == 1


@pytest.mark.parametrize('failure', ['host', 'identity', 'cleanup'])
def test_uncertain_host_or_guest_outcome_retains_claim_and_manifest(config, failure):
    pytest.importorskip('pycdlib')
    runner = FakeRunner(failure)
    with pytest.raises(PreparationError, match='UNKNOWN'):
        run(config, runner)
    manifests = list(config.workspace_root.glob('*.control/manifest.json'))
    assert len(manifests) == 1
    state = json.loads(manifests[0].read_text())
    assert state['status'] == 'maintenance_unknown' and state['accepted'] is False
    assert (manifests[0].parent / 'launch.claim').is_file()
    assert SECRET not in manifests[0].read_text()


def test_changed_input_refused_before_host_or_copy(config):
    config.source.write_bytes(config.source.read_bytes() + b'changed')
    runner = FakeRunner()
    with pytest.raises(PreparationError, match='reviewed digest'):
        run(config, runner)
    assert runner.calls == [] and list(config.workspace_root.iterdir()) == []


def test_publication_requires_separate_acceptance_before_reading_inputs(tmp_path):
    with pytest.raises(PreparationError, match='separate publication'):
        publication.publish_finalized_image(tmp_path / 'absent.json', 'a' * 64, tmp_path)


def test_inspection_cannot_be_published_even_with_acceptance(config, tmp_path):
    pytest.importorskip('pycdlib')
    manifest = run(config, FakeRunner())
    with pytest.raises(PreparationError, match='successful'):
        publication.publish_finalized_image(manifest, host._digest(manifest), tmp_path,
                                             operator_authorized=True, audit_accepted=True, runner=FakeRunner())


def test_native_scripts_never_mount_or_start_the_source_and_bound_serial():
    scripts = Path(__file__).resolve().parents[2] / 'night_shifts/backends/hyperv_scripts'
    source = (scripts / 'maintain_image_copy.ps1').read_text()
    assert 'Mount-VHD' not in source and 'Remove-Item' not in source
    assert "[System.IO.File]::Open($SourceDisk, 'Open', 'Read', 'Read')" in source
    assert '$sourceLock.CopyTo($destination)' in source
    assert '$data.Length -gt 32768' in source and '$pending.Wait($remaining)' in source
    assert '-BootOrder $boot' in source and 'Assert-Owned $owned' in source
    publish = (scripts / 'publish_image_copy.ps1').read_text()
    assert "'CreateNew'" in publish and '$acl.SetAccessRuleProtection($true, $false)' in publish
    assert '$item.IsReadOnly = $true' in publish


def test_guest_mounts_only_fixed_copy_partition_and_never_executes_target():
    source = Path(guest.__file__).read_text()
    assert "'autoinstall' not in cmdline" in source
    assert "'ro,noload,nodev,nosuid,noexec'" in source
    assert "'rw,nodev,nosuid,noexec'" in source
    assert "'/dev/sda2'" in source and 'chroot' not in source
    assert "'unmounted_read_only'" in source


class FakePublicationRunner:
    def __init__(self, private=True):
        self.private = private
        self.calls = 0

    def run(self, script, arguments):
        self.calls += 1
        assert script.name == 'publish_image_copy.ps1'
        args = dict(zip(arguments[::2], arguments[1::2], strict=True))
        destination = Path(args['-Destination'])
        with destination.open('xb') as stream:
            stream.write(Path(args['-SourceDisk']).read_bytes())
        return json.dumps({'sha256': args['-ExpectedSha256'], 'read_only': True, 'private': self.private})


def test_publication_success_is_separate_provenance_and_never_gate_a(config, tmp_path, monkeypatch):
    from dataclasses import replace

    pytest.importorskip('pycdlib')
    manifest = run(replace(config, mode='finalize'), FakeRunner())
    destination = tmp_path / 'private-published-images'
    destination.mkdir()
    monkeypatch.setattr(publication, '_check_control_permissions', lambda path: None)
    runner = FakePublicationRunner()
    provenance = publication.publish_finalized_image(
        manifest, host._digest(manifest), destination,
        operator_authorized=True, audit_accepted=True, runner=runner,
    )
    data = json.loads(provenance.read_text())
    assert data['operator_accepted'] is True and data['gate_a'] == 'unrun'
    assert host._digest(Path(data['image'])) == data['sha256']
    assert (manifest.parent / 'publication.claim').is_file()
    assert not (manifest.parent / 'retirement.claim').exists()
    assert runner.calls == 1


def test_publication_policy_failure_retains_claim_and_no_accepted_provenance(config, tmp_path, monkeypatch):
    from dataclasses import replace

    pytest.importorskip('pycdlib')
    manifest = run(replace(config, mode='finalize'), FakeRunner())
    destination = tmp_path / 'private-published-images'
    destination.mkdir()
    monkeypatch.setattr(publication, '_check_control_permissions', lambda path: None)
    runner = FakePublicationRunner(private=False)
    with pytest.raises(PreparationError, match='UNKNOWN'):
        publication.publish_finalized_image(manifest, host._digest(manifest), destination,
                                             operator_authorized=True, audit_accepted=True, runner=runner)
    assert (manifest.parent / 'publication.claim').is_file()
    assert len(list(destination.glob('*.vhdx'))) == 1
    assert list(destination.glob('*.json')) == []
    with pytest.raises(PreparationError, match='already exists'):
        publication.publish_finalized_image(manifest, host._digest(manifest), destination,
                                             operator_authorized=True, audit_accepted=True, runner=runner)
    assert runner.calls == 1


def test_reviewed_manifest_hash_cannot_be_substituted(config, tmp_path):
    pytest.importorskip('pycdlib')
    manifest = run(config, FakeRunner())
    with pytest.raises(PreparationError, match='changed since review'):
        publication.publish_finalized_image(manifest, '0' * 64, tmp_path,
                                             operator_authorized=True, audit_accepted=True, runner=FakeRunner())
    assert not (manifest.parent / 'publication.claim').exists()
