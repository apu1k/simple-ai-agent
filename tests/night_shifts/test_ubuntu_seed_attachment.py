"""Fake-runner-only attachment tests; never execute PowerShell against Hyper-V."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from night_shifts.protocol_image_bundle import build_protocol_image_bundle
from night_shifts.ubuntu_image_preparation import (
    PreparationError,
    UbuntuPreparationConfig,
    UbuntuPreparationRecord,
    create_image_preparation_vm,
)
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
    staging = tmp_path / "staging"
    staging.mkdir()
    staged = stage_ubuntu_seed(staging, record.vm_name)
    media = build_ubuntu_seed_iso(staged.directory)
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
        ("-VmConfigPath", str(record.workspace / "vm-config")),
        ("-SeedIso", str(media)),
        ("-SeedIsoSha256", sha256),
    ):
        assert args[args.index(name) + 1] == expected
    manifest = json.loads((record.workspace / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == result.status
    assert manifest["seed_iso_sha256"] == sha256
    assert manifest["network_enabled"] is False
    script = (Path(__file__).resolve().parents[2] / "night_shifts" / "backends" / "hyperv_scripts" / runner.calls[0][0]).read_text(encoding="utf-8")
    assert "Start-VM" not in script
    assert "$vm.State -ne 'Off'" in script
    assert "$vm.Notes -ne $OwnerMarker" in script
    assert "$vm.Path -ne $VmConfigPath" in script
    assert "Get-VMNetworkAdapter" in script
    assert "Get-FileHash -LiteralPath $SeedIso -Algorithm SHA256" in script
    assert "Add-VMDvdDrive -VM $vm -Path $SeedIso" in script


@pytest.mark.parametrize("authorized,reviewed", [(False, True), (True, False)])
def test_authorization_required_without_manifest_mutation(
    prepared: tuple[UbuntuPreparationRecord, Path, str], authorized: bool, reviewed: bool,
) -> None:
    record, media, sha256 = prepared
    previous = (record.workspace / "manifest.json").read_bytes()
    runner = FakeRunner()
    with pytest.raises(PreparationError, match="authorization"):
        attach_preparation_seed(
            record, media, sha256, operator_authorized=authorized, seed_iso_reviewed=reviewed,
            runner=runner,
        )
    assert not runner.calls
    assert (record.workspace / "manifest.json").read_bytes() == previous


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
    manifest_path = record.workspace / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["owner_marker"] = "wrong"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(PreparationError, match="manifest differs"):
        attach_preparation_seed(
            record, media, sha256, operator_authorized=True, seed_iso_reviewed=True, runner=runner
        )
    assert not runner.calls


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
    manifest = json.loads((record.workspace / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "seed_attach_unknown"
    assert manifest["seed_iso_sha256"] == sha256
    with pytest.raises(PreparationError, match="manifest differs"):
        attach_preparation_seed(
            record, media, sha256, operator_authorized=True, seed_iso_reviewed=True, runner=runner
        )
    assert len(runner.calls) == 1
