"""POSIX shell control-flow tests using fake media commands, never real mounts.

Only fixture scripts run: no trusted guest payload, root privilege, /target,
Hyper-V, device access or review-marker creation. Windows skips these behavioral
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
    ))
    _script(binaries / "sha256sum", (
        "printf 'checksum\\n' >> \"$FIXTURE_LOG\"\n"
        "test \"$PWD\" = \"$FIXTURE_MOUNT\"\n"
        "test \"$*\" = '-c -- SHA256SUMS'\n"
        "exit \"$FIXTURE_CHECKSUM_STATUS\"\n"
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
        assert "(cd " in command and "install_protocol_test_target.sh); " in command
        command = command.replace("(cd ", "cd ", 1).replace(
            "install_protocol_test_target.sh); ", "install_protocol_test_target.sh; ", 1,
        )
    # Redirect EVERY fixed production mount/device path before invoking a shell.
    command = command.replace(_MOUNT, shlex.quote(str(mount_dir)))
    command = command.replace(_DEVICE, shlex.quote(str(device)))
    assert _MOUNT not in command and _DEVICE not in command
    environment = dict(os.environ)
    environment.update({
        "PATH": str(binaries) + os.pathsep + environment.get("PATH", ""),
        "FIXTURE_LOG": str(log), "FIXTURE_MOUNT": str(mount_dir),
        "FIXTURE_DEVICE": str(device), "FIXTURE_PAYLOAD": str(payload),
        "FIXTURE_CALLER": str(caller),
    })
    for phase in ("mount", "checksum", "payload", "umount"):
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
    assert events == ["mount", "checksum", "payload", "umount"]
    assert result.returncode == (32 if legacy_cwd else 0), result.stderr
    assert ("target is busy" in result.stderr) is legacy_cwd


@pytest.mark.parametrize(("phase", "status", "events"), [
    ("mount", 32, ["mount"]),
    ("checksum", 7, ["mount", "checksum"]),
    ("payload", 9, ["mount", "checksum", "payload"]),
    ("umount", 32, ["mount", "checksum", "payload", "umount"]),
])
def test_subshell_preserves_failure_and_does_not_continue(
    tmp_path: Path, phase: str, status: int, events: list[str],
) -> None:
    result, actual_events = _run_fixture(tmp_path, fail_stage=phase, fail_status=status)
    assert result.returncode == status, result.stderr
    assert actual_events == events
