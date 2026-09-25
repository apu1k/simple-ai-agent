"""Fixed, offline-verifiable guest responder for the Commit 04 transfer fixture.

Not the coding-worker service. It accepts no model tools and never invokes a
repository command. Deploying it in a reviewed Linux image is a separate gate.
The trusted parent of workspace_root must be root-owned and not guest-writable.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Any, BinaryIO, Callable

from night_shifts.snapshot import MAX_SNAPSHOT_BYTES, Snapshot, decode_snapshot

_FRAME = 64 * 1024
_CHUNK = 16 * 1024
_JOB = re.compile(r"[0-9a-f]{32}\Z")
_SANDBOX = re.compile(r"[0-9a-f]{32}\Z")
_SESSION = re.compile(r"[0-9a-f]{32}\Z")
_FIXTURE = b"night-shift-fixture\n"
_RESULT_NAME = "fixture-result.txt"


class FixtureTransferError(RuntimeError):
    """A malformed session or incomplete transfer must fail closed."""


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise FixtureTransferError("duplicate session field")
        result[key] = value
    return result


def _frame(message: dict[str, Any]) -> bytes:
    data = json.dumps(message, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8") + b"\n"
    if len(data) > _FRAME:
        raise FixtureTransferError("guest response frame exceeds limit")
    return data


def _decode(data: bytes) -> dict[str, Any]:
    if (not isinstance(data, bytes) or not data.endswith(b"\n")
            or b"\n" in data[:-1] or len(data) > _FRAME):
        raise FixtureTransferError("guest request frame is invalid")
    try:
        value = json.loads(data[:-1].decode("utf-8"), object_pairs_hook=_unique)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise FixtureTransferError("guest request JSON is invalid") from exc
    if not isinstance(value, dict):
        raise FixtureTransferError("guest request must be an object")
    return value


def install_fixture(snapshot: Snapshot, workspace_root: Path) -> None:
    """Create a fresh Linux guest workspace without following any links.

    A partial write is not retried. Only the orchestrator destroys the VM after
    an error. The parent must already be trusted; dirfd operations anchor all
    untrusted paths beneath the newly created workspace directory.
    """
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory = getattr(os, "O_DIRECTORY", 0)
    if not nofollow or not directory:
        raise FixtureTransferError("safe installation requires Linux openat support")
    parent = workspace_root.parent
    parent_stat = parent.lstat()
    if (not stat.S_ISDIR(parent_stat.st_mode) or parent.is_symlink()
            or parent_stat.st_uid != 0 or parent_stat.st_mode & 0o022):
        raise FixtureTransferError("workspace parent must be root-owned and not worker-writable")
    parent_fd = os.open(parent, os.O_RDONLY | directory | nofollow)
    try:
        os.mkdir(workspace_root.name, mode=0o700, dir_fd=parent_fd)
        root_fd = os.open(workspace_root.name,
                          os.O_RDONLY | directory | nofollow, dir_fd=parent_fd)
        try:
            for item in snapshot.files:
                components = item.path.split("/")  # validated by decode_snapshot
                current = os.dup(root_fd)
                try:
                    for part in components[:-1]:
                        try:
                            os.mkdir(part, mode=0o700, dir_fd=current)
                        except FileExistsError:
                            pass
                        following = os.open(part, os.O_RDONLY | directory | nofollow,
                                            dir_fd=current)
                        os.close(current)
                        current = following
                    descriptor = os.open(components[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                                         nofollow, 0o600, dir_fd=current)
                    with os.fdopen(descriptor, "wb") as stream:
                        stream.write(item.content)
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.chmod(components[-1], 0o755 if item.mode == "100755" else 0o644,
                             dir_fd=current, follow_symlinks=False)
                finally:
                    os.close(current)
        finally:
            os.close(root_fd)
    finally:
        os.close(parent_fd)


def write_fixed_output(workspace_root: Path, content: bytes) -> None:
    """Write the fixed check output exclusively beneath the installed guest root."""
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory = getattr(os, "O_DIRECTORY", 0)
    if not nofollow or not directory or content not in (
        b"fixed fixture matched\n", b"fixed fixture did not match\n",
    ):
        raise FixtureTransferError("invalid fixture output or unsupported guest filesystem")
    root_fd = os.open(workspace_root, os.O_RDONLY | directory | nofollow)
    try:
        descriptor = os.open(_RESULT_NAME, os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow,
                             0o600, dir_fd=root_fd)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(root_fd)


def _fixture_report(snapshot: Snapshot, data: bytes) -> tuple[bytes, bytes]:
    files = {item.path: item.content for item in snapshot.files}
    if _RESULT_NAME in files:
        raise FixtureTransferError("reserved fixture output name is already tracked")
    passed = files.get("fixture.txt") == _FIXTURE
    output_text = "fixed fixture matched\n" if passed else "fixed fixture did not match\n"
    report = {
        "version": 1, "job_id": snapshot.job_id, "revision": snapshot.revision,
        "image_sha256": snapshot.image_sha256,
        "snapshot_sha256": hashlib.sha256(data).hexdigest(),
        "check": {"name": "fixed-fixture-text", "passed": passed,
                  "output": "fixed fixture matched" if passed else "fixed fixture did not match"},
        "output": {"path": _RESULT_NAME, "text": output_text},
    }
    encoded = json.dumps(report, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_SNAPSHOT_BYTES:
        raise FixtureTransferError("guest report exceeds export limit")
    return encoded, output_text.encode("utf-8")


class FixtureGuestSession:
    """One bounded, identity-bound session with no guest-initiated host requests."""

    def __init__(self, workspace_root: Path, *,
                 installer: Callable[[Snapshot, Path], None] = install_fixture,
                 writer: Callable[[Path, bytes], None] = write_fixed_output) -> None:
        self._root = workspace_root
        self._installer = installer
        self._writer = writer
        self._identity: dict[str, str] | None = None
        self._phase = "new"
        self._request_id = 1
        self._incoming = bytearray()
        self._outgoing = b""
        self._snapshot: Snapshot | None = None

    def handle(self, frame: bytes) -> bytes:
        """One full JSONL frame in, one full frame out; failure ends the session."""
        try:
            return self._handle(_decode(frame))
        except Exception:
            self._phase = "closed"
            raise

    def _handle(self, message: dict[str, Any]) -> bytes:
        if self._phase == "closed" or type(message.get("version")) is not int or message["version"] != 1:
            raise FixtureTransferError("session version or phase is invalid")
        if self._phase == "new":
            if set(message) != {"version", "type", "job_id", "sandbox_id", "session_id"} or message["type"] != "hello":
                raise FixtureTransferError("expected bound hello")
            identity = {key: message[key] for key in ("job_id", "sandbox_id", "session_id")}
            if (not isinstance(identity["job_id"], str) or not _JOB.fullmatch(identity["job_id"])
                    or not isinstance(identity["sandbox_id"], str) or not _SANDBOX.fullmatch(identity["sandbox_id"])
                    or not isinstance(identity["session_id"], str) or not _SESSION.fullmatch(identity["session_id"])):
                raise FixtureTransferError("invalid session identity")
            self._identity = identity
            self._phase = "loading"
            return _frame({"version": 1, "type": "hello_ack", **identity})
        assert self._identity is not None
        if (set(message) != {"version", "type", "request_id", "operation", "payload", *self._identity}
                or message["type"] != "request" or type(message["request_id"]) is not int
                or message["request_id"] != self._request_id
                or not all(message[key] == value for key, value in self._identity.items())
                or not isinstance(message["payload"], dict)):
            raise FixtureTransferError("unexpected, replayed or mismatched request")
        operation, payload = message["operation"], message["payload"]
        response: dict[str, Any] = {}
        if self._phase == "loading" and operation == "load_chunk":
            if (set(payload) != {"offset", "data", "final"} or type(payload["offset"]) is not int
                    or payload["offset"] != len(self._incoming) or type(payload["final"]) is not bool
                    or not isinstance(payload["data"], str) or len(payload["data"]) > 4 * _CHUNK // 3 + 4):
                raise FixtureTransferError("invalid workspace chunk")
            try:
                chunk = base64.b64decode(payload["data"], validate=True)
            except (ValueError, binascii.Error) as exc:
                raise FixtureTransferError("invalid workspace encoding") from exc
            if len(chunk) > _CHUNK or len(self._incoming) + len(chunk) > MAX_SNAPSHOT_BYTES or (not chunk and not payload["final"]):
                raise FixtureTransferError("workspace exceeds chunk or total limit")
            self._incoming.extend(chunk)
            if payload["final"]:
                self._snapshot = decode_snapshot(bytes(self._incoming))
                if self._snapshot.job_id != self._identity["job_id"]:
                    raise FixtureTransferError("workspace belongs to another job")
                if any(item.path == _RESULT_NAME for item in self._snapshot.files):
                    raise FixtureTransferError("fixture output conflicts with a tracked file")
                self._installer(self._snapshot, self._root)
                self._phase = "ready"
        elif self._phase == "ready" and operation == "finalize":
            if payload != {} or self._snapshot is None:
                raise FixtureTransferError("invalid finalization")
            report, output = _fixture_report(self._snapshot, bytes(self._incoming))
            self._writer(self._root, output)
            self._outgoing = report
            self._phase = "exporting"
        elif self._phase == "exporting" and operation == "export_chunk":
            if (set(payload) != {"offset", "limit_bytes"} or type(payload["offset"]) is not int
                    or type(payload["limit_bytes"]) is not int or not 1 <= payload["limit_bytes"] <= _CHUNK
                    or payload["offset"] < 0 or payload["offset"] > len(self._outgoing)):
                raise FixtureTransferError("invalid result chunk request")
            # The guest must reject a replay even when the host lies about its offset.
            if payload["offset"] != getattr(self, "_sent", 0):
                raise FixtureTransferError("result offset mismatch")
            end = min(payload["offset"] + payload["limit_bytes"], len(self._outgoing))
            chunk = self._outgoing[payload["offset"]:end]
            response = {"data": base64.b64encode(chunk).decode("ascii"),
                        "eof": end == len(self._outgoing)}
            self._sent = end
            if response["eof"]:
                self._phase = "done"
        else:
            raise FixtureTransferError("operation is not allowed in this phase")
        request_id = self._request_id
        self._request_id += 1
        return _frame({"version": 1, "type": "response", **self._identity,
                       "request_id": request_id, "ok": True, "payload": response})


def serve(channel: BinaryIO, workspace_root: Path) -> None:
    """Guest-only serial entry point; exit on EOF or any malformed frame."""
    session = FixtureGuestSession(workspace_root)
    while True:
        frame = channel.readline(_FRAME + 1)
        if not frame:
            return
        reply = session.handle(frame)
        view = memoryview(reply)
        while view:
            written = channel.write(view)
            if written is None or written <= 0:
                raise FixtureTransferError("serial channel disconnected during reply")
            view = view[written:]
        channel.flush()
