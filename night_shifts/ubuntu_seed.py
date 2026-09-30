"""Render reviewed, credential-free NoCloud data for Ubuntu image preparation.

These are seed *files*, not an ISO. Nothing here mounts media, executes guest
code, starts Hyper-V, or proves the Ubuntu installer accepts this configuration.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

import yaml  # type: ignore[import-untyped]  # PyYAML has no bundled type stubs

_INSTANCE_ID = re.compile(r"^night-shift-image-prep-[0-9a-f]{32}$")
_HOSTNAME = "night-shift-protocol"
# Executed by Subiquity as root in the live installer, after /target exists.
# The path is fixed; neither a model nor a repository supplies shell text.
# A separate packaging step MUST supply the verified script/assets on CIDATA
# before this candidate may be used in a real image-preparation VM.
_TARGET_INSTALL_COMMAND = (
    "set -eu; "
    "mkdir -m 0700 /run/night-shift-protocol-seed; "
    "mount -t iso9660 -o ro,nodev,nosuid,noexec "
    "/dev/disk/by-label/CIDATA /run/night-shift-protocol-seed; "
    "cd /run/night-shift-protocol-seed; "
    "sha256sum -c -- SHA256SUMS; "
    "sh ./install_protocol_test_target.sh; "
    "umount /run/night-shift-protocol-seed"
)

# One-time operator inspection in the live installer, not a target login.
# The marker ONLY releases installation; it does not certify the image or
# authorize first boot/Gate A. A stale marker or exhausted wait fails closed.
_TARGET_REVIEW_COMMAND = (
    "set -eu; "
    "ack=/run/night-shift-image-review-approved; "
    "if [ -e \"$ack\" ] || [ -L \"$ack\" ]; then "
    "echo 'Unexpected existing image-review marker' >&2; exit 1; fi; "
    "echo 'Night-shift target review required in live installer; 1800 polling attempts'; "
    "remaining=1800; "
    "while [ \"$remaining\" -gt 0 ]; do "
    "if [ -f \"$ack\" ] && [ ! -L \"$ack\" ] && "
    "[ \"$(stat -c %u -- \"$ack\")\" -eq 0 ] && "
    "[ \"$(stat -c %a -- \"$ack\")\" = 600 ]; then exit 0; fi; "
    "sleep 1; remaining=$((remaining - 1)); done; "
    "echo 'Image-review checkpoint expired; do not freeze this image' >&2; exit 1"
)


@dataclass(frozen=True)
class NoCloudSeed:
    """In-memory, bounded candidate installer inputs, not a VM/image result."""

    user_data: bytes
    meta_data: bytes
    user_data_sha256: str
    meta_data_sha256: str


def render_ubuntu_seed(instance_id: str, *, install_protocol_test: bool = False) -> NoCloudSeed:
    """Produce an offline, single-disk autoinstall candidate without logins.

    The `user-data` section deliberately replaces installer `identity`: per
    Canonical's reference the latter is optional when user-data is present.
    Real validation of 24.04.5 parsing, storage choice and first boot remains
    mandatory. On failure discard the disposable image, never relax policy by
    attaching a network or injecting a default account into the final base.
    """
    if not isinstance(instance_id, str) or not _INSTANCE_ID.fullmatch(instance_id):
        raise ValueError("instance_id must be a generated image-preparation VM identity")
    if not isinstance(install_protocol_test, bool):
        raise ValueError("install_protocol_test must be a boolean policy choice")
    settings: dict[str, object] = {
        "version": 1,
        "refresh-installer": {"update": False},
        "network": {"version": 2, "ethernets": {}},
        "apt": {"geoip": False, "fallback": "offline-install"},
        "ssh": {"install-server": False, "allow-pw": False},
        # Abort before disk configuration if a second disk is exposed.
        # A DVD/seed ISO is an optical 'rom', not a writable 'disk'.
        "early-commands": [
            ["sh", "-c", 'test "$(lsblk -dn -o TYPE | grep -cx disk)" -eq 1']
        ],
        "storage": {"layout": {"name": "direct"}},
        "user-data": {
            "users": [],
            "disable_root": True,
            "ssh_pwauth": False,
            "package_update": False,
            "package_upgrade": False,
        },
    }
    if install_protocol_test:
        settings["late-commands"] = [
            ["sh", "-c", _TARGET_INSTALL_COMMAND],
            ["sh", "-c", _TARGET_REVIEW_COMMAND],
        ]
        # Prevent an automatic return to the still-attached installer or an
        # unreviewed first boot. Subiquity acceptance must be observed for real.
        settings["shutdown"] = "poweroff"
    user_data = ("#cloud-config\n" + yaml.safe_dump({"autoinstall": settings}, sort_keys=False)).encode("utf-8")
    meta_data = yaml.safe_dump(
        {"instance-id": instance_id, "local-hostname": _HOSTNAME},
        sort_keys=False,
    ).encode("utf-8")
    if len(user_data) > 8192 or len(meta_data) > 512:
        raise ValueError("generated NoCloud seed exceeds fixed bounds")
    return NoCloudSeed(
        user_data=user_data,
        meta_data=meta_data,
        user_data_sha256=hashlib.sha256(user_data).hexdigest(),
        meta_data_sha256=hashlib.sha256(meta_data).hexdigest(),
    )


def render_ubuntu_install_seed(instance_id: str) -> NoCloudSeed:
    """Candidate install/review/power-off seed, for the combined builder only.

    The older staging and ISO builder use render_ubuntu_seed without guest
    payload. This candidate pauses for manual live-installer target review and
    requests power-off, not automatic first boot. Packaging it with fixed assets
    is not proof Subiquity accepts it; never launch merely because YAML renders.
    """
    return render_ubuntu_seed(instance_id, install_protocol_test=True)
