"""Fake-runner retirement evidence only; never stop/remove a real VM."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import pytest

from night_shifts.ubuntu_preparation_control import preparation_control_path as _control

import night_shifts.ubuntu_preparation_retirement as retirement
from night_shifts.protocol_image_bundle import build_protocol_image_bundle
from night_shifts.ubuntu_image_preparation import (
    PreparationError,
    UbuntuPreparationConfig,
    UbuntuPreparationRecord,
    create_image_preparation_vm,
)

_GUID = "12345678-1234-1234-1234-123456789abc"


class CreateRunner:
    def run(self, script: Path, args: Sequence[str]) -> str:
        assert script.name == "prepare_image_vm.ps1"
        return args[args.index("-VmName") + 1]


class RetireRunner:
    def __init__(self, workspace: Path, *, fail: bool = False, change: str = ""):
        self.workspace = workspace
        self.fail = fail
        self.change = change
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def run(self, script: Path, args: Sequence[str]) -> str:
        self.calls.append((script.name, tuple(args)))
        snapshot = json.loads((_control(self.workspace) / "manifest.json").read_bytes())
        assert snapshot["status"] == "retirement_unknown"
        assert snapshot["retirement_mode"] == "discard_vm_retain_disk"
        assert (_control(self.workspace) / "retirement.claim").is_file()
        if self.fail:
            raise OSError("host may have stopped or unregistered the VM before disconnect")
        receipt: dict[str, object] = {
            "vm_name": args[args.index("-VmName") + 1], "vm_id": _GUID,
            "vm_absent": True, "disk_retained": True,
        }
        if self.change == "malformed":
            return "not json"
        if self.change == "oversized":
            return "x" * 2049
        if self.change == "identity":
            receipt["vm_name"] = "another-vm"
        elif self.change == "guid":
            receipt["vm_id"] = "not-a-guid"
        elif self.change == "null-guid":
            receipt["vm_id"] = None
        elif self.change == "numeric-guid":
            receipt["vm_id"] = 123
        elif self.change == "zero-guid":
            receipt["vm_id"] = "00000000-0000-0000-0000-000000000000"
        elif self.change == "absence":
            receipt["vm_absent"] = False
        elif self.change == "retention":
            receipt["disk_retained"] = False
        elif self.change == "non-boolean":
            receipt["vm_absent"] = 1
        elif self.change == "extra":
            receipt["unexpected"] = True
        elif self.change == "missing":
            del receipt["disk_retained"]
        elif self.change == "disk-disappeared":
            (self.workspace / "ubuntu-build.vhdx").unlink()  # TEST-owned fake file only
        return json.dumps(receipt)


@pytest.fixture
def prepared(tmp_path: Path) -> UbuntuPreparationRecord:
    iso = tmp_path / "ubuntu-24.04.5-live-server-amd64.iso"
    data = bytearray(17 * 2048)
    data[16 * 2048:16 * 2048 + 7] = b"\x01CD001\x01"
    data[16 * 2048 + 40:16 * 2048 + 72] = b"Ubuntu-Server 24.04.5 LTS amd64".ljust(32)
    iso.write_bytes(data)  # Synthetic descriptor, not bootable Ubuntu media.
    bundle = tmp_path / "guest.zip"
    bundle_hash = build_protocol_image_bundle(bundle).sha256
    root = tmp_path / "build-sandboxes"
    root.mkdir()
    record = create_image_preparation_vm(
        UbuntuPreparationConfig(iso, hashlib.sha256(data).hexdigest(), bundle, bundle_hash, root),
        operator_authorized=True, iso_provenance_reviewed=True, runner=CreateRunner(),
    )
    (record.workspace / "ubuntu-build.vhdx").write_bytes(b"TEST-owned fake disk, NOT a VHDX")
    configuration = record.workspace / "vm-config" / record.vm_name
    configuration.mkdir(parents=True)
    (configuration / "test-evidence.txt").write_bytes(b"configuration evidence")
    (record.workspace / "installer-evidence.txt").write_bytes(b"keep build evidence")
    return record


def _call(record: UbuntuPreparationRecord, runner: RetireRunner, **kwargs) -> UbuntuPreparationRecord:
    return retirement.retire_image_preparation_vm(
        record, operator_authorized=True, discard_image_reviewed=True, runner=runner, **kwargs,
    )


def test_exact_owned_retirement_records_guid_and_retains_disk_and_evidence(prepared: UbuntuPreparationRecord) -> None:
    workspace = prepared.workspace
    keep = {
        path: path.read_bytes() for path in workspace.rglob("*")
        if path.is_file() and path.name != "manifest.json"
    }
    runner = RetireRunner(workspace)
    result = _call(prepared, runner)
    assert result.status == "retired_vm_disk_retained"
    assert result.sandbox_id == prepared.sandbox_id
    assert len(runner.calls) == 1
    script, args = runner.calls[0]
    assert script == "retire_image_vm.ps1"
    assert args == (
        "-VmName", prepared.vm_name,
        "-OwnerMarker", "night-shift-image-prep-owner:" + prepared.sandbox_id,
        "-DiskPath", str(workspace / "ubuntu-build.vhdx"),
        "-VmConfigPath", str(workspace / "vm-config" / prepared.vm_name),
    )
    snapshot = json.loads((_control(workspace) / "manifest.json").read_bytes())
    assert snapshot["status"] == result.status
    assert snapshot["retired_vm_id"] == _GUID
    assert snapshot["retirement_previous_status"] == prepared.status
    assert snapshot["retirement_mode"] == "discard_vm_retain_disk"
    assert (_control(workspace) / "retirement.claim").read_text(encoding="ascii") == prepared.vm_name + "\n"
    for path, data in keep.items():
        assert path.read_bytes() == data  # fake runner only; real Remove-VM may remove VM metadata
    with pytest.raises(PreparationError, match="inspect"):
        _call(result, runner)
    assert len(runner.calls) == 1


@pytest.mark.parametrize("authorized,reviewed", [(False, True), (True, False), (False, False)])
def test_retirement_requires_separate_discard_consent(
    prepared: UbuntuPreparationRecord, authorized: bool, reviewed: bool,
) -> None:
    before = (_control(prepared.workspace) / "manifest.json").read_bytes()
    runner = RetireRunner(prepared.workspace)
    with pytest.raises(PreparationError, match="authorization"):
        retirement.retire_image_preparation_vm(
            prepared, operator_authorized=authorized, discard_image_reviewed=reviewed, runner=runner,
        )
    assert not runner.calls
    assert (_control(prepared.workspace) / "manifest.json").read_bytes() == before
    assert not (_control(prepared.workspace) / "retirement.claim").exists()


@pytest.mark.parametrize("timeout", [0.0, 301.0, float("nan"), float("inf")])
def test_invalid_timeout_has_no_mutation(prepared: UbuntuPreparationRecord, timeout: float) -> None:
    before = (_control(prepared.workspace) / "manifest.json").read_bytes()
    runner = RetireRunner(prepared.workspace)
    with pytest.raises(PreparationError, match="timeout"):
        _call(prepared, runner, command_timeout_seconds=timeout)
    assert not runner.calls
    assert (_control(prepared.workspace) / "manifest.json").read_bytes() == before
    assert not (_control(prepared.workspace) / "retirement.claim").exists()


@pytest.mark.parametrize("field", [
    "sandbox_id", "vm_name", "owner_marker", "disk", "vm_config_root", "vm_config", "network_enabled", "status", "version", "workspace", "control",
])
def test_manifest_ownership_mismatch_rejected_without_claim(prepared: UbuntuPreparationRecord, field: str) -> None:
    path = _control(prepared.workspace) / "manifest.json"
    snapshot = json.loads(path.read_bytes())
    snapshot[field] = True if field == "network_enabled" else "wrong"
    path.write_text(json.dumps(snapshot), encoding="utf-8")
    before = path.read_bytes()
    runner = RetireRunner(prepared.workspace)
    with pytest.raises(PreparationError, match="manifest differs"):
        _call(prepared, runner)
    assert not runner.calls
    assert path.read_bytes() == before
    assert not (_control(prepared.workspace) / "retirement.claim").exists()


@pytest.mark.parametrize("problem", ["pending", "claim", "missing-disk", "missing-config", "bad-json", "oversized-manifest"])
def test_incomplete_or_missing_inputs_block_host_call(prepared: UbuntuPreparationRecord, problem: str) -> None:
    workspace = prepared.workspace
    if problem == "pending":
        (_control(workspace) / "manifest.pending").write_bytes(b"incomplete")
    elif problem == "claim":
        (_control(workspace) / "retirement.claim").write_bytes(b"earlier attempt")
    elif problem == "missing-disk":
        (workspace / "ubuntu-build.vhdx").unlink()
    elif problem == "missing-config":
        configuration = workspace / "vm-config" / prepared.vm_name
        (configuration / "test-evidence.txt").unlink()
        configuration.rmdir()  # root still exists; it must not count as the exact VM directory
    elif problem == "bad-json":
        (_control(workspace) / "manifest.json").write_bytes(b"not json")
    else:
        (_control(workspace) / "manifest.json").write_bytes(b"x" * 8193)
    before = (_control(workspace) / "manifest.json").read_bytes()
    runner = RetireRunner(workspace)
    with pytest.raises(PreparationError):
        _call(prepared, runner)
    assert not runner.calls
    assert (_control(workspace) / "manifest.json").read_bytes() == before


@pytest.mark.parametrize("status", ["provisioning_unknown", "seed_attach_unknown", "created_seed_attached_not_started"])
def test_unknown_attempt_requires_extra_review_but_eligible_known_state_does_not(
    prepared: UbuntuPreparationRecord, status: str,
) -> None:
    path = _control(prepared.workspace) / "manifest.json"
    snapshot = json.loads(path.read_bytes())
    snapshot["status"] = status
    path.write_text(json.dumps(snapshot), encoding="utf-8")
    record = replace(prepared, status=status)
    runner = RetireRunner(prepared.workspace)
    if status.endswith("unknown"):
        before = path.read_bytes()
        with pytest.raises(PreparationError, match="separate operator inspection"):
            _call(record, runner)
        assert not runner.calls
        assert path.read_bytes() == before
        assert not (_control(prepared.workspace) / "retirement.claim").exists()
    result = _call(record, runner, unknown_state_reviewed=True)
    assert result.status == "retired_vm_disk_retained"


@pytest.mark.parametrize("change", [
    "raise", "malformed", "oversized", "identity", "guid", "null-guid", "numeric-guid", "zero-guid", "absence", "retention",
    "non-boolean", "extra", "missing", "disk-disappeared",
])
def test_uncertain_host_receipt_retains_unknown_marker_and_blocks_retry(
    prepared: UbuntuPreparationRecord, change: str,
) -> None:
    runner = RetireRunner(prepared.workspace, fail=change == "raise", change=change)
    with pytest.raises(PreparationError, match=f"status unknown; inspect exact ID {prepared.sandbox_id}"):
        _call(prepared, runner)
    snapshot = json.loads((_control(prepared.workspace) / "manifest.json").read_bytes())
    assert snapshot["status"] == "retirement_unknown"
    assert snapshot["sandbox_id"] == prepared.sandbox_id
    assert (_control(prepared.workspace) / "retirement.claim").is_file()
    with pytest.raises(PreparationError, match="inspect"):
        _call(prepared, runner)
    assert len(runner.calls) == 1


@pytest.mark.parametrize("fail_on", [1, 2])
def test_manifest_storage_failure_keeps_claim_and_blocks_retry(
    prepared: UbuntuPreparationRecord, monkeypatch: pytest.MonkeyPatch, fail_on: int,
) -> None:
    original = retirement._store_manifest
    count = 0

    def failing_store(path, data, *, first):
        nonlocal count
        count += 1
        if count == fail_on:
            raise OSError("test-only manifest storage failure")
        return original(path, data, first=first)

    monkeypatch.setattr(retirement, "_store_manifest", failing_store)
    runner = RetireRunner(prepared.workspace)
    with pytest.raises(PreparationError, match="status unknown"):
        _call(prepared, runner)
    assert (_control(prepared.workspace) / "retirement.claim").is_file()
    assert len(runner.calls) == fail_on - 1
    with pytest.raises(PreparationError, match="inspect"):
        _call(prepared, runner)
    assert len(runner.calls) == fail_on - 1


def _launched_record(record: UbuntuPreparationRecord, status: str) -> UbuntuPreparationRecord:
    manifest = _control(record.workspace) / "manifest.json"
    snapshot = json.loads(manifest.read_bytes())
    snapshot.update({"status": status, "vm_id": _GUID, "launch_plan_sha256": "1" * 64})
    manifest.write_text(json.dumps(snapshot), encoding="utf-8")
    (_control(record.workspace) / "launch.claim").write_text(json.dumps({
        "version": 1, "vm_name": record.vm_name, "vm_id": _GUID, "plan_sha256": "1" * 64,
    }), encoding="utf-8")
    return replace(record, status=status)


@pytest.mark.parametrize("status", ["launch_unknown", "installer_vm_started_not_reviewed"])
def test_launched_retirement_forwards_original_guid_and_checks_review(
    prepared: UbuntuPreparationRecord, status: str,
) -> None:
    record = _launched_record(prepared, status)
    runner = RetireRunner(record.workspace)
    if status == "launch_unknown":
        with pytest.raises(PreparationError, match="separate operator inspection"):
            _call(record, runner)
        assert not runner.calls
    result = _call(record, runner, unknown_state_reviewed=True)
    assert result.status == "retired_vm_disk_retained"
    args = runner.calls[0][1]
    assert args[args.index("-ExpectedVmId") + 1] == _GUID
    assert (_control(record.workspace) / "launch.claim").is_file()
    assert not (_control(record.workspace) / "vm-operation.lock").exists()


@pytest.mark.parametrize("problem", ["missing-claim", "changed-claim", "missing-guid", "missing-digest", "malformed-claim", "orphan-claim"])
def test_launched_binding_must_match_before_discard_claim_or_host_call(
    prepared: UbuntuPreparationRecord, problem: str,
) -> None:
    record = _launched_record(prepared, "installer_vm_started_not_reviewed")
    claim = _control(record.workspace) / "launch.claim"
    manifest = _control(record.workspace) / "manifest.json"
    if problem == "missing-claim":
        claim.unlink()
    elif problem == "changed-claim":
        data = json.loads(claim.read_bytes())
        data["vm_id"] = "87654321-4321-4321-4321-cba987654321"
        claim.write_text(json.dumps(data), encoding="utf-8")
    elif problem == "malformed-claim":
        claim.write_bytes(b"not json")
    else:
        data = json.loads(manifest.read_bytes())
        if problem == "missing-guid":
            del data["vm_id"]
        elif problem == "missing-digest":
            del data["launch_plan_sha256"]
        else:
            data["status"] = "created_seed_attached_not_started"
            record = replace(record, status=data["status"])
        manifest.write_text(json.dumps(data), encoding="utf-8")
    previous = manifest.read_bytes()
    runner = RetireRunner(record.workspace)
    with pytest.raises(PreparationError):
        _call(record, runner, unknown_state_reviewed=True)
    assert not runner.calls
    assert manifest.read_bytes() == previous
    assert not (_control(record.workspace) / "retirement.claim").exists()


def test_wrong_retired_guid_keeps_unknown_state(prepared: UbuntuPreparationRecord) -> None:
    record = _launched_record(prepared, "installer_vm_started_not_reviewed")
    path = _control(record.workspace) / "manifest.json"
    snapshot = json.loads(path.read_bytes())
    other = "87654321-4321-4321-4321-cba987654321"
    snapshot["vm_id"] = other
    path.write_text(json.dumps(snapshot), encoding="utf-8")
    claim = _control(record.workspace) / "launch.claim"
    binding = json.loads(claim.read_bytes())
    binding["vm_id"] = other
    claim.write_text(json.dumps(binding), encoding="utf-8")
    runner = RetireRunner(record.workspace)  # reports original _GUID, not the pinned one
    with pytest.raises(PreparationError, match="retirement status unknown"):
        _call(record, runner)
    assert json.loads(path.read_bytes())["status"] == "retirement_unknown"
    assert (_control(record.workspace) / "retirement.claim").is_file()


def test_retirement_respects_busy_launch_guard(prepared: UbuntuPreparationRecord) -> None:
    guard = _control(prepared.workspace) / "vm-operation.lock"
    guard.write_bytes(b"existing launch or interrupted operation")
    before = (_control(prepared.workspace) / "manifest.json").read_bytes()
    runner = RetireRunner(prepared.workspace)
    with pytest.raises(PreparationError, match="busy or interrupted"):
        _call(prepared, runner)
    assert not runner.calls
    assert (_control(prepared.workspace) / "manifest.json").read_bytes() == before
    assert guard.read_bytes() == b"existing launch or interrupted operation"
    assert not (_control(prepared.workspace) / "retirement.claim").exists()


@pytest.mark.parametrize("problem", ["missing-root", "legacy-root", "wrong-vm"])
def test_legacy_or_wrong_configuration_cannot_retire(prepared, problem: str) -> None:
    path = _control(prepared.workspace) / "manifest.json"
    snapshot = json.loads(path.read_bytes())
    if problem == "missing-root":
        del snapshot["vm_config_root"]
    elif problem == "legacy-root":
        snapshot["vm_config"] = str(prepared.workspace / "vm-config")
    else:
        snapshot["vm_config"] = str(prepared.workspace / "vm-config" / "another-vm")
    path.write_text(json.dumps(snapshot), encoding="utf-8")
    previous = path.read_bytes()
    runner = RetireRunner(prepared.workspace)
    with pytest.raises(PreparationError, match="manifest differs"):
        _call(prepared, runner)
    assert not runner.calls
    assert path.read_bytes() == previous
    assert not (_control(prepared.workspace) / "retirement.claim").exists()


def test_reconciled_never_started_retirement_is_guid_bound(prepared) -> None:
    path = _control(prepared.workspace) / "manifest.json"
    snapshot = json.loads(path.read_bytes())
    snapshot["vm_id"] = _GUID
    path.write_text(json.dumps(snapshot), encoding="utf-8")
    runner = RetireRunner(prepared.workspace)
    _call(prepared, runner)
    args = runner.calls[0][1]
    assert args[args.index("-ExpectedVmId") + 1] == _GUID


def test_worker_metadata_decoys_are_retained_but_ignored_on_retirement(prepared) -> None:
    decoy = prepared.workspace / "manifest.json"
    decoy.write_bytes(b"worker-controlled manifest, not authority")
    result = _call(prepared, RetireRunner(prepared.workspace))
    assert result.status == "retired_vm_disk_retained"
    assert decoy.read_bytes() == b"worker-controlled manifest, not authority"
    assert (prepared.control / "retirement.claim").is_file()


@pytest.mark.parametrize("problem", ["missing-control", "legacy-version", "unsafe-acl"])
def test_control_refusal_blocks_retirement_without_claim(prepared, monkeypatch, problem) -> None:
    if problem == "missing-control":
        (prepared.workspace / "manifest.json").write_bytes(prepared.manifest.read_bytes())
        prepared.control.rename(prepared.control.with_name(prepared.control.name + ".retained-test"))
    elif problem == "legacy-version":
        snapshot = json.loads(prepared.manifest.read_bytes())
        snapshot["version"] = 1
        prepared.manifest.write_text(json.dumps(snapshot), encoding="utf-8")
    else:
        def unsafe(path):
            raise PreparationError("test model: VM worker control rights")
        monkeypatch.setattr("night_shifts.ubuntu_preparation_control._check_control_permissions", unsafe)
    runner = RetireRunner(prepared.workspace)
    with pytest.raises(PreparationError):
        _call(prepared, runner)
    assert not runner.calls
    assert not (prepared.control / "retirement.claim").exists()


def test_retirement_script_pins_guid_rechecks_ownership_and_never_deletes_disk() -> None:
    script = (Path(__file__).resolve().parents[2] / "night_shifts" / "backends" / "hyperv_scripts" / "retire_image_vm.ps1").read_text(encoding="utf-8")
    assert "Start-VM" not in script
    assert "Remove-Item" not in script
    assert "New-VHD" not in script
    assert "SilentlyContinue" not in script
    assert "$Candidate.Notes -ne $OwnerMarker" in script
    assert "$Candidate.Path -ne $VmConfigPath" in script
    assert "Join-Path (Join-Path $workspace 'vm-config') $VmName" in script
    assert "$VmConfigPath -ne $expectedConfigPath" in script
    assert "$disks.Count -ne 1 -or $disks[0].Path -ne $DiskPath" in script
    assert script.count("Assert-PreparationOwner $vm") == 2
    assert script.index("$vmId = $vm.Id") < script.index("Stop-VM -VM $vm")
    assert script.index("Get-VM -Id $vmId") < script.index("Remove-VM -VM $vm")
    assert "$_ .Id" not in script
    assert "$_.Id -eq $vmId -or $_.Name -eq $VmName" in script
    assert "if ($vm.State -ne 'Off') { throw" in script
    assert "Get-VM -Id ([guid]$ExpectedVmId)" in script
    assert "$Candidate.Id -ne [guid]$ExpectedVmId" in script
    assert "vm_absent = $true" in script
    assert "disk_retained = $true" in script
