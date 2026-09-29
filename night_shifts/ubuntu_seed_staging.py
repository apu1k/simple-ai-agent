"""Stage reviewed NoCloud *files* offline; never build media or operate a VM.

The caller supplies an image-preparation ID, not an agent job ID. The resulting
write-once directory must be reviewed and converted to/attached as seed media
by a separately authorized future step. An incomplete directory is deliberately
left for inspection instead of being silently retried or deleted.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from night_shifts.hyperv_image_preflight import _checked_path
from night_shifts.ubuntu_seed import render_ubuntu_seed


class SeedStagingError(ValueError):
    """Refuse unsafe destination or a previously used seed identity."""


@dataclass(frozen=True)
class StagedNoCloudSeed:
    """Local files and hashes only: no ISO, disk installation, or VM evidence."""

    directory: Path
    user_data_sha256: str
    meta_data_sha256: str


def _write_new(path: Path, data: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def stage_ubuntu_seed(parent: Path, instance_id: str) -> StagedNoCloudSeed:
    """Create a new external directory containing fixed NoCloud input files.

    The parent must already exist. Reusing an ID is refused even if the earlier
    attempt left only partial files. No paths come from the guest or model.
    Files are bounded by render_ubuntu_seed, and output names are fixed.
    """
    seed = render_ubuntu_seed(instance_id)  # validate before touching the filesystem
    root = _checked_path(parent, "seed staging directory")
    checkout = Path(__file__).resolve().parents[1]
    if not root.is_dir() or root == Path(root.anchor):
        raise SeedStagingError("seed staging parent must be a dedicated directory")
    if root == checkout or checkout in root.parents:
        raise SeedStagingError("seed staging parent must be outside the checkout")
    directory = root / instance_id
    # mkdir without exist_ok is the exclusive claim on this identity. Never
    # remove the directory automatically: partial files must be investigated.
    directory.mkdir(exist_ok=False)
    manifest = {
        "schema_version": 1,
        "instance_id": instance_id,
        "format": "NoCloud files only; NOT an ISO or bootable installer",
        "files": {
            "user-data": {"sha256": seed.user_data_sha256, "bytes": len(seed.user_data)},
            "meta-data": {"sha256": seed.meta_data_sha256, "bytes": len(seed.meta_data)},
        },
    }
    _write_new(directory / "user-data", seed.user_data)
    _write_new(directory / "meta-data", seed.meta_data)
    _write_new(
        directory / "manifest.json",
        (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"),
    )
    return StagedNoCloudSeed(directory, seed.user_data_sha256, seed.meta_data_sha256)
