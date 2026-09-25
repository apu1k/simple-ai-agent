"""Guest-only bounded text repository facade (not a host filesystem tool).

Linux dirfd + no-follow traversal is required in the real guest; the Windows
path fallback exists for offline fixture tests only, not security isolation.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class RepositoryToolError(ValueError):
    """An unsafe, stale or oversized repository operation."""


_PART = re.compile(r"[A-Za-z0-9._-]{1,100}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_MAX_DEPTH = 8
_MAX_ENTRIES = 128
_MAX_FILE = 256 * 1024
_MAX_READ = 16 * 1024
_MAX_MATCHES = 50
_MAX_SEARCH_BYTES = 16 * 1024
_RESERVED = frozenset({"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                       *(f"LPT{i}" for i in range(1, 10))})


def _parts(value: str, *, root: bool = False) -> tuple[str, ...]:
    if root and value == ".":
        return ()
    if (not isinstance(value, str) or not value or len(value) > 240
            or value.startswith("/") or "\\" in value):
        raise RepositoryToolError("path must be a bounded relative POSIX path")
    parts = tuple(value.split("/"))
    if len(parts) > _MAX_DEPTH or any(
        not _PART.fullmatch(part) or part.endswith(".") or part.lower() == ".git"
        or part.upper().split(".")[0] in _RESERVED for part in parts
    ):
        raise RepositoryToolError("path is not portable or escapes the workspace")
    return parts


class GuestRepository:
    """Text-only single-session file tools inside the disposable guest."""

    def __init__(self, root: Path) -> None:
        if root.is_symlink() or not root.is_dir():
            raise RepositoryToolError("workspace root is unavailable")
        self._root = root.resolve()

    @contextmanager
    def _parent(self, parts: tuple[str, ...]) -> Iterator[int | Path]:
        if os.name == "posix":
            directory = getattr(os, "O_DIRECTORY", 0)
            nofollow = getattr(os, "O_NOFOLLOW", 0)
            if not directory or not nofollow:
                raise RepositoryToolError("Linux no-follow directory traversal is required")
            flags = os.O_RDONLY | directory | nofollow
            try:
                fd = os.open(self._root, flags)
                try:
                    for part in parts:
                        child = os.open(part, flags, dir_fd=fd)
                        os.close(fd)
                        fd = child
                    yield fd
                finally:
                    os.close(fd)
            except OSError as exc:
                raise RepositoryToolError("workspace directory is unavailable or linked") from exc
        else:
            parent = self._root
            for part in parts:
                parent = parent / part
                try:
                    mode = parent.lstat().st_mode
                except OSError as exc:
                    raise RepositoryToolError("workspace directory is unavailable") from exc
                if not stat.S_ISDIR(mode):
                    raise RepositoryToolError("workspace directory is linked or not a directory")
            yield parent

    def _read(self, parts: tuple[str, ...]) -> bytes:
        try:
            with self._parent(parts[:-1]) as parent:
                if isinstance(parent, int):
                    fd = os.open(parts[-1], os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=parent)
                    with os.fdopen(fd, "rb") as stream:
                        info = os.fstat(stream.fileno())
                        if not stat.S_ISREG(info.st_mode) or info.st_size > _MAX_FILE:
                            raise RepositoryToolError("file is not a bounded regular file")
                        data = stream.read(_MAX_FILE + 1)
                else:
                    path = parent / parts[-1]
                    info = path.lstat()
                    if not stat.S_ISREG(info.st_mode) or info.st_size > _MAX_FILE:
                        raise RepositoryToolError("file is not a bounded regular file")
                    data = path.read_bytes()
        except OSError as exc:
            raise RepositoryToolError("file is unavailable or linked") from exc
        if len(data) > _MAX_FILE or b"\0" in data:
            raise RepositoryToolError("oversized or binary file is unsupported")
        try:
            data.decode("utf-8")
        except UnicodeError as exc:
            raise RepositoryToolError("non-UTF-8 file is unsupported") from exc
        return data

    def _walk(self, directory: tuple[str, ...] = ()) -> list[str]:
        results: list[str] = []
        examined = 0

        def visit(parts: tuple[str, ...]) -> None:
            nonlocal examined
            try:
                with self._parent(parts) as parent:
                    with os.scandir(parent) as entries:
                        names: list[str] = []
                        for entry in entries:
                            examined += 1
                            if examined > _MAX_ENTRIES:
                                raise RepositoryToolError("repository entry limit exceeded")
                            names.append(entry.name)
                    for name in sorted(names):
                        child = (*parts, name)
                        _parts("/".join(child))
                        if isinstance(parent, int):
                            mode = os.stat(name, dir_fd=parent, follow_symlinks=False).st_mode
                        else:
                            mode = (parent / name).lstat().st_mode
                        if stat.S_ISDIR(mode):
                            if len(child) >= _MAX_DEPTH:
                                raise RepositoryToolError("repository recursion limit exceeded")
                            visit(child)
                        elif stat.S_ISREG(mode):
                            results.append("/".join(child))
                        else:
                            raise RepositoryToolError("links and special files are unsupported")
            except OSError as exc:
                raise RepositoryToolError("repository traversal failed") from exc

        visit(directory)
        return results

    def list_files(self, path: str = ".") -> dict[str, object]:
        paths = self._walk(_parts(path, root=True))
        return {"files": paths, "count": len(paths)}

    def read_file(self, path: str) -> dict[str, object]:
        data = self._read(_parts(path))
        if len(data) > _MAX_READ:
            raise RepositoryToolError("file exceeds 16 KiB read limit; use search_text")
        return {"path": path, "content": data.decode("utf-8"),
                "sha256": hashlib.sha256(data).hexdigest()}

    def search_text(self, query: str) -> dict[str, object]:
        if (not isinstance(query, str) or not query or len(query.encode("utf-8")) > 256
                or "\n" in query or "\r" in query):
            raise RepositoryToolError("search query must be a bounded single line")
        matches: list[dict[str, object]] = []
        output_bytes = 0
        for path in self._walk():
            text = self._read(_parts(path)).decode("utf-8")
            for number, line in enumerate(text.splitlines(), 1):
                if query not in line:
                    continue
                preview = line[:240]
                output_bytes += len(path.encode("utf-8")) + len(preview.encode("utf-8")) + 100
                if len(matches) >= _MAX_MATCHES or output_bytes > _MAX_SEARCH_BYTES:
                    raise RepositoryToolError("search results exceed limit; narrow the query")
                matches.append({"path": path, "line": number, "text": preview})
        return {"matches": matches}

    def apply_patch(self, path: str, expected_sha256: str | None,
                    find: str, replace: str) -> dict[str, object]:
        parts = _parts(path)
        if (expected_sha256 is not None and (not isinstance(expected_sha256, str)
                or not _DIGEST.fullmatch(expected_sha256))):
            raise RepositoryToolError("expected_sha256 must be a digest or null for creation")
        if not isinstance(find, str) or not isinstance(replace, str):
            raise RepositoryToolError("patch text must be UTF-8 strings")
        if len(find.encode("utf-8")) > _MAX_READ or len(replace.encode("utf-8")) > _MAX_READ:
            raise RepositoryToolError("patch exceeds 16 KiB limit")
        if expected_sha256 is None:
            if find:
                raise RepositoryToolError("new files require an empty find string")
            content = replace.encode("utf-8")
            mode = 0o644
        else:
            if not find:
                raise RepositoryToolError("existing files require a nonempty unique find string")
            before = self._read(parts)
            if hashlib.sha256(before).hexdigest() != expected_sha256:
                raise RepositoryToolError("stale file digest; patch not applied")
            needle = find.encode("utf-8")
            if before.count(needle) != 1:
                raise RepositoryToolError("patch context is missing or ambiguous")
            content = before.replace(needle, replace.encode("utf-8"), 1)
            with self._parent(parts[:-1]) as parent:
                if isinstance(parent, int):
                    current = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
                else:
                    current = (parent / parts[-1]).lstat()
                if not stat.S_ISREG(current.st_mode):
                    raise RepositoryToolError("patch target is not a regular file")
                mode = 0o755 if current.st_mode & 0o111 else 0o644
        if len(content) > _MAX_FILE or b"\0" in content:
            raise RepositoryToolError("patched file is oversized or binary")
        with self._parent(parts[:-1]) as parent:
            name = parts[-1]
            temporary = f".night-shift-{uuid.uuid4().hex}"
            try:
                if isinstance(parent, int):
                    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                                 getattr(os, "O_NOFOLLOW", 0), 0o600, dir_fd=parent)
                else:
                    fd = os.open(parent / temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as stream:
                    stream.write(content)
                    stream.flush()
                    if isinstance(parent, int):
                        os.fchmod(stream.fileno(), mode)
                    else:
                        os.chmod(parent / temporary, mode)
                    os.fsync(stream.fileno())
                if isinstance(parent, int):
                    if expected_sha256 is None:
                        os.link(temporary, name, src_dir_fd=parent, dst_dir_fd=parent,
                                follow_symlinks=False)
                    else:
                        if hashlib.sha256(self._read(parts)).hexdigest() != expected_sha256:
                            raise RepositoryToolError("file changed during patch")
                        os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
                elif expected_sha256 is None:
                    os.link(parent / temporary, parent / name)
                else:
                    if hashlib.sha256(self._read(parts)).hexdigest() != expected_sha256:
                        raise RepositoryToolError("file changed during patch")
                    os.replace(parent / temporary, parent / name)
            except OSError as exc:
                raise RepositoryToolError("patch write failed or new file already exists") from exc
            finally:
                try:
                    if isinstance(parent, int):
                        os.unlink(temporary, dir_fd=parent)
                    else:
                        (parent / temporary).unlink(missing_ok=True)
                except OSError as exc:
                    raise RepositoryToolError(
                        "patch staging cleanup failed; mutation status is unknown"
                    ) from exc
        return {"path": path, "sha256": hashlib.sha256(content).hexdigest(),
                "size_bytes": len(content), "created": expected_sha256 is None}
