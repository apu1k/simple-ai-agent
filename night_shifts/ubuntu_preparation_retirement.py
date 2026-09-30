"""Opt-in discard of one owned preparation VM, retaining its untrusted disk.

This is NOT image finalization or disk cleanup. Real execution requires separate
operator approval; tests use a fake runner and never invoke Hyper-V.
"""

from __future__ import annotations

import json
import math
import os
import re
import stat
import uuid
from pathlib import Path
from typing import Any

from night_shifts.backends.hyperv import PowerShellCommandRunner, SubprocessPowerShellRunner
from night_shifts.hyperv_image_preflight import _checked_path
from night_shifts.ubuntu_image_preparation import (
    PreparationError,
    UbuntuPreparationRecord,
    _store_manifest,
)

_ID = re.compile(r"^[0-9a-f]{32}$")
_GUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_ELIGIBLE = frozenset({
    "created_not_started", "created_seed_attached_not_started",
    "provisioning_unknown", "seed_attach_unknown",
})
_UNKNOWN = frozenset({"provisioning_unknown", "seed_attach_unknown"})


def _retirement_inputs(record: UbuntuPreparationRecord) -> tuple[Path, dict[str, Any]]:
    if not _ID.fullmatch(record.sandbox_id) or record.vm_name != "night-shift-image-prep-" + record.sandbox_id:
        raise PreparationError("invalid image-preparation identity")
    if record.status not in _ELIGIBLE:
        raise PreparationError("preparation status is not eligible; inspect before retirement")
    workspace = _checked_path(record.workspace, "preparation workspace")
    checkout = Path(__file__).resolve().parents[1]
    if not workspace.is_dir() or workspace.name != record.sandbox_id or workspace == checkout or checkout in workspace.parents:
        raise PreparationError("preparation workspace identity or location differs")
    manifest = _checked_path(workspace / "manifest.json", "preparation ownership manifest")
    info = manifest.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > 8192:
        raise PreparationError("preparation manifest is not a bounded regular file")
    pending = workspace / "manifest.pending"
    if pending.exists() or pending.is_symlink():
        raise PreparationError("incomplete manifest update; inspect before retirement")
    with manifest.open("rb") as stream:
        data = stream.read(8193)
    if len(data) > 8192:
        raise PreparationError("preparation manifest exceeds fixed bounds")
    try:
        snapshot = json.loads(data)
    except (ValueError, UnicodeError) as exc:
        raise PreparationError("invalid preparation manifest") from exc
    if not isinstance(snapshot, dict) or any((
        snapshot.get("version") != 1,
        snapshot.get("sandbox_id") != record.sandbox_id,
        snapshot.get("vm_name") != record.vm_name,
        snapshot.get("owner_marker") != "night-shift-image-prep-owner:" + record.sandbox_id,
        snapshot.get("disk") != str(workspace / "ubuntu-build.vhdx"),
        snapshot.get("vm_config") != str(workspace / "vm-config"),
        snapshot.get("network_enabled") is not False,
        snapshot.get("status") != record.status,
    )):
        raise PreparationError("preparation ownership manifest differs; inspect before retirement")
    disk = _checked_path(workspace / "ubuntu-build.vhdx", "retained preparation disk")
    config = _checked_path(workspace / "vm-config", "preparation VM configuration")
    if not stat.S_ISREG(disk.stat().st_mode) or not config.is_dir():
        raise PreparationError("recorded preparation disk or configuration is missing or irregular")
    return workspace, snapshot


def retire_image_preparation_vm(
    record: UbuntuPreparationRecord,
    *,
    operator_authorized: bool = False,
    discard_image_reviewed: bool = False,
    unknown_state_reviewed: bool = False,
    runner: PowerShellCommandRunner | None = None,
    powershell_executable: str = "powershell.exe",
    command_timeout_seconds: float = 180.0,
) -> UbuntuPreparationRecord:
    """Force off/unregister ONE owned VM; keep disk, manifest and evidence.

    This may interrupt installation and corrupt the retained disk. It is only
    for discarding a preparation attempt, NEVER for producing a reviewed image.
    A permanent exclusive claim and unknown status precede the host call.
    Any failure blocks retry and requires inspection of the exact recorded ID.
    No CLI, agent tool, broad VM sweep or filesystem deletion is provided.
    """
    if not operator_authorized or not discard_image_reviewed:
        raise PreparationError("explicit retirement authorization and discard-image review required")
    if not math.isfinite(command_timeout_seconds) or not 1 <= command_timeout_seconds <= 300:
        raise PreparationError("command timeout must be finite and from 1 to 300 seconds")
    try:
        workspace, snapshot = _retirement_inputs(record)
    except (OSError, ValueError) as exc:
        raise PreparationError(f"retirement inputs rejected: {exc}") from exc
    if record.status in _UNKNOWN and not unknown_state_reviewed:
        raise PreparationError("unknown preparation state needs separate operator inspection before retirement")
    claim = workspace / "retirement.claim"
    try:
        with claim.open("xb") as stream:
            stream.write((record.vm_name + "\n").encode("ascii"))
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise PreparationError("retirement already claimed; inspect the exact recorded ID, never retry") from exc
    except OSError as exc:
        raise PreparationError("retirement claim uncertain; inspect the exact recorded ID") from exc
    snapshot["retirement_previous_status"] = record.status
    snapshot["retirement_mode"] = "discard_vm_retain_disk"
    snapshot["status"] = "retirement_unknown"
    manifest = workspace / "manifest.json"
    script = Path(__file__).resolve().parent / "backends" / "hyperv_scripts" / "retire_image_vm.ps1"
    try:
        _store_manifest(manifest, snapshot, first=False)
        selected_runner = runner or SubprocessPowerShellRunner(
            powershell_executable, timeout_seconds=command_timeout_seconds,
        )
        output = selected_runner.run(script, (
            "-VmName", record.vm_name,
            "-OwnerMarker", "night-shift-image-prep-owner:" + record.sandbox_id,
            "-DiskPath", str(workspace / "ubuntu-build.vhdx"),
            "-VmConfigPath", str(workspace / "vm-config"),
        ))
        if len(output) > 2048:
            raise PreparationError("oversized retirement receipt")
        receipt = json.loads(output)
        if not isinstance(receipt, dict) or set(receipt) != {"vm_name", "vm_id", "vm_absent", "disk_retained"}:
            raise PreparationError("invalid retirement receipt")
        vm_id = receipt.get("vm_id")
        if any((
            receipt.get("vm_name") != record.vm_name,
            receipt.get("vm_absent") is not True,
            receipt.get("disk_retained") is not True,
        )):
            raise PreparationError("retirement receipt identity or observations differ")
        if not isinstance(vm_id, str) or not _GUID.fullmatch(vm_id) or uuid.UUID(vm_id).int == 0:
            raise PreparationError("invalid retired Hyper-V VM GUID")
        disk = _checked_path(workspace / "ubuntu-build.vhdx", "retained preparation disk")
        if not stat.S_ISREG(disk.stat().st_mode):
            raise PreparationError("preparation disk retention not observed")
        snapshot["retired_vm_id"] = vm_id
        snapshot["status"] = "retired_vm_disk_retained"
        _store_manifest(manifest, snapshot, first=False)
    except Exception as exc:
        raise PreparationError(
            f"VM retirement status unknown; inspect exact ID {record.sandbox_id}; retained disk is NOT a reviewed image"
        ) from exc
    return UbuntuPreparationRecord(record.sandbox_id, record.vm_name, workspace, "retired_vm_disk_retained")
