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
    assert "shutdown" not in generic_settings
    assert {key: value for key, value in settings.items() if key not in {"late-commands", "shutdown"}} == generic_settings
    assert settings["shutdown"] == "poweroff"
    assert candidate.meta_data == generic.meta_data
    assert candidate.user_data_sha256 == hashlib.sha256(candidate.user_data).hexdigest()
    assert len(candidate.user_data) <= 8192
    assert len(settings["late-commands"]) == 2
    argv = settings["late-commands"][0]
    assert argv[:2] == ["sh", "-c"]
    command = argv[2]
    assert "set -eu" in command
    assert "-o ro,nodev,nosuid,noexec" in command
    assert "/dev/disk/by-label/CIDATA" in command
    assert "sha256sum -c -- SHA256SUMS" in command
    assert "sh ./install_protocol_test_target.sh" in command
    # A parent cwd inside the seed made the real late-command fail with
    # 'target is busy' after the payload completed. Keep all seed-local work
    # in a subshell; ordinary unmount must run only after that child exits.
    assert (
        "(cd /run/night-shift-protocol-seed; "
        "sha256sum -c -- SHA256SUMS; "
        "sh ./install_protocol_test_target.sh; "
        "install -o 0 -g 0 -m 0600 review_protocol_test_target.py "
        "/run/night-shift-target-review.py); "
        "umount /run/night-shift-protocol-seed"
    ) in command
    assert command.endswith("umount /run/night-shift-protocol-seed")
    assert not any(token in command for token in ("umount -l", "umount -f", "|| true"))
    assert not any(token in command for token in ("http://", "https://", "curl ", "wget ", "apt ", "ssh "))
    assert "password" not in candidate.user_data.decode("utf-8").lower()
    assert "identity" not in settings


def test_combined_candidate_has_finite_manual_review_checkpoint_then_poweroff() -> None:
    candidate = render_ubuntu_install_seed(_ID)
    settings = yaml.safe_load(candidate.user_data)["autoinstall"]
    install, review = settings["late-commands"]
    assert "install_protocol_test_target.sh" in install[2]
    assert review[:2] == ["sh", "-c"]
    command = review[2]
    assert "ack=/run/night-shift-image-review-approved" in command
    assert '[ -e "$ack" ] || [ -L "$ack" ]' in command
    assert "remaining=3600" in command and "remaining=1800" not in command
    assert "NS-REVIEW WINDOW start=%s estimated_deadline=%s" in command
    assert "date -u -d '+3600 seconds'" in command
    assert "NS-REVIEW WAIT %s polling attempts left" in command
    assert "not a host lifetime bound" in command
    assert "NS-REVIEW BLOCKED preexisting approval marker" in command
    assert "NS-REVIEW EXPIRED; no release, retry or first-boot approval" in command
    audit = "python3 -B /run/night-shift-target-review.py --instance-id " + _ID
    assert command.count(audit) == 2  # Before the timer AND after valid manual acknowledgment.
    assert command.index(audit) < command.index("remaining=3600")
    from night_shifts.protocol_image_bundle import _assets
    assets = _assets()
    for name, option in (("protocol_test_bootstrap.py", "--bootstrap-sha256"),
                         ("night-shift-protocol-test.service", "--unit-sha256")):
        assert command.count(option + " " + hashlib.sha256(assets[name]).hexdigest()) == 2
    assert "__AUDIT__" not in command
    assert 'while [ "$remaining" -gt 0 ]' in command
    assert "sleep 1; remaining=$((remaining - 1))" in command
    assert '[ -f "$ack" ] && [ ! -L "$ack" ]' in command
    assert 'stat -c %u -- "$ack"' in command
    assert 'stat -c %a -- "$ack"' in command
    assert '= 600 ]; then python3 -B /run/night-shift-target-review.py' in command
    assert command.index("NS-REVIEW RELEASE accepted") > command.rindex(audit)
    assert not any(token in command for token in ("touch ", "umask ", ": >", "install -", "tee "))
    assert command.endswith("exit 1")  # no acknowledgment must fail, not continue to first boot
    assert settings["shutdown"] == "poweroff"
    assert settings["user-data"]["users"] == []
    assert "identity" not in settings
    assert not any(token in command for token in (
        "http://", "https://", "curl ", "wget ", "ssh ", "useradd ", "passwd ", "> /target", "rm ",
    ))
    assert candidate.user_data == render_ubuntu_install_seed(_ID).user_data


@pytest.mark.parametrize("bad", ["", "night-shift-image-prep-" + "X" * 32])
def test_invalid_id_refused_for_install_candidate(bad: str) -> None:
    with pytest.raises(ValueError, match="instance_id"):
        render_ubuntu_install_seed(bad)


def test_policy_flag_is_explicit_and_boolean() -> None:
    with pytest.raises(ValueError, match="boolean"):
        render_ubuntu_seed(_ID, install_protocol_test="yes")  # type: ignore[arg-type]
