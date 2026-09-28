"""Read-only image input checks; fixtures are NOT real or bootable VHDX files."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from night_shifts.hyperv_image_preflight import (
    ImagePreflightError,
    inspect_protocol_image,
    main,
)


@pytest.fixture
def inputs(tmp_path: Path) -> tuple[Path, str, Path, Path]:
    image = tmp_path / "images" / "protocol.vhdx"
    image.parent.mkdir()
    content = b"vhdxfile" + b"offline fixture, not a real virtual disk"
    image.write_bytes(content)
    workspace = tmp_path / "test-workspace"
    workspace.mkdir()
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    return image, hashlib.sha256(content).hexdigest(), workspace, checkout


def test_report_is_read_only_and_does_not_claim_vm_validation(
    inputs: tuple[Path, str, Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    image, digest, workspace, checkout = inputs
    before = image.read_bytes()
    report = inspect_protocol_image(image, digest.upper(), workspace, checkout_root=checkout)
    assert report.image_sha256 == digest
    assert report.image_bytes == len(before)
    assert image.read_bytes() == before
    assert list(workspace.iterdir()) == []
    # Default CLI uses the real checkout and never calls the hypervisor.
    assert main(["--image", str(image), "--sha256", digest, "--workspace", str(workspace)]) == 0
    assert "NOT verified" in capsys.readouterr().out


@pytest.mark.parametrize("invalid", ["not-a-digest", "f" * 63, "z" * 64])
def test_rejects_unpinned_image(
    inputs: tuple[Path, str, Path, Path], invalid: str
) -> None:
    image, _, workspace, checkout = inputs
    with pytest.raises(ImagePreflightError, match="SHA-256"):
        inspect_protocol_image(image, invalid, workspace, checkout_root=checkout)


def test_rejects_modified_or_non_vhdx_file(
    inputs: tuple[Path, str, Path, Path]
) -> None:
    image, digest, workspace, checkout = inputs
    image.write_bytes(b"vhdxfile" + b"changed")
    with pytest.raises(ImagePreflightError, match="does not match"):
        inspect_protocol_image(image, digest, workspace, checkout_root=checkout)
    data = b"not-a-vhdx"
    image.write_bytes(data)
    with pytest.raises(ImagePreflightError, match="signature"):
        inspect_protocol_image(
            image, hashlib.sha256(data).hexdigest(), workspace, checkout_root=checkout
        )


def test_rejects_unapproved_paths(inputs: tuple[Path, str, Path, Path]) -> None:
    image, digest, workspace, checkout = inputs
    (workspace / "existing-vm.vhdx").write_bytes(b"do not delete")
    with pytest.raises(ImagePreflightError, match="empty"):
        inspect_protocol_image(image, digest, workspace, checkout_root=checkout)
    assert (workspace / "existing-vm.vhdx").exists()
    (workspace / "existing-vm.vhdx").unlink()
    with pytest.raises(ImagePreflightError, match="absolute"):
        inspect_protocol_image(Path("relative.vhdx"), digest, workspace, checkout_root=checkout)
    in_checkout = checkout / "image.vhdx"
    in_checkout.write_bytes(image.read_bytes())
    with pytest.raises(ImagePreflightError, match="outside the checkout"):
        inspect_protocol_image(in_checkout, digest, workspace, checkout_root=checkout)
    with pytest.raises(ImagePreflightError, match="outside the checkout"):
        inspect_protocol_image(image, digest, checkout, checkout_root=checkout)
    in_workspace = workspace / "protocol.vhdx"
    in_workspace.write_bytes(image.read_bytes())
    with pytest.raises(ImagePreflightError, match="inside the disposable workspace"):
        inspect_protocol_image(in_workspace, digest, workspace, checkout_root=checkout)


def test_rejects_link_component(inputs: tuple[Path, str, Path, Path], tmp_path: Path) -> None:
    image, digest, workspace, checkout = inputs
    link = tmp_path / "linked-workspace"
    try:
        link.symlink_to(workspace, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("this host does not permit test symlinks")
    with pytest.raises(ImagePreflightError, match="link or reparse"):
        inspect_protocol_image(image, digest, link, checkout_root=checkout)


def test_rejects_insufficient_space_and_invalid_limit(
    inputs: tuple[Path, str, Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    image, digest, workspace, checkout = inputs
    monkeypatch.setattr(
        "night_shifts.hyperv_image_preflight.shutil.disk_usage",
        lambda _: SimpleNamespace(free=1024),
    )
    with pytest.raises(ImagePreflightError, match="free space"):
        inspect_protocol_image(image, digest, workspace, checkout_root=checkout)
    for invalid in (0, -1, 1025, True, 1.5):
        with pytest.raises(ImagePreflightError, match="disk_gb"):
            inspect_protocol_image(
                image, digest, workspace, disk_gb=invalid, checkout_root=checkout
            )
