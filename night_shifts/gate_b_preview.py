"""B1: build a read-only, content-addressed workspace preview (no VM or network)."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Protocol

from night_shifts.gate_b_files import Directory, open_directory, signature
from night_shifts.gate_b_git import blob_size, open_git
from night_shifts.gate_b_profile import (
    MAX_DEPTH,
    PreviewError,
    Profile,
    Source,
    collisions_key,
    load_profile,
    matches,
    portable,
)

_MAX_ENTRIES = 200_000
_CHUNK = 1024 * 1024


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def sha256(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def _hash_stream(stream: IO[bytes], count: int, output: IO[bytes] | None = None) -> str:
    digest = hashlib.sha256()
    while count:
        chunk = stream.read(min(count, _CHUNK))
        if not chunk:
            raise PreviewError("file ended before its declared size")
        digest.update(chunk)
        if output is not None and output.write(chunk) != len(chunk):
            raise PreviewError("short write while staging a workspace file")
        count -= len(chunk)
    return digest.hexdigest()


def _looks_sensitive(path: str) -> bool:
    name = path.rsplit("/", 1)[-1].casefold()
    return (name in {".git", ".ssh", ".aws", ".netrc", "credentials", "credentials.json",
                     "apikey.txt", "secrets.json", "providers.toml"}
            or name.startswith((".env", "id_rsa", "id_ed25519"))
            or name.endswith((".key", ".pem", ".pfx", ".p12", ".kdbx")))


@dataclass
class _Budget:
    remaining: int
    entries: int = 0

    def entry(self, parts: tuple[str, ...]) -> None:
        self.entries += 1
        if self.entries > _MAX_ENTRIES or len(parts) > MAX_DEPTH:
            raise PreviewError("workspace exceeds the entry count or path depth limit")

    def bytes(self, size: int) -> None:
        if not 0 <= size <= self.remaining:
            raise PreviewError("selected workspace exceeds max_bytes")
        self.remaining -= size


class _CopySink(Protocol):
    def bind_git(self, revision: str, upstream_tip: str | None) -> None: ...

    def file(self, path: str, stream: IO[bytes], length: int, mode: str) -> str: ...


@dataclass
class _Scan:
    source: Source
    budget: _Budget
    sink: _CopySink | None = None
    entries: dict[str, dict[str, object]] = field(default_factory=dict)
    names: dict[str, str] = field(default_factory=dict)
    warnings: set[str] = field(default_factory=set)
    excluded: int = 0
    not_included: int = 0
    size: int = 0
    files: int = 0
    revision: str | None = None
    upstream_tip: str | None = None

    def exclude(self, parts: tuple[str, ...]) -> bool:
        if not any(matches(pattern, parts) for pattern in self.source.exclude):
            return False
        self.excluded += 1
        return True

    def include(self, parts: tuple[str, ...]) -> bool:
        selection = self.source.include
        return not selection or any(matches(pattern, parts) for pattern in selection)

    def _entry(self, path: str, record: dict[str, object]) -> None:
        other = self.names.setdefault(collisions_key(path), path)
        if other != path:
            raise PreviewError(f"case or Unicode collision: {other!r} and {path!r}")
        previous = self.entries.setdefault(path, record)
        if previous is not record and (previous["kind"] != "directory" or record["kind"] != "directory"):
            raise PreviewError(f"duplicate path or file/directory collision: {path!r}")
        if _looks_sensitive(path):
            self.warnings.add(path)

    def directory(self, parts: tuple[str, ...]) -> None:
        for depth in range(1, len(parts) + 1):
            path = portable(parts[:depth])
            self._entry(path, {"path": path, "kind": "directory"})

    def file(self, parts: tuple[str, ...], stream: IO[bytes], length: int, mode: str) -> None:
        path = portable(parts)
        self.directory(parts[:-1])
        self.budget.bytes(length)
        digest = _hash_stream(stream, length) if self.sink is None else self.sink.file(path, stream, length, mode)
        self._entry(path, {"path": path, "kind": "file", "size": length, "sha256": digest, "mode": mode})
        self.size += length
        self.files += 1

    def folder(self, directory: Directory, prefix: tuple[str, ...] = ()) -> None:
        for name, is_dir in directory.entries():
            parts = (*prefix, name)
            self.budget.entry(parts)
            if self.exclude(parts):
                continue
            if is_dir:
                portable(parts)
                with directory.child(name) as child:
                    if self.include(parts):
                        self.directory(parts)
                    self.folder(child, parts)
            elif not self.include(parts):
                self.not_included += 1
            else:
                portable(parts)
                with directory.file(name) as stream:
                    before = os.fstat(stream.fileno())
                    mode = "100755" if os.name != "nt" and before.st_mode & stat.S_IXUSR else "100644"
                    self.file(parts, stream, before.st_size, mode)
                    if stream.read(1) or signature(before) != signature(os.fstat(stream.fileno())):
                        raise PreviewError(f"file changed while it was being read: {'/'.join(parts)!r}")

    def git(self) -> None:
        with open_git(self.source) as git:
            self.revision, self.upstream_tip = git.revision, git.upstream_tip
            if self.sink is not None:
                self.sink.bind_git(git.revision, git.upstream_tip)
            with (git.reader("ls-tree", "--full-tree", "-rtz", git.revision) as (_, listing),
                  git.reader("cat-file", "--batch", batch=True) as (stdin, blobs)):
                assert stdin is not None
                pruned: set[tuple[str, ...]] = set()
                for mode, kind, oid, parts in git.listing(listing):
                    self.budget.entry(parts)
                    if any(parts[:n] in pruned for n in range(1, len(parts))):
                        continue
                    if self.exclude(parts):
                        if kind == "tree":
                            pruned.add(parts)
                        continue
                    if kind == "tree" and mode == "040000":
                        if self.include(parts):
                            self.directory(parts)
                    elif not self.include(parts):
                        self.not_included += 1
                    elif kind == "blob" and mode in ("100644", "100755"):
                        length = blob_size(stdin, blobs, oid)
                        self.file(parts, blobs, length, mode)
                        if blobs.read(1) != b"\n":
                            raise PreviewError("Git blob delimiter is missing")
                    else:
                        raise PreviewError(f"Git link, submodule or unsupported mode: {'/'.join(parts)!r}")

    def manifest(self) -> dict[str, object]:
        return {"name": self.source.name, "kind": self.source.kind, "access": self.source.access,
                "revision": self.revision, "entries": [self.entries[path] for path in sorted(self.entries)]}

    def summary(self) -> dict[str, object]:
        return {"name": self.source.name, "kind": self.source.kind, "access": self.source.access,
                "path": str(self.source.path), "revision_requested": self.source.revision if self.revision else None,
                "revision": self.revision, "upstream": self.source.upstream, "upstream_tip": self.upstream_tip,
                "allow_unpublished": self.source.allow_unpublished, "include": self.source.include,
                "exclude": self.source.exclude, "files": self.files, "directories": len(self.entries) - self.files,
                "bytes": self.size, "excluded_entries": self.excluded, "not_included_files": self.not_included,
                "sensitive_name_warnings": sorted(self.warnings)}


def build_preview(profile: Profile) -> dict[str, object]:
    """Hash selected file bytes, not paths alone. No source content is copied or executed."""
    return _build_preview(profile)


def _build_preview(profile: Profile, sink_for: Callable[[Source], _CopySink] | None = None) -> dict[str, object]:
    budget = _Budget(profile.max_bytes)
    scans = []
    for source in profile.sources:
        scan = _Scan(source, budget, None if sink_for is None else sink_for(source))
        try:
            if source.kind == "git":
                scan.git()
            else:
                with open_directory(source.path) as directory:
                    scan.folder(directory)
        except (PreviewError, OSError, subprocess.SubprocessError) as exc:
            raise PreviewError(f"source {source.name!r}: {exc}") from exc
        scans.append(scan)
    manifest = {"version": 1, "sources": [scan.manifest() for scan in scans]}
    summary = {"version": 1, "max_bytes": profile.max_bytes,
               "total_files": sum(scan.files for scan in scans),
               "total_bytes": profile.max_bytes - budget.remaining,
               "sources": [scan.summary() for scan in scans], "manifest_sha256": sha256(manifest)}
    return {**summary, "preview_sha256": sha256(summary), "manifest": manifest}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", type=Path, help="operator-owned JSON workspace profile")
    parser.add_argument("--summary", action="store_true", help="omit the individual manifest entries")
    args = parser.parse_args()
    try:
        result = build_preview(load_profile(args.profile))
    except (PreviewError, OSError) as exc:
        print(f"Gate B preview failed: {str(exc).encode('ascii', 'backslashreplace').decode('ascii')}", file=sys.stderr)
        return 2
    if args.summary:
        del result["manifest"]
    json.dump(result, sys.stdout, indent=2, ensure_ascii=True)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
