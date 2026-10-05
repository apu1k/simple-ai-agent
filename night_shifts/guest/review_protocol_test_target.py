#!/usr/bin/env python3
"""Read-only live-installer target checks, NOT approval or first-boot validation.

Only fixed /target paths are inspected. No service/target program is executed,
no marker/report file is written, and no credentials/configuration are printed.
The caller supplies the independently reviewed seed identity and payload hashes.
Run with Python -B; live-installer PyYAML is required, never installed here.
"""

from __future__ import annotations

import hashlib
import json
import os
import posixpath
import re
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

_TARGET = Path("/target")
_LIVE_ID = Path("/var/lib/cloud/data/instance-id")
_VENDOR = Path("/sys/class/dmi/id/sys_vendor")
_CMDLINE = Path("/proc/cmdline")
_BOOTSTRAP = "usr/local/lib/night-shift/protocol_test_bootstrap.py"
_UNIT = "etc/systemd/system/night-shift-protocol-test.service"
_SYSTEM_USERS = frozenset("""
root daemon bin sys sync games man lp mail news uucp proxy www-data backup list
irc _apt nobody systemd-network systemd-timesync dhcpcd messagebus systemd-resolve
pollinate polkitd syslog uuidd tcpdump tss landscape fwupd-refresh usbmux night-shift
""".split())


class AuditFailure(RuntimeError):
    """Internal refusal; raw exception/configuration text must never be printed."""


def _require(condition: bool) -> None:
    if not condition:
        raise AuditFailure("inspection refused")


def _metadata(path: Path) -> os.stat_result:
    return path.lstat()


def _directory(path: Path) -> None:
    info = _metadata(path)
    _require(stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and info.st_gid == 0)
    _require(info.st_mode & 0o7022 == 0)


def _parents(path: Path) -> None:
    path.relative_to(_TARGET)  # Fixed paths only; refuse escape instead of resolving links.
    for parent in (path.parent, *path.parent.parents):
        _directory(parent)
        if parent == _TARGET:
            return
    raise AuditFailure("inspection refused")


def _regular(path: Path, *, mode: int | None = None, executable: bool = False) -> os.stat_result:
    _parents(path)
    info = _metadata(path)
    _require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and info.st_nlink == 1)
    _require(info.st_mode & 0o7022 == 0)
    if mode is not None:
        _require(info.st_gid == 0 and stat.S_IMODE(info.st_mode) == mode)
    if executable:
        _require(info.st_mode & 0o111 != 0)
    return info


def _read(name: str, limit: int = 1024 * 1024, *, mode: int | None = None) -> bytes:
    path = _TARGET / name
    info = _regular(path, mode=mode)
    _require(0 <= info.st_size <= limit)
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    _require(len(data) == info.st_size and _regular(path, mode=mode).st_size == info.st_size)
    return data


def _live_read(path: Path, limit: int = 4096) -> bytes:
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    _require(len(data) <= limit)
    return data


def _link(name: str) -> str:
    path = _TARGET / name
    _parents(path)
    info = _metadata(path)
    _require(stat.S_ISLNK(info.st_mode) and info.st_uid == 0 and info.st_gid == 0)
    return os.readlink(path)


def _json_command(argv: tuple[str, ...]) -> dict[str, Any]:
    result = subprocess.run(argv, capture_output=True, text=True, timeout=10, check=False)
    _require(result.returncode == 0 and len(result.stdout) <= 128 * 1024)
    parsed = json.loads(result.stdout)
    _require(isinstance(parsed, dict))
    return parsed


def _guard(instance_id: str) -> None:
    _require(os.name == "posix" and getattr(os, "geteuid", lambda: -1)() == 0)
    _require(_live_read(_VENDOR).strip() == b"Microsoft Corporation")
    _require(_live_read(_LIVE_ID).decode("ascii").strip() == instance_id)
    _directory(_TARGET.parent)
    _directory(_TARGET)


