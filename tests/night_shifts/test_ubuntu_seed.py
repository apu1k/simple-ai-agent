"""Offline NoCloud seed policy tests, NOT Ubuntu/Hyper-V boot tests."""

from __future__ import annotations

import hashlib

import pytest
import yaml

from night_shifts.ubuntu_seed import render_ubuntu_seed


_ID = "night-shift-image-prep-" + "a" * 32


def test_credential_free_single_disk_seed_is_stable() -> None:
    first = render_ubuntu_seed(_ID)
    assert first == render_ubuntu_seed(_ID)
    assert first.user_data.startswith(b"#cloud-config\n")
    assert first.user_data_sha256 == hashlib.sha256(first.user_data).hexdigest()
    assert first.meta_data_sha256 == hashlib.sha256(first.meta_data).hexdigest()
    assert len(first.user_data) <= 8192
    assert len(first.meta_data) <= 512
    data = yaml.safe_load(first.user_data)
    assert list(data) == ["autoinstall"]
    settings = data["autoinstall"]
    assert settings["version"] == 1
    assert settings["refresh-installer"] == {"update": False}
    assert settings["network"] == {"version": 2, "ethernets": {}}
    assert settings["apt"] == {"geoip": False, "fallback": "offline-install"}
    assert settings["ssh"] == {"install-server": False, "allow-pw": False}
    assert settings["storage"] == {"layout": {"name": "direct"}}
    assert settings["early-commands"] == [
        ["sh", "-c", 'test "$(lsblk -dn -o TYPE | grep -cx disk)" -eq 1']
    ]
    assert settings["user-data"] == {
        "users": [], "disable_root": True, "ssh_pwauth": False,
        "package_update": False, "package_upgrade": False,
    }
    assert "identity" not in settings
    assert "password" not in first.user_data.decode("utf-8").lower()
    assert "ssh_authorized_keys" not in first.user_data.decode("utf-8")
    assert yaml.safe_load(first.meta_data) == {
        "instance-id": _ID,
        "local-hostname": "night-shift-protocol",
    }


@pytest.mark.parametrize(
    "instance_id", ["", "agent-chosen", "night-shift-image-prep-" + "G" * 32,
                    "night-shift-image-prep-" + "a" * 31, 42],
)
def test_rejects_unguarded_identity(instance_id: str | int) -> None:
    with pytest.raises(ValueError, match="instance_id"):
        render_ubuntu_seed(instance_id)  # type: ignore[arg-type]
