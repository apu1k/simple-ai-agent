"""Read-only launch packet and separately authorized, start-once preparation VM.

No CLI/agent tool exposes launch. A packet is NOT approval or host evidence.
Offline tests use fake runners; no installed image or Gate A is certified here.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import stat
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from night_shifts.backends.hyperv import PowerShellCommandRunner, SubprocessPowerShellRunner
from night_shifts.hyperv_image_preflight import _checked_path
from night_shifts.ubuntu_image_preparation import PreparationError, UbuntuPreparationRecord, _store_manifest, preparation_config_paths
from night_shifts.ubuntu_install_seed_iso import inspect_ubuntu_install_seed_iso
from night_shifts.ubuntu_iso_inputs import inspect_ubuntu_inputs
from night_shifts.ubuntu_preparation_control import checked_preparation_control
from night_shifts.ubuntu_preparation_safety import checked_vm_guid, preparation_operation

_ID = re.compile(r"^[0-9a-f]{32}$")
_DIGEST = re.compile(r"^[0-9a-fA-F]{64}$")
_READY = "created_seed_attached_not_started"


@dataclass(frozen=True)
class UbuntuPreparationLaunchPlan:
    """Immutable local-input review packet; GUID comes from the trusted operator."""

    sandbox_id: str
    vm_name: str
    vm_id: str
    workspace: Path
    control: Path
    disk: Path
    vm_config: Path
    installer_iso: Path
    installer_iso_sha256: str
    bundle: Path
    bundle_sha256: str
    seed_iso: Path
    seed_iso_sha256: str
    cpu_count: int
    memory_mb: int
    disk_gb: int
    manifest_sha256: str
    launch_script_sha256: str
    command_timeout_seconds: float

    def _fields(self) -> dict[str, object]:
        fields = {key: str(value) if isinstance(value, Path) else value for key, value in asdict(self).items()}
        fields["manifest"] = str(self.control / "manifest.json")
        return fields

    @property
    def sha256(self) -> str:
        """Bind fields for operator review, NOT a signature or authorization token."""
        data = json.dumps(self._fields(), sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        return hashlib.sha256(data).hexdigest()

    def to_review_dict(self) -> dict[str, object]:
        """Return public review data in memory; no files/host commands are written."""
        return {
            "schema_version": 2,
            "purpose": "attended preparation installer launch only; NOT Gate A",
            "plan_sha256": self.sha256,
            "inputs": self._fields(),
            "expected_host_policy": {
                "generation": 2, "network_enabled": False, "dynamic_memory": False,
                "checkpoints": "Disabled", "automatic_start": "Nothing", "automatic_stop": "ShutDown",
                "secure_boot": "On", "secure_boot_template": "MicrosoftUEFICertificateAuthority",
                "disk_format": "VHDX", "disk_type": "Dynamic", "disk_parent": None,
                "installer_first_boot": True, "minimum_free_bytes": self.disk_gb * 1024**3,
            },
            "scope": "start pinned owned OFF VM once; manual disk confirmation and target review; request poweroff",
            "not_in_scope": [
                "automatic installation supervision or hard VM lifetime deadline",
                "first boot of installed guest", "media/boot-order changes", "image freezing",
                "automatic retirement or disk deletion", "repository transfer", "model calls", "Gate A acceptance",
            ],
            "operator_review_required": [
                "authenticated Ubuntu ISO provenance", "current repository commit and scripts",
                "actual host GUID/ownership/configuration/resources/media/network/off-state",
                "directory ACLs, host integration/shares, free space, exclusive host use",
                "attended console access and time window", "separate discard consent if needed",
            ],
        }


def _launch_inputs(
    record: UbuntuPreparationRecord, vm_id: str, command_timeout_seconds: float, *, operation_held: bool = False,
) -> tuple[UbuntuPreparationLaunchPlan, dict[str, Any]]:
    vm_id = checked_vm_guid(vm_id)
    if isinstance(command_timeout_seconds, bool) or not isinstance(command_timeout_seconds, (int, float)) or (
        not math.isfinite(command_timeout_seconds) or not 1 <= command_timeout_seconds <= 300
    ):
        raise PreparationError("launch command timeout must be finite and from 1 to 300 seconds")
    if not _ID.fullmatch(record.sandbox_id) or record.vm_name != "night-shift-image-prep-" + record.sandbox_id:
        raise PreparationError("invalid image-preparation identity")
    if record.status != _READY:
        raise PreparationError("launch requires an attached combined seed and never-started record")
    root = _checked_path(record.workspace, "preparation workspace")
    checkout = Path(__file__).resolve().parents[1]
    if not root.is_dir() or root.name != record.sandbox_id or root == checkout or checkout in root.parents:
        raise PreparationError("preparation workspace identity or location differs")
    control = checked_preparation_control(root)
    blocked: tuple[str, ...] = ("manifest.pending", "launch.claim", "retirement.claim")
    if not operation_held:
        blocked += ("vm-operation.lock",)
    for name in blocked:
        path = control / name
        if path.exists() or path.is_symlink():
            raise PreparationError(f"{name} present; inspect exact workspace, never launch or retry blindly")
    manifest = _checked_path(control / "manifest.json", "preparation ownership manifest")
    if not stat.S_ISREG(manifest.stat().st_mode) or manifest.stat().st_size > 8192:
        raise PreparationError("preparation manifest is not a bounded regular file")
    with manifest.open("rb") as stream:
        raw = stream.read(8193)
    if len(raw) > 8192:
        raise PreparationError("preparation manifest exceeds fixed bounds")
    try:
        snapshot = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise PreparationError("invalid preparation manifest") from exc
    config_root, config_path = preparation_config_paths(root, record.vm_name)
    if not isinstance(snapshot, dict) or any((
        type(snapshot.get("version")) is not int, snapshot.get("version") != 2,
        snapshot.get("workspace") != str(root), snapshot.get("control") != str(control),        snapshot.get("sandbox_id") != record.sandbox_id, snapshot.get("vm_name") != record.vm_name,
        snapshot.get("owner_marker") != "night-shift-image-prep-owner:" + record.sandbox_id,
        snapshot.get("disk") != str(root / "ubuntu-build.vhdx"),
        snapshot.get("vm_config_root") != str(config_root),
        snapshot.get("vm_config") != str(config_path),
        snapshot.get("status") != _READY, snapshot.get("network_enabled") is not False,
        snapshot.get("seed_kind") != "ubuntu-protocol-install-v1",
    )):
        raise PreparationError("preparation ownership or combined-seed manifest differs")
    if "vm_id" in snapshot and checked_vm_guid(snapshot["vm_id"]) != vm_id:
        raise PreparationError("observed VM GUID differs from the recorded preparation binding")
    for field in ("iso", "bundle", "seed_iso", "iso_sha256", "bundle_sha256", "seed_iso_sha256"):
        value = snapshot.get(field)
        if not isinstance(value, str) or not value or (field.endswith("sha256") and not _DIGEST.fullmatch(value)):
            raise PreparationError("missing or invalid manifest media binding")
    for field, lower, upper in (("cpu_count", 1, 8), ("memory_mb", 1024, 8192), ("disk_gb", 10, 40)):
        value = snapshot.get(field)
        if type(value) is not int or not lower <= value <= upper:
            raise PreparationError("manifest resources are outside fixed bounds")
    installer = _checked_path(Path(snapshot["iso"]), "installer ISO")
    bundle = _checked_path(Path(snapshot["bundle"]), "fixed guest bundle")
    seed = _checked_path(Path(snapshot["seed_iso"]), "combined install seed ISO")
    disk = _checked_path(root / "ubuntu-build.vhdx", "preparation disk")
    config = _checked_path(config_path, "exact preparation VM configuration")
    if not stat.S_ISREG(disk.stat().st_mode) or not config.is_dir():
        raise PreparationError("recorded disk or VM configuration is missing or irregular")
    for path in (root, installer, bundle, seed):
        if path.drive.startswith("\\\\"):
            raise PreparationError("preparation launch paths must be on local storage, not UNC shares")
    for media in (installer, bundle, seed):
        if root in media.parents or checkout in media.parents or media.drive.lower() != root.drive.lower():
            raise PreparationError("launch media must be external to workspace/checkout on the preparation volume")
    if installer == seed:
        raise PreparationError("installer and combined seed must be distinct media")
    inputs = inspect_ubuntu_inputs(installer, snapshot["iso_sha256"], bundle, snapshot["bundle_sha256"])
    install_seed = inspect_ubuntu_install_seed_iso(seed, record.vm_name, snapshot["seed_iso_sha256"], bundle, inputs.bundle_sha256)
    if shutil.disk_usage(root).free < snapshot["disk_gb"] * 1024**3:
        raise PreparationError("preparation volume lacks the conservative free-space reserve")
    script = _checked_path(Path(__file__).resolve().parent / "backends" / "hyperv_scripts" / "launch_image_vm.ps1", "trusted launch script")
    info = script.stat()
    if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= 64 * 1024:
        raise PreparationError("trusted launch script is not a bounded regular file")
    with script.open("rb") as stream:
        script_bytes = stream.read(64 * 1024 + 1)
    if len(script_bytes) != info.st_size or script.stat().st_size != info.st_size:
        raise PreparationError("trusted launch script changed during review")
    plan = UbuntuPreparationLaunchPlan(
        record.sandbox_id, record.vm_name, vm_id, root, control, disk, config,
        installer, inputs.iso_sha256, bundle, inputs.bundle_sha256, seed, install_seed.sha256,
        snapshot["cpu_count"], snapshot["memory_mb"], snapshot["disk_gb"],
        hashlib.sha256(raw).hexdigest(), hashlib.sha256(script_bytes).hexdigest(), float(command_timeout_seconds),
    )
    return plan, snapshot


def build_preparation_launch_plan(
    record: UbuntuPreparationRecord, observed_vm_id: str, *, command_timeout_seconds: float = 180.0,
) -> UbuntuPreparationLaunchPlan:
    """Check files/read manifest and return a packet, WITHOUT calling Hyper-V.

    observed_vm_id must come from independent trusted host inspection. Hashes
    detect changes, not provenance. Host settings/ACLs are NOT observed here.
    """
    try:
        plan, _ = _launch_inputs(record, observed_vm_id, command_timeout_seconds)
        return plan
    except (OSError, ValueError) as exc:
        raise PreparationError(f"launch packet inputs rejected: {exc}") from exc


def launch_image_preparation_vm(
    record: UbuntuPreparationRecord,
    approved_plan: UbuntuPreparationLaunchPlan,
    *,
    operator_authorized: bool = False,
    iso_provenance_reviewed: bool = False,
    host_state_reviewed: bool = False,
    runner: PowerShellCommandRunner | None = None,
    powershell_executable: str = "powershell.exe",
) -> UbuntuPreparationRecord:
    """Start the pinned installer VM ONCE, after separate attended-run approval.

    Rebuild/compare the complete packet under an exclusive launch/retirement
    guard before making a permanent claim. Persist GUID/plan/unknown state
    BEFORE the command. Never auto-retry, stop/discard, or mark OS/image success.
    The command timeout does not bound the subsequently running VM's lifetime.
    """
    if not operator_authorized or not iso_provenance_reviewed or not host_state_reviewed:
        raise PreparationError("explicit launch authorization, ISO provenance and host-state review required")
    if not isinstance(approved_plan, UbuntuPreparationLaunchPlan) or record.workspace != approved_plan.workspace:
        raise PreparationError("launch requires the reviewed packet for this exact workspace")
    workspace = _checked_path(record.workspace, "preparation workspace")
    with preparation_operation(workspace, "launch"):
        try:
            actual, snapshot = _launch_inputs(
                record, approved_plan.vm_id, approved_plan.command_timeout_seconds, operation_held=True,
            )
        except (OSError, ValueError) as exc:
            raise PreparationError(f"launch inputs rejected before host call: {exc}") from exc
        # Fingerprints also distinguish Python-equal but differently typed fields
        # (e.g. 180 vs 180.0). The exact reviewed packet must survive unchanged.
        if actual != approved_plan or actual.sha256 != approved_plan.sha256:
            raise PreparationError("launch packet changed since review; obtain new explicit approval")
        claim_data = {
            "version": 1, "vm_name": actual.vm_name, "vm_id": actual.vm_id, "plan_sha256": actual.sha256,
        }
        try:
            with (actual.control / "launch.claim").open("xb") as stream:
                stream.write((json.dumps(claim_data, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii"))
                stream.flush()
                os.fsync(stream.fileno())
        except OSError as exc:
            raise PreparationError("launch claim uncertain; inspect exact workspace, never retry blindly") from exc
        snapshot["vm_id"] = actual.vm_id
        snapshot["launch_plan_sha256"] = actual.sha256
        snapshot["launch_mode"] = "attended_install_only"
        snapshot["status"] = "launch_unknown"
        manifest = actual.control / "manifest.json"
        script = Path(__file__).resolve().parent / "backends" / "hyperv_scripts" / "launch_image_vm.ps1"
        try:
            _store_manifest(manifest, snapshot, first=False)
            selected_runner = runner or SubprocessPowerShellRunner(
                powershell_executable, timeout_seconds=actual.command_timeout_seconds,
            )
            output = selected_runner.run(script, (
                "-VmName", actual.vm_name, "-VmId", actual.vm_id,
                "-OwnerMarker", "night-shift-image-prep-owner:" + actual.sandbox_id,
                "-DiskPath", str(actual.disk), "-VmConfigPath", str(actual.vm_config),
                "-InstallerIso", str(actual.installer_iso), "-InstallerIsoSha256", actual.installer_iso_sha256,
                "-SeedIso", str(actual.seed_iso), "-SeedIsoSha256", actual.seed_iso_sha256,
                "-DiskSizeBytes", str(actual.disk_gb * 1024**3),
                "-MemoryBytes", str(actual.memory_mb * 1024**2), "-CpuCount", str(actual.cpu_count),
            ))
            if len(output) > 2048:
                raise PreparationError("oversized launch receipt")
            receipt = json.loads(output)
            if not isinstance(receipt, dict) or set(receipt) != {"vm_name", "vm_id", "state", "network_enabled"}:
                raise PreparationError("invalid launch receipt")
            if any((
                receipt.get("vm_name") != actual.vm_name,
                checked_vm_guid(receipt.get("vm_id")) != actual.vm_id,
                receipt.get("state") != "Running", receipt.get("network_enabled") is not False,
            )):
                raise PreparationError("launch receipt identity, running state or network observation differs")
            snapshot["status"] = "installer_vm_started_not_reviewed"
            _store_manifest(manifest, snapshot, first=False)
        except Exception as exc:
            raise PreparationError(
                f"VM launch status unknown; inspect exact ID {actual.sandbox_id} / GUID {actual.vm_id}; never retry"
            ) from exc
    return UbuntuPreparationRecord(record.sandbox_id, record.vm_name, workspace, "installer_vm_started_not_reviewed")