def _mount() -> None:
    mounted = _json_command(("/usr/bin/findmnt", "--json", "--mountpoint", "/target", "-o", "TARGET,SOURCE,FSTYPE"))
    filesystems = mounted["filesystems"]
    _require(len(filesystems) == 1 and filesystems[0]["target"] == "/target")
    _require(filesystems[0]["fstype"] == "ext4")
    source = filesystems[0]["source"]
    _require(isinstance(source, str) and re.fullmatch(r"/dev/[a-zA-Z0-9]+", source) is not None)
    # PATH alone does not make lsblk emit children[]; request its tree explicitly.
    inventory = _json_command(("/usr/bin/lsblk", "--json", "--tree", "-b", "-e", "7", "-o", "PATH,TYPE,SIZE"))
    disks = [entry for entry in inventory["blockdevices"] if entry["type"] == "disk"]
    _require(len(disks) == 1)
    _require(any(child["path"] == source and child["type"] == "part" for child in disks[0].get("children", [])))


def _payload(bootstrap_sha256: str, unit_sha256: str) -> None:
    for name, digest in ((_BOOTSTRAP, bootstrap_sha256), (_UNIT, unit_sha256)):
        _require(hashlib.sha256(_read(name, mode=0o644)).hexdigest() == digest)


def _records(name: str, fields: int) -> dict[str, list[str]]:
    records: dict[str, list[str]] = {}
    for line in _read(name).decode("utf-8").splitlines():
        row = line.split(":")
        _require(len(row) == fields and bool(row[0]) and row[0] not in records)
        records[row[0]] = row
    return records


def _accounts() -> None:
    passwd = _records("etc/passwd", 7)
    shadow = _records("etc/shadow", 9)
    groups = _records("etc/group", 4)
    _require({"root", "night-shift"} <= passwd.keys() <= _SYSTEM_USERS)
    _require(passwd.keys() == shadow.keys())
    uids = [int(row[2]) for row in passwd.values()]
    _require(len(uids) == len(set(uids)))
    _require(passwd["root"][3] == "0" and passwd["root"][5:] == ["/root", "/bin/bash"])
    for name, row in passwd.items():
        uid = int(row[2])
        _require(row[1] == "x" and (0 <= uid < 1000 or name == "nobody" and uid == 65534))
        _require((uid == 0) == (name == "root"))
        _require(bool(shadow[name][1]) and shadow[name][1][0] in "!*")
        if name not in {"root", "sync"}:
            _require(row[6] in {"/usr/sbin/nologin", "/bin/false"})
    worker = passwd["night-shift"]
    _require(worker[5:] == ["/nonexistent", "/usr/sbin/nologin"])
    _require(groups["night-shift"][2] == worker[3] and 0 < int(worker[3]) < 1000)
    _require(groups["dialout"][2] == "20")
    memberships = {name for name, row in groups.items() if "night-shift" in row[3].split(",")}
    _require(memberships | {"night-shift"} == {"night-shift", "dialout"})


def _service_links() -> None:
    enabled = "etc/systemd/system/multi-user.target.wants/night-shift-protocol-test.service"
    destination = _link(enabled)
    absolute = posixpath.normpath(destination if destination.startswith("/") else "/" + posixpath.join(posixpath.dirname(enabled), destination))
    _require(absolute == "/" + _UNIT)
    _require(_link("etc/systemd/system/serial-getty@ttyS0.service") == "/dev/null")


def _serial_boot() -> None:
    for name in ("etc/default/grub", "boot/grub/grub.cfg"):
        _require(b"console=ttyS0" not in _read(name, 4 * 1024 * 1024))
    _require(b"console=ttyS0" not in _live_read(_CMDLINE))


def _prerequisites() -> None:
    python = _link("usr/bin/python3")
    _require(re.fullmatch(r"python3\.[0-9]+", python) is not None)
    for name in ("usr/bin/" + python, "usr/bin/systemctl"):
        path = _TARGET / name
        _regular(path, executable=True)
        with path.open("rb") as stream:
            _require(stream.read(4) == b"\x7fELF")


