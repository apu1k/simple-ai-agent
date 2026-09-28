"""Package fixed guest protocol-test assets; never build or launch a VM.

A trusted operator transfers the resulting archive to a *separate* Linux
image-preparation guest after independently reviewing its SHA-256 and source.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

_ASSET_NAMES = (
    "protocol_test_bootstrap.py",
    "night-shift-protocol-test.service",
    "install_protocol_test.sh",
)
_MAX_ASSET_BYTES = 1024 * 1024


class BundleError(ValueError):
    """A guest asset or operator-selected output location is unsuitable."""


@dataclass(frozen=True)
class BundleReport:
    """The digest of an offline archive, not a validated VM image."""

    sha256: str
    size_bytes: int


def _check_existing_path(path: Path) -> Path:
    if not path.is_absolute():
        raise BundleError("output path must be absolute")
    for component in (path, *path.parents):
        info = component.lstat()
        if stat.S_ISLNK(info.st_mode) or (
            info.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT
            if hasattr(info, "st_file_attributes")
            else False
        ):
            raise BundleError("output path contains a link or reparse point")
    return path.resolve(strict=True)


def _zip_entry(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    info.compress_type = zipfile.ZIP_STORED
    return info


def _assets() -> dict[str, bytes]:
    guest_dir = Path(__file__).resolve().parent / "guest"
    result: dict[str, bytes] = {}
    for name in _ASSET_NAMES:
        path = guest_dir / name
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > _MAX_ASSET_BYTES:
            raise BundleError(f"guest asset is not a bounded regular file: {name}")
        with path.open("rb") as stream:
            data = stream.read(_MAX_ASSET_BYTES + 1)
        if len(data) > _MAX_ASSET_BYTES or path.stat().st_size != len(data):
            raise BundleError(f"guest asset changed or exceeds limit: {name}")
        result[name] = data
    return result


def build_protocol_image_bundle(output: Path) -> BundleReport:
    """Write once to a new external path, with deterministic contents and hashes.

    Only repository-owned asset filenames are admitted. The archive contains
    no OS disk, secrets, provider config, arbitrary host directory or repo
    checkout. Its shell installer requires an explicit action inside a guest.
    """
    if output.suffix.lower() != ".zip" or not output.is_absolute():
        raise BundleError("output must be an absolute .zip path")
    parent = _check_existing_path(output.parent)
    checkout = Path(__file__).resolve().parents[1]
    if parent == checkout or checkout in parent.parents:
        raise BundleError("output must be outside the repository checkout")
    if not parent.is_dir():
        raise BundleError("output parent must be an existing directory")
    if output.exists() or output.is_symlink():
        raise BundleError("output exists; bundles are write-once")
    assets = _assets()
    digests = {name: hashlib.sha256(data).hexdigest() for name, data in assets.items()}
    sums = "".join(f"{digests[name]}  {name}\n" for name in _ASSET_NAMES).encode("ascii")
    manifest = (
        json.dumps(
            {
                "schema_version": 1,
                "purpose": "offline Hyper-V protocol-test guest installation assets",
                "files": {
                    name: {"sha256": digests[name], "bytes": len(assets[name])}
                    for name in _ASSET_NAMES
                },
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    fd, temporary = tempfile.mkstemp(prefix=".night-shift-bundle-", dir=parent)
    try:
        with os.fdopen(fd, "w+b") as stream:
            with zipfile.ZipFile(stream, mode="w") as archive:
                for name in _ASSET_NAMES:
                    archive.writestr(_zip_entry(name), assets[name])
                archive.writestr(_zip_entry("SHA256SUMS"), sums)
                archive.writestr(_zip_entry("manifest.json"), manifest)
            stream.flush()
            os.fsync(stream.fileno())
        # Atomic hard link refuses to replace an existing file, even if a
        # different process races us after the initial existence check.
        os.link(temporary, output)
        result = Path(temporary).read_bytes()
        return BundleReport(hashlib.sha256(result).hexdigest(), len(result))
    finally:
        Path(temporary).unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    """Opt-in offline package operation; never invoke the shell installer."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        report = build_protocol_image_bundle(args.output)
    except (BundleError, OSError) as exc:
        parser.exit(2, f"bundle BLOCKED: {exc}\n")
    print(f"Offline guest bundle SHA-256: {report.sha256}; bytes: {report.size_bytes}")
    print("No Linux image built or reviewed; no VM launched. Guest installation and real-host tests require separate approval.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
