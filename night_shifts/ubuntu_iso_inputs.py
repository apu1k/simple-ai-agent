"""Read-only input contract for a future Ubuntu 24.04 image-preparation VM.

No download, mount, ISO remaster, Hyper-V command, or guest execution occurs here.
A signed/reviewed upstream checksum and real boot still require operator work.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

from night_shifts.hyperv_image_preflight import _checked_path
from night_shifts.protocol_image_bundle import _ASSET_NAMES, _assets

_SECTOR = 2048
_PRIMARY_VOLUME_DESCRIPTOR = 16 * _SECTOR
_MAX_ISO_BYTES = 10 * 1024**3
_MAX_BUNDLE_BYTES = 4 * 1024**2


class UbuntuInputError(ValueError):
    """The supplied ISO or guest bundle does not match the trusted inputs."""


@dataclass(frozen=True)
class UbuntuInputReport:
    """Evidence about local inputs, NOT a bootable VHDX or isolation evidence."""

    iso_sha256: str
    iso_bytes: int
    iso_volume_label: str
    bundle_sha256: str


def _outside_checkout(path: Path, label: str) -> Path:
    resolved = _checked_path(path, label)
    checkout = Path(__file__).resolve().parents[1]
    if resolved == checkout or checkout in resolved.parents:
        raise UbuntuInputError(f"{label} must be outside the checkout")
    if not resolved.is_file():
        raise UbuntuInputError(f"{label} must be an existing regular file")
    return resolved


def _digest(value: str) -> str:
    if not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        raise UbuntuInputError("a separately reviewed 64-character SHA-256 is required")
    return value.lower()


def _hash_bounded(path: Path, limit: int, expected: str) -> int:
    size = path.stat().st_size
    if size > limit or size <= 0:
        raise UbuntuInputError("input file exceeds its size limit or is empty")
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    if path.stat().st_size != size:
        raise UbuntuInputError("input changed size during validation")
    if hasher.hexdigest() != expected:
        raise UbuntuInputError("input does not match its separately reviewed SHA-256")
    return size


def inspect_ubuntu_inputs(
    iso: Path, iso_sha256: str, bundle: Path, bundle_sha256: str
) -> UbuntuInputReport:
    """Verify exact local inputs, not upstream provenance or install safety.

    A matching volume label is only a sanity check: an attacker could forge it.
    The ISO digest must come from an independently reviewed upstream source.
    """
    iso_hash = _digest(iso_sha256)
    bundle_hash = _digest(bundle_sha256)
    if iso.suffix.lower() != ".iso" or bundle.suffix.lower() != ".zip":
        raise UbuntuInputError("expected a .iso installer and a .zip guest bundle")
    iso_file = _outside_checkout(iso, "ISO")
    bundle_file = _outside_checkout(bundle, "bundle")
    iso_size = _hash_bounded(iso_file, _MAX_ISO_BYTES, iso_hash)
    if iso_size < _PRIMARY_VOLUME_DESCRIPTOR + _SECTOR:
        raise UbuntuInputError("ISO is too short to contain a primary volume descriptor")
    with iso_file.open("rb") as stream:
        stream.seek(_PRIMARY_VOLUME_DESCRIPTOR)
        descriptor = stream.read(_SECTOR)
    if descriptor[:7] != b"\x01CD001\x01":
        raise UbuntuInputError("ISO lacks an ISO9660 primary volume descriptor")
    try:
        label = descriptor[40:72].decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise UbuntuInputError("ISO volume label must be ASCII") from exc
    upper_label = label.upper()
    if not ("UBUNTU" in upper_label and "24.04" in upper_label and "AMD64" in upper_label):
        raise UbuntuInputError("ISO label is not Ubuntu 24.04 amd64; review the source")
    _hash_bounded(bundle_file, _MAX_BUNDLE_BYTES, bundle_hash)
    expected_assets = _assets()
    expected_digests = {
        name: hashlib.sha256(content).hexdigest()
        for name, content in expected_assets.items()
    }
    expected_manifest = {
        "schema_version": 1,
        "purpose": "offline Hyper-V protocol-test guest installation assets",
        "files": {
            name: {"sha256": expected_digests[name], "bytes": len(expected_assets[name])}
            for name in _ASSET_NAMES
        },
    }
    try:
        with zipfile.ZipFile(bundle_file) as archive:
            if archive.namelist() != [*_ASSET_NAMES, "SHA256SUMS", "manifest.json"]:
                raise UbuntuInputError("guest bundle has unexpected or missing entries")
            if any(entry.file_size > 1024 * 1024 for entry in archive.infolist()):
                raise UbuntuInputError("guest bundle contains an oversized entry")
            if any(archive.read(name) != expected_assets[name] for name in _ASSET_NAMES):
                raise UbuntuInputError("guest bundle is stale relative to trusted assets")
            expected_sums = "".join(
                f"{expected_digests[name]}  {name}\n" for name in _ASSET_NAMES
            ).encode("ascii")
            if archive.read("SHA256SUMS") != expected_sums:
                raise UbuntuInputError("guest bundle checksum list is inconsistent")
            if json.loads(archive.read("manifest.json")) != expected_manifest:
                raise UbuntuInputError("guest bundle manifest is inconsistent")
    except (zipfile.BadZipFile, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UbuntuInputError("guest bundle is malformed") from exc
    return UbuntuInputReport(iso_hash, iso_size, label, bundle_hash)


def main(argv: list[str] | None = None) -> int:
    """Read-only check of operator-selected sources; no Hyper-V integration."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iso", required=True, type=Path)
    parser.add_argument("--iso-sha256", required=True)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--bundle-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        report = inspect_ubuntu_inputs(
            args.iso, args.iso_sha256, args.bundle, args.bundle_sha256
        )
    except (UbuntuInputError, OSError, ValueError) as exc:
        parser.exit(2, f"Ubuntu input check BLOCKED: {exc}\n")
    print(
        f"Local ISO bytes: {report.iso_bytes}; label: {report.iso_volume_label}; "
        f"ISO SHA-256: {report.iso_sha256}; bundle SHA-256: {report.bundle_sha256}"
    )
    print("No VM/image built. Upstream ISO authenticity, boot, guest service, networking, pipe ACLs and cleanup are NOT verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
