"""Real offline pycdlib extraction checks; no Ubuntu/Hyper-V launch."""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pytest
import yaml

from night_shifts.protocol_image_bundle import build_protocol_image_bundle
from night_shifts.ubuntu_install_seed_iso import (
    build_ubuntu_install_seed_iso,
    inspect_ubuntu_install_seed_iso,
)
from night_shifts.ubuntu_seed import render_ubuntu_install_seed
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
    before = report.path.read_bytes()
    inspected = inspect_ubuntu_install_seed_iso(report.path, _ID, report.sha256, bundle, bundle_hash)
    assert inspected == report
    assert report.path.read_bytes() == before
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


def _untrusted_candidate(path: Path, variant: str) -> str:
    """Author test-only media; a fresh self-hash must NOT bypass content checks."""
    pycdlib = pytest.importorskip("pycdlib")
    if variant == "malformed":
        data = bytearray(17 * 2048)
        data[16 * 2048:16 * 2048 + 7] = b"\x01CD001\x01"
        data[16 * 2048 + 40:16 * 2048 + 72] = b"CIDATA".ljust(32)
        path.write_bytes(data)
        return hashlib.sha256(data).hexdigest()
    seed = render_ubuntu_install_seed(_ID)
    guest = Path(__file__).resolve().parents[2] / "night_shifts" / "guest"
    payload_names = (
        "protocol_test_bootstrap.py", "night-shift-protocol-test.service", "install_protocol_test_target.sh",
    )
    contents = {name: (guest / name).read_bytes() for name in payload_names}
    contents["SHA256SUMS"] = "".join(
        f"{hashlib.sha256(contents[name]).hexdigest()}  {name}\n" for name in payload_names
    ).encode("ascii")
    contents.update({"user-data": seed.user_data, "meta-data": seed.meta_data})
    iso_names = {
        "user-data": "/USERDATA.;1", "meta-data": "/METADATA.;1",
        "protocol_test_bootstrap.py": "/BOOTSTRP.PY;1",
        "night-shift-protocol-test.service": "/PROTUNIT.SRV;1",
        "install_protocol_test_target.sh": "/TARGETSH.SH;1", "SHA256SUMS": "/SHASUMS.;1",
    }
    if variant == "missing":
        del contents["install_protocol_test_target.sh"]
    elif variant == "config":
        contents["user-data"] += b"\n"
    elif variant == "instance":
        contents["meta-data"] = render_ubuntu_install_seed("night-shift-image-prep-" + "a" * 32).meta_data
    elif variant == "bootstrap":
        original = contents["protocol_test_bootstrap.py"]
        contents["protocol_test_bootstrap.py"] = b"!" + original[1:]
    elif variant == "checksums":
        contents["SHA256SUMS"] = b"!" + contents["SHA256SUMS"][1:]
    iso = pycdlib.PyCdlib()
    rr = variant != "no-rr"
    joliet = variant != "no-joliet"
    iso.new(vol_ident="CIDATA", rock_ridge="1.09" if rr else None, joliet=3 if joliet else None)
    try:
        for name, data in contents.items():
            rr_name = "unexpected" if variant == "rr-name" and name == "user-data" else name
            joliet_name = "unexpected" if variant == "joliet-name" and name == "user-data" else name
            iso.add_fp(
                io.BytesIO(data), len(data), iso_path=iso_names[name],
                rr_name=rr_name if rr else None, joliet_path="/" + joliet_name if joliet else None,
            )
        if variant == "extra-file":
            iso.add_fp(io.BytesIO(b"extra"), 5, iso_path="/EXTRA.;1", rr_name="extra", joliet_path="/extra")
        elif variant == "extra-directory":
            iso.add_directory(iso_path="/EXTRA", rr_name="extra", joliet_path="/extra")
        elif variant == "symlink":
            iso.add_symlink(symlink_path="/LINK.;1", rr_symlink_name="link", rr_path="/user-data", joliet_path="/link")
        iso.write(str(path))
    finally:
        iso.close()
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("variant", [
    "missing", "extra-file", "extra-directory", "symlink", "config", "instance",
    "bootstrap", "checksums", "rr-name", "joliet-name", "no-rr", "no-joliet", "malformed",
])
def test_inspection_rejects_untrusted_contents_even_with_matching_hash(tmp_path: Path, variant: str) -> None:
    bundle, bundle_hash = _bundle(tmp_path)
    media = tmp_path / (_ID + ".iso")
    digest = _untrusted_candidate(media, variant)
    before = media.read_bytes()
    with pytest.raises(SeedIsoError):
        inspect_ubuntu_install_seed_iso(media, _ID, digest, bundle, bundle_hash)
    assert media.read_bytes() == before
    assert {entry.name for entry in tmp_path.iterdir()} == {media.name, bundle.name}


def test_inspection_rejects_wrong_hash_or_changed_bound_bundle(tmp_path: Path) -> None:
    pytest.importorskip("pycdlib")
    bundle, bundle_hash = _bundle(tmp_path)
    output_dir = tmp_path / "media"
    output_dir.mkdir()
    media = build_ubuntu_install_seed_iso(output_dir, _ID, bundle, bundle_hash)
    with pytest.raises(SeedIsoError, match="seed ISO differs from reviewed SHA-256"):
        inspect_ubuntu_install_seed_iso(media.path, _ID, "0" * 64, bundle, bundle_hash)
    bundle.write_bytes(bundle.read_bytes() + b"altered")
    with pytest.raises(SeedIsoError, match="bundle differs from reviewed SHA-256"):
        inspect_ubuntu_install_seed_iso(media.path, _ID, media.sha256, bundle, bundle_hash)


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
