from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys

import pytest

from night_shifts.gate_b_files import open_directory
from night_shifts.gate_b_preview import build_preview, sha256
from night_shifts.gate_b_profile import PreviewError, load_profile, portable


def _profile(tmp_path, *sources, **extra):
    path = tmp_path / "workspace.json"
    path.write_text(json.dumps({"version": 1, "sources": sources, **extra}), encoding="utf-8")
    return path


def _folder(path, **extra):
    return {"kind": "folder", "name": "data", "path": str(path), **extra}


def _git(root, *args):
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True,
                          text=True, timeout=15, env=env).stdout.strip()


@pytest.fixture
def git_checkout(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("local Git required")
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "fixture@example.invalid")
    _git(root, "config", "user.name", "Gate B Fixture")
    _git(root, "config", "core.autocrlf", "false")
    (root / "committed.bin").write_bytes(b"\x00published\xff")
    (root / ".gitattributes").write_text("*.bin filter=fail\n", encoding="ascii")
    _git(root, "add", "--all")
    _git(root, "commit", "-m", "First committed fixture")
    published = _git(root, "rev-parse", "HEAD")
    _git(root, "update-ref", "refs/remotes/origin/main", published)
    (root / "next.txt").write_bytes(b"local commit only")
    _git(root, "add", "next.txt")
    _git(root, "commit", "-m", "Local-only fixture")
    (root / "committed.bin").write_bytes(b"modified on disk")
    (root / ".env").write_bytes(b"untracked fixture")
    return root, published


def test_multi_source_exact_committed_tree_and_folder(tmp_path, git_checkout):
    root, head = git_checkout
    # Enable the deliberately broken filter only after fixture setup. Raw Git
    # object reads must succeed without asking Git for working-tree conversions.
    _git(root, "config", "filter.fail.required", "true")
    _git(root, "config", "filter.fail.smudge", "nonexistent-gate-b-fixture-filter")
    data = tmp_path / "measurements"
    data.mkdir()
    (data / "empty").mkdir()
    (data / "café reading.bin").write_bytes(b"\x01\xff" * (3 * 1024**2))
    (data / ".env").write_bytes(b"example only")
    git = {"kind": "git", "name": "code", "path": str(root), "access": "writable",
           "revision": head, "upstream": "refs/remotes/origin/main"}
    profile = load_profile(_profile(tmp_path, git, _folder(data)))
    result = build_preview(profile)
    manifest = result["manifest"]
    first, second = manifest["sources"]
    assert first["revision"] == head and first["access"] == "writable"
    assert second["access"] == "read-only"
    assert [entry["path"] for entry in first["entries"]] == [".gitattributes", "committed.bin"]
    assert first["entries"][1]["sha256"] == hashlib.sha256(b"\x00published\xff").hexdigest()
    assert second["entries"] == [
        {"path": ".env", "kind": "file", "size": 12, "sha256": hashlib.sha256(b"example only").hexdigest(),
         "mode": "100644"},
        {"path": "café reading.bin", "kind": "file", "size": 6 * 1024**2,
         "sha256": hashlib.sha256(b"\x01\xff" * (3 * 1024**2)).hexdigest(), "mode": "100644"},
        {"path": "empty", "kind": "directory"},
    ]
    assert result["sources"][1]["sensitive_name_warnings"] == [".env"]
    assert str(data) not in json.dumps(manifest) and "example only" not in json.dumps(result)
    assert result["manifest_sha256"] == sha256(manifest)
    assert result == build_preview(profile)
    (data / ".env").write_bytes(b"example alt!")  # same length, different content
    changed = build_preview(profile)
    assert result["preview_sha256"] != changed["preview_sha256"]
    assert (root / "committed.bin").read_bytes() == b"modified on disk"


def test_git_unpublished_requires_opt_in(tmp_path, git_checkout):
    root, first = git_checkout
    spec = {"kind": "git", "name": "code", "path": str(root)}
    with pytest.raises(PreviewError, match="remote-tracking upstream"):
        load_profile(_profile(tmp_path, spec))
    with pytest.raises(PreviewError, match="not proven reachable"):
        build_preview(load_profile(_profile(tmp_path, {**spec, "upstream": "refs/remotes/origin/main"})))
    _git(root, "symbolic-ref", "refs/remotes/origin/alias", "refs/heads/main")
    with pytest.raises(PreviewError, match="not a symbolic reference"):
        build_preview(load_profile(_profile(tmp_path, {**spec, "upstream": "refs/remotes/origin/alias"})))
    result = build_preview(load_profile(_profile(tmp_path, {**spec, "allow_unpublished": True})))
    source = result["sources"][0]
    assert source["revision"] != first and source["upstream_tip"] is None
    assert source["files"] == 3


