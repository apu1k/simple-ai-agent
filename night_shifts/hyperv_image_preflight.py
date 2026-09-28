"""Read-only operator preflight for the fixed Hyper-V protocol-test image.

This checks *inputs* for an opt-in real-host run. It never builds an image,
starts Hyper-V, validates guest contents, or authorizes a real-host test.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path

_VHDX_SIGNATURE = b"vhdxfile"
_GIB = 1024**3


class ImagePreflightError(ValueError):
    """An operator-supplied path, digest, or resource choice is unsuitable."""


@dataclass(frozen=True)
class ImagePreflightReport:
    """Read-only evidence; NOT a certification of the image or VM isolation."""

    image_sha256: str
    image_bytes: int
    workspace_free_bytes: int
    requested_disk_gb: int


def _checked_path(path: Path, label: str) -> Path:
    if not path.is_absolute():
        raise ImagePreflightError(f"{label} must be an absolute path")
    # Reject directory junctions too: Path.is_symlink() alone misses Windows
    # reparse points. Check every existing component before resolving the path.
    for component in (path, *path.parents):
        try:
            info = component.lstat()
        except FileNotFoundError as exc:
            raise ImagePreflightError(f"{label} does not exist: {component}") from exc
        if stat.S_ISLNK(info.st_mode) or (
            info.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT
            if hasattr(info, "st_file_attributes")
            else False
        ):
            raise ImagePreflightError(f"{label} contains a link or reparse point")
    return path.resolve(strict=True)


def _within(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def inspect_protocol_image(
    image: Path,
    expected_sha256: str,
    workspace: Path,
    *,
    disk_gb: int = 20,
    checkout_root: Path | None = None,
) -> ImagePreflightReport:
    """Inspect already-prepared inputs without changing files or Hyper-V state.

    The signature is only a cheap wrong-file check. A pinned SHA-256 detects a
    change from a separately reviewed image, NOT whether the guest is safe.
    Physical free space is not a guarantee or a Hyper-V disk quota.
    """
    if not re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha256):
        raise ImagePreflightError("expected SHA-256 must contain 64 hex characters")
    if isinstance(disk_gb, bool) or not isinstance(disk_gb, int) or not 1 <= disk_gb <= 1024:
        raise ImagePreflightError("disk_gb must be an integer from 1 to 1024")
    resolved_image = _checked_path(image, "image")
    resolved_workspace = _checked_path(workspace, "workspace")
    root = (checkout_root or Path(__file__).resolve().parents[1]).resolve(strict=True)
    if _within(resolved_image, root) or _within(resolved_workspace, root):
        raise ImagePreflightError("image and workspace must be outside the checkout")
    if _within(resolved_image, resolved_workspace):
        raise ImagePreflightError("the image must not be inside the disposable workspace")
    if resolved_workspace == Path(resolved_workspace.anchor):
        raise ImagePreflightError("workspace must not be a filesystem root")
    if image.suffix.lower() != ".vhdx" or not resolved_image.is_file():
        raise ImagePreflightError("image must be an existing regular .vhdx file")
    if not resolved_workspace.is_dir():
        raise ImagePreflightError("workspace must be an existing directory")
    if next(resolved_workspace.iterdir(), None) is not None:
        raise ImagePreflightError("test-only workspace must be empty")
    image_bytes = resolved_image.stat().st_size
    hasher = hashlib.sha256()
    with resolved_image.open("rb") as stream:
        if stream.read(len(_VHDX_SIGNATURE)) != _VHDX_SIGNATURE:
            raise ImagePreflightError("image lacks the VHDX file signature")
        stream.seek(0)
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    if hasher.hexdigest() != expected_sha256.lower():
        raise ImagePreflightError("image SHA-256 does not match the reviewed digest")
    if resolved_image.stat().st_size != image_bytes:
        raise ImagePreflightError("image changed size during preflight")
    free_bytes = shutil.disk_usage(resolved_workspace).free
    if free_bytes < disk_gb * _GIB:
        raise ImagePreflightError("workspace volume has less free space than the requested virtual disk size")
    return ImagePreflightReport(expected_sha256.lower(), image_bytes, free_bytes, disk_gb)


def main(argv: list[str] | None = None) -> int:
    """Explicit read-only preflight, separate from opt-in real-host tests."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, type=Path)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--disk-gb", type=int, default=20)
    args = parser.parse_args(argv)
    try:
        report = inspect_protocol_image(
            args.image, args.sha256, args.workspace, disk_gb=args.disk_gb
        )
    except (ImagePreflightError, OSError) as exc:
        parser.exit(2, f"preflight BLOCKED: {exc}\n")
    print(
        f"Input check passed: image SHA-256 {report.image_sha256}; "
        f"file bytes {report.image_bytes}; workspace free bytes "
        f"{report.workspace_free_bytes}; requested disk GiB {report.requested_disk_gb}."
    )
    print("NOT verified: guest contents, VHDX virtual size, Hyper-V permissions, "
          "network isolation, pipe ACLs, or VM cleanup. Real tests require separate approval.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
