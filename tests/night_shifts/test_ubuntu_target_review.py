"""Read-only auditor contract models, NOT real Linux/Hyper-V review evidence.

Windows fixtures explicitly replace Unix metadata, live context and two JSON
commands. No production permission bypass, guest, service or real /target exists.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from night_shifts.guest import review_protocol_test_target as audit

_ID = "night-shift-image-prep-" + "a" * 32
_SECRET = "SECRET_CANARY_MUST_NEVER_APPEAR_IN_AUDIT_OUTPUT"
_NATIVE_JSON_COMMAND = audit._json_command


@pytest.fixture
def model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    target = tmp_path / "synthetic-target"
    modes: dict[Path, tuple[int, int, int, int]] = {}
    links: dict[Path, str] = {}
    calls: list[tuple[str, ...]] = []

    def put(name: str, data: bytes | str, mode: int = 0o644):
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)
        modes[path] = (stat.S_IFREG | mode, 0, 0, 1)
        return path

    bootstrap = b"fixture bootstrap, NOT guest code\n"
    unit = b"fixture unit, NOT a real service\n"
    put(audit._BOOTSTRAP, bootstrap)
    put(audit._UNIT, unit)
    put("etc/passwd", "root:x:0:0:root:/root:/bin/bash\nnight-shift:x:999:988::/nonexistent:/usr/sbin/nologin\nnobody:x:65534:65534::/nonexistent:/usr/sbin/nologin\n")
    put("etc/shadow", "".join(f"{name}:!{_SECRET}:0:0:99999:7:::\n" for name in ("root", "night-shift", "nobody")), 0o640)
    put("etc/group", "root:x:0:\nnight-shift:x:988:\ndialout:x:20:night-shift\nnogroup:x:65534:\nsudo:x:27:\n")
    put("etc/default/grub", 'GRUB_CMDLINE_LINUX=""\n')
    put("boot/grub/grub.cfg", "fixture normal boot\n", 0o444)
    put("usr/bin/python3.12", b"\x7fELFfixture", 0o755)
    put("usr/bin/systemctl", b"\x7fELFfixture", 0o755)
    put("var/lib/dpkg/status", "Package: openssh-client\nStatus: install ok installed\n\n")
    (target / "home").mkdir()
    (target / "root/.ssh").mkdir(parents=True)
    (target / "etc/ssh").mkdir()
    user = {
        "users": [], "disable_root": True, "ssh_pwauth": False,
        "package_update": False, "package_upgrade": False,
        "growpart": {"mode": "off"}, "resize_rootfs": False,
        "locale": "en_US.UTF-8", "write_files": [{"path": "/etc/cloud/cloud-init.disabled",
            "defer": True, "content": "Disabled by Ubuntu live installer after first boot.\n"}],
    }
    cloud = {"datasource": {"None": {"metadata": {"instance-id": "23664a8a-56de-400d-ad41-771631fd7ad1"},
        "userdata_raw": ""}}, "datasource_list": ["None"]}

    def save_cloud():
        cloud["datasource"]["None"]["userdata_raw"] = "#cloud-config\n" + yaml.safe_dump(user)
        put("etc/cloud/cloud.cfg.d/99-installer.cfg", yaml.safe_dump(cloud), 0o600)

    save_cloud()
    for name, destination in (
        ("etc/systemd/system/multi-user.target.wants/night-shift-protocol-test.service", "/" + audit._UNIT),
        ("etc/systemd/system/serial-getty@ttyS0.service", "/dev/null"),
        ("usr/bin/python3", "python3.12"),
    ):
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        links[path] = destination
    live_id = tmp_path / "fixture-live-id"
    live_id.write_text(_ID + "\n", encoding="ascii")
    vendor = tmp_path / "fixture-vendor"
    vendor.write_text("Microsoft Corporation\n", encoding="ascii")
    cmdline = tmp_path / "fixture-cmdline"
    cmdline.write_text("fixture normal live boot\n", encoding="ascii")

    def metadata(path):
        if path in links:
            row = (stat.S_IFLNK | 0o777, 0, 0, 1)
            size = len(links[path])
        else:
            real = path.lstat()
            row = modes.get(path, (stat.S_IFDIR | 0o755 if path.is_dir() else stat.S_IFREG | 0o644, 0, 0, 1))
            size = real.st_size
        mode, uid, gid, nlink = row
        return SimpleNamespace(st_mode=mode, st_uid=uid, st_gid=gid, st_nlink=nlink, st_size=size)

    mounted = {"filesystems": [{"target": "/target", "source": "/dev/sda2", "fstype": "ext4"}]}
    inventory = {"blockdevices": [{"path": "/dev/sda", "type": "disk", "size": 20 * 1024**3,
        "children": [{"path": "/dev/sda2", "type": "part"}]}]}

    def command(argv):
        calls.append(argv)
        if argv[0] == "/usr/bin/findmnt":
            assert "--mountpoint" in argv
            return json.loads(json.dumps(mounted))
        assert argv[0] == "/usr/bin/lsblk" and "--tree" in argv
        return json.loads(json.dumps(inventory))

    # Explicit model substitution, confined to this fixture.
    monkeypatch.setattr(audit, "_TARGET", target)
    monkeypatch.setattr(audit, "_LIVE_ID", live_id)
    monkeypatch.setattr(audit, "_VENDOR", vendor)
    monkeypatch.setattr(audit, "_CMDLINE", cmdline)
    monkeypatch.setattr(audit, "_metadata", metadata)
    monkeypatch.setattr(audit, "_json_command", command)
    monkeypatch.setattr(audit, "os", SimpleNamespace(name="posix", geteuid=lambda: 0, readlink=lambda path: links[path]))
    argv = ["--instance-id", _ID, "--bootstrap-sha256", hashlib.sha256(bootstrap).hexdigest(),
        "--unit-sha256", hashlib.sha256(unit).hexdigest()]
    return SimpleNamespace(target=target, modes=modes, links=links, calls=calls, put=put,
        user=user, cloud=cloud, save_cloud=save_cloud, argv=argv, mounted=mounted,
        inventory=inventory, live_id=live_id, vendor=vendor, cmdline=cmdline)


def _snapshot(root: Path):
    return {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_observed_target_shape_passes_without_writes_or_secret_output(model, capsys):
    before = _snapshot(model.target.parent)
    assert audit.main(model.argv) == 0
    output = capsys.readouterr()
    assert output.err == "" and _SECRET not in output.out
    assert output.out.count("NS-REVIEW PASS ") == 8
    assert "NS-REVIEW RESULT PASS" in output.out and "NOT first-boot validation or Gate A" in output.out
    assert _snapshot(model.target.parent) == before
    assert [call[0] for call in model.calls] == ["/usr/bin/findmnt", "/usr/bin/lsblk"]
    assert not (model.target / "run/night-shift-image-review-approved").exists()


@pytest.mark.parametrize("fault", [
    "bootstrap", "unit", "owner", "group-write", "parent-write", "parent-owner",
    "symlink-file", "hardlink-file", "disabled-unit", "unmasked-getty", "interactive-shell",
    "unlocked-root", "extra-user", "extra-group", "duplicate-uid", "alias-uid", "root-home", "home-directory",
    "ssh-key", "ssh-daemon", "ssh-package", "host-private-key", "serial-grub",
    "serial-generated-grub", "serial-live", "missing-python", "wrong-python-link",
    "users", "root-login", "password-auth", "package-update", "extra-cloud-key",
    "extra-write", "cloud-uuid", "cloud-yaml", "missing-cloud", "wrong-mount",
    "second-disk", "missing-disk-hierarchy",
])
def test_refuses_drift_and_redacts_raw_values_and_exceptions(model, fault, capsys):
    t = model.target
    if fault in {"bootstrap", "unit"}:
        name = audit._BOOTSTRAP if fault == "bootstrap" else audit._UNIT
        model.put(name, _SECRET)
    elif fault in {"owner", "group-write", "symlink-file", "hardlink-file"}:
        model.modes[t / audit._BOOTSTRAP] = (
            stat.S_IFLNK | 0o777 if fault == "symlink-file" else stat.S_IFREG | (0o664 if fault == "group-write" else 0o644),
            999 if fault == "owner" else 0, 0, 2 if fault == "hardlink-file" else 1)
    elif fault in {"parent-write", "parent-owner"}:
        model.modes[t / "usr/local/lib"] = (stat.S_IFDIR | (0o777 if fault == "parent-write" else 0o755),
            999 if fault == "parent-owner" else 0, 0, 1)
    elif fault == "disabled-unit":
        del model.links[t / "etc/systemd/system/multi-user.target.wants/night-shift-protocol-test.service"]
    elif fault == "unmasked-getty":
        model.links[t / "etc/systemd/system/serial-getty@ttyS0.service"] = _SECRET
    elif fault in {"interactive-shell", "duplicate-uid", "alias-uid", "root-home", "extra-user"}:
        value = (t / "etc/passwd").read_text(encoding="utf-8")
        value = value.replace("/usr/sbin/nologin", "/bin/bash", 1) if fault == "interactive-shell" else value
        value = value.replace("999:988", "0:988") if fault == "duplicate-uid" else value
        value = value.replace("nobody:x:65534:", "nobody:x:999:") if fault == "alias-uid" else value
        value = value.replace("root:/root:/bin/bash", "root:/nonexistent:/bin/bash") if fault == "root-home" else value
        value += "ubuntu:x:1000:1000::/home/ubuntu:/bin/bash\n" if fault == "extra-user" else ""
        model.put("etc/passwd", value)
    elif fault == "unlocked-root":
        model.put("etc/shadow", (t / "etc/shadow").read_text(encoding="utf-8").replace("root:!", "root:", 1), 0o640)
    elif fault == "extra-group":
        model.put("etc/group", (t / "etc/group").read_text(encoding="utf-8").replace("sudo:x:27:", "sudo:x:27:night-shift"))
    elif fault == "home-directory":
        (t / "home/ubuntu").mkdir()
    elif fault in {"ssh-key", "ssh-daemon", "ssh-package", "host-private-key"}:
        name = {"ssh-key": "root/.ssh/authorized_keys", "ssh-daemon": "usr/sbin/sshd",
            "ssh-package": "var/lib/dpkg/status", "host-private-key": "etc/ssh/ssh_host_ed25519_key"}[fault]
        model.put(name, "Package: openssh-server\nStatus: install ok installed\n" if fault == "ssh-package" else _SECRET)
    elif fault in {"serial-grub", "serial-generated-grub", "serial-live"}:
        if fault == "serial-live":
            model.cmdline.write_text("console=ttyS0", encoding="ascii")
        else:
            model.put("etc/default/grub" if fault == "serial-grub" else "boot/grub/grub.cfg", "console=ttyS0 " + _SECRET)
    elif fault == "missing-python":
        (t / "usr/bin/python3.12").unlink()
    elif fault == "wrong-python-link":
        model.links[t / "usr/bin/python3"] = "../../" + _SECRET
    elif fault in {"users", "root-login", "password-auth", "package-update", "extra-cloud-key", "extra-write", "cloud-uuid"}:
        if fault == "users":
            model.user["users"] = [{"name": "ubuntu", "passwd": _SECRET}]
        elif fault in {"root-login", "password-auth", "package-update"}:
            model.user[{"root-login": "disable_root", "password-auth": "ssh_pwauth", "package-update": "package_update"}[fault]] = fault != "root-login"
        elif fault == "extra-cloud-key":
            model.user["runcmd"] = [_SECRET]
        elif fault == "extra-write":
            model.user["write_files"][0]["path"] = "/root/.ssh/authorized_keys"
        else:
            model.cloud["datasource"]["None"]["metadata"]["instance-id"] = _SECRET
        model.save_cloud()
    elif fault == "cloud-yaml":
        model.put("etc/cloud/cloud.cfg.d/99-installer.cfg", "[" + _SECRET, 0o600)
    elif fault == "missing-cloud":
        (t / "etc/cloud/cloud.cfg.d/99-installer.cfg").unlink()
    elif fault == "wrong-mount":
        model.mounted["filesystems"][0]["source"] = "/dev/sdb2"
    elif fault == "second-disk":
        model.inventory["blockdevices"].append({"path": "/dev/sdb", "type": "disk"})
    else:
        del model.inventory["blockdevices"][0]["children"]
    before = _snapshot(model.target.parent)
    assert audit.main(model.argv) == 1
    output = capsys.readouterr()
    assert "NS-REVIEW FAIL " in output.out and "NS-REVIEW RESULT FAIL" in output.out
    # A broken mount must NOT make every negative test pass accidentally.
    labels = {
        "PAYLOAD_BYTES_AND_PERMISSIONS": {"bootstrap", "unit", "owner", "group-write", "parent-write", "parent-owner", "symlink-file", "hardlink-file"},
        "LOCKED_SYSTEM_ACCOUNTS_AND_GROUPS": {"interactive-shell", "unlocked-root", "extra-user", "extra-group", "duplicate-uid", "alias-uid", "root-home"},
        "ENABLED_UNIT_AND_MASKED_GETTY": {"disabled-unit", "unmasked-getty"},
        "NO_SERIAL_CONSOLE_CONFLICT": {"serial-grub", "serial-generated-grub", "serial-live"},
        "PYTHON_AND_SYSTEMD_PRESENT": {"missing-python", "wrong-python-link"},
        "NO_SSH_SERVER_OR_CREDENTIALS": {"home-directory", "ssh-key", "ssh-daemon", "ssh-package", "host-private-key"},
        "INSTALLER_CLOUD_INIT_POLICY": {"users", "root-login", "password-auth", "package-update", "extra-cloud-key", "extra-write", "cloud-uuid", "cloud-yaml", "missing-cloud"},
        "TARGET_MOUNT": {"wrong-mount", "second-disk", "missing-disk-hierarchy"},
    }
    expected = next(label for label, faults in labels.items() if fault in faults)
    failures = [line for line in output.out.splitlines() if line.startswith("NS-REVIEW FAIL ")]
    assert failures == ["NS-REVIEW FAIL " + expected + ": inspection failed or policy differs"]
    assert _SECRET not in output.out + output.err and "Traceback" not in output.out + output.err
    assert _snapshot(model.target.parent) == before


@pytest.mark.parametrize("fault", ["non-root", "vendor", "live-id"])
def test_live_context_refusal_before_any_commands(model, fault, monkeypatch, capsys):
    if fault == "non-root":
        monkeypatch.setattr(audit.os, "geteuid", lambda: 1000)
    elif fault == "vendor":
        model.vendor.write_text(_SECRET, encoding="ascii")
    else:
        model.live_id.write_text(_SECRET, encoding="ascii")
    assert audit.main(model.argv) == 1 and model.calls == []
    assert _SECRET not in capsys.readouterr().out


def test_missing_yaml_and_inspection_errors_fail_without_raw_trace(model, monkeypatch, capsys):
    monkeypatch.setitem(__import__("sys").modules, "yaml", None)
    monkeypatch.setattr(audit, "_mount", lambda: (_ for _ in ()).throw(RuntimeError(_SECRET)))
    assert audit.main(model.argv) == 1
    output = capsys.readouterr()
    assert "FAIL TARGET_MOUNT" in output.out and "FAIL INSTALLER_CLOUD_INIT_POLICY" in output.out
    assert _SECRET not in output.out + output.err


@pytest.mark.parametrize("args", [[], ["--target", "/"], ["--instance-id", _SECRET, "--bootstrap-sha256", "0" * 64, "--unit-sha256", "0" * 64]])
def test_no_arbitrary_target_or_unreviewed_input_arguments(args, capsys):
    assert audit.main(args) == 1
    assert _SECRET not in capsys.readouterr().out


def test_auditor_source_has_only_read_file_opens_and_no_marker_writer():
    source = Path(audit.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    opens = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "open"]
    assert opens and all(node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == "rb" for node in opens)
    assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in {
        "write_bytes", "write_text", "mkdir", "touch", "unlink", "chmod", "chown",
    } for node in ast.walk(tree))
    assert "night-shift-image-review-approved" not in source


@pytest.mark.skipif(os.name != "nt", reason="native non-Linux context rejection")
def test_native_windows_never_reaches_real_target_or_commands(capsys):
    args = ["--instance-id", _ID, "--bootstrap-sha256", "0" * 64, "--unit-sha256", "0" * 64]
    assert audit.main(args) == 1
    assert "FAIL LIVE_CONTEXT" in capsys.readouterr().out


@pytest.mark.parametrize("fault", ["exit-status", "timeout", "not-json", "json-array", "oversized", "wrong-shape"])
def test_live_json_runner_errors_are_bounded_redacted_and_read_only(model, fault, monkeypatch, capsys):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        assert argv[0] == "/usr/bin/findmnt" and "--mountpoint" in argv
        assert kwargs == {"capture_output": True, "text": True, "timeout": 10, "check": False}
        if fault == "timeout":
            raise audit.subprocess.TimeoutExpired(argv, 10, output=_SECRET, stderr=_SECRET)
        stdout = {"exit-status": _SECRET, "not-json": _SECRET, "json-array": "[]",
            "oversized": _SECRET * 5000, "wrong-shape": '{"unexpected": true}'}[fault]
        return SimpleNamespace(returncode=1 if fault == "exit-status" else 0,
            stdout=stdout, stderr=_SECRET)

    monkeypatch.setattr(audit, "_json_command", _NATIVE_JSON_COMMAND)
    monkeypatch.setattr(audit.subprocess, "run", fake_run)
    before = _snapshot(model.target.parent)
    assert audit.main(model.argv) == 1
    output = capsys.readouterr()
    assert len(calls) == 1 and "FAIL TARGET_MOUNT" in output.out
    assert _SECRET not in output.out + output.err and "Traceback" not in output.out + output.err
    assert _snapshot(model.target.parent) == before