def test_git_link_refused_unless_explicitly_excluded(tmp_path, git_checkout):
    root, _ = git_checkout
    (root / "target").write_text("sample", encoding="ascii")
    oid = _git(root, "hash-object", "-w", "target")
    _git(root, "update-index", "--add", "--cacheinfo", f"120000,{oid},link")
    _git(root, "commit", "-m", "Git link fixture")
    spec = {"kind": "git", "name": "code", "path": str(root), "allow_unpublished": True}
    with pytest.raises(PreviewError, match="Git link"):
        build_preview(load_profile(_profile(tmp_path, spec)))
    result = build_preview(load_profile(_profile(tmp_path, {**spec, "exclude": ["link"]})))
    assert result["sources"][0]["excluded_entries"] == 1


def test_folder_filters_and_limits(tmp_path):
    data = tmp_path / "data"
    (data / "nested" / "private").mkdir(parents=True)
    (data / "a.txt").write_bytes(b"abc")
    (data / "a.bin").write_bytes(b"binary")
    (data / "nested" / "b.txt").write_bytes(b"42")
    (data / "nested" / "private" / "c.txt").write_bytes(b"not selected")
    spec = _folder(data, include=["**/*.txt"], exclude=["nested/private/**"])
    result = build_preview(load_profile(_profile(tmp_path, spec, max_bytes=5)))
    assert [e["path"] for e in result["manifest"]["sources"][0]["entries"]] == [
        "a.txt", "nested", "nested/b.txt",
    ]
    assert result["total_bytes"] == 5
    assert result["sources"][0]["excluded_entries"] == result["sources"][0]["not_included_files"] == 1
    with pytest.raises(PreviewError, match="max_bytes"):
        build_preview(load_profile(_profile(tmp_path, spec, max_bytes=4)))


def test_folder_does_not_follow_junction_or_symlink(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "example.txt").write_text("not in the source", encoding="ascii")
    data = tmp_path / "data"
    data.mkdir()
    link = data / "linked"
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(outside), str(link))
    else:
        link.symlink_to(outside, target_is_directory=True)
    try:
        with pytest.raises(PreviewError, match="link|reparse"):
            build_preview(load_profile(_profile(tmp_path, _folder(data))))
        with pytest.raises(PreviewError, match="linked"):
            build_preview(load_profile(_profile(tmp_path, _folder(link))))
        result = build_preview(load_profile(_profile(tmp_path, _folder(data, exclude=["linked/**"]))))
        assert result["total_files"] == 0 and result["sources"][0]["excluded_entries"] == 1
    finally:
        if os.name == "nt":
            link.rmdir()
        else:
            link.unlink()


@pytest.mark.skipif(os.name != "nt", reason="Windows directory-handle sharing semantics")
def test_windows_holds_source_directory_against_rename(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    renamed = tmp_path / "renamed"
    with open_directory(data):
        with pytest.raises(PermissionError):
            data.rename(renamed)
    data.rename(renamed)
    assert renamed.is_dir()


def test_folder_rejects_hardlinked_file(tmp_path):
    outside = tmp_path / "original"
    outside.write_bytes(b"outside source")
    data = tmp_path / "data"
    data.mkdir()
    os.link(outside, data / "linked")
    with pytest.raises(PreviewError, match="multiply linked"):
        build_preview(load_profile(_profile(tmp_path, _folder(data))))


@pytest.mark.parametrize("name", ["..", "Nul.txt", "LPT².bin", "relative:stream", "trailing ", "x\n"])
def test_nonportable_names_are_refused(name):
    with pytest.raises(PreviewError):
        portable((name,))


def test_profile_invalid_fields_and_names(tmp_path):
    spec = _folder(tmp_path)
    for sources in ((spec, spec), ({**spec, "name": "../outside"},), ({**spec, "include": ["../x"]},),
                    ({**spec, "typo": True},), ({**spec, "path": "relative"},)):
        with pytest.raises(PreviewError):
            load_profile(_profile(tmp_path, *sources))
    path = tmp_path / "duplicate.json"
    path.write_text('{"version":1,"version":1,"sources":[]}', encoding="ascii")
    with pytest.raises(PreviewError, match="duplicate profile field"):
        load_profile(path)


def test_cli_summary_is_json_and_omits_file_list(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "sample.bin").write_bytes(b"\x01\x02")
    path = _profile(tmp_path, _folder(data))
    result = subprocess.run([sys.executable, "-m", "night_shifts.gate_b_preview", str(path), "--summary"],
                            check=True, capture_output=True, timeout=15)
    summary = json.loads(result.stdout)
    assert summary["total_files"] == 1 and "manifest" not in summary
    assert len(summary["preview_sha256"]) == 64
