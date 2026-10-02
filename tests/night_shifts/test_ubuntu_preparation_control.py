"""Control path/ACL policy models plus a read-only native Windows reader check."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import night_shifts.ubuntu_preparation_control as control
from night_shifts.ubuntu_preparation_control import AclRule, AclSnapshot, PreparationError

_USER = "S-1-5-21-1-2-3-1001"
_ALLOWED = frozenset({_USER, "S-1-5-18", "S-1-5-32-544"})
_WORKER = "S-1-15-3-1024-2268835264-3721307629-241982045-173645152-1490879176-104643441-2915960892-1612460704"
_FULL = 0x1F01FF


def _private() -> AclSnapshot:
    return AclSnapshot(_USER, tuple(AclRule(sid, _FULL) for sid in sorted(_ALLOWED)))


@pytest.fixture
def modeled_control(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    workspace = tmp_path / ("a" * 32)
    workspace.mkdir()
    directory = control.preparation_control_path(workspace)
    directory.mkdir()
    monkeypatch.setattr(control, "_current_user_sid", lambda: _USER)
    monkeypatch.setattr(control, "_read_acl", lambda path: _private())
    return workspace, directory


def test_control_is_exact_identity_sibling_not_worker_descendant(tmp_path: Path) -> None:
    workspace = tmp_path / ("a" * 32)
    path = control.preparation_control_path(workspace)
    assert path == tmp_path / (("a" * 32) + ".control")
    assert workspace not in path.parents
    assert path.parent == workspace.parent
    assert not path.exists()  # derivation does not create state or migrate


@pytest.mark.parametrize("name", ["personal-vm", "a" * 31, "A" * 32, "a" * 32 + ".control"])
def test_control_refuses_wrong_identity(tmp_path: Path, name: str) -> None:
    with pytest.raises(PreparationError, match="identity-scoped"):
        control.preparation_control_path(tmp_path / name)


def test_control_refuses_relative_workspace() -> None:
    with pytest.raises(PreparationError, match="absolute"):
        control.preparation_control_path(Path("a" * 32))


def test_simple_private_acl_is_accepted_without_repair() -> None:
    control._validate_acl(_private(), _ALLOWED, private=True)


@pytest.mark.parametrize("sid", [_WORKER, "S-1-5-83-0", "S-1-1-0", "S-1-5-11", "S-1-5-32-545"])
@pytest.mark.parametrize("mask", [_FULL, 0x1200A9])
def test_private_control_refuses_worker_or_broad_access_even_read_only(sid: str, mask: int) -> None:
    snapshot = AclSnapshot(_USER, (*_private().rules, AclRule(sid, mask)))
    with pytest.raises(PreparationError, match="only operator"):
        control._validate_acl(snapshot, _ALLOWED, private=True)


@pytest.mark.parametrize("problem", ["owner", "empty", "missing-user", "deny", "callback", "limited", "inherit-only"])
def test_private_acl_refuses_unknown_or_incomplete_policy(problem: str) -> None:
    snapshot = _private()
    if problem == "owner":
        snapshot = AclSnapshot("S-1-5-11", snapshot.rules)
    elif problem == "empty":
        snapshot = AclSnapshot(_USER, ())
    elif problem == "missing-user":
        snapshot = AclSnapshot(_USER, tuple(rule for rule in snapshot.rules if rule.sid != _USER))
    else:
        changed = AclRule(
            _USER, _FULL if problem != "limited" else 0x1200A9,
            flags=8 if problem == "inherit-only" else 0,
            kind=1 if problem == "deny" else 9 if problem == "callback" else 0,
        )
        snapshot = AclSnapshot(_USER, tuple(changed if rule.sid == _USER else rule for rule in snapshot.rules))
    with pytest.raises(PreparationError):
        control._validate_acl(snapshot, _ALLOWED, private=True)


@pytest.mark.parametrize("mask", [0x40, 0x10000, 0x40000, 0x80000, 0x10000000])
def test_ancestor_replacement_or_permission_grants_are_refused(mask: int) -> None:
    snapshot = AclSnapshot(_USER, (*_private().rules, AclRule(_WORKER, mask)))
    with pytest.raises(PreparationError, match="replacement or ACL"):
        control._validate_acl(snapshot, _ALLOWED, private=False)


def test_volume_root_modify_is_not_permission_to_replace_private_descendants() -> None:
    snapshot = AclSnapshot("S-1-5-18", (AclRule("S-1-5-11", 0x1301BF),))
    control._validate_acl(snapshot, _ALLOWED, private=False, volume_root=True)
    with pytest.raises(PreparationError):
        control._validate_acl(snapshot, _ALLOWED, private=False)


def test_ancestor_read_access_and_inherit_only_creator_rule_do_not_grant_active_replacement() -> None:
    snapshot = AclSnapshot(_USER, (AclRule("S-1-5-11", 0x1200A9), AclRule("S-1-3-0", 0x10000000, flags=8)))
    control._validate_acl(snapshot, _ALLOWED, private=False)
    with pytest.raises(PreparationError):
        control._validate_acl(snapshot, _ALLOWED, private=True)


def test_permission_reader_checks_file_parent_and_all_ancestors(modeled_control, monkeypatch) -> None:
    workspace, directory = modeled_control
    manifest = directory / "manifest.json"
    manifest.write_bytes(b"test manifest")
    seen = []
    def read(path):
        seen.append(path)
        return _private()
    monkeypatch.setattr(control, "_read_acl", read)
    assert control.checked_preparation_control(workspace) == directory
    assert manifest in seen and directory in seen and directory.parent in seen
    assert Path(directory.anchor) in seen
    assert workspace not in seen  # VM storage ACLs are not control authority


@pytest.mark.parametrize("where", ["directory", "parent", "file", "ancestor"])
def test_permission_drift_at_any_control_boundary_is_refused(modeled_control, monkeypatch, where) -> None:
    workspace, directory = modeled_control
    manifest = directory / "manifest.json"
    manifest.write_bytes(b"test manifest")
    bad = {"directory": directory, "parent": directory.parent, "file": manifest, "ancestor": directory.parent.parent}[where]
    def read(path):
        if path == bad:
            return AclSnapshot(_USER, (*_private().rules, AclRule(_WORKER, _FULL)))
        return _private()
    monkeypatch.setattr(control, "_read_acl", read)
    with pytest.raises(PreparationError):
        control.checked_preparation_control(workspace)
    assert manifest.read_bytes() == b"test manifest"  # no automatic ACL/state repair


def test_missing_control_never_adopts_legacy_worker_manifest(tmp_path: Path) -> None:
    workspace = tmp_path / ("a" * 32)
    workspace.mkdir()
    (workspace / "manifest.json").write_bytes(b"legacy worker-writable state")
    with pytest.raises(PreparationError, match="legacy migration"):
        control.checked_preparation_control(workspace)
    assert not control.preparation_control_path(workspace).exists()


@pytest.mark.parametrize("problem", ["unknown-file", "directory", "hard-link"])
def test_control_entries_must_be_known_regular_single_link_files(modeled_control, tmp_path, problem) -> None:
    workspace, directory = modeled_control
    if problem == "unknown-file":
        (directory / "unreviewed.json").write_bytes(b"extra")
    elif problem == "directory":
        (directory / "manifest.json").mkdir()
    else:
        source = tmp_path / "test-worker-file"
        source.write_bytes(b"not isolated")
        os.link(source, directory / "manifest.json")
    with pytest.raises(PreparationError):
        control.checked_preparation_control(workspace)


def test_production_acl_api_has_no_non_windows_success_fallback(monkeypatch) -> None:
    with monkeypatch.context() as context:
        context.setattr(control.os, "name", "posix")
        with pytest.raises(PreparationError, match="require Windows"):
            control._api()


@pytest.mark.skipif(os.name != "nt", reason="native read-only Windows ACL API")
def test_native_acl_reader_reads_only_test_owned_directory(tmp_path: Path) -> None:
    snapshot = control._read_acl(tmp_path)
    assert snapshot.owner.startswith("S-1-")
    assert isinstance(snapshot.rules, tuple) and snapshot.rules
    assert control._current_user_sid().startswith("S-1-")
