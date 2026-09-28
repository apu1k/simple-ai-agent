"""Synthetic ISO headers test input rejection; no ISO here is bootable Linux."""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import pytest

from night_shifts.protocol_image_bundle import build_protocol_image_bundle
from night_shifts.ubuntu_iso_inputs import UbuntuInputError, inspect_ubuntu_inputs, main


@pytest.fixture
def inputs(tmp_path: Path) -> tuple[Path, str, Path, str]:
    iso = tmp_path / "ubuntu-24.04-live-server-amd64.iso"
    contents = bytearray(17 * 2048)
    offset = 16 * 2048
    contents[offset : offset + 7] = b"\x01CD001\x01"
    label = b"Ubuntu-Server 24.04 LTS amd64"
    contents[offset + 40 : offset + 72] = label.ljust(32)
    iso.write_bytes(contents)
    bundle = tmp_path / "trusted-assets.zip"
    report = build_protocol_image_bundle(bundle)
    return iso, hashlib.sha256(contents).hexdigest(), bundle, report.sha256


def test_offline_inputs_are_read_only_and_not_vm_evidence(
    inputs: tuple[Path, str, Path, str], capsys: pytest.CaptureFixture[str]
) -> None:
    iso, iso_sha, bundle, bundle_sha = inputs
    report = inspect_ubuntu_inputs(iso, iso_sha.upper(), bundle, bundle_sha)
    assert report.iso_bytes == 17 * 2048
    assert report.iso_volume_label == "Ubuntu-Server 24.04 LTS amd64"
    assert main([
        "--iso", str(iso), "--iso-sha256", iso_sha,
        "--bundle", str(bundle), "--bundle-sha256", bundle_sha,
    ]) == 0
    assert "No VM/image built" in capsys.readouterr().out
    assert {file.name for file in iso.parent.iterdir()} == {iso.name, bundle.name}


@pytest.mark.parametrize("wrong", ["", "f" * 63, "z" * 64])
def test_missing_reviewed_digest_is_rejected(
    inputs: tuple[Path, str, Path, str], wrong: str
) -> None:
    iso, _, bundle, bundle_sha = inputs
    with pytest.raises(UbuntuInputError, match="SHA-256"):
        inspect_ubuntu_inputs(iso, wrong, bundle, bundle_sha)


def test_wrong_checksum_and_version_are_rejected(
    inputs: tuple[Path, str, Path, str]
) -> None:
    iso, iso_sha, bundle, bundle_sha = inputs
    with pytest.raises(UbuntuInputError, match="SHA-256"):
        inspect_ubuntu_inputs(iso, "f" * 64, bundle, bundle_sha)
    data = iso.read_bytes().replace(b"24.04", b"22.04")
    iso.write_bytes(data)
    with pytest.raises(UbuntuInputError, match="Ubuntu 24.04"):
        inspect_ubuntu_inputs(iso, hashlib.sha256(data).hexdigest(), bundle, bundle_sha)
    iso.write_bytes(data.replace(b"\x01CD001\x01", b"\x00CD001\x01"))
    new_data = iso.read_bytes()
    with pytest.raises(UbuntuInputError, match="primary volume descriptor"):
        inspect_ubuntu_inputs(iso, hashlib.sha256(new_data).hexdigest(), bundle, bundle_sha)
    assert iso_sha != hashlib.sha256(new_data).hexdigest()


def test_stale_bundle_with_its_own_matching_hash_is_rejected(
    inputs: tuple[Path, str, Path, str], tmp_path: Path
) -> None:
    iso, iso_sha, bundle, _ = inputs
    stale = tmp_path / "stale.zip"
    with zipfile.ZipFile(bundle) as source, zipfile.ZipFile(stale, "w") as dest:
        for name in source.namelist():
            value = source.read(name)
            if name == "protocol_test_bootstrap.py":
                value += b"\n# stale\n"
            dest.writestr(name, value)
    stale_sha = hashlib.sha256(stale.read_bytes()).hexdigest()
    with pytest.raises(UbuntuInputError, match="stale"):
        inspect_ubuntu_inputs(iso, iso_sha, stale, stale_sha)


def test_paths_outside_checkout_and_link_free(
    inputs: tuple[Path, str, Path, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    iso, iso_sha, bundle, bundle_sha = inputs
    with pytest.raises(ValueError, match="absolute"):
        inspect_ubuntu_inputs(Path("relative.iso"), iso_sha, bundle, bundle_sha)
    # Model a checkout rooted at tmp_path without writing a test file into
    # the real repository or bypassing the .iso/.zip filename checks.
    with monkeypatch.context() as patch:
        patch.setattr("night_shifts.ubuntu_iso_inputs.__file__", str(tmp_path / "pkg" / "module.py"))
        with pytest.raises(UbuntuInputError, match="outside the checkout"):
            inspect_ubuntu_inputs(iso, iso_sha, bundle, bundle_sha)
    link = tmp_path / "linked.iso"
    try:
        link.symlink_to(iso)
    except (OSError, NotImplementedError):
        pytest.skip("this host does not permit test symlinks")
    with pytest.raises(ValueError, match="link or reparse"):
        inspect_ubuntu_inputs(link, iso_sha, bundle, bundle_sha)
