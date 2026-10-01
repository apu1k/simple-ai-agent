"""Opt-in, create-only Hyper-V Ubuntu image-preparation VM.

This does NOT install Ubuntu, start the VM, inject the bundle, or produce a
reviewed base image. No CLI or agent tool exposes this operation. A trusted
operator must explicitly authorize creation after reviewing the ISO source,
workspace and PowerShell script. All offline tests inject a fake runner.
"""

from __future__ import annotations

import json
import math
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from night_shifts.backends.hyperv import PowerShellCommandRunner, SubprocessPowerShellRunner
from night_shifts.hyperv_image_preflight import _checked_path
from night_shifts.ubuntu_iso_inputs import inspect_ubuntu_inputs


class PreparationError(RuntimeError):
    """A preparation attempt cannot safely proceed or needs investigation."""


@dataclass(frozen=True)
class UbuntuPreparationConfig:
    """Trusted, administrator-supplied values; never accept agent task text."""

    iso: Path
    iso_sha256: str
    bundle: Path
    bundle_sha256: str
    workspace_root: Path
    cpu_count: int = 2
    memory_mb: int = 2048
    disk_gb: int = 20
    powershell_executable: str = "powershell.exe"
    command_timeout_seconds: float = 180.0

    def __post_init__(self) -> None:
        for label, value, minimum, maximum in (
            ("cpu_count", self.cpu_count, 1, 8),
            ("memory_mb", self.memory_mb, 1024, 8192),
            ("disk_gb", self.disk_gb, 10, 40),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
                raise ValueError(f"{label} must be an integer from {minimum} to {maximum}")
        if not math.isfinite(self.command_timeout_seconds) or not 1 <= self.command_timeout_seconds <= 300:
            raise ValueError("command timeout must be finite and from 1 to 300 seconds")


@dataclass(frozen=True)
class UbuntuPreparationRecord:
    """Durable ownership reference, not a clean image or cleanup certificate."""

    sandbox_id: str
    vm_name: str
    workspace: Path
    status: str


def preparation_config_paths(workspace: Path, vm_name: str) -> tuple[Path, Path]:
    """Derive the New-VM -Path root and exact resulting VM.Path, never discover it.

    Hyper-V creates a VM-name subdirectory under the supplied configuration
    root. Both paths stay bound to the generated preparation identity.
    """
    if not re.fullmatch(r"night-shift-image-prep-[0-9a-f]{32}", vm_name) or (
        not workspace.is_absolute() or workspace.name != vm_name[23:]
    ):
        raise PreparationError("configuration paths require an identity-scoped preparation workspace")
    root = workspace / "vm-config"
    return root, root / vm_name


def _store_manifest(path: Path, data: dict[str, Any], *, first: bool) -> None:
    encoded = (json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    if first:
        with path.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        return
    temporary = path.with_name("manifest.pending")
    with temporary.open("xb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def create_image_preparation_vm(
    config: UbuntuPreparationConfig,
    *,
    operator_authorized: bool = False,
    iso_provenance_reviewed: bool = False,
    runner: PowerShellCommandRunner | None = None,
) -> UbuntuPreparationRecord:
    """Create but NEVER start one exact-ID VM from pinned operator inputs.

    On an uncertain host result, retain the ownership manifest and do not
    automatically destroy resources whose creation status is unknown. The
    operator must inspect and reconcile the exact recorded ID before retrying.
    """
    if not operator_authorized or not iso_provenance_reviewed:
        raise PreparationError("explicit VM-create authorization and independently reviewed ISO provenance required")
    report = inspect_ubuntu_inputs(
        config.iso, config.iso_sha256, config.bundle, config.bundle_sha256
    )
    root = _checked_path(config.workspace_root, "image-preparation workspace")
    if not root.is_dir() or root == Path(root.anchor):
        raise PreparationError("image-preparation workspace must be a dedicated directory")
    checkout = Path(__file__).resolve().parents[1]
    if root == checkout or checkout in root.parents:
        raise PreparationError("image-preparation workspace must be outside the checkout")
    if root == config.iso.parent or root in config.iso.parents or root == config.bundle.parent or root in config.bundle.parents:
        raise PreparationError("image-preparation workspace must not contain input files")
    if next(root.iterdir(), None) is not None:
        raise PreparationError("image-preparation workspace must be initially empty; inspect leftovers before retrying")
    if config.iso.drive.lower() != root.drive.lower() or config.bundle.drive.lower() != root.drive.lower():
        raise PreparationError("ISO, guest bundle and preparation workspace must be on the same volume")

    sandbox_id = uuid.uuid4().hex
    vm_name = f"night-shift-image-prep-{sandbox_id}"
    workspace = root / sandbox_id
    disk = workspace / "ubuntu-build.vhdx"
    vm_config_root, vm_config = preparation_config_paths(workspace, vm_name)
    owner = f"night-shift-image-prep-owner:{sandbox_id}"
    workspace.mkdir(exist_ok=False)
    manifest = workspace / "manifest.json"
    snapshot: dict[str, Any] = {
        "version": 1,
        "sandbox_id": sandbox_id,
        "vm_name": vm_name,
        "owner_marker": owner,
        "iso": str(config.iso),
        "iso_sha256": report.iso_sha256,
        "bundle": str(config.bundle),
        "bundle_sha256": report.bundle_sha256,
        "disk": str(disk),
        "vm_config_root": str(vm_config_root),
        "vm_config": str(vm_config),
        "cpu_count": config.cpu_count,
        "memory_mb": config.memory_mb,
        "disk_gb": config.disk_gb,
        "network_enabled": False,
        "status": "provisioning_unknown",
    }
    _store_manifest(manifest, snapshot, first=True)
    script = Path(__file__).resolve().parent / "backends" / "hyperv_scripts" / "prepare_image_vm.ps1"
    try:
        selected_runner = runner or SubprocessPowerShellRunner(
            config.powershell_executable, timeout_seconds=config.command_timeout_seconds
        )
        result = selected_runner.run(
            script,
            (
                "-VmName", vm_name,
                "-OwnerMarker", owner,
                "-InstallerIso", str(config.iso),
                "-InstallerIsoSha256", report.iso_sha256,
                "-DiskPath", str(disk),
                "-VmConfigRootPath", str(vm_config_root),
                "-VmConfigPath", str(vm_config),
                "-DiskSizeBytes", str(config.disk_gb * 1024**3),
                "-MemoryBytes", str(config.memory_mb * 1024**2),
                "-CpuCount", str(config.cpu_count),
            ),
        )
        if result.strip() != vm_name:
            raise PreparationError("VM creation returned an unexpected identity")
        snapshot["status"] = "created_not_started"
        _store_manifest(manifest, snapshot, first=False)
    except Exception as exc:
        # Even a command failure may have created a VM before disconnecting.
        # A durable manifest stays behind; no automatic retry or broad sweep.
        raise PreparationError(f"VM creation status unknown; inspect exact ID {sandbox_id}") from exc
    return UbuntuPreparationRecord(sandbox_id, vm_name, workspace, "created_not_started")
