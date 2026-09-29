"""Static policy checks only: never execute installer shell on Windows/host."""

from __future__ import annotations

from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "night_shifts" / "guest" / "install_protocol_test_target.sh"
)


def test_candidate_late_install_is_guest_target_only_and_no_network() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert source.startswith("#!/bin/sh\n")
    assert "set -eu" in source
    assert "Microsoft Corporation" in source
    assert "mountpoint -q /target" in source
    assert "[ ! -f /target/etc/default/grub ]" in source
    assert "grep -q 'console=ttyS0' /target/etc/default/grub" in source
    assert "/target/usr/bin/python3" in source
    assert "sha256sum -c -- SHA256SUMS" in source
    assert "chroot /target groupadd --system night-shift" in source
    assert "chroot /target useradd --system --gid night-shift" in source
    assert "chroot /target passwd -l night-shift" in source
    assert "install -o 0 -g 0 -m 0644 protocol_test_bootstrap.py" in source
    assert "install -o 0 -g 0 -m 0644 night-shift-protocol-test.service" in source
    assert "systemctl --root=/target mask serial-getty@ttyS0.service" in source
    assert "systemctl --root=/target enable night-shift-protocol-test.service" in source
    assert "systemctl --root=/target mask --now" not in source
    assert "systemctl start " not in source
    assert "curl " not in source and "wget " not in source
    assert "ssh " not in source and "apt " not in source


def test_no_bootstrap_is_invoked_from_current_seed_builder() -> None:
    seed = (SCRIPT.parents[1] / "ubuntu_seed.py").read_text(encoding="utf-8")
    iso = (SCRIPT.parents[1] / "ubuntu_seed_iso.py").read_text(encoding="utf-8")
    assert "late-commands" not in seed
    assert "install_protocol_test_target.sh" not in iso
