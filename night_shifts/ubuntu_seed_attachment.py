"""Opt-in, attach-only NoCloud media operation for one owned, OFF preparation VM.

This does not start a VM or install an OS. A real host call needs separate
operator authorization; offline tests inject a fake PowerShell runner.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import stat
from pathlib import Path

from night_shifts.backends.hyperv import PowerShellCommandRunner, SubprocessPowerShellRunner
from night_shifts.hyperv_image_preflight import _checked_path
from night_shifts.ubuntu_image_preparation import (
    PreparationError,
    UbuntuPreparationRecord,
    _store_manifest,
)

_ID = re.compile(r"^[0-9a-f]{32}$")
_DIGEST = re.compile(r"^[0-9a-fA-F]{64}$")


def attach_preparation_seed(
    record: UbuntuPreparationRecord,
    seed_iso: Path,
    expected_sha256: str,
    *,
    operator_authorized: bool = False,
    seed_iso_reviewed: bool = False,
    runner: PowerShellCommandRunner | None = None,
    powershell_executable: str = "powershell.exe",
    command_timeout_seconds: float = 180.0,
) -> UbuntuPreparationRecord:
    """Attach pinned CIDATA ISO to an exact-owned preparation VM, never start.

    A durable 'unknown' marker precedes the host call. Any unexpected output,
    timeout or crash requires manual inspection of this exact recorded VM;
    retrying an uncertain attachment could create another DVD drive.
    """
    if not operator_authorized or not seed_iso_reviewed:
        raise PreparationError("explicit seed-attachment authorization and reviewed seed ISO required")
    if not _DIGEST.fullmatch(expected_sha256):
        raise PreparationError("expected seed ISO SHA-256 must be 64 hexadecimal characters")
    if not math.isfinite(command_timeout_seconds) or not 1 <= command_timeout_seconds <= 300:
        raise PreparationError("command timeout must be finite and from 1 to 300 seconds")
    if not _ID.fullmatch(record.sandbox_id) or record.vm_name != "night-shift-image-prep-" + record.sandbox_id:
        raise PreparationError("invalid image-preparation identity")
    workspace = _checked_path(record.workspace, "preparation workspace")
    checkout = Path(__file__).resolve().parents[1]
    if not workspace.is_dir() or workspace.name != record.sandbox_id or workspace == checkout or checkout in workspace.parents:
        raise PreparationError("preparation workspace identity or location differs")
    if record.status != "created_not_started":
        raise PreparationError("preparation record is not in the created, off state")
    manifest = workspace / "manifest.json"
    manifest_file = _checked_path(manifest, "preparation ownership manifest")
    if not stat.S_ISREG(manifest_file.stat().st_mode) or manifest_file.stat().st_size > 8192:
        raise PreparationError("preparation manifest is not a bounded regular file")
    if (workspace / "manifest.pending").exists() or (workspace / "manifest.pending").is_symlink():
        raise PreparationError("incomplete manifest update; inspect before retrying")
    try:
        with manifest_file.open("rb") as stream:
            snapshot = json.loads(stream.read(8193))
    except (ValueError, UnicodeError) as exc:
        raise PreparationError("invalid preparation manifest") from exc
    owner = "night-shift-image-prep-owner:" + record.sandbox_id
    if not isinstance(snapshot, dict) or any((
        snapshot.get("version") != 1,
        snapshot.get("sandbox_id") != record.sandbox_id,
        snapshot.get("vm_name") != record.vm_name,
        snapshot.get("owner_marker") != owner,
        snapshot.get("disk") != str(workspace / "ubuntu-build.vhdx"),
        snapshot.get("vm_config") != str(workspace / "vm-config"),
        snapshot.get("network_enabled") is not False,
        snapshot.get("status") != "created_not_started",
        not isinstance(snapshot.get("iso"), str),
        not isinstance(snapshot.get("iso_sha256"), str),
        not isinstance(snapshot.get("bundle_sha256"), str),
    )):
        raise PreparationError("preparation ownership manifest differs from record")
    installer = _checked_path(Path(snapshot["iso"]), "installer ISO")
    if not installer.is_file() or not _DIGEST.fullmatch(snapshot["iso_sha256"]) or not _DIGEST.fullmatch(snapshot["bundle_sha256"]):
        raise PreparationError("installer or manifest digests are invalid")
    media = _checked_path(seed_iso, "NoCloud seed ISO")
    if not media.is_file() or media.suffix.lower() != ".iso" or media.name != record.vm_name + ".iso":
        raise PreparationError("seed ISO must be the recorded image-preparation ID's .iso")
    if media.drive.lower() != workspace.drive.lower() or workspace == media.parent or workspace in media.parents:
        raise PreparationError("seed ISO must be outside workspace on the preparation volume")
    if media.stat().st_size > 1024 * 1024 or media.stat().st_size < 17 * 2048:
        raise PreparationError("NoCloud seed ISO size is outside the fixed bounds")
    digest = hashlib.sha256()
    with media.open("rb") as stream:
        stream.seek(16 * 2048)
        descriptor = stream.read(72)
        if descriptor[:7] != b"\x01CD001\x01" or descriptor[40:72].rstrip(b" ") != b"CIDATA":
            raise PreparationError("NoCloud seed ISO lacks the CIDATA descriptor")
        stream.seek(0)
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    if media.stat().st_size > 1024 * 1024 or digest.hexdigest() != expected_sha256.lower():
        raise PreparationError("NoCloud seed ISO differs from reviewed SHA-256")
    snapshot["seed_iso"] = str(media)
    snapshot["seed_iso_sha256"] = expected_sha256.lower()
    snapshot["status"] = "seed_attach_unknown"
    _store_manifest(manifest, snapshot, first=False)
    script = Path(__file__).resolve().parent / "backends" / "hyperv_scripts" / "attach_image_seed.ps1"
    try:
        selected_runner = runner or SubprocessPowerShellRunner(
            powershell_executable, timeout_seconds=command_timeout_seconds
        )
        result = selected_runner.run(script, (
            "-VmName", record.vm_name,
            "-OwnerMarker", owner,
            "-DiskPath", str(workspace / "ubuntu-build.vhdx"),
            "-VmConfigPath", str(workspace / "vm-config"),
            "-InstallerIso", str(installer),
            "-InstallerIsoSha256", snapshot["iso_sha256"],
            "-SeedIso", str(media),
            "-SeedIsoSha256", expected_sha256.lower(),
        ))
        if result.strip() != record.vm_name:
            raise PreparationError("unexpected VM identity after seed attachment")
        snapshot["status"] = "created_seed_attached_not_started"
        _store_manifest(manifest, snapshot, first=False)
    except Exception as exc:
        raise PreparationError(
            f"seed attachment status unknown; inspect exact ID {record.sandbox_id}"
        ) from exc
    return UbuntuPreparationRecord(
        record.sandbox_id, record.vm_name, workspace, "created_seed_attached_not_started"
    )
