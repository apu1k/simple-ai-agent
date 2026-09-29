"""Real offline pycdlib extraction checks; no Ubuntu/Hyper-V launch."""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pytest
import yaml

from night_shifts.protocol_image_bundle import build_protocol_image_bundle
from night_shifts.ubuntu_install_seed_iso import build_ubuntu_install_seed_iso
from night_shifts.ubuntu_seed_iso import SeedIsoError

_ID = "night-shift-image-prep-" + "f" * 32
_FILES = {
    "user-data", "meta-data", "protocol_test_bootstrap.py",
    "night-shift-protocol-test.service", "install_protocol_test_target.sh", "SHA256SUMS",
}


def _bundle(tmp_path: Path) -> tuple[Path, str]:
    bundle = tmp_path / "protocol-bundle.zip"
    return bundle, build_protocol_image_bundle(bundle).sha256


def test_combined_seed_contains_exact_fixed_payload_and_late_command(tmp_path: Path) -> None:
    pycdlib = pytest.importorskip("pycdlib")
    bundle, bundle_hash = _bundle(tmp_path)
    output_dir = tmp_path / "media"
    output_dir.mkdir()
    report = build_ubuntu_install_seed_iso(output_dir, _ID, bundle, bundle_hash)
    assert report.path == output_dir / (_ID + ".iso")
    assert report.sha256 == hashlib.sha256(report.path.read_bytes()).hexdigest()
    assert report.bundle_sha256 == bundle_hash
    assert 0 < report.size_bytes <= 2 * 1024 * 1024
    with report.path.open("rb") as stream:
        stream.seek(16 * 2048)
        descriptor = stream.read(72)
    assert descriptor[:7] == b"\x01CD001\x01"
    assert descriptor[40:72].rstrip(b" ") == b"CIDATA"
    iso = pycdlib.PyCdlib()
    iso.open(str(report.path))
    try:
        contents = {}
        for name in _FILES:
            extracted = io.BytesIO()
            iso.get_file_from_iso_fp(extracted, rr_path="/" + name)
            contents[name] = extracted.getvalue()
            joliet = io.BytesIO()
            iso.get_file_from_iso_fp(joliet, joliet_path="/" + name)
            assert joliet.getvalue() == contents[name]
        config = yaml.safe_load(contents["user-data"])["autoinstall"]
        assert "late-commands" in config
        assert "identity" not in config
        assert "sh ./install_protocol_test_target.sh" in config["late-commands"][0][2]
        sums = contents["SHA256SUMS"].decode("ascii").splitlines()
        assert {line.split("  ")[1] for line in sums} == _FILES - {"user-data", "meta-data", "SHA256SUMS"}
        for line in sums:
            digest, filename = line.split("  ")
            assert hashlib.sha256(contents[filename]).hexdigest() == digest
        for name in _FILES - {"user-data", "meta-data", "SHA256SUMS"}:
            trusted = Path(__file__).resolve().parents[2] / "night_shifts" / "guest" / name
            assert contents[name] == trusted.read_bytes()
    finally:
        iso.close()
    with pytest.raises(SeedIsoError, match="already exists"):
        build_ubuntu_install_seed_iso(output_dir, _ID, bundle, bundle_hash)


def test_rejects_stale_bundle_before_media_creation(tmp_path: Path) -> None:
    bundle, bundle_hash = _bundle(tmp_path)
    output_dir = tmp_path / "media"
    output_dir.mkdir()
    bundle.write_bytes(bundle.read_bytes() + b"tampered")
    with pytest.raises(SeedIsoError, match="reviewed SHA-256"):
        build_ubuntu_install_seed_iso(output_dir, _ID, bundle, bundle_hash)
    assert not list(output_dir.iterdir())


def test_rejects_invalid_id_before_media_creation(tmp_path: Path) -> None:
    bundle, bundle_hash = _bundle(tmp_path)
    output_dir = tmp_path / "media"
    output_dir.mkdir()
    with pytest.raises(ValueError, match="instance_id"):
        build_ubuntu_install_seed_iso(output_dir, "untrusted", bundle, bundle_hash)
    assert not list(output_dir.iterdir())


def test_rejects_checkout_or_existing_output(tmp_path: Path) -> None:
    bundle, bundle_hash = _bundle(tmp_path)
    checkout = Path(__file__).resolve().parents[2]
    with pytest.raises(SeedIsoError, match="outside checkout"):
        build_ubuntu_install_seed_iso(checkout, _ID, bundle, bundle_hash)
    output_dir = tmp_path / "media"
    output_dir.mkdir()
    existing = output_dir / (_ID + ".iso")
    existing.write_bytes(b"never overwrite")
    with pytest.raises(SeedIsoError, match="already exists"):
        build_ubuntu_install_seed_iso(output_dir, _ID, bundle, bundle_hash)
    assert existing.read_bytes() == b"never overwrite"
