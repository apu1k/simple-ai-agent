"""Fake-runner-only attachment tests; never execute PowerShell against Hyper-V."""

from __future__ import annotations

import builtins
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from night_shifts.ubuntu_preparation_control import preparation_control_path as _control

from night_shifts.protocol_image_bundle import build_protocol_image_bundle
from night_shifts.ubuntu_image_preparation import (
    PreparationError,
    UbuntuPreparationConfig,
    UbuntuPreparationRecord,
    create_image_preparation_vm,
)
from night_shifts.ubuntu_install_seed_iso import build_ubuntu_install_seed_iso
from night_shifts.ubuntu_seed_attachment import attach_preparation_seed
from night_shifts.ubuntu_seed_iso import build_ubuntu_seed_iso
from night_shifts.ubuntu_seed_staging import stage_ubuntu_seed


class FakeRunner:
    def __init__(self, *, fail: bool = False, mismatched: bool = False):
        self.calls: list[tuple[str, tuple[str, ...]]] = []
        self.fail = fail
        self.mismatched = mismatched

    def run(self, script: Path, args: Sequence[str]) -> str:
        self.calls.append((script.name, tuple(args)))
        if self.fail:
            raise OSError("host may have attached media before disconnect")
        return "other-vm" if self.mismatched else args[args.index("-VmName") + 1]


@pytest.fixture
def prepared(tmp_path: Path) -> tuple[UbuntuPreparationRecord, Path, str]:
    pytest.importorskip("pycdlib")
    iso = tmp_path / "ubuntu-24.04.5-live-server-amd64.iso"
    fixture = bytearray(17 * 2048)
    fixture[16 * 2048:16 * 2048 + 7] = b"\x01CD001\x01"
    fixture[16 * 2048 + 40:16 * 2048 + 72] = b"Ubuntu-Server 24.04.5 LTS amd64".ljust(32)
    iso.write_bytes(fixture)  # Synthetic descriptor, not a bootable Ubuntu ISO.
    bundle = tmp_path / "guest.zip"
    bundle_hash = build_protocol_image_bundle(bundle).sha256
    root = tmp_path / "build-sandboxes"
    root.mkdir()
    config = UbuntuPreparationConfig(iso, hashlib.sha256(fixture).hexdigest(), bundle, bundle_hash, root)
    record = create_image_preparation_vm(
        config, operator_authorized=True, iso_provenance_reviewed=True, runner=FakeRunner()
    )
    (record.workspace / "vm-config" / record.vm_name).mkdir(parents=True)
    staging = tmp_path / "staging"
    staging.mkdir()
    media = build_ubuntu_install_seed_iso(staging, record.vm_name, bundle, bundle_hash)
    return record, media.path, media.sha256


