"""POSIX shell control-flow tests using fake media commands, never real mounts.

Only fixture scripts run: no trusted guest payload, root privilege, /target,
Hyper-V, device access or PRODUCTION review-marker creation. Any simulated
approval file lives only in a temporary fixture directory. Windows skips these behavioral
tests; the portable renderer/ISO contract tests still cover subshell grouping.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from night_shifts.ubuntu_seed import render_ubuntu_install_seed

pytestmark = pytest.mark.skipif(
    os.name != "posix" or shutil.which("sh") is None,
    reason="requires a local POSIX shell; no WSL/VM is started for this test",
)

_ID = "night-shift-image-prep-" + "e" * 32
_MOUNT = "/run/night-shift-protocol-seed"
_DEVICE = "/dev/disk/by-label/CIDATA"


def _script(path: Path, body: str) -> None:
    path.write_text("#!/bin/sh\nset -eu\n" + body, encoding="utf-8", newline="\n")
    path.chmod(0o700)


def _run_fixture(
    tmp_path: Path, *, legacy_cwd: bool = False,
    fail_stage: str | None = None, fail_status: int = 0,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    shell = shutil.which("sh")
    assert shell is not None
    root = tmp_path.resolve()
    caller = root / "caller"
    caller.mkdir()
    binaries = root / "fixture-bin"
    binaries.mkdir()
    mount_dir = root / "seed mount"
    device = root / "fixture-cidata"
    device.write_bytes(b"fixture only; not a device or ISO")
    log = root / "events.log"
    payload = root / "fixture-payload.sh"
    _script(payload, (
        "printf 'payload\\n' >> \"$FIXTURE_LOG\"\n"
        "test \"$PWD\" = \"$FIXTURE_MOUNT\"\n"
        "exit \"$FIXTURE_PAYLOAD_STATUS\"\n"
    ))
    _script(binaries / "mount", (
        "printf 'mount\\n' >> \"$FIXTURE_LOG\"\n"
        "test \"$5\" = \"$FIXTURE_DEVICE\"\n"
        "test \"$6\" = \"$FIXTURE_MOUNT\"\n"
        "if [ \"$FIXTURE_MOUNT_STATUS\" -ne 0 ]; then exit \"$FIXTURE_MOUNT_STATUS\"; fi\n"
        "cp -- \"$FIXTURE_PAYLOAD\" \"$FIXTURE_MOUNT/install_protocol_test_target.sh\"\n"
        ": > \"$FIXTURE_MOUNT/SHA256SUMS\"\n"
        ": > \"$FIXTURE_MOUNT/review_protocol_test_target.py\"\n"
    ))
    _script(binaries / "sha256sum", (
        "printf 'checksum\\n' >> \"$FIXTURE_LOG\"\n"
        "test \"$PWD\" = \"$FIXTURE_MOUNT\"\n"
        "test \"$*\" = '-c -- SHA256SUMS'\n"
        "exit \"$FIXTURE_CHECKSUM_STATUS\"\n"
    ))
    _script(binaries / "install", (
        "printf 'stage-audit\\n' >> \"$FIXTURE_LOG\"\n"
        "test \"$PWD\" = \"$FIXTURE_MOUNT\"\n"
        "test \"$#\" -eq 8\n"
        "test \"$7\" = review_protocol_test_target.py\n"
        "test \"$8\" = \"$FIXTURE_STAGED\"\n"
        "exit \"$FIXTURE_STAGE_STATUS\"\n"
    ))
    _script(binaries / "umount", (
        "printf 'umount\\n' >> \"$FIXTURE_LOG\"\n"
        "test \"$1\" = \"$FIXTURE_MOUNT\"\n"
        "case \"$PWD/\" in \"$FIXTURE_MOUNT/\"*)\n"
        "  printf '%s\\n' 'fixture: target is busy' >&2; exit 32;;\n"
        "esac\n"
        "test \"$PWD\" = \"$FIXTURE_CALLER\"\n"
        "exit \"$FIXTURE_UMOUNT_STATUS\"\n"
    ))
    settings = yaml.safe_load(render_ubuntu_install_seed(_ID).user_data)["autoinstall"]
    argv = settings["late-commands"][0]
    assert argv[:2] == ["sh", "-c"]
    command = argv[2]
    if legacy_cwd:
        # Negative control: reconstruct the confirmed parent-cwd defect.
        assert "(cd " in command and "night-shift-target-review.py); " in command
        command = command.replace("(cd ", "cd ", 1).replace(
            "night-shift-target-review.py); ", "night-shift-target-review.py; ", 1,
        )
    # Redirect EVERY fixed production mount/device path before invoking a shell.
    command = command.replace(_MOUNT, shlex.quote(str(mount_dir)))
    command = command.replace(_DEVICE, shlex.quote(str(device)))
    staged = root / "fixture-staged-audit.py"
    command = command.replace("/run/night-shift-target-review.py", shlex.quote(str(staged)))
    assert _MOUNT not in command and _DEVICE not in command and "/run/night-shift-target-review.py" not in command
    environment = dict(os.environ)
    environment.update({
        "PATH": str(binaries) + os.pathsep + environment.get("PATH", ""),
        "FIXTURE_LOG": str(log), "FIXTURE_MOUNT": str(mount_dir),
        "FIXTURE_DEVICE": str(device), "FIXTURE_PAYLOAD": str(payload),
        "FIXTURE_CALLER": str(caller), "FIXTURE_STAGED": str(staged),
    })
    for phase in ("mount", "checksum", "payload", "stage", "umount"):
        environment["FIXTURE_" + phase.upper() + "_STATUS"] = str(
            fail_status if phase == fail_stage else 0,
        )
    result = subprocess.run(
        [shell, "-c", command], cwd=caller, env=environment,
        capture_output=True, text=True, timeout=10, check=False,
    )
    return result, log.read_text(encoding="utf-8").splitlines()


@pytest.mark.parametrize("legacy_cwd", [False, True], ids=["isolated-cwd", "legacy-cwd-busy"])
def test_payload_child_exits_before_parent_unmount(tmp_path: Path, legacy_cwd: bool) -> None:
    result, events = _run_fixture(tmp_path, legacy_cwd=legacy_cwd)
    assert events == ["mount", "checksum", "payload", "stage-audit", "umount"]
    assert result.returncode == (32 if legacy_cwd else 0), result.stderr
    assert ("target is busy" in result.stderr) is legacy_cwd


@pytest.mark.parametrize(("phase", "status", "events"), [
    ("mount", 32, ["mount"]),
    ("checksum", 7, ["mount", "checksum"]),
    ("payload", 9, ["mount", "checksum", "payload"]),
    ("stage", 11, ["mount", "checksum", "payload", "stage-audit"]),
    ("umount", 32, ["mount", "checksum", "payload", "stage-audit", "umount"]),
])
def test_subshell_preserves_failure_and_does_not_continue(
    tmp_path: Path, phase: str, status: int, events: list[str],
) -> None:
    result, actual_events = _run_fixture(tmp_path, fail_stage=phase, fail_status=status)
    assert result.returncode == status, result.stderr
    assert actual_events == events


def _run_review_fixture(tmp_path: Path, mode: str):
    shell = shutil.which("sh")
    assert shell is not None
    root = tmp_path.resolve()
    binaries = root / "bin"
    binaries.mkdir()
    log = root / "review-events.log"
    log.write_text("", encoding="utf-8")
    ack = root / "fixture-ack"
    if mode == "stale":
        ack.write_bytes(b"")
    elif mode == "stale-directory":
        ack.mkdir()
    elif mode == "stale-symlink":
        ack.symlink_to(root / "missing")
    _script(binaries / "python3", (
        "printf 'audit\\n' >> \"$FIXTURE_LOG\"\n"
        "test \"$1\" = -B\n"
        "test \"$2\" = \"$FIXTURE_AUDIT\"\n"
        "if [ \"$FIXTURE_MODE\" = initial-fail ]; then exit 11; fi\n"
        "if [ \"$FIXTURE_MODE\" = drift ] && [ \"$(grep -c '^audit$' \"$FIXTURE_LOG\")\" -eq 2 ]; then exit 12; fi\n"
        "printf 'NS-REVIEW RESULT PASS; fixture ONLY\\n'\n"
    ))
    _script(binaries / "date", "printf '2000-01-01T00:00:00Z\\n'\n")
    _script(binaries / "sleep", (
        "printf 'sleep\\n' >> \"$FIXTURE_LOG\"\n"
        "case \"$FIXTURE_MODE\" in approve|drift|bad-owner|bad-mode)\n"
        "  if [ ! -e \"$FIXTURE_ACK\" ]; then (umask 077; : > \"$FIXTURE_ACK\"); fi;;\n"
        "symlink) if [ ! -L \"$FIXTURE_ACK\" ]; then ln -s \"$FIXTURE_ROOT/missing\" \"$FIXTURE_ACK\"; fi;;\n"
        "esac\n"
    ))
    _script(binaries / "stat", (
        "test \"$1\" = -c\n"
        "test \"$4\" = \"$FIXTURE_ACK\"\n"
        "case \"$2\" in\n"
        "%u) if [ \"$FIXTURE_MODE\" = bad-owner ]; then echo 1000; else echo 0; fi;;\n"
        "%a) if [ \"$FIXTURE_MODE\" = bad-mode ]; then echo 644; else echo 600; fi;;\n"
        "*) exit 13;;\n"
        "esac\n"
    ))
    command = yaml.safe_load(render_ubuntu_install_seed(_ID).user_data)["autoinstall"]["late-commands"][1][2]
    assert "remaining=3600" in command
    command = command.replace("remaining=3600", "remaining=3", 1)
    command = command.replace("/run/night-shift-image-review-approved", shlex.quote(str(ack)))
    staged = root / "fixture-audit.py"
    command = command.replace("/run/night-shift-target-review.py", shlex.quote(str(staged)))
    assert "/run/night-shift-image-review-approved" not in command and "/run/night-shift-target-review.py" not in command
    environment = dict(os.environ)
    environment.update({
        "PATH": str(binaries) + os.pathsep + environment.get("PATH", ""),
        "FIXTURE_LOG": str(log), "FIXTURE_MODE": mode, "FIXTURE_ACK": str(ack),
        "FIXTURE_ROOT": str(root), "FIXTURE_AUDIT": str(staged),
    })
    result = subprocess.run([shell, "-c", command], cwd=root, env=environment,
        capture_output=True, text=True, timeout=10, check=False)
    return result, log.read_text(encoding="utf-8").splitlines()


@pytest.mark.parametrize(("mode", "status", "events"), [
    ("approve", 0, ["audit", "sleep", "audit"]),
    ("drift", 12, ["audit", "sleep", "audit"]),
    ("initial-fail", 11, ["audit"]),
    ("expire", 1, ["audit", "sleep", "sleep", "sleep"]),
    ("bad-owner", 1, ["audit", "sleep", "sleep", "sleep"]),
    ("bad-mode", 1, ["audit", "sleep", "sleep", "sleep"]),
    ("symlink", 1, ["audit", "sleep", "sleep", "sleep"]),
    ("stale", 1, []),
    ("stale-directory", 1, []),
    ("stale-symlink", 1, []),
])
def test_review_audits_before_wait_and_before_release_and_fails_closed(tmp_path: Path, mode, status, events):
    result, actual = _run_review_fixture(tmp_path, mode)
    assert result.returncode == status, result.stdout + result.stderr
    assert actual == events
    assert ("NS-REVIEW RELEASE accepted" in result.stdout) is (mode == "approve")
    if mode.startswith("stale"):
        assert "Unexpected existing image-review marker" in result.stderr
        assert "NS-REVIEW BLOCKED" in result.stderr
        assert "NS-REVIEW WINDOW" not in result.stdout
    elif mode == "initial-fail":
        assert "NS-REVIEW WINDOW" not in result.stdout
    else:
        assert "NS-REVIEW WINDOW" in result.stdout
    if mode in {"expire", "bad-owner", "bad-mode", "symlink"}:
        assert "Image-review checkpoint expired" in result.stderr
        assert "NS-REVIEW EXPIRED" in result.stderr
