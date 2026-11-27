"""B2 host step: stage a reviewed preview and read back the destination bytes."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any

from night_shifts.gate_b_files import open_directory
from night_shifts.gate_b_preview import _build_preview, _hash_stream, build_preview, canonical, sha256
from night_shifts.gate_b_profile import OID, PreviewError, Profile, Source, collisions_key, load_profile, portable

_MANIFEST = "manifest.json"
_SEAL = "sealed.json"
_WORKSPACE = "workspace"
_MAX_REVIEW_BYTES = 128 * 1024**2
_MAX_MEMBERS = 200_000
_SHA = re.compile(r"[0-9a-f]{64}")


def _is_sha(value: object) -> bool:
    return isinstance(value, str) and _SHA.fullmatch(value) is not None


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PreviewError(f"duplicate preview field: {key!r}")
        result[key] = value
    return result


def _read_review(path: Path) -> dict[str, Any]:
    with path.open("rb") as stream:
        data = stream.read(_MAX_REVIEW_BYTES + 1)
    if len(data) > _MAX_REVIEW_BYTES:
        raise PreviewError("preview file exceeds 128 MiB; split the sources into smaller workspaces")
    # Windows PowerShell 5.1 may write UTF-16 when redirecting stdout to a file.
    encoding = "utf-16" if data.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
    try:
        raw = json.loads(data.decode(encoding), object_pairs_hook=_unique)
    except (ValueError, RecursionError) as exc:
        raise PreviewError("preview is not valid JSON") from exc
    if not isinstance(raw, dict):
        raise PreviewError("expected a full preview object, not --summary")
    return raw


def _entries(raw: object) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, list) or len(raw) > _MAX_MEMBERS:
        raise PreviewError("invalid workspace member list")
    result: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    for entry in raw:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise PreviewError("invalid workspace member")
        name = portable(tuple(entry["path"].split("/")))
        key = collisions_key(name)
        if key in seen:
            raise PreviewError(f"duplicate or colliding workspace member: {name!r}")
        seen.add(key)
        if entry.get("kind") == "directory":
            valid = set(entry) == {"path", "kind"}
        else:
            valid = (set(entry) == {"path", "kind", "size", "mode", "sha256"} and entry["kind"] == "file"
                     and type(entry["size"]) is int and 0 <= entry["size"] <= 1024**4
                     and entry["mode"] in ("100644", "100755") and _is_sha(entry["sha256"]))
        if not valid:
            raise PreviewError(f"invalid manifest member: {name!r}")
        result[name] = entry
    if list(result) != sorted(result):
        raise PreviewError("manifest members are not in canonical path order")
    for name in result:
        parent, sep, _ = name.rpartition("/")
        if sep and result.get(parent, {}).get("kind") != "directory":
            raise PreviewError(f"manifest member has no directory parent: {name!r}")
    return result


@dataclass(frozen=True)
class _ReviewedSource:
    revision: str | None
    upstream_tip: str | None
    entries: dict[str, dict[str, Any]]


@dataclass(frozen=True)
class _Review:
    manifest: dict[str, Any]
    sources: dict[str, _ReviewedSource]
    preview_sha256: str
    manifest_sha256: str


def _review(profile: Profile, raw: dict[str, Any], approved: str) -> _Review:
    summary = {key: value for key, value in raw.items() if key not in ("manifest", "preview_sha256")}
    manifest = raw.get("manifest")
    if not _is_sha(approved) or approved != raw.get("preview_sha256") or approved != sha256(summary):
        raise PreviewError("preview does not match the explicitly approved SHA-256")
    if (not isinstance(manifest, dict) or set(manifest) != {"version", "sources"}
            or type(manifest["version"]) is not int or manifest["version"] != 1):
        raise PreviewError("the complete version 1 manifest is required (not --summary)")
    manifest_sha = sha256(manifest)
    if manifest_sha != summary.get("manifest_sha256"):
        raise PreviewError("manifest does not match the approved preview")
    summaries, records = summary.get("sources"), manifest["sources"]
    if (type(summary.get("version")) is not int or summary["version"] != 1
            or summary.get("max_bytes") != profile.max_bytes or not isinstance(summaries, list)
            or not isinstance(records, list) or len(summaries) != len(profile.sources)
            or len(records) != len(profile.sources) or not profile.sources):
        raise PreviewError("preview does not match the workspace profile")
    reviewed: dict[str, _ReviewedSource] = {}
    count = total_bytes = total_files = 0
    for spec, info, record in zip(profile.sources, summaries, records, strict=True):
        portable((spec.name,))
        settings = {"name": spec.name, "kind": spec.kind, "access": spec.access, "path": str(spec.path),
                    "revision_requested": spec.revision if spec.kind == "git" else None,
                    "upstream": spec.upstream, "allow_unpublished": spec.allow_unpublished,
                    "include": list(spec.include), "exclude": list(spec.exclude)}
        if (not isinstance(info, dict) or not isinstance(record, dict) or spec.name in reviewed
                or any(info.get(key) != value for key, value in settings.items())
                or set(record) != {"entries", "name", "kind", "access", "revision"}
                or any(record[key] != settings[key] for key in ("name", "kind", "access"))):
            raise PreviewError(f"reviewed settings do not match source {spec.name!r}")
        revision, tip = record["revision"], info.get("upstream_tip")
        if revision != info.get("revision"):
            raise PreviewError("inconsistent Git revision in preview")
        if spec.kind == "git":
            if (not isinstance(revision, str) or not OID.fullmatch(revision)
                    or (spec.revision != "HEAD" and revision != spec.revision)
                    or (spec.allow_unpublished and tip is not None)
                    or (not spec.allow_unpublished and (not isinstance(tip, str) or not OID.fullmatch(tip)))):
                raise PreviewError(f"invalid reviewed Git provenance for {spec.name!r}")
        elif revision is not None or tip is not None:
            raise PreviewError("unexpected Git provenance on a folder source")
        entries = _entries(record["entries"])
        count += len(entries)
        files = [e for e in entries.values() if e["kind"] == "file"]
        total_files += len(files)
        total_bytes += sum(e["size"] for e in files)
        if count > _MAX_MEMBERS or total_bytes > profile.max_bytes:
            raise PreviewError("approved workspace exceeds staging limits")
        reviewed[spec.name] = _ReviewedSource(revision, tip, entries)
    if (len({collisions_key(name) for name in reviewed}) != len(reviewed)
            or (total_files, total_bytes) != (summary.get("total_files"), summary.get("total_bytes"))):
        raise PreviewError("invalid source names or manifest totals")
    return _Review(manifest, reviewed, approved, manifest_sha)


@dataclass(frozen=True)
class _SourceWriter:
    destination: Path
    approved: _ReviewedSource

    def bind_git(self, revision: str, upstream_tip: str | None) -> None:
        if (revision, upstream_tip) != (self.approved.revision, self.approved.upstream_tip):
            raise PreviewError("Git revision or cached upstream tip changed after review")

    def file(self, path: str, stream: IO[bytes], length: int, mode: str) -> str:
        entry = self.approved.entries.get(path)
        if entry is None or (entry.get("kind"), entry.get("size"), entry.get("mode")) != ("file", length, mode):
            raise PreviewError(f"file not in the approved manifest or metadata changed: {path!r}")
        output = self.destination.joinpath(*path.split("/"))
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("xb") as target:
            digest = _hash_stream(stream, length, target)
        if digest != entry["sha256"]:
            raise PreviewError(f"file bytes changed after review: {path!r}")
        return digest


def _file_data(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # The payload filesystem need not preserve Unix executable bits. They are
    # recorded in the sealed manifest for the guest's writable copies.
    return [{key: value for key, value in record.items() if key != "mode"} for record in entries]


def _verify_payload(destination: Path, review: _Review, max_bytes: int) -> None:
    sources = tuple(Source(name, "folder", destination / _WORKSPACE / name, "read-only") for name in review.sources)
    with open_directory(destination / _WORKSPACE) as workspace:
        if dict(workspace.entries()) != dict.fromkeys(review.sources, True):
            raise PreviewError("unexpected staged source folders")
    manifest = build_preview(Profile(sources, max_bytes))["manifest"]
    assert isinstance(manifest, dict)
    for source in manifest["sources"]:
        expected = review.sources[source["name"]]
        if _file_data(source["entries"]) != _file_data(list(expected.entries.values())):
            raise PreviewError(f"destination readback differs for {source['name']!r}")
    with open_directory(destination) as root, root.file(_MANIFEST) as stream:
        size = len(canonical(review.manifest))
        if _hash_stream(stream, size) != review.manifest_sha256 or stream.read(1):
            raise PreviewError("destination manifest differs from the reviewed manifest")


def stage_workspace(profile: Profile, preview_path: Path, approved: str, destination: Path) -> dict[str, str]:
    """Write only to a fresh child of an operator-controlled local directory."""
    review = _review(profile, _read_review(preview_path), approved)
    if not destination.is_absolute() or ".." in destination.parts or len(destination.parts) < 3:
        raise PreviewError("destination must be an absolute new directory under a local work folder")
    portable(destination.parts[1:])
    with open_directory(destination.parent):
        for source in profile.sources:
            with open_directory(source.path):
                if any(parent.samefile(source.path) for parent in destination.parents):
                    raise PreviewError("destination must not be inside a source directory")
        destination.mkdir(mode=0o700, exist_ok=False)
        try:
            with open_directory(destination):
                workspace = destination / _WORKSPACE
                workspace.mkdir()

                def sink_for(source: Source) -> _SourceWriter:
                    target = workspace / source.name
                    target.mkdir(exist_ok=False)
                    return _SourceWriter(target, review.sources[source.name])

                actual = _build_preview(profile, sink_for)
                if actual["preview_sha256"] != review.preview_sha256:
                    raise PreviewError("source tree or selection changed after review")
                for name, src in review.sources.items():
                    for path, record in src.entries.items():
                        if record["kind"] == "directory":
                            (workspace / name).joinpath(*path.split("/")).mkdir(parents=True, exist_ok=True)
                with (destination / _MANIFEST).open("xb") as stream:
                    stream.write(canonical(review.manifest))
                _verify_payload(destination, review, profile.max_bytes)
                seal = {"preview_sha256": review.preview_sha256, "manifest_sha256": review.manifest_sha256}
                with (destination / _SEAL).open("xb") as stream:
                    stream.write(canonical(seal))
        except BaseException:
            try:
                shutil.rmtree(destination)
            except OSError as exc:
                raise PreviewError(f"could not remove incomplete staging directory {str(destination)!r}; do not use it") from exc
            raise
    return seal


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", type=Path)
    parser.add_argument("preview", type=Path, help="full saved B1 preview, including the manifest")
    parser.add_argument("destination", type=Path, help="new staging directory under an operator-controlled work folder")
    parser.add_argument("--approve-preview-sha256", required=True, help="SHA-256 of the exact preview the operator reviewed")
    args = parser.parse_args()
    try:
        seal = stage_workspace(load_profile(args.profile), args.preview, args.approve_preview_sha256, args.destination)
    except (PreviewError, OSError, RecursionError) as exc:
        print(f"Gate B staging failed: {str(exc).encode('ascii', 'backslashreplace').decode('ascii')}", file=sys.stderr)
        return 2
    print(json.dumps({"status": "sealed", "destination": str(args.destination), **seal}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
