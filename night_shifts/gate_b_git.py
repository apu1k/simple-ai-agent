"""Read raw committed Git blobs; no checkout, filters, lazy fetch or network."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Timer
from typing import IO

from night_shifts.gate_b_files import open_directory
from night_shifts.gate_b_profile import OID, PreviewError, Source


def _git_exe() -> Path:
    # Ignore relative PATH components and implicit current-directory executable search.
    for part in os.get_exec_path():
        directory = Path(part)
        candidate = directory / ("git.exe" if os.name == "nt" else "git")
        if directory.is_absolute() and candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate.resolve(strict=True)
    raise PreviewError("Git was not found on the trusted host PATH")


@dataclass(frozen=True)
class GitTree:
    git_dir: Path
    exe: Path
    env: Mapping[str, str]
    revision: str
    upstream_tip: str | None

    def command(self, *args: str) -> list[str]:
        return [str(self.exe), "--no-replace-objects", f"--git-dir={self.git_dir}",
                "-c", "core.fsmonitor=false", "-c", "core.commitGraph=false", *args]

    @contextmanager
    def reader(self, *args: str, batch: bool = False) -> Iterator[tuple[IO[bytes] | None, IO[bytes]]]:
        with subprocess.Popen(self.command(*args), cwd=self.exe.parent, env=self.env,
                              stdin=subprocess.PIPE if batch else subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as process:
            assert process.stdout is not None
            timer = Timer(7200, process.kill)
            timer.daemon = True
            timer.start()
            try:
                yield process.stdin, process.stdout
                if process.stdin is not None:
                    process.stdin.close()
                if process.wait(timeout=30) != 0:
                    raise PreviewError("Git object read failed or timed out")
            finally:
                timer.cancel()
                if process.poll() is None:
                    process.kill()

    def listing(self, stream: IO[bytes]) -> Iterator[tuple[str, str, str, tuple[str, ...]]]:
        tail = b""
        while block := stream.read(64 * 1024):
            *records, tail = (tail + block).split(b"\0")
            for record in records:
                if len(record) > 8192:
                    raise PreviewError("oversized Git tree entry")
                try:
                    header, path = record.split(b"\t", 1)
                    mode, kind, oid = header.decode("ascii").split()
                    parts = tuple(path.decode("utf-8").split("/"))
                except (ValueError, UnicodeError) as exc:
                    raise PreviewError("malformed or non-UTF-8 Git tree entry") from exc
                if not OID.fullmatch(oid) or any(part.casefold() == ".git" for part in parts):
                    raise PreviewError("invalid Git tree object or reserved .git path")
                yield mode, kind, oid, parts
            if len(tail) > 8192:
                raise PreviewError("oversized Git tree entry")
        if tail:
            raise PreviewError("Git tree listing was truncated")


def blob_size(writer: IO[bytes], reader: IO[bytes], oid: str) -> int:
    writer.write(oid.encode("ascii") + b"\n")
    writer.flush()
    header = reader.readline(256)
    fields = header.split()
    if (not header.endswith(b"\n") or len(fields) != 3 or fields[0] != oid.encode("ascii")
            or fields[1] != b"blob" or not fields[2].isdigit()):
        raise PreviewError("Git blob was missing, invalid or not available locally")
    return int(fields[2])


@contextmanager
def open_git(source: Source) -> Iterator[GitTree]:
    # Operator-owned, ordinary local Git checkout only. Linked worktrees and bare repos
    # are not accepted. The local Git installation, config and object store are trusted.
    git_dir = source.path / ".git"
    with open_directory(git_dir):
        exe = _git_exe()
        env = {key: value for key, value in os.environ.items()
               if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR"}}
        env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                    "GIT_NO_LAZY_FETCH": "1", "GIT_NO_REPLACE_OBJECTS": "1",
                    "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0",
                    "GIT_GRAFT_FILE": os.devnull, "GIT_ALLOW_PROTOCOL": ""})
        git = GitTree(git_dir, exe, env, "", None)

        def run(*args: str) -> subprocess.CompletedProcess[bytes]:
            return subprocess.run(git.command(*args), cwd=exe.parent, env=env,
                                  stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, timeout=30)

        def resolve(rev: str, *, peel: bool) -> str:
            result = run("rev-parse", "--verify", "--end-of-options", rev + ("^{commit}" if peel else ""))
            try:
                oid = result.stdout.decode("ascii").strip()
            except UnicodeError as exc:
                raise PreviewError("invalid Git commit identity") from exc
            if result.returncode != 0 or not OID.fullmatch(oid):
                raise PreviewError(f"Git reference is unavailable locally: {rev!r}")
            return oid

        revision = resolve(source.revision, peel=True)
        if source.revision != "HEAD" and source.revision != revision:
            raise PreviewError("the pinned Git object must be the commit itself, not a tag")
        tip = None
        if not source.allow_unpublished:
            if source.upstream is None or run("symbolic-ref", "-q", source.upstream).returncode != 1:
                raise PreviewError("use a direct local remote-tracking branch, not a symbolic reference")
            tip = resolve(source.upstream, peel=False)
            if run("merge-base", "--is-ancestor", revision, tip).returncode != 0:
                raise PreviewError("commit is not proven reachable from the local upstream tip; fetch first or opt in")
        yield GitTree(git_dir, exe, env, revision, tip)