def _ssh_hygiene() -> None:
    _directory(_TARGET / "home")
    _require(not any((_TARGET / "home").iterdir()))
    root = _TARGET / "root"
    _directory(root)
    ssh = root / ".ssh"
    try:
        _metadata(ssh)
    except FileNotFoundError:
        pass
    else:
        _directory(ssh)
        _require(not any(ssh.iterdir()))  # Empty .ssh is normal; never read credentials.
    _require(not (_TARGET / "usr/sbin/sshd").exists() and not (_TARGET / "usr/sbin/sshd").is_symlink())
    for stanza in _read("var/lib/dpkg/status", 16 * 1024 * 1024).decode("utf-8").split("\n\n"):
        if "Package: openssh-server" in stanza.splitlines():
            _require("Status: deinstall ok config-files" in stanza.splitlines() or "Status: purge ok not-installed" in stanza.splitlines())
    ssh_config = _TARGET / "etc/ssh"
    if ssh_config.exists() or ssh_config.is_symlink():
        _directory(ssh_config)
        _require(not any(ssh_config.glob("ssh_host_*_key")))


def _cloud_init() -> None:
    import yaml  # type: ignore[import-untyped]  # Provided by live cloud-init; fail closed if absent.

    config = yaml.safe_load(_read("etc/cloud/cloud.cfg.d/99-installer.cfg", 64 * 1024))
    _require(isinstance(config, dict) and set(config) == {"datasource", "datasource_list"})
    _require(config["datasource_list"] == ["None"] and set(config["datasource"]) == {"None"})
    source = config["datasource"]["None"]
    _require(set(source) == {"metadata", "userdata_raw"} and set(source["metadata"]) == {"instance-id"})
    identity = source["metadata"]["instance-id"]
    _require(isinstance(identity, str) and re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", identity) is not None)
    raw = source["userdata_raw"]
    _require(isinstance(raw, str) and raw.startswith("#cloud-config\n"))
    user = yaml.safe_load(raw)
    expected_keys = {"users", "disable_root", "ssh_pwauth", "package_update", "package_upgrade", "growpart", "resize_rootfs", "locale", "write_files"}
    _require(isinstance(user, dict) and set(user) == expected_keys)
    _require(user["users"] == [] and user["disable_root"] is True and user["ssh_pwauth"] is False)
    _require(user["package_update"] is False and user["package_upgrade"] is False)
    _require(user["growpart"] == {"mode": "off"} and user["resize_rootfs"] is False)
    _require(isinstance(user["locale"], str) and re.fullmatch(r"[a-zA-Z0-9_.@-]{1,64}", user["locale"]) is not None)
    writes = user["write_files"]
    _require(isinstance(writes, list) and len(writes) == 1)
    entry = writes[0]
    _require(set(entry) == {"path", "defer", "content"})
    _require(entry["path"] == "/etc/cloud/cloud-init.disabled" and entry["defer"] is True)
    _require(isinstance(entry["content"], str) and 0 < len(entry["content"]) <= 4096)
    # A first boot is STILL required to validate the effective accounts/units.


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 6 or args[::2] != ["--instance-id", "--bootstrap-sha256", "--unit-sha256"] or (
        re.fullmatch(r"night-shift-image-prep-[0-9a-f]{32}", args[1]) is None or
        any(re.fullmatch(r"[0-9a-f]{64}", value) is None for value in (args[3], args[5]))
    ):
        print("NS-REVIEW FAIL INPUTS: reviewed identity and hashes required")
        return 1
    try:
        _guard(args[1])
    except Exception:
        print("NS-REVIEW FAIL LIVE_CONTEXT: root Hyper-V live installer identity required")
        return 1
    checks = (
        ("TARGET_MOUNT", _mount),
        ("PAYLOAD_BYTES_AND_PERMISSIONS", lambda: _payload(args[3], args[5])),
        ("LOCKED_SYSTEM_ACCOUNTS_AND_GROUPS", _accounts),
        ("ENABLED_UNIT_AND_MASKED_GETTY", _service_links),
        ("NO_SERIAL_CONSOLE_CONFLICT", _serial_boot),
        ("PYTHON_AND_SYSTEMD_PRESENT", _prerequisites),
        ("NO_SSH_SERVER_OR_CREDENTIALS", _ssh_hygiene),
        ("INSTALLER_CLOUD_INIT_POLICY", _cloud_init),
    )
    passed = True
    for label, check in checks:
        try:
            check()
        except Exception:
            passed = False
            print("NS-REVIEW FAIL " + label + ": inspection failed or policy differs")
        else:
            print("NS-REVIEW PASS " + label)
    print("NS-REVIEW RESULT " + ("PASS" if passed else "FAIL") + "; no approval marker written; NOT first-boot validation or Gate A", flush=True)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
