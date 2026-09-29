"""Candidate late-command YAML contract only; no live installer or VM."""

from __future__ import annotations

import hashlib

import pytest
import yaml

from night_shifts.ubuntu_seed import render_ubuntu_install_seed, render_ubuntu_seed

_ID = "night-shift-image-prep-" + "d" * 32


def test_candidate_command_mounts_only_fixed_local_payload() -> None:
    generic = render_ubuntu_seed(_ID)
    candidate = render_ubuntu_install_seed(_ID)
    settings = yaml.safe_load(candidate.user_data)["autoinstall"]
    generic_settings = yaml.safe_load(generic.user_data)["autoinstall"]
    assert "late-commands" not in generic_settings
    assert {key: value for key, value in settings.items() if key != "late-commands"} == generic_settings
    assert candidate.meta_data == generic.meta_data
    assert candidate.user_data_sha256 == hashlib.sha256(candidate.user_data).hexdigest()
    assert len(candidate.user_data) <= 8192
    assert len(settings["late-commands"]) == 1
    argv = settings["late-commands"][0]
    assert argv[:2] == ["sh", "-c"]
    command = argv[2]
    assert "set -eu" in command
    assert "-o ro,nodev,nosuid,noexec" in command
    assert "/dev/disk/by-label/CIDATA" in command
    assert "sha256sum -c -- SHA256SUMS" in command
    assert "sh ./install_protocol_test_target.sh" in command
    assert command.endswith("umount /run/night-shift-protocol-seed")
    assert not any(token in command for token in ("http://", "https://", "curl ", "wget ", "apt ", "ssh "))
    assert "password" not in candidate.user_data.decode("utf-8").lower()
    assert "identity" not in settings


@pytest.mark.parametrize("bad", ["", "night-shift-image-prep-" + "X" * 32])
def test_invalid_id_refused_for_install_candidate(bad: str) -> None:
    with pytest.raises(ValueError, match="instance_id"):
        render_ubuntu_install_seed(bad)


def test_policy_flag_is_explicit_and_boolean() -> None:
    with pytest.raises(ValueError, match="boolean"):
        render_ubuntu_seed(_ID, install_protocol_test="yes")  # type: ignore[arg-type]
