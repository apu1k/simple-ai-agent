"""Operator-owned profile and portable path rules for Gate B previews."""

from __future__ import annotations

import fnmatch
import json
import re
import unicodedata
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Literal


class PreviewError(RuntimeError):
    """A complete, reviewable preview could not be produced."""


OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
_NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,62}")
_UPSTREAM = re.compile(r"refs/remotes/[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9_./-]+")
_DEVICE = re.compile(r"(?:CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³]|CONIN\$|CONOUT\$)")
_DEFAULT_BYTES = 64 * 1024**3
_MAX_PROFILE_BYTES = 256 * 1024
MAX_DEPTH = 64


@dataclass(frozen=True)
class Source:
    name: str
    kind: Literal["git", "folder"]
    path: Path
    access: Literal["read-only", "writable"]
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    revision: str = "HEAD"
    upstream: str | None = None
    allow_unpublished: bool = False


@dataclass(frozen=True)
class Profile:
    sources: tuple[Source, ...]
    max_bytes: int = _DEFAULT_BYTES


def portable(parts: tuple[str, ...]) -> str:
    path = "/".join(parts)
    if not parts or len(parts) > MAX_DEPTH or len(path.encode("utf-8", "surrogatepass")) > 1024:
        raise PreviewError(f"path is too deep or too long: {path!r}")
    for part in parts:
        if (not part or part in (".", "..") or part.endswith((".", " "))
                or _DEVICE.fullmatch(part.split(".", 1)[0].rstrip().upper())
                or len(part.encode("utf-8", "surrogatepass")) > 255
                or any(c in '<>:"/\\|?*' or unicodedata.category(c) in ("Cc", "Cf", "Cs")
                       for c in part)):
            raise PreviewError(f"path cannot be represented portably: {path!r}")
    return path


def collisions_key(path: str) -> str:
    return unicodedata.normalize("NFC", path).casefold()


def matches(pattern: str, path: tuple[str, ...]) -> bool:
    """Slash-separated, case-sensitive globs; ** matches zero or more components."""
    pattern_parts = pattern.split("/")

    @cache
    def match(index: int, position: int) -> bool:
        if index == len(pattern_parts):
            return position == len(path)
        part = pattern_parts[index]
        if part == "**":
            return match(index + 1, position) or (position < len(path) and match(index, position + 1))
        return (position < len(path) and fnmatch.fnmatchcase(path[position], part)
                and match(index + 1, position + 1))

    return match(0, 0)


def _patterns(raw: object) -> tuple[str, ...]:
    if not isinstance(raw, list) or len(raw) > 64:
        raise PreviewError("include/exclude must be lists of up to 64 patterns")
    for value in raw:
        if not isinstance(value, str) or not 1 <= len(value) <= 256 or "\\" in value:
            raise PreviewError("patterns must be nonempty strings with relative '/' separators")
        parts = value.split("/")
        if (len(parts) > MAX_DEPTH or any(p in ("", ".", "..") or ("**" in p and p != "**") for p in parts)
                or any(unicodedata.category(c) in ("Cc", "Cf", "Cs") for c in value)):
            raise PreviewError(f"invalid workspace pattern: {value!r}")
    return tuple(raw)


def _source(raw: object) -> Source:
    common = {"name", "kind", "path", "access", "include", "exclude"}
    git_fields = {"revision", "upstream", "allow_unpublished"}
    if not isinstance(raw, dict):
        raise PreviewError("each source must be an object")
    kind = raw.get("kind")
    access = raw.get("access", "read-only")
    name, path = raw.get("name"), raw.get("path")
    if (kind not in ("folder", "git") or access not in ("read-only", "writable")
            or not isinstance(name, str) or not _NAME.fullmatch(name)
            or not isinstance(path, str) or not path
            or set(raw) - (common | (git_fields if kind == "git" else set()))):
        raise PreviewError("invalid source name, kind, path, access, or unknown field")
    portable((name,))
    root = Path(path)
    if not root.is_absolute() or ".." in root.parts or len(root.parts) <= 1:
        raise PreviewError("source path must be an absolute local path to a folder, not a drive root")
    portable(root.parts[1:])
    revision = raw.get("revision", "HEAD")
    upstream = raw.get("upstream")
    allow = raw.get("allow_unpublished", False)
    if (not isinstance(revision, str) or (revision != "HEAD" and not OID.fullmatch(revision))
            or type(allow) is not bool
            or (upstream is not None and (not isinstance(upstream, str) or len(upstream) > 200
                or not _UPSTREAM.fullmatch(upstream)))):
        raise PreviewError("invalid Git revision, upstream or allow_unpublished flag")
    if kind == "git" and ((upstream is not None) == allow):
        raise PreviewError("Git source requires a remote-tracking upstream or explicit allow_unpublished: true")
    return Source(name, kind, root, access, _patterns(raw.get("include", [])),
                  _patterns(raw.get("exclude", [])), revision, upstream, allow)


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise PreviewError(f"duplicate profile field: {key!r}")
        result[key] = value
    return result


def load_profile(path: Path) -> Profile:
    with path.open("rb") as stream:
        data = stream.read(_MAX_PROFILE_BYTES + 1)
    if len(data) > _MAX_PROFILE_BYTES:
        raise PreviewError("workspace profile is too large")
    try:
        raw = json.loads(data.decode("utf-8"), object_pairs_hook=_unique)
    except (ValueError, RecursionError) as exc:
        raise PreviewError("workspace profile is not valid UTF-8 JSON") from exc
    if (not isinstance(raw, dict) or set(raw) - {"version", "sources", "max_bytes"}
            or type(raw.get("version")) is not int or raw["version"] != 1
            or not isinstance(raw.get("sources"), list) or not 1 <= len(raw["sources"]) <= 32):
        raise PreviewError("expected a version 1 profile with 1–32 sources")
    max_bytes = raw.get("max_bytes", _DEFAULT_BYTES)
    if type(max_bytes) is not int or not 1 <= max_bytes <= 1024**4:
        raise PreviewError("max_bytes must be a positive integer no greater than 1 TiB")
    sources = tuple(_source(value) for value in raw["sources"])
    if len({source.name for source in sources}) != len(sources):
        raise PreviewError("source names must be unique")
    return Profile(sources, max_bytes)
