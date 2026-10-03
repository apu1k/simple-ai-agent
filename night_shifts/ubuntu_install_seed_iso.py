"""Candidate offline CIDATA image with both autoinstall config and fixed guest payload.

This does NOT invoke the Ubuntu installer or attach media to a VM. The source
bundle's pinned hash and fixed trusted contents are rechecked before packaging.
Fixed Linux text is canonical UTF-8/LF before hashes and media are written.
Previously packaged CRLF payloads are stale, even with matching self-hashes.
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
from night_shifts.protocol_image_bundle import (
    _ASSET_NAMES,
    BundleError,
    _assets,
    _linux_text_bytes,
)
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
    try:
        trusted = _assets()
    except BundleError as exc:
        raise SeedIsoError(f"invalid trusted guest payload: {exc}") from exc
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
    try:
        contents[_TARGET_SCRIPT] = _linux_text_bytes(data, _TARGET_SCRIPT)
    except BundleError as exc:
        raise SeedIsoError(f"invalid target installer text: {exc}") from exc
    contents["SHA256SUMS"] = "".join(
        f"{hashlib.sha256(contents[name]).hexdigest()}  {name}\n"
        for name in (*_GUEST_NAMES, _TARGET_SCRIPT)
    ).encode("ascii")
    return contents


def _install_seed_files(instance_id: str, payload: dict[str, bytes]) -> dict[str, tuple[bytes, str]]:
    """One fixed file layout shared by authoring and read-only verification."""
    seed = render_ubuntu_install_seed(instance_id)
    return {
        "user-data": (seed.user_data, "/USERDATA.;1"),
        "meta-data": (seed.meta_data, "/METADATA.;1"),
        "protocol_test_bootstrap.py": (payload["protocol_test_bootstrap.py"], "/BOOTSTRP.PY;1"),
        "night-shift-protocol-test.service": (payload["night-shift-protocol-test.service"], "/PROTUNIT.SRV;1"),
        _TARGET_SCRIPT: (payload[_TARGET_SCRIPT], "/TARGETSH.SH;1"),
        "SHA256SUMS": (payload["SHA256SUMS"], "/SHASUMS.;1"),
    }


def inspect_ubuntu_install_seed_iso(
    seed_iso: Path,
    instance_id: str,
    expected_sha256: str,
    bundle: Path,
    expected_bundle_sha256: str,
) -> ProtocolInstallSeedReport:
    """Read-only check of exact combined seed contents, never mount or run them.

    Hash the bounded byte snapshot that is parsed, and require the exact files
    in ISO9660, Rock Ridge and Joliet. The bundle must still match its reviewed
    digest and current trusted sources. This is NOT Subiquity/guest validation.
    """
    render_ubuntu_install_seed(instance_id)  # reject invalid identities first
    if not _DIGEST.fullmatch(expected_sha256):
        raise SeedIsoError("a separately reviewed seed ISO SHA-256 is required")
    media = _checked_path(seed_iso, "combined install seed ISO")
    checkout = Path(__file__).resolve().parents[1]
    if not media.is_file() or media.name != instance_id + ".iso" or checkout in media.parents:
        raise SeedIsoError("combined seed must be an external identity-named regular .iso")
    size = media.stat().st_size
    if not 17 * 2048 <= size <= _MAX_MEDIA:
        raise SeedIsoError("combined seed ISO size is outside fixed bounds")
    with media.open("rb") as stream:
        data = stream.read(_MAX_MEDIA + 1)
    if len(data) != size or media.stat().st_size != size:
        raise SeedIsoError("combined seed ISO changed size during inspection")
    digest = hashlib.sha256(data).hexdigest()
    if digest != expected_sha256.lower():
        raise SeedIsoError("combined seed ISO differs from reviewed SHA-256")
    descriptor = data[16 * 2048:16 * 2048 + 72]
    if descriptor[:7] != b"\x01CD001\x01" or descriptor[40:72].rstrip(b" ") != b"CIDATA":
        raise SeedIsoError("combined seed ISO lacks the CIDATA descriptor")
    files = _install_seed_files(instance_id, _fixed_payload(bundle, expected_bundle_sha256))
    try:
        import pycdlib  # type: ignore[import-not-found]  # pinned development dependency
        from pycdlib.pycdlibexception import PyCdlibException  # type: ignore[import-not-found]
    except ImportError as exc:
        raise SeedIsoError("pycdlib is required to inspect combined seed ISO contents") from exc
    iso = pycdlib.PyCdlib()
    opened = False
    try:
        iso.open_fp(io.BytesIO(data))
        opened = True
        if not iso.has_rock_ridge() or not iso.has_joliet() or iso.has_udf() or iso.eltorito_boot_catalog is not None:
            raise SeedIsoError("combined seed must be data-only Rock Ridge/Joliet media")
        for namespace in ("iso_path", "rr_path", "joliet_path"):
            expected = {
                iso_name[1:] if namespace == "iso_path" else name: contents
                for name, (contents, iso_name) in files.items()
            }
            seen: set[str] = set()
            for entry in iso.list_children(**{namespace: "/"}):
                if entry.is_dot() or entry.is_dotdot():
                    continue
                if entry.is_symlink() or not entry.is_file() or entry.is_associated_file():
                    raise SeedIsoError("combined seed contains a non-regular entry")
                if namespace == "rr_path":
                    if entry.rock_ridge is None:
                        raise SeedIsoError("combined seed entry lacks a Rock Ridge name")
                    name = entry.rock_ridge.name().decode("utf-8")
                else:
                    name = entry.file_identifier().decode("utf-16-be" if namespace == "joliet_path" else "ascii")
                if name not in expected or name in seen:
                    raise SeedIsoError("combined seed contains extra or duplicate entries")
                seen.add(name)
                if entry.get_data_length() != len(expected[name]):
                    raise SeedIsoError("combined seed file length differs from trusted contents")
                extracted = io.BytesIO()
                iso.get_file_from_iso_fp(extracted, **{namespace: "/" + name})
                if extracted.getvalue() != expected[name]:
                    raise SeedIsoError("combined seed file differs from trusted contents")
            if seen != set(expected):
                raise SeedIsoError("combined seed is missing required install files")
    except (PyCdlibException, UnicodeError, ValueError, OSError) as exc:
        if isinstance(exc, SeedIsoError):
            raise
        raise SeedIsoError("invalid combined install seed ISO") from exc
    finally:
        if opened:
            iso.close()
    return ProtocolInstallSeedReport(media, digest, size, expected_bundle_sha256.lower())


def build_ubuntu_install_seed_iso(
    parent: Path, instance_id: str, bundle: Path, expected_bundle_sha256: str
) -> ProtocolInstallSeedReport:
    """Write one fresh ISO with exact NoCloud data and reviewed fixed payload.

    Unlike build_ubuntu_seed_iso, this image has Subiquity late-commands AND
    their payload. Only its matching ID-named .iso can later be considered for
    attachment; this function itself never invokes Hyper-V or PowerShell.
    """
    render_ubuntu_install_seed(instance_id)  # validate identity before any output
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
    files = _install_seed_files(instance_id, _fixed_payload(source, expected_bundle_sha256))
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
