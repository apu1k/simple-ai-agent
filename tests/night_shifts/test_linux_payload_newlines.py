"""Windows checkout newlines must never become Linux guest payload bytes.

All authoring is in temporary fixture directories; no guest execution, live
assets, Hyper-V actions or failed-image repair are involved.
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest

from night_shifts import protocol_image_bundle as bundle_module
from night_shifts import ubuntu_install_seed_iso as seed_module
from night_shifts.ubuntu_seed_iso import SeedIsoError

_ID = "night-shift-image-prep-" + "e" * 32
_NAMES = (*bundle_module._ASSET_NAMES, seed_module._TARGET_SCRIPT)


def _sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, newline: str,
) -> tuple[Path, dict[str, bytes]]:
    real = Path(bundle_module.__file__).resolve().parent / "guest"
    canonical = {name: (real / name).read_bytes().replace(b"\r\n", b"\n") for name in _NAMES}
    guest = tmp_path / "checkout" / "night_shifts" / "guest"
    guest.mkdir(parents=True)
    for name, data in canonical.items():
        if newline == "crlf":
            data = data.replace(b"\n", b"\r\n")
        elif newline == "mixed":
            data = data.replace(b"\n", b"\r\n", 1)
        (guest / name).write_bytes(data)
    monkeypatch.setattr(bundle_module, "__file__", str(guest.parent / "protocol_image_bundle.py"))
    monkeypatch.setattr(seed_module, "__file__", str(guest.parent / "ubuntu_install_seed_iso.py"))
    return guest, canonical


def _iso_files(path: Path) -> dict[str, bytes]:
    pycdlib = pytest.importorskip("pycdlib")
    iso = pycdlib.PyCdlib()
    iso.open(str(path))
    try:
        names = (*seed_module._GUEST_NAMES, seed_module._TARGET_SCRIPT, "SHA256SUMS", "user-data", "meta-data")
        result = {}
        for name in names:
            out = io.BytesIO()
            iso.get_file_from_iso_fp(out, rr_path="/" + name)
            result[name] = out.getvalue()
        return result
    finally:
        iso.close()


@pytest.mark.parametrize("newline", ["lf", "crlf", "mixed"])
def test_packaged_zip_and_iso_are_lf_only_without_editing_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, newline: str,
) -> None:
    pytest.importorskip("pycdlib")
    guest, canonical = _sources(tmp_path, monkeypatch, newline)
    before = {name: (guest / name).read_bytes() for name in _NAMES}
    output = tmp_path / "output"
    output.mkdir()
    bundle = output / "bundle.zip"
    report = bundle_module.build_protocol_image_bundle(bundle)
    with zipfile.ZipFile(bundle) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        sums = archive.read("SHA256SUMS").decode("ascii")
        for name in bundle_module._ASSET_NAMES:
            data = archive.read(name)
            assert data == canonical[name]
            assert b"\r" not in data
            digest = hashlib.sha256(data).hexdigest()
            assert manifest["files"][name] == {"sha256": digest, "bytes": len(data)}
            assert f"{digest}  {name}\n" in sums
    media = seed_module.build_ubuntu_install_seed_iso(output, _ID, bundle, report.sha256)
    assert seed_module.inspect_ubuntu_install_seed_iso(
        media.path, _ID, media.sha256, bundle, report.sha256,
    ) == media
    contents = _iso_files(media.path)
    assert all(b"\r" not in data for data in contents.values())
    for name in (*seed_module._GUEST_NAMES, seed_module._TARGET_SCRIPT):
        assert contents[name] == canonical[name]
    assert b"set -eu\n" in contents[seed_module._TARGET_SCRIPT]
    for line in contents["SHA256SUMS"].decode("ascii").splitlines():
        digest, name = line.split("  ")
        assert hashlib.sha256(contents[name]).hexdigest() == digest
    assert {name: (guest / name).read_bytes() for name in _NAMES} == before


def test_checkout_newline_change_preserves_bundle_and_seed_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("pycdlib")
    guest, canonical = _sources(tmp_path, monkeypatch, "crlf")
    output = tmp_path / "output"
    output.mkdir()
    first = output / "crlf.zip"
    first_report = bundle_module.build_protocol_image_bundle(first)
    media = seed_module.build_ubuntu_install_seed_iso(output, _ID, first, first_report.sha256)
    contents = _iso_files(media.path)
    for name, data in canonical.items():
        (guest / name).write_bytes(data)
    second = output / "lf.zip"
    second_report = bundle_module.build_protocol_image_bundle(second)
    assert first.read_bytes() == second.read_bytes()
    assert first_report == second_report
    # The SAME media still verifies after a checkout newline change.
    assert seed_module.inspect_ubuntu_install_seed_iso(
        media.path, _ID, media.sha256, second, second_report.sha256,
    ) == media
    assert _iso_files(media.path) == contents


@pytest.mark.parametrize("name", _NAMES)
@pytest.mark.parametrize("invalid", [b"\r", b"\xff", b"\x00", b"\xef\xbb\xbf"])
def test_invalid_text_refused_before_output_without_source_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str, invalid: bytes,
) -> None:
    guest, canonical = _sources(tmp_path, monkeypatch, "lf")
    path = guest / name
    bad = invalid + canonical[name] if invalid == b"\xef\xbb\xbf" else canonical[name] + invalid
    path.write_bytes(bad)
    output = tmp_path / "output"
    output.mkdir()
    bundle = output / "bundle.zip"
    if name in bundle_module._ASSET_NAMES:
        with pytest.raises(bundle_module.BundleError, match="UTF-8|BOM, lone CR or NUL"):
            bundle_module.build_protocol_image_bundle(bundle)
        assert not list(output.iterdir())
    else:
        report = bundle_module.build_protocol_image_bundle(bundle)
        with pytest.raises(SeedIsoError, match="invalid target installer text"):
            seed_module.build_ubuntu_install_seed_iso(output, _ID, bundle, report.sha256)
        assert {entry.name for entry in output.iterdir()} == {"bundle.zip"}
    assert path.read_bytes() == bad


def test_self_consistent_crlf_bundle_is_stale_even_with_correct_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, canonical = _sources(tmp_path, monkeypatch, "lf")
    output = tmp_path / "output"
    output.mkdir()
    legacy = output / "legacy.zip"
    raw = {name: canonical[name].replace(b"\n", b"\r\n") for name in bundle_module._ASSET_NAMES}
    manifest = {
        "schema_version": 1,
        "purpose": "offline Hyper-V protocol-test guest installation assets",
        "files": {
            name: {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
            for name, data in raw.items()
        },
    }
    sums = "".join(f"{hashlib.sha256(data).hexdigest()}  {name}\n" for name, data in raw.items())
    with zipfile.ZipFile(legacy, "w") as archive:
        for name, data in raw.items():
            archive.writestr(name, data)
        archive.writestr("SHA256SUMS", sums.encode("ascii"))
        archive.writestr("manifest.json", json.dumps(manifest).encode("utf-8"))
    before = legacy.read_bytes()
    digest = hashlib.sha256(before).hexdigest()
    with pytest.raises(SeedIsoError, match="invalid guest bundle|stale relative"):
        seed_module.build_ubuntu_install_seed_iso(output, _ID, legacy, digest)
    assert legacy.read_bytes() == before
    assert {entry.name for entry in output.iterdir()} == {"legacy.zip"}
