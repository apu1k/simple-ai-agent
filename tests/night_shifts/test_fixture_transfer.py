"""Offline Git-object and fake-serial tests; never launch a VM or model."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest

from night_shifts.fixture_transfer import run_fixture_in_sandbox, transfer_fixture
from night_shifts.guest.fixture_transfer import (
    FixtureGuestSession,
    FixtureTransferError,
    install_fixture,
    write_fixed_output,
)
from night_shifts.models import SandboxRecord, SandboxSpec, SandboxStatus
from night_shifts.snapshot import (
    MAX_CONTENT_BYTES,
    GitSnapshotExporter,
    Snapshot,
    SnapshotError,
    SnapshotFile,
    decode_snapshot,
    encode_snapshot,
)
from night_shifts.tool_session import SandboxToolSession
from night_shifts.worker_capabilities import worker_tool_names
from night_shifts.contracts.worker_tool import WorkerToolSpec
from night_shifts.workspaces import RepositoryRegistry, TrustedRepository

JOB = "a" * 32
SANDBOX = "b" * 32
COMMIT = "c" * 40
IMAGE = "d" * 64


def fixture_snapshot(data: bytes = b"night-shift-fixture\n") -> Snapshot:
    return Snapshot(JOB, "fixture", COMMIT, IMAGE, (SnapshotFile("fixture.txt", "100644", data),))


class GuestTransport:
    def __init__(self, guest: FixtureGuestSession, *, corrupt_export: bool = False) -> None:
        self.guest = guest
        self.reply = b""
        self.closed = False
        self.corrupt_export = corrupt_export

    def send(self, frame: bytes, *, timeout_seconds: float) -> None:
        assert timeout_seconds > 0 and not self.closed
        self.reply = self.guest.handle(frame)
        if self.corrupt_export and b'"export_chunk"' in frame:
            response = json.loads(self.reply)
            response["request_id"] += 1
            self.reply = json.dumps(response).encode() + b"\n"

    def receive(self, *, max_bytes: int, timeout_seconds: float) -> bytes:
        assert timeout_seconds > 0 and len(self.reply) <= max_bytes and not self.closed
        response, self.reply = self.reply, b""
        return response

    def close(self) -> None:
        self.closed = True


def session(transport: GuestTransport, sandbox: SandboxRecord | None = None) -> SandboxToolSession:
    sandbox = sandbox or SandboxRecord(JOB, "hyperv", SandboxSpec(), SANDBOX,
                                       external_id=f"night-shift-{SANDBOX}")
    tools = tuple(WorkerToolSpec(name, "fixture", {"type": "object"})
                  for name in worker_tool_names("coding-worker"))
    return SandboxToolSession(sandbox, "coding-worker", tools, transport,
                              deadline=time.monotonic() + 10)


def test_fake_serial_load_fixed_check_retrieve_and_close(tmp_path: Path) -> None:
    loaded: list[Snapshot] = []
    guest = FixtureGuestSession(tmp_path / "workspace",
                                installer=lambda snapshot, _: loaded.append(snapshot),
                                writer=lambda *_: None)
    transport = GuestTransport(guest)
    snapshot = fixture_snapshot()
    evidence = transfer_fixture(session(transport), snapshot)
    assert loaded == [snapshot]
    assert evidence.reported_pass
    assert evidence.reported_output == "fixed fixture matched\n"
    assert evidence.snapshot_sha256 == hashlib.sha256(encode_snapshot(snapshot)).hexdigest()
    assert transport.closed
    assert not (tmp_path / "workspace").exists()  # in-memory fake, not real isolation


def test_failed_check_is_evidence_not_success(tmp_path: Path) -> None:
    guest = FixtureGuestSession(tmp_path / "workspace", installer=lambda *_: None,
                                writer=lambda *_: None)
    report = transfer_fixture(session(GuestTransport(guest)), fixture_snapshot(b"no\n"))
    assert not report.reported_pass
    assert report.reported_output == "fixed fixture did not match\n"


@pytest.mark.parametrize("change", [
    lambda p: p["files"][0].update(path="../escape"),
    lambda p: p["files"][0].update(path="C:/escape"),
    lambda p: p["files"][0].update(path=".git/config"),
    lambda p: p["files"][0].update(mode="120000"),
    lambda p: p["files"][0].update(sha256="0" * 64),
    lambda p: p.update(job_id="wrong"),
    lambda p: p.update(job_id=None),
    lambda p: p.update(revision=None),
    lambda p: p.update(image_sha256="wrong"),
    lambda p: p.update(image_sha256=None),
    lambda p: p.update(version=True),
    lambda p: p["files"].append(p["files"][0].copy()),
])
def test_rejects_unsafe_or_mismatched_snapshot(change: Any) -> None:
    payload = json.loads(encode_snapshot(fixture_snapshot()))
    change(payload)
    with pytest.raises(SnapshotError):
        decode_snapshot(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())


def test_rejects_duplicate_json_fields_and_unsupported_bytes() -> None:
    snapshot = fixture_snapshot()
    data = encode_snapshot(snapshot)
    with pytest.raises(SnapshotError):
        decode_snapshot(data.replace(b'"version":1', b'"version":1,"version":1'))
    for content in (b"\x00", b"\xff", b"version https://git-lfs.github.com/spec/v1\n"):
        with pytest.raises(SnapshotError):
            encode_snapshot(fixture_snapshot(content))
    with pytest.raises(SnapshotError):
        encode_snapshot(fixture_snapshot(b"x" * (MAX_CONTENT_BYTES + 1)))


def test_guest_rejects_replay_and_tools(tmp_path: Path) -> None:
    guest = FixtureGuestSession(tmp_path / "workspace", installer=lambda *_: None,
                                writer=lambda *_: None)
    hello = {"version": 1, "type": "hello", "job_id": JOB,
             "sandbox_id": SANDBOX, "session_id": "f" * 32}
    guest.handle(json.dumps(hello).encode() + b"\n")
    with pytest.raises(FixtureTransferError):
        guest.handle(json.dumps(hello).encode() + b"\n")
    transport = GuestTransport(FixtureGuestSession(tmp_path / "workspace", installer=lambda *_: None,
                                                   writer=lambda *_: None))
    worker = session(transport)
    worker.start()
    with pytest.raises(FixtureTransferError):
        transport.send(json.dumps({"version": 1, "type": "request", "job_id": JOB,
                                   "sandbox_id": SANDBOX, "session_id": worker._session_id,
                                   "request_id": 1, "operation": "tool", "payload": {}}).encode() + b"\n",
                       timeout_seconds=1)
    assert not (tmp_path / "workspace").exists()


class FakeProvider:
    def __init__(self, *, destroy_fails: bool = False) -> None:
        self.destroyed = False
        self.destroy_fails = destroy_fails

    def create(self, *, job_id: str, spec: SandboxSpec) -> SandboxRecord:
        assert not spec.network_enabled
        return SandboxRecord(job_id, "hyperv", spec, SANDBOX,
                             external_id=f"night-shift-{SANDBOX}")

    def start(self, sandbox: SandboxRecord) -> None:
        assert sandbox.sandbox_id == SANDBOX

    def status(self, sandbox: SandboxRecord) -> SandboxStatus:
        return SandboxStatus.RUNNING

    def destroy(self, sandbox: SandboxRecord) -> None:
        self.destroyed = True
        if self.destroy_fails:
            raise RuntimeError("disk retained")


def test_cleanup_is_attempted_after_failed_export_and_unknown_status(tmp_path: Path) -> None:
    provider = FakeProvider()

    def factory(sandbox: SandboxRecord, _: float) -> SandboxToolSession:
        guest = FixtureGuestSession(tmp_path / "workspace", installer=lambda *_: None,
                                    writer=lambda *_: None)
        return session(GuestTransport(guest, corrupt_export=True), sandbox)

    outcome = run_fixture_in_sandbox(provider, factory, fixture_snapshot(),
                                     reviewed_image_sha256=IMAGE, spec=SandboxSpec())
    assert not outcome.succeeded and outcome.error and provider.destroyed
    assert outcome.sandbox_id == SANDBOX
    broken = FakeProvider(destroy_fails=True)
    outcome = run_fixture_in_sandbox(broken, factory, fixture_snapshot(),
                                     reviewed_image_sha256=IMAGE, spec=SandboxSpec())
    assert outcome.cleanup_error and "disk retained" in outcome.cleanup_error
    assert not outcome.succeeded


def test_linux_installer_writes_files_and_fixed_output(tmp_path: Path) -> None:
    if os.name != "posix" or os.geteuid() != 0:
        pytest.skip("Linux guest installer needs a root-owned test parent")
    workspace = tmp_path / "workspace"
    install_fixture(fixture_snapshot(), workspace)
    write_fixed_output(workspace, b"fixed fixture matched\n")
    assert (workspace / "fixture.txt").read_bytes() == b"night-shift-fixture\n"
    assert (workspace / "fixture-result.txt").read_bytes() == b"fixed fixture matched\n"
    with pytest.raises(FileExistsError):
        install_fixture(fixture_snapshot(), workspace)


def test_linux_installer_rejects_link_parent(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unavailable")
    with pytest.raises(FixtureTransferError):
        install_fixture(fixture_snapshot(), link / "workspace")
    assert list(target.iterdir()) == []


def test_git_object_export_ignores_checkout_edits_and_rejects_unapproved_files(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()

    def git(*args: str, input_data: bytes | None = None) -> str:
        result = subprocess.run(["git", *args], cwd=source, input=input_data, capture_output=True,
                                check=True, timeout=5)
        return result.stdout.decode().strip()

    git("init", "-q")
    git("config", "user.name", "fixture")
    git("config", "user.email", "fixture@example.invalid")
    (source / "fixture.txt").write_bytes(b"night-shift-fixture\n")
    git("add", "--", "fixture.txt")  # test-owned fixture with no hooks or filters
    tree = git("write-tree")
    revision = git("commit-tree", tree, "-m", "approved fixture")
    approved = {"fixture.txt": hashlib.sha256(b"night-shift-fixture\n").hexdigest()}
    exporter = GitSnapshotExporter(RepositoryRegistry([TrustedRepository("fixture", source)]))
    (source / "fixture.txt").write_bytes(b"changed checkout, must not export\n")
    snapshot = exporter.export(job_id=JOB, repository_id="fixture", revision=revision,
                               image_sha256=IMAGE, approved_files=approved)
    assert snapshot.files[0].content == b"night-shift-fixture\n"
    assert (source / "fixture.txt").read_bytes() == b"changed checkout, must not export\n"
    with pytest.raises(SnapshotError):
        exporter.export(job_id=JOB, repository_id="fixture", revision=revision,
                        image_sha256=IMAGE, approved_files={"fixture.txt": "0" * 64})
    with pytest.raises(SnapshotError):
        exporter.export(job_id=JOB, repository_id="fixture", revision=revision,
                        image_sha256=IMAGE, approved_files={"other.txt": approved["fixture.txt"]})
    (source / "secret.txt").write_text("secret", encoding="utf-8")
    git("add", "--", "secret.txt")
    newer = git("commit-tree", git("write-tree"), "-m", "unreviewed file")
    with pytest.raises(SnapshotError):
        exporter.export(job_id=JOB, repository_id="fixture", revision=newer,
                        image_sha256=IMAGE, approved_files=approved)
    assert os.path.exists(source / "secret.txt")  # exporter never touches source
