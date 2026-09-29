"""Offline-only write-once NoCloud file staging; never builds ISO/VM."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from night_shifts.ubuntu_seed import render_ubuntu_seed
from night_shifts.ubuntu_seed_staging import SeedStagingError, stage_ubuntu_seed

_ID = "night-shift-image-prep-" + "b" * 32


def test_stages_exact_reviewable_files_and_hashes(tmp_path: Path) -> None:
    parent = tmp_path / "staging"
    parent.mkdir()
    record = stage_ubuntu_seed(parent, _ID)
    expected = render_ubuntu_seed(_ID)
    assert record.directory == parent / _ID
    assert sorted(p.name for p in record.directory.iterdir()) == [
        "manifest.json", "meta-data", "user-data",
    ]
    assert (record.directory / "user-data").read_bytes() == expected.user_data
    assert (record.directory / "meta-data").read_bytes() == expected.meta_data
    manifest = json.loads((record.directory / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["instance_id"] == _ID
    assert manifest["files"] == {
        "user-data": {"sha256": record.user_data_sha256, "bytes": len(expected.user_data)},
        "meta-data": {"sha256": record.meta_data_sha256, "bytes": len(expected.meta_data)},
    }
    for name in ("user-data", "meta-data"):
        assert hashlib.sha256((record.directory / name).read_bytes()).hexdigest() == manifest["files"][name]["sha256"]
    assert not any(p.suffix == ".iso" for p in record.directory.iterdir())


def test_existing_identity_or_partial_attempt_never_overwritten(tmp_path: Path) -> None:
    parent = tmp_path / "staging"
    parent.mkdir()
    previous = parent / _ID
    previous.mkdir()
    sentinel = previous / "user-data"
    sentinel.write_bytes(b"untouched")
    with pytest.raises(FileExistsError):
        stage_ubuntu_seed(parent, _ID)
    assert sentinel.read_bytes() == b"untouched"
    assert list(previous.iterdir()) == [sentinel]


@pytest.mark.parametrize("id_value", ["bad", "night-shift-image-prep-" + "A" * 32])
def test_bad_identity_does_not_touch_staging_parent(tmp_path: Path, id_value: str) -> None:
    parent = tmp_path / "staging"
    parent.mkdir()
    with pytest.raises(ValueError, match="instance_id"):
        stage_ubuntu_seed(parent, id_value)
    assert not list(parent.iterdir())


def test_refuses_checkout_as_destination_before_writing() -> None:
    checkout = Path(__file__).resolve().parents[2]
    with pytest.raises(SeedStagingError, match="checkout"):
        stage_ubuntu_seed(checkout, _ID)


def test_refuses_linked_parent(tmp_path: Path) -> None:
    parent = tmp_path / "staging"
    parent.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(parent, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlinks unavailable on this host")
    with pytest.raises(ValueError, match="link or reparse"):
        stage_ubuntu_seed(link, _ID)
    assert not list(parent.iterdir())
