"""Fake Hyper-V only: no VM, ISO install, or operator authorization here."""

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
    create_image_preparation_vm,
)


class FakeRunner:
    def __init__(self, *, fail: bool = False, mismatched: bool = False):
        self.calls: list[tuple[str, tuple[str, ...]]] = []
        self.fail = fail
        self.mismatched = mismatched

    def run(self, script: Path, args: Sequence[str]) -> str:
        self.calls.append((script.name, tuple(args)))
        if self.fail:
            raise OSError("simulated host failure after partial creation")
        return "other-vm" if self.mismatched else args[args.index("-VmName") + 1]


@pytest.fixture
def config(tmp_path: Path) -> UbuntuPreparationConfig:
    iso = tmp_path / "ubuntu-24.04.5-live-server-amd64.iso"
    fixture = bytearray(17 * 2048)
    fixture[16 * 2048 : 16 * 2048 + 7] = b"\x01CD001\x01"
    fixture[16 * 2048 + 40 : 16 * 2048 + 72] = b"Ubuntu-Server 24.04.5 LTS amd64".ljust(32)
    iso.write_bytes(fixture)  # Synthetic descriptor; never a bootable ISO.
    bundle = tmp_path / "guest.zip"
    bundle_hash = build_protocol_image_bundle(bundle).sha256
    root = tmp_path / "build-sandboxes"
    root.mkdir()
    return UbuntuPreparationConfig(
        iso=iso,
        iso_sha256=hashlib.sha256(fixture).hexdigest(),
        bundle=bundle,
        bundle_sha256=bundle_hash,
        workspace_root=root,
    )


def test_preparation_creates_durable_manifest_but_does_not_start_vm(
    config: UbuntuPreparationConfig
) -> None:
    runner = FakeRunner()
    record = create_image_preparation_vm(
        config, operator_authorized=True, iso_provenance_reviewed=True, runner=runner
    )
    assert record.status == "created_not_started"
    assert len(record.sandbox_id) == 32
    assert record.vm_name == f"night-shift-image-prep-{record.sandbox_id}"
    assert len(runner.calls) == 1
    name, args = runner.calls[0]
    assert name == "prepare_image_vm.ps1"
    assert args[args.index("-VmName") + 1] == record.vm_name
    assert args[args.index("-OwnerMarker") + 1] == f"night-shift-image-prep-owner:{record.sandbox_id}"
    assert args[args.index("-InstallerIso") + 1] == str(config.iso)
    assert args[args.index("-InstallerIsoSha256") + 1] == config.iso_sha256
    assert args[args.index("-VmConfigPath") + 1] == str(record.workspace / "vm-config")
    assert args[args.index("-DiskPath") + 1] == str(record.workspace / "ubuntu-build.vhdx")
    script = (Path(__file__).resolve().parents[2] / "night_shifts" / "backends" / "hyperv_scripts" / name).read_text(encoding="utf-8")
    assert "Start-VM" not in script
    assert "Get-FileHash -LiteralPath $InstallerIso -Algorithm SHA256" in script
    assert "Add-VMDvdDrive -VM $createdVm -Path $InstallerIso -Passthru" in script
    manifest = json.loads((record.workspace / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "created_not_started"
    assert manifest["network_enabled"] is False
    assert manifest["iso_sha256"] == config.iso_sha256
    assert manifest["bundle_sha256"] == config.bundle_sha256
    assert not (record.workspace / "ubuntu-build.vhdx").exists()  # Fake runner
    assert [item.name for item in config.workspace_root.iterdir()] == [record.sandbox_id]


@pytest.mark.parametrize("authorized,reviewed", [(False, True), (True, False), (False, False)])
def test_refuses_missing_operator_consent_before_writing(
    config: UbuntuPreparationConfig, authorized: bool, reviewed: bool
) -> None:
    runner = FakeRunner()
    with pytest.raises(PreparationError, match="authorization"):
        create_image_preparation_vm(
            config, operator_authorized=authorized, iso_provenance_reviewed=reviewed, runner=runner
        )
    assert not runner.calls
    assert not list(config.workspace_root.iterdir())


@pytest.mark.parametrize("failure", ["raise", "mismatch"])
def test_unknown_host_creation_retains_exact_id_for_investigation(
    config: UbuntuPreparationConfig, failure: str
) -> None:
    runner = FakeRunner(fail=failure == "raise", mismatched=failure == "mismatch")
    with pytest.raises(PreparationError, match="status unknown; inspect exact ID"):
        create_image_preparation_vm(
            config, operator_authorized=True, iso_provenance_reviewed=True, runner=runner
        )
    [folder] = list(config.workspace_root.iterdir())
    data = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert data["status"] == "provisioning_unknown"
    assert data["sandbox_id"] == folder.name
    assert len(runner.calls) == 1
    with pytest.raises(PreparationError, match="initially empty"):
        create_image_preparation_vm(
            config, operator_authorized=True, iso_provenance_reviewed=True, runner=runner
        )
    assert len(runner.calls) == 1


def test_rejects_stale_iso_and_nonempty_workspace_before_host_call(
    config: UbuntuPreparationConfig
) -> None:
    runner = FakeRunner()
    config.iso.write_bytes(config.iso.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="SHA-256"):
        create_image_preparation_vm(
            config, operator_authorized=True, iso_provenance_reviewed=True, runner=runner
        )
    assert not list(config.workspace_root.iterdir())
    assert not runner.calls


def test_invalid_resources_and_wrong_volume_fail_closed(config: UbuntuPreparationConfig) -> None:
    with pytest.raises(ValueError, match="disk_gb"):
        UbuntuPreparationConfig(
            config.iso, config.iso_sha256, config.bundle, config.bundle_sha256,
            config.workspace_root, disk_gb=0,
        )
    with pytest.raises(ValueError, match="timeout"):
        UbuntuPreparationConfig(
            config.iso, config.iso_sha256, config.bundle, config.bundle_sha256,
            config.workspace_root, command_timeout_seconds=float("nan"),
        )
