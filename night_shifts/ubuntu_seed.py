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


@dataclass(frozen=True)
class NoCloudSeed:
    """In-memory, bounded candidate installer inputs, not a VM/image result."""

    user_data: bytes
    meta_data: bytes
    user_data_sha256: str
    meta_data_sha256: str


def render_ubuntu_seed(instance_id: str) -> NoCloudSeed:
    """Produce an offline, single-disk autoinstall candidate without logins.

    The `user-data` section deliberately replaces installer `identity`: per
    Canonical's reference the latter is optional when user-data is present.
    Real validation of 24.04.5 parsing, storage choice and first boot remains
    mandatory. On failure discard the disposable image, never relax policy by
    attaching a network or injecting a default account into the final base.
    """
    if not isinstance(instance_id, str) or not _INSTANCE_ID.fullmatch(instance_id):
        raise ValueError("instance_id must be a generated image-preparation VM identity")
    config = {
        "autoinstall": {
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
    }
    user_data = ("#cloud-config\n" + yaml.safe_dump(config, sort_keys=False)).encode("utf-8")
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
