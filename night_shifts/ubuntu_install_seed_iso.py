"""Candidate offline CIDATA image with both autoinstall config and fixed guest payload.

This does NOT invoke the Ubuntu installer or attach media to a VM. The source
bundle's pinned hash and fixed trusted contents are rechecked before packaging.
The resulting ISO requires independent review and a real guest validation.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from night_shifts.hyperv_image_preflight import _checked_path
from night_shifts.protocol_image_bundle import _ASSET_NAMES, _assets
from night_shifts.ubuntu_seed import render_ubuntu_install_seed
from night_shifts.ubuntu_seed_iso import SeedIsoError

_DIGEST = re.compile(r"^[0-9a-fA-F]{64}$")
_GUEST_NAMES = ("protocol_test_bootstrap.py", "night-shift-protocol-test.service")
_TARGET_SCRIPT = "install_protocol_test_target.sh"
_MAX_MEDIA = 2 * 1024 * 1024


@dataclass(frozen=True)
class ProtocolInstallSeedReport:
    """ISO identity/digest, NOT a booted or trusted base image."""

    path: Path
    sha256: str
    size_bytes: int
    bundle_sha256: str


def _fixed_payload(bundle: Path, expected_sha256: str) -> dict[str, bytes]:
    if not _DIGEST.fullmatch(expected_sha256):
        raise SeedIsoError("a separately reviewed bundle SHA-256 is required")
    source = _checked_path(bundle, "fixed guest bundle")
    checkout = Path(__file__).resolve().parents[1]
    if source.suffix.lower() != ".zip" or not source.is_file() or source == checkout or checkout in source.parents:
        raise SeedIsoError("guest bundle must be an external regular .zip")
    if not 0 < source.stat().st_size <= 4 * 1024 * 1024:
        raise SeedIsoError("guest bundle size is outside fixed bounds")
    digest = hashlib.sha256()
    with source.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    if source.stat().st_size > 4 * 1024 * 1024 or digest.hexdigest() != expected_sha256.lower():
        raise SeedIsoError("guest bundle differs from reviewed SHA-256")
    trusted = _assets()
    expected_sums = "".join(
        f"{hashlib.sha256(trusted[name]).hexdigest()}  {name}\n" for name in _ASSET_NAMES
    ).encode("ascii")
    expected_manifest = {
        "schema_version": 1,
        "purpose": "offline Hyper-V protocol-test guest installation assets",
        "files": {
            name: {"sha256": hashlib.sha256(trusted[name]).hexdigest(), "bytes": len(trusted[name])}
            for name in _ASSET_NAMES
        },
    }
    try:
        with zipfile.ZipFile(source) as archive:
            if archive.namelist() != [*_ASSET_NAMES, "SHA256SUMS", "manifest.json"]:
                raise SeedIsoError("unexpected fixed guest bundle entries")
            if any(entry.file_size > 1024 * 1024 for entry in archive.infolist()):
                raise SeedIsoError("oversized fixed guest bundle entry")
            if any(archive.read(name) != trusted[name] for name in _ASSET_NAMES):
                raise SeedIsoError("guest bundle is stale relative to trusted guest files")
            if archive.read("SHA256SUMS") != expected_sums or json.loads(archive.read("manifest.json")) != expected_manifest:
                raise SeedIsoError("guest bundle manifest or checksums are inconsistent")
    except (zipfile.BadZipFile, UnicodeDecodeError, ValueError) as exc:
        raise SeedIsoError("invalid guest bundle") from exc
    script = Path(__file__).resolve().parent / "guest" / _TARGET_SCRIPT
    info = script.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > 128 * 1024:
        raise SeedIsoError("target installer is not a bounded regular trusted file")
    data = script.read_bytes()
    if len(data) != info.st_size:
        raise SeedIsoError("target installer changed during read")
    contents = {name: trusted[name] for name in _GUEST_NAMES}
    contents[_TARGET_SCRIPT] = data
    contents["SHA256SUMS"] = "".join(
        f"{hashlib.sha256(contents[name]).hexdigest()}  {name}\n"
        for name in (*_GUEST_NAMES, _TARGET_SCRIPT)
    ).encode("ascii")
    return contents


def build_ubuntu_install_seed_iso(
    parent: Path, instance_id: str, bundle: Path, expected_bundle_sha256: str
) -> ProtocolInstallSeedReport:
    """Write one fresh ISO with exact NoCloud data and reviewed fixed payload.

    Unlike build_ubuntu_seed_iso, this image has Subiquity late-commands AND
    their payload. Only its matching ID-named .iso can later be considered for
    attachment; this function itself never invokes Hyper-V or PowerShell.
    """
    seed = render_ubuntu_install_seed(instance_id)
    root = _checked_path(parent, "seed media output directory")
    checkout = Path(__file__).resolve().parents[1]
    if not root.is_dir() or root == Path(root.anchor) or root == checkout or checkout in root.parents:
        raise SeedIsoError("seed output directory must be dedicated and outside checkout")
    source = _checked_path(bundle, "fixed guest bundle")
    if root.drive.lower() != source.drive.lower():
        raise SeedIsoError("seed output and fixed guest bundle must be on the same volume")
    output = root / (instance_id + ".iso")
    if output.exists() or output.is_symlink():
        raise SeedIsoError("seed ISO already exists; never overwrite")
    payload = _fixed_payload(source, expected_bundle_sha256)
    files = {
        "user-data": (seed.user_data, "/USERDATA.;1"),
        "meta-data": (seed.meta_data, "/METADATA.;1"),
        "protocol_test_bootstrap.py": (payload["protocol_test_bootstrap.py"], "/BOOTSTRP.PY;1"),
        "night-shift-protocol-test.service": (payload["night-shift-protocol-test.service"], "/PROTUNIT.SRV;1"),
        _TARGET_SCRIPT: (payload[_TARGET_SCRIPT], "/TARGETSH.SH;1"),
        "SHA256SUMS": (payload["SHA256SUMS"], "/SHASUMS.;1"),
    }
    try:
        import pycdlib  # type: ignore[import-not-found]  # pinned development dependency
    except ImportError as exc:
        raise SeedIsoError("pycdlib is required for offline ISO authoring") from exc
    iso = pycdlib.PyCdlib()
    iso.new(vol_ident="CIDATA", rock_ridge="1.09", joliet=3)
    try:
        for name, (data, iso_name) in files.items():
            iso.add_fp(io.BytesIO(data), len(data), iso_path=iso_name, rr_name=name, joliet_path="/" + name)
        fd, temporary = tempfile.mkstemp(prefix=".night-shift-install-seed-", dir=root)
        os.close(fd)
        try:
            iso.write(temporary)
            with open(temporary, "r+b") as stream:
                os.fsync(stream.fileno())
                digest = hashlib.sha256()
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
                size = stream.tell()
            if not 0 < size <= _MAX_MEDIA:
                raise SeedIsoError("combined seed ISO exceeds fixed 2 MiB bound")
            os.link(temporary, output)  # atomic no-replace claim
            return ProtocolInstallSeedReport(output, digest.hexdigest(), size, expected_bundle_sha256.lower())
        finally:
            Path(temporary).unlink(missing_ok=True)
    finally:
        iso.close()
