"""Offline-only seed ISO checks; no installer, guest, or Hyper-V tests."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from night_shifts.ubuntu_seed import render_ubuntu_seed
from night_shifts.ubuntu_seed_iso import SeedIsoError, build_ubuntu_seed_iso
from night_shifts.ubuntu_seed_staging import stage_ubuntu_seed

_ID = "night-shift-image-prep-" + "c" * 32


def _staged(tmp_path: Path) -> Path:
    parent = tmp_path / "staging"
    parent.mkdir()
    return stage_ubuntu_seed(parent, _ID).directory


def test_refuses_changed_data_before_build(tmp_path: Path) -> None:
    directory = _staged(tmp_path)
    (directory / "user-data").write_bytes(b"#cloud-config\nsecret: yes\n")
    with pytest.raises(SeedIsoError, match="seed file"):
        build_ubuntu_seed_iso(directory)
    assert not (directory.parent / (_ID + ".iso")).exists()


def test_refuses_changed_manifest_and_extra_files(tmp_path: Path) -> None:
    directory = _staged(tmp_path)
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["instance_id"] = "some-other-image"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(SeedIsoError, match="manifest differs"):
        build_ubuntu_seed_iso(directory)
    (directory / "secret.txt").write_text("never included", encoding="utf-8")
    with pytest.raises(SeedIsoError, match="extra files"):
        build_ubuntu_seed_iso(directory)


def test_refuses_existing_output_without_replacing(tmp_path: Path) -> None:
    directory = _staged(tmp_path)
    output = directory.parent / (_ID + ".iso")
    output.write_bytes(b"keep this media")
    with pytest.raises(SeedIsoError, match="already exists"):
        build_ubuntu_seed_iso(directory)
    assert output.read_bytes() == b"keep this media"


def test_real_seed_iso_has_cidata_and_exact_nocloud_paths(tmp_path: Path) -> None:
    pycdlib = pytest.importorskip("pycdlib", reason="optional pinned seed ISO builder not installed")
    directory = _staged(tmp_path)
    report = build_ubuntu_seed_iso(directory)
    data = report.path.read_bytes()
    assert report.path.name == _ID + ".iso"
    assert report.size_bytes == len(data) <= 1024 * 1024
    assert data[16 * 2048 : 16 * 2048 + 7] == b"\x01CD001\x01"
    assert data[16 * 2048 + 40 : 16 * 2048 + 72].rstrip(b" ") == b"CIDATA"
    iso = pycdlib.PyCdlib()
    iso.open(str(report.path))
    try:
        for name, content in (
            ("user-data", render_ubuntu_seed(_ID).user_data),
            ("meta-data", render_ubuntu_seed(_ID).meta_data),
        ):
            for path_kind in ("joliet_path", "rr_path"):
                extracted = io.BytesIO()
                iso.get_file_from_iso_fp(extracted, **{path_kind: "/" + name})
                assert extracted.getvalue() == content
    finally:
        iso.close()
    with pytest.raises(SeedIsoError, match="already exists"):
        build_ubuntu_seed_iso(directory)
    assert report.path.read_bytes() == data
