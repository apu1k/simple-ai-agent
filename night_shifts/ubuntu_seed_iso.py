"""Build a bounded NoCloud seed ISO offline, never attach media or run Hyper-V.

Requires the pinned optional development dependency pycdlib. Inputs must be
exactly the trusted staged files for an image-preparation identity. The ISO
contains only user-data and meta-data, not guest installers or host files.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path

from night_shifts.hyperv_image_preflight import _checked_path
from night_shifts.ubuntu_seed import render_ubuntu_seed


class SeedIsoError(ValueError):
    """Untrusted, incomplete, or already-used offline seed ISO input."""


@dataclass(frozen=True)
class SeedIsoReport:
    """A local media digest, not an installed or booted Ubuntu image."""

    path: Path
    sha256: str
    size_bytes: int


def _read_exact_file(path: Path, expected: bytes) -> None:
    checked = _checked_path(path, "seed input")
    info = checked.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_size != len(expected):
        raise SeedIsoError(f"seed file is not the expected bounded regular file: {path.name}")
    with checked.open("rb") as stream:
        if stream.read(len(expected) + 1) != expected:
            raise SeedIsoError(f"seed file differs from trusted renderer: {path.name}")


def build_ubuntu_seed_iso(directory: Path) -> SeedIsoReport:
    """Create a fresh sibling .iso from the fixed NoCloud seed for one VM ID.

    The output is exclusively claimed with a hard link, so a concurrent or
    pre-existing output is never replaced. On failure the temporary ISO is
    removed; any staged seed input remains untouched for investigation.
    """
    stage = _checked_path(directory, "staged seed directory")
    checkout = Path(__file__).resolve().parents[1]
    if not stage.is_dir() or stage == Path(stage.anchor) or stage == checkout or checkout in stage.parents:
        raise SeedIsoError("seed directory must be an external, non-root directory")
    seed = render_ubuntu_seed(stage.name)  # checks exact generated identity
    if {entry.name for entry in stage.iterdir()} != {"user-data", "meta-data", "manifest.json"}:
        raise SeedIsoError("staged seed has missing or extra files")
    _read_exact_file(stage / "user-data", seed.user_data)
    _read_exact_file(stage / "meta-data", seed.meta_data)
    expected_manifest = {
        "schema_version": 1,
        "instance_id": stage.name,
        "format": "NoCloud files only; NOT an ISO or bootable installer",
        "files": {
            "user-data": {"sha256": seed.user_data_sha256, "bytes": len(seed.user_data)},
            "meta-data": {"sha256": seed.meta_data_sha256, "bytes": len(seed.meta_data)},
        },
    }
    manifest_path = stage / "manifest.json"
    manifest_checked = _checked_path(manifest_path, "seed manifest")
    if not stat.S_ISREG(manifest_checked.stat().st_mode) or manifest_checked.stat().st_size > 2048:
        raise SeedIsoError("seed manifest is not a bounded regular file")
    try:
        with manifest_checked.open("rb") as stream:
            manifest = json.loads(stream.read(2049))
    except (ValueError, UnicodeError) as exc:
        raise SeedIsoError("invalid staged seed manifest") from exc
    if manifest != expected_manifest:
        raise SeedIsoError("seed manifest differs from trusted renderer")
    output = stage.with_name(stage.name + ".iso")
    if output.exists() or output.is_symlink():
        raise SeedIsoError("seed ISO already exists; never overwrite reviewed media")
    try:
        import pycdlib  # type: ignore[import-not-found]  # pinned development-only dependency
    except ImportError as exc:
        raise SeedIsoError("pycdlib is required to author a seed ISO; no ISO was written") from exc

    iso = pycdlib.PyCdlib()
    iso.new(vol_ident="CIDATA", rock_ridge="1.09", joliet=3)
    try:
        # ISO9660 names fit 8.3; Rock Ridge and Joliet expose exact NoCloud
        # filenames to Linux. The media is data-only and has no boot catalog.
        for name, data, iso_name in (
            ("user-data", seed.user_data, "/USERDATA.;1"),
            ("meta-data", seed.meta_data, "/METADATA.;1"),
        ):
            iso.add_fp(
                io.BytesIO(data), len(data), iso_path=iso_name,
                rr_name=name, joliet_path="/" + name,
            )
        fd, temporary = tempfile.mkstemp(prefix=".night-shift-seed-", dir=stage.parent)
        os.close(fd)
        try:
            iso.write(temporary)
            # Windows FlushFileBuffers requires a write-capable handle.
            with open(temporary, "r+b") as stream:
                os.fsync(stream.fileno())
                hasher = hashlib.sha256()
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    hasher.update(chunk)
                size = stream.tell()
            if not 0 < size <= 1024 * 1024:
                raise SeedIsoError("seed ISO exceeds its 1 MiB media bound")
            os.link(temporary, output)  # atomic no-replace claim (also on Windows NTFS)
            return SeedIsoReport(output, hasher.hexdigest(), size)
        finally:
            Path(temporary).unlink(missing_ok=True)
    finally:
        iso.close()