def test_exact_owned_off_vm_is_only_attachment_target(
    prepared: tuple[UbuntuPreparationRecord, Path, str],
) -> None:
    record, media, sha256 = prepared
    runner = FakeRunner()
    result = attach_preparation_seed(
        record, media, sha256, operator_authorized=True, seed_iso_reviewed=True, runner=runner
    )
    assert result.status == "created_seed_attached_not_started"
    assert runner.calls[0][0] == "attach_image_seed.ps1"
    args = runner.calls[0][1]
    for name, expected in (
        ("-VmName", record.vm_name),
        ("-OwnerMarker", "night-shift-image-prep-owner:" + record.sandbox_id),
        ("-DiskPath", str(record.workspace / "ubuntu-build.vhdx")),
        ("-VmConfigPath", str(record.workspace / "vm-config" / record.vm_name)),
        ("-SeedIso", str(media)),
        ("-SeedIsoSha256", sha256),
    ):
        assert args[args.index(name) + 1] == expected
    manifest = json.loads((_control(record.workspace) / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == result.status
    assert not (record.control / "vm-operation.lock").exists()
    assert not (record.workspace / "manifest.json").exists()
    assert manifest["seed_iso_sha256"] == sha256
    assert manifest["seed_kind"] == "ubuntu-protocol-install-v1"
    assert manifest["network_enabled"] is False
    script = (Path(__file__).resolve().parents[2] / "night_shifts" / "backends" / "hyperv_scripts" / runner.calls[0][0]).read_text(encoding="utf-8")
    assert "Start-VM" not in script
    assert "$vm.State -ne 'Off'" in script
    assert "$vm.Notes -ne $OwnerMarker" in script
    assert "$vm.Path -ne $VmConfigPath" in script
    assert "Join-Path (Join-Path $workspace 'vm-config') $VmName" in script
    assert "$VmConfigPath -ne $expectedConfigPath" in script
    assert "Get-VM -Id ([guid]$ExpectedVmId)" in script
    assert "$vm.Id -ne [guid]$ExpectedVmId" in script
    assert "Get-VMNetworkAdapter" in script
    assert "Get-FileHash -LiteralPath $SeedIso -Algorithm SHA256" in script
    assert "Add-VMDvdDrive -VM $vm -Path $SeedIso" in script


@pytest.mark.parametrize("authorized,reviewed", [(False, True), (True, False)])
def test_authorization_required_without_manifest_mutation(
    prepared: tuple[UbuntuPreparationRecord, Path, str], authorized: bool, reviewed: bool,
) -> None:
    record, media, sha256 = prepared
    previous = (_control(record.workspace) / "manifest.json").read_bytes()
    runner = FakeRunner()
    with pytest.raises(PreparationError, match="authorization"):
        attach_preparation_seed(
            record, media, sha256, operator_authorized=authorized, seed_iso_reviewed=reviewed,
            runner=runner,
        )
    assert not runner.calls
    assert (_control(record.workspace) / "manifest.json").read_bytes() == previous


def test_modified_iso_or_manifest_rejected_before_host_call(
    prepared: tuple[UbuntuPreparationRecord, Path, str],
) -> None:
    record, media, sha256 = prepared
    runner = FakeRunner()
    media.write_bytes(media.read_bytes() + b"altered")
    with pytest.raises(PreparationError, match="reviewed SHA-256"):
        attach_preparation_seed(
            record, media, sha256, operator_authorized=True, seed_iso_reviewed=True, runner=runner
        )
    assert not runner.calls
    media.write_bytes(media.read_bytes()[:-7])
    manifest_path = _control(record.workspace) / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["owner_marker"] = "wrong"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(PreparationError, match="manifest differs"):
        attach_preparation_seed(
            record, media, sha256, operator_authorized=True, seed_iso_reviewed=True, runner=runner
        )
    assert not runner.calls


@pytest.mark.parametrize("problem", [
    "missing-root-binding", "legacy-root-path", "wrong-vm", "outside-root", "wrong-root", "missing-exact-directory",
])
def test_configuration_binding_refusal_has_no_host_call_or_manifest_change(prepared, problem: str) -> None:
    record, media, digest = prepared
    path = _control(record.workspace) / "manifest.json"
    snapshot = json.loads(path.read_bytes())
    if problem == "missing-root-binding":
        del snapshot["vm_config_root"]
    elif problem == "legacy-root-path":
        snapshot["vm_config"] = str(record.workspace / "vm-config")
    elif problem == "wrong-vm":
        snapshot["vm_config"] = str(record.workspace / "vm-config" / "another-vm")
    elif problem == "outside-root":
        snapshot["vm_config"] = str(record.workspace.parent / record.vm_name)
    elif problem == "wrong-root":
        snapshot["vm_config_root"] = str(record.workspace.parent)
    else:
        (record.workspace / "vm-config" / record.vm_name).rmdir()
    path.write_text(json.dumps(snapshot), encoding="utf-8")
    previous = path.read_bytes()
    runner = FakeRunner()
    with pytest.raises(PreparationError):
        attach_preparation_seed(record, media, digest, operator_authorized=True, seed_iso_reviewed=True, runner=runner)
    assert not runner.calls
    assert path.read_bytes() == previous


def test_reconciled_guid_is_forwarded_without_deriving_it_from_name(prepared) -> None:
    record, media, digest = prepared
    path = _control(record.workspace) / "manifest.json"
    snapshot = json.loads(path.read_bytes())
    guid = "12345678-1234-1234-1234-123456789abc"
    snapshot["vm_id"] = guid
    path.write_text(json.dumps(snapshot), encoding="utf-8")
    runner = FakeRunner()
    attach_preparation_seed(record, media, digest, operator_authorized=True, seed_iso_reviewed=True, runner=runner)
    args = runner.calls[0][1]
    assert args[args.index("-ExpectedVmId") + 1] == guid


@pytest.mark.parametrize("guid", [None, 123, "not-a-guid", "00000000-0000-0000-0000-000000000000"])
def test_invalid_recorded_guid_refused_before_attachment_mutation(prepared, guid) -> None:
    record, media, digest = prepared
    path = _control(record.workspace) / "manifest.json"
    snapshot = json.loads(path.read_bytes())
    snapshot["vm_id"] = guid
    path.write_text(json.dumps(snapshot), encoding="utf-8")
    previous = path.read_bytes()
    runner = FakeRunner()
    with pytest.raises(PreparationError, match="GUID"):
        attach_preparation_seed(record, media, digest, operator_authorized=True, seed_iso_reviewed=True, runner=runner)
    assert not runner.calls
    assert path.read_bytes() == previous


def test_old_generic_seed_is_rejected_without_host_call_or_manifest_change(
    prepared: tuple[UbuntuPreparationRecord, Path, str], tmp_path: Path,
) -> None:
    record, _, _ = prepared
    generic_dir = tmp_path / "generic-seed"
    generic_dir.mkdir()
    staged = stage_ubuntu_seed(generic_dir, record.vm_name)
    generic = build_ubuntu_seed_iso(staged.directory)
    manifest = _control(record.workspace) / "manifest.json"
    previous = manifest.read_bytes()
    runner = FakeRunner()
    with pytest.raises(PreparationError, match="combined install seed rejected"):
        attach_preparation_seed(
            record, generic.path, generic.sha256, operator_authorized=True,
            seed_iso_reviewed=True, runner=runner,
        )
    assert not runner.calls
    assert manifest.read_bytes() == previous


@pytest.mark.parametrize("changed", ["payload", "instance", "bundle", "missing-bundle-binding", "oversized"])
def test_invalid_combined_seed_is_rejected_before_manifest_update(
    prepared: tuple[UbuntuPreparationRecord, Path, str], changed: str,
) -> None:
    record, media, digest = prepared
    manifest_path = _control(record.workspace) / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    if changed == "missing-bundle-binding":
        del manifest["bundle"]
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    elif changed == "bundle":
        bundle = Path(manifest["bundle"])
        bundle.write_bytes(bundle.read_bytes() + b"altered")
    elif changed == "oversized":
        media.write_bytes(media.read_bytes() + b"x" * (2 * 1024 * 1024))
        digest = hashlib.sha256(media.read_bytes()).hexdigest()
    else:
        data = media.read_bytes()
        if changed == "payload":
            trusted_path = (
                Path(__file__).resolve().parents[2]
                / "night_shifts" / "guest" / "protocol_test_bootstrap.py"
            )
            # Find the actual LF-packaged payload, not raw CRLF checkout bytes.
            # Keep the tamper, fresh hash and pre-host-call refusal assertions.
            trusted = trusted_path.read_bytes().replace(b"\r\n", b"\n")
            assert trusted in data
            data = data.replace(trusted, b"!" + trusted[1:])
        else:
            assert record.vm_name.encode("ascii") in data
            other_id = "a" * 32 if record.sandbox_id != "a" * 32 else "b" * 32
            data = data.replace(record.vm_name.encode("ascii"), ("night-shift-image-prep-" + other_id).encode("ascii"))
        media.write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()  # re-pinning does not authorize different contents
    previous = manifest_path.read_bytes()
    runner = FakeRunner()
    with pytest.raises(PreparationError):
        attach_preparation_seed(
            record, media, digest, operator_authorized=True, seed_iso_reviewed=True, runner=runner,
        )
    assert not runner.calls
    assert manifest_path.read_bytes() == previous


@pytest.mark.parametrize("problem", ["control-binding", "workspace-binding", "legacy-version", "busy", "unsafe-acl"])
def test_control_refusal_blocks_attachment_without_host_call(prepared, monkeypatch, problem) -> None:
    record, media, digest = prepared
    snapshot = json.loads(record.manifest.read_bytes())
    if problem == "busy":
        (record.control / "vm-operation.lock").write_bytes(b"interrupted operation")
    elif problem == "unsafe-acl":
        def unsafe(path):
            raise PreparationError("test model: VM worker access")
        monkeypatch.setattr("night_shifts.ubuntu_preparation_control._check_control_permissions", unsafe)
    else:
        field = {"control-binding": "control", "workspace-binding": "workspace", "legacy-version": "version"}[problem]
        snapshot[field] = 1 if field == "version" else str(record.workspace)
        if field == "workspace":
            snapshot[field] = str(record.workspace.parent)
        record.manifest.write_text(json.dumps(snapshot), encoding="utf-8")
    previous = record.manifest.read_bytes()
    runner = FakeRunner()
    with pytest.raises(PreparationError):
        attach_preparation_seed(record, media, digest, operator_authorized=True, seed_iso_reviewed=True, runner=runner)
    assert not runner.calls
    assert record.manifest.read_bytes() == previous


def test_missing_inspection_dependency_blocks_attachment_without_mutation(
    prepared: tuple[UbuntuPreparationRecord, Path, str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    record, media, digest = prepared
    previous = (_control(record.workspace) / "manifest.json").read_bytes()
    original_import = builtins.__import__

    def without_pycdlib(name, *args, **kwargs):
        if name == "pycdlib" or name.startswith("pycdlib."):
            raise ImportError("test-only missing optional dependency")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_pycdlib)
    runner = FakeRunner()
    with pytest.raises(PreparationError, match="pycdlib is required to inspect"):
        attach_preparation_seed(
            record, media, digest, operator_authorized=True, seed_iso_reviewed=True, runner=runner,
        )
    assert not runner.calls
    assert (_control(record.workspace) / "manifest.json").read_bytes() == previous


@pytest.mark.parametrize("fail,mismatched", [(True, False), (False, True)])
def test_unknown_result_retains_exact_id_and_blocks_retry(
    prepared: tuple[UbuntuPreparationRecord, Path, str], fail: bool, mismatched: bool,
) -> None:
    record, media, sha256 = prepared
    runner = FakeRunner(fail=fail, mismatched=mismatched)
    with pytest.raises(PreparationError, match=f"status unknown; inspect exact ID {record.sandbox_id}"):
        attach_preparation_seed(
            record, media, sha256, operator_authorized=True, seed_iso_reviewed=True, runner=runner
        )
    manifest = json.loads((_control(record.workspace) / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "seed_attach_unknown"
    assert manifest["seed_iso_sha256"] == sha256
    with pytest.raises(PreparationError, match="manifest differs"):
        attach_preparation_seed(
            record, media, sha256, operator_authorized=True, seed_iso_reviewed=True, runner=runner
        )
    assert len(runner.calls) == 1
