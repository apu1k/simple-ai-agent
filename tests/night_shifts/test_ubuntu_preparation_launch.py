"""Offline create/attach/packet/start/discard contracts; never invoke Hyper-V."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

import night_shifts.ubuntu_preparation_launch as launch
from night_shifts.protocol_image_bundle import build_protocol_image_bundle
from night_shifts.ubuntu_image_preparation import PreparationError, UbuntuPreparationConfig, UbuntuPreparationRecord, create_image_preparation_vm
from night_shifts.ubuntu_install_seed_iso import build_ubuntu_install_seed_iso
from night_shifts.ubuntu_preparation_retirement import retire_image_preparation_vm
from night_shifts.ubuntu_preparation_safety import checked_vm_guid, preparation_operation
from night_shifts.ubuntu_seed_attachment import attach_preparation_seed

_GUID = "12345678-1234-1234-1234-123456789abc"
_OTHER_GUID = "87654321-4321-4321-4321-cba987654321"


class FakeHost:
    """A host CONTRACT MODEL, not PowerShell execution or guest boot evidence."""

    def __init__(self):
        self.calls: list[tuple[str, tuple[str, ...]]] = []
        self.workspace: Path | None = None
        self.state = "Missing"
        self.started = 0
        self.removed = 0
        self.preflight_error = ""
        self.timeout_after_start = False
        self.receipt_change = ""
        self.on_start = None

    def run(self, script: Path, args: Sequence[str]) -> str:
        self.calls.append((script.name, tuple(args)))
        values = dict(zip(args[::2], args[1::2], strict=True))
        name = values["-VmName"]
        disk = Path(values["-DiskPath"])
        self.workspace = disk.parent
        if script.name == "prepare_image_vm.ps1":
            disk.write_bytes(b"TEST-owned fake disk, NOT a VHDX")
            Path(values["-VmConfigPath"]).mkdir()
            self.state = "Off"
            return name
        if script.name == "attach_image_seed.ps1":
            assert self.state == "Off"
            return name
        snapshot = json.loads((self.workspace / "manifest.json").read_bytes())
        assert (self.workspace / "vm-operation.lock").is_file()
        if script.name == "retire_image_vm.ps1":
            assert snapshot["status"] == "retirement_unknown"
            if values.get("-ExpectedVmId", _GUID) != _GUID:
                raise OSError("fake host GUID mismatch; no VM discarded")
            self.state = "Missing"
            self.removed += 1
            return json.dumps({"vm_name": name, "vm_id": _GUID, "vm_absent": True, "disk_retained": True})
        assert script.name == "launch_image_vm.ps1"
        assert snapshot["status"] == "launch_unknown"
        assert snapshot["vm_id"] == values["-VmId"] == _GUID
        assert (self.workspace / "launch.claim").is_file()
        assert values["-MemoryBytes"] == str(snapshot["memory_mb"] * 1024**2)
        assert values["-DiskSizeBytes"] == str(snapshot["disk_gb"] * 1024**3)
        assert values["-CpuCount"] == str(snapshot["cpu_count"])
        if self.on_start:
            self.on_start()
        if self.preflight_error or self.state != "Off":
            raise OSError(self.preflight_error or "fake host not off")
        self.state = "Running"
        self.started += 1
        if self.timeout_after_start:
            raise TimeoutError("VM may have started before loss of receipt")
        receipt: dict[str, object] = {"vm_name": name, "vm_id": _GUID, "state": "Running", "network_enabled": False}
        if self.receipt_change == "malformed":
            return "not json"
        if self.receipt_change == "oversized":
            return "x" * 2049
        if self.receipt_change == "guid":
            receipt["vm_id"] = _OTHER_GUID
        elif self.receipt_change == "null-guid":
            receipt["vm_id"] = None
        elif self.receipt_change == "name":
            receipt["vm_name"] = "another-vm"
        elif self.receipt_change == "state":
            receipt["state"] = "Off"
        elif self.receipt_change == "network":
            receipt["network_enabled"] = True
        elif self.receipt_change == "numeric-network":
            receipt["network_enabled"] = 0
        elif self.receipt_change == "extra":
            receipt["unexpected"] = True
        elif self.receipt_change == "missing":
            del receipt["state"]
        return json.dumps(receipt)


@pytest.fixture
def ready(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[UbuntuPreparationRecord, launch.UbuntuPreparationLaunchPlan, FakeHost]:
    pytest.importorskip("pycdlib")
    monkeypatch.setattr(launch.shutil, "disk_usage", lambda path: SimpleNamespace(free=100 * 1024**3))
    iso = tmp_path / "ubuntu-24.04.5-live-server-amd64.iso"
    data = bytearray(17 * 2048)
    data[16 * 2048:16 * 2048 + 7] = b"\x01CD001\x01"
    data[16 * 2048 + 40:16 * 2048 + 72] = b"Ubuntu-Server 24.04.5 LTS amd64".ljust(32)
    iso.write_bytes(data)  # Synthetic descriptor, NOT a bootable installer.
    bundle = tmp_path / "guest.zip"
    bundle_hash = build_protocol_image_bundle(bundle).sha256
    root = tmp_path / "build-sandboxes"
    root.mkdir()
    host = FakeHost()
    created = create_image_preparation_vm(
        UbuntuPreparationConfig(iso, hashlib.sha256(data).hexdigest(), bundle, bundle_hash, root),
        operator_authorized=True, iso_provenance_reviewed=True, runner=host,
    )
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    seed = build_ubuntu_install_seed_iso(media_dir, created.vm_name, bundle, bundle_hash)
    record = attach_preparation_seed(created, seed.path, seed.sha256, operator_authorized=True, seed_iso_reviewed=True, runner=host)
    plan = launch.build_preparation_launch_plan(record, _GUID)
    return record, plan, host


def _start(record, plan, host):
    return launch.launch_image_preparation_vm(
        record, plan, operator_authorized=True, iso_provenance_reviewed=True, host_state_reviewed=True, runner=host,
    )


def _discard(record, host, **kwargs):
    return retire_image_preparation_vm(record, operator_authorized=True, discard_image_reviewed=True, runner=host, **kwargs)


def test_packet_is_deterministic_read_only_and_not_host_evidence(ready, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    record, plan, host = ready
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    calls = list(host.calls)
    packet = plan.to_review_dict()
    assert packet["plan_sha256"] == plan.sha256
    assert packet["inputs"]["vm_id"] == _GUID
    assert packet["expected_host_policy"]["network_enabled"] is False
    assert packet["expected_host_policy"]["minimum_free_bytes"] == 20 * 1024**3
    assert "NOT Gate A" in packet["purpose"]
    assert plan.manifest_sha256 == hashlib.sha256((record.workspace / "manifest.json").read_bytes()).hexdigest()
    monkeypatch.setattr(launch.shutil, "disk_usage", lambda path: SimpleNamespace(free=99 * 1024**3))
    assert launch.build_preparation_launch_plan(record, _GUID) == plan
    assert host.calls == calls
    assert {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()} == before


def test_integrated_start_once_then_guid_bound_discard_keeps_disk(ready) -> None:
    record, plan, host = ready
    started = _start(record, plan, host)
    assert started.status == "installer_vm_started_not_reviewed"
    assert host.started == 1 and host.state == "Running"
    snapshot = json.loads((record.workspace / "manifest.json").read_bytes())
    assert snapshot["vm_id"] == _GUID
    assert snapshot["launch_plan_sha256"] == plan.sha256
    assert snapshot["launch_mode"] == "attended_install_only"
    assert not (record.workspace / "vm-operation.lock").exists()
    with pytest.raises(PreparationError):
        _start(record, plan, host)
    assert host.started == 1
    disk_before = plan.disk.read_bytes()
    retired = _discard(started, host)
    assert retired.status == "retired_vm_disk_retained"
    assert host.removed == 1 and host.state == "Missing"
    assert plan.disk.read_bytes() == disk_before
    assert (record.workspace / "launch.claim").is_file()
    assert (record.workspace / "retirement.claim").is_file()
    assert "-ExpectedVmId" in host.calls[-1][1]


@pytest.mark.parametrize("flags", [(False, True, True), (True, False, True), (True, True, False), (False, False, False)])
def test_separate_launch_consent_is_required_before_mutation(ready, flags) -> None:
    record, plan, host = ready
    before = (record.workspace / "manifest.json").read_bytes()
    with pytest.raises(PreparationError, match="authorization"):
        launch.launch_image_preparation_vm(record, plan, operator_authorized=flags[0], iso_provenance_reviewed=flags[1], host_state_reviewed=flags[2], runner=host)
    assert host.started == 0 and len(host.calls) == 2
    assert (record.workspace / "manifest.json").read_bytes() == before
    assert not (record.workspace / "launch.claim").exists()


@pytest.mark.parametrize("change", ["manifest", "iso", "bundle", "seed", "resource-plan", "typed-plan", "guid-plan", "busy", "retirement", "launch-claim", "pending", "disk", "config", "space"])
def test_stale_packet_or_bad_local_inputs_rejected_without_launch_claim(ready, change: str, monkeypatch: pytest.MonkeyPatch) -> None:
    record, plan, host = ready
    manifest = record.workspace / "manifest.json"
    if change == "manifest":
        data = json.loads(manifest.read_bytes())
        data["review_note"] = "changed after approval"
        manifest.write_text(json.dumps(data), encoding="utf-8")
    elif change in {"iso", "bundle", "seed"}:
        path = {"iso": plan.installer_iso, "bundle": plan.bundle, "seed": plan.seed_iso}[change]
        path.write_bytes(path.read_bytes() + b"altered")
    elif change == "resource-plan":
        plan = replace(plan, cpu_count=3)
    elif change == "typed-plan":
        plan = replace(plan, command_timeout_seconds=180)  # Python-equal to 180.0 but not the reviewed JSON fields
    elif change == "guid-plan":
        plan = replace(plan, vm_id="not-a-guid")
    elif change in {"busy", "retirement", "launch-claim", "pending"}:
        filename = {"busy": "vm-operation.lock", "retirement": "retirement.claim", "launch-claim": "launch.claim", "pending": "manifest.pending"}[change]
        (record.workspace / filename).write_bytes(b"earlier unresolved operation")
    elif change == "disk":
        plan.disk.unlink()
    elif change == "config":
        plan.vm_config.rmdir()
    else:
        monkeypatch.setattr(launch.shutil, "disk_usage", lambda path: SimpleNamespace(free=1))
    before = manifest.read_bytes()
    with pytest.raises(PreparationError):
        _start(record, plan, host)
    assert host.started == 0 and len(host.calls) == 2
    assert manifest.read_bytes() == before
    if change != "launch-claim":
        assert not (record.workspace / "launch.claim").exists()


@pytest.mark.parametrize("field,bad", [("cpu_count", True), ("cpu_count", 9), ("memory_mb", 0), ("disk_gb", 41), ("network_enabled", True), ("seed_kind", "generic"), ("version", True)])
def test_invalid_manifest_policy_cannot_generate_packet(ready, field: str, bad) -> None:
    record, _, host = ready
    manifest = record.workspace / "manifest.json"
    data = json.loads(manifest.read_bytes())
    data[field] = bad
    manifest.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(PreparationError):
        launch.build_preparation_launch_plan(record, _GUID)
    assert host.started == 0 and len(host.calls) == 2


@pytest.mark.parametrize("timeout", [0.0, 301.0, True, float("nan"), float("inf")])
def test_invalid_packet_timeout_has_no_side_effect(ready, timeout) -> None:
    record, _, host = ready
    before = (record.workspace / "manifest.json").read_bytes()
    with pytest.raises(PreparationError, match="timeout"):
        launch.build_preparation_launch_plan(record, _GUID, command_timeout_seconds=timeout)
    assert (record.workspace / "manifest.json").read_bytes() == before
    assert host.started == 0 and len(host.calls) == 2
    assert not (record.workspace / "launch.claim").exists()


@pytest.mark.parametrize("value", ["", "not-a-guid", "00000000-0000-0000-0000-000000000000", None, 123])
def test_host_guid_never_derived_or_guessed(value) -> None:
    with pytest.raises(PreparationError, match="GUID"):
        checked_vm_guid(value)


@pytest.mark.parametrize("change", ["malformed", "oversized", "guid", "null-guid", "name", "state", "network", "numeric-network", "extra", "missing", "timeout"])
def test_unknown_launch_retains_guid_claim_and_blocks_retry(ready, change: str) -> None:
    record, plan, host = ready
    host.receipt_change = change
    host.timeout_after_start = change == "timeout"
    with pytest.raises(PreparationError, match="launch status unknown"):
        _start(record, plan, host)
    snapshot = json.loads((record.workspace / "manifest.json").read_bytes())
    assert snapshot["status"] == "launch_unknown"
    assert snapshot["vm_id"] == _GUID
    assert snapshot["launch_plan_sha256"] == plan.sha256
    assert (record.workspace / "launch.claim").is_file()
    assert not (record.workspace / "vm-operation.lock").exists()
    with pytest.raises(PreparationError):
        _start(record, plan, host)
    assert host.started == 1 and host.removed == 0
    unknown = replace(record, status="launch_unknown")
    with pytest.raises(PreparationError, match="separate operator inspection"):
        _discard(unknown, host)
    retired = _discard(unknown, host, unknown_state_reviewed=True)
    assert retired.status == "retired_vm_disk_retained" and host.removed == 1


@pytest.mark.parametrize("reason", ["network", "ownership", "generation", "off-state", "resources", "dvd", "secure-boot", "boot-order", "disk-parent", "checkpoint", "media-hash"])
def test_fake_host_preflight_refusal_is_unknown_not_an_automatic_retry(ready, reason: str) -> None:
    record, plan, host = ready
    host.preflight_error = "fake preflight refusal: " + reason
    with pytest.raises(PreparationError, match="launch status unknown"):
        _start(record, plan, host)
    assert host.started == 0 and host.removed == 0
    assert json.loads((record.workspace / "manifest.json").read_bytes())["status"] == "launch_unknown"
    assert (record.workspace / "launch.claim").is_file()


def test_discard_cannot_overlap_inflight_launch_even_with_unknown_review(ready) -> None:
    record, plan, host = ready

    def concurrent_discard():
        unknown = replace(record, status="launch_unknown")
        with pytest.raises(PreparationError, match="busy or interrupted"):
            _discard(unknown, host, unknown_state_reviewed=True)
        assert not (record.workspace / "retirement.claim").exists()

    host.on_start = concurrent_discard
    assert _start(record, plan, host).status == "installer_vm_started_not_reviewed"
    assert host.started == 1 and host.removed == 0


@pytest.mark.parametrize("fail_on", [1, 2])
def test_launch_manifest_storage_failure_never_retries(ready, monkeypatch: pytest.MonkeyPatch, fail_on: int) -> None:
    record, plan, host = ready
    original = launch._store_manifest
    count = 0

    def failing_store(path, data, *, first):
        nonlocal count
        count += 1
        if count == fail_on:
            raise OSError("test-only persistence fault")
        return original(path, data, first=first)

    monkeypatch.setattr(launch, "_store_manifest", failing_store)
    with pytest.raises(PreparationError, match="launch status unknown"):
        _start(record, plan, host)
    assert host.started == fail_on - 1
    assert (record.workspace / "launch.claim").is_file()
    with pytest.raises(PreparationError):
        _start(record, plan, host)
    assert host.started == fail_on - 1


def test_operation_guard_excludes_nested_operations_and_releases_on_exception(tmp_path: Path) -> None:
    with pytest.raises(OSError, match="test fault"):
        with preparation_operation(tmp_path, "launch"):
            with pytest.raises(PreparationError, match="busy or interrupted"):
                with preparation_operation(tmp_path, "retire"):
                    pytest.fail("nested operation must never start")
            raise OSError("test fault")
    assert not (tmp_path / "vm-operation.lock").exists()
    with preparation_operation(tmp_path, "retire"):
        pass


def test_changed_operation_guard_is_retained_for_inspection(tmp_path: Path) -> None:
    with pytest.raises(PreparationError, match="guard changed"):
        with preparation_operation(tmp_path, "launch"):
            (tmp_path / "vm-operation.lock").write_bytes(b"unexpected replacement")
    assert (tmp_path / "vm-operation.lock").read_bytes() == b"unexpected replacement"


def test_start_script_guards_before_only_power_action_and_never_repairs() -> None:
    script = (Path(__file__).resolve().parents[2] / "night_shifts" / "backends" / "hyperv_scripts" / "launch_image_vm.ps1").read_text(encoding="utf-8")
    before, after = script.split("Start-VM -VM $vm -ErrorAction Stop")
    for expected in (
        "Get-VM -Id ([guid]$VmId)", "Assert-LaunchIdentity $vm 'Off'",
        "$Candidate.Id -ne [guid]$VmId", "$Candidate.Notes -cne $OwnerMarker",
        "$Candidate.Path -ne $VmConfigPath", "$Candidate.Generation -ne 2",
        "$disks.Count -ne 1", "$adapter.SwitchName", "$adapter.SwitchId",
        "Get-VMSnapshot", "$vm.CheckpointType", "$processor.Count -ne $CpuCount",
        "$memory.Startup -ne $MemoryBytes", "$memory.DynamicMemoryEnabled",
        "$vhd.VhdType -ne 'Dynamic'", "$vhd.Size -ne $DiskSizeBytes", "$vhd.ParentPath", "$vhd.Attached",
        "$dvds.Count -ne 2", "$firmware.SecureBoot", "$firmware.SecureBootTemplate",
        "$firmware.BootOrder[0].Device.Path -ne $InstallerIso",
        "Get-FileHash -LiteralPath $InstallerIso", "Get-FileHash -LiteralPath $SeedIso",
    ):
        assert expected in before
    assert "Assert-LaunchIdentity $started 'Running'" in after
    assert "network_enabled = $false" in after
    assert not any(command in script for command in ("Set-VM", "Add-VM", "New-VM", "Remove-VM", "Stop-VM", "Remove-Item", "SilentlyContinue"))
