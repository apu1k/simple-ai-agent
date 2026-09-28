"""Offline guest-asset packaging; never install Linux or invoke Hyper-V."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from night_shifts.protocol_image_bundle import (
    BundleError,
    build_protocol_image_bundle,
    main,
)

_ASSETS = (
    "protocol_test_bootstrap.py",
    "night-shift-protocol-test.service",
    "install_protocol_test.sh",
)


def test_bundle_is_deterministic_and_contains_only_reviewed_assets(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    first, second = tmp_path / "one.zip", tmp_path / "two.zip"
    report = build_protocol_image_bundle(first)
    assert main(["--output", str(second)]) == 0
    assert "No Linux image built" in capsys.readouterr().out
    assert first.read_bytes() == second.read_bytes()
    assert report.sha256 == hashlib.sha256(first.read_bytes()).hexdigest()
    with zipfile.ZipFile(first) as archive:
        assert archive.namelist() == [*_ASSETS, "SHA256SUMS", "manifest.json"]
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["schema_version"] == 1
        sums = archive.read("SHA256SUMS").decode("ascii")
        for name in _ASSETS:
            content = archive.read(name)
            digest = hashlib.sha256(content).hexdigest()
            assert manifest["files"][name] == {"sha256": digest, "bytes": len(content)}
            assert f"{digest}  {name}\n" in sums
            assert archive.getinfo(name).file_size < 1024 * 1024
        installer = archive.read("install_protocol_test.sh")
        assert b"sha256sum -c -- SHA256SUMS" in installer
        assert b"systemctl enable night-shift-protocol-test.service" in installer
        assert b"systemctl mask --now serial-getty@ttyS0.service" in installer
        assert all("/" not in name and "\\" not in name for name in archive.namelist())
        assert all(not name.endswith(".vhdx") for name in archive.namelist())


def test_rejects_overwrite_and_checkout_target(tmp_path: Path) -> None:
    output = tmp_path / "bundle.zip"
    output.write_bytes(b"do not overwrite")
    with pytest.raises(BundleError, match="write-once"):
        build_protocol_image_bundle(output)
    assert output.read_bytes() == b"do not overwrite"
    with pytest.raises(BundleError, match="absolute"):
        build_protocol_image_bundle(Path("relative.zip"))
    with pytest.raises(BundleError, match="outside the repository"):
        build_protocol_image_bundle(
            Path(__file__).resolve().parents[2] / "do-not-write.zip"
        )


def test_rejects_linked_parent(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    try:
        linked.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("this host does not permit test symlinks")
    with pytest.raises(BundleError, match="link or reparse"):
        build_protocol_image_bundle(linked / "bundle.zip")
    assert not (real / "bundle.zip").exists()


def test_failure_removes_partial_temp_but_not_unrelated_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    keep = tmp_path / "existing.txt"
    keep.write_bytes(b"keep")

    def fail_link(_source: str, _destination: Path) -> None:
        raise OSError("link unavailable")

    monkeypatch.setattr("night_shifts.protocol_image_bundle.os.link", fail_link)
    with pytest.raises(OSError, match="link unavailable"):
        build_protocol_image_bundle(tmp_path / "bundle.zip")
    assert [entry.name for entry in tmp_path.iterdir()] == ["existing.txt"]
    assert keep.read_bytes() == b"keep"
