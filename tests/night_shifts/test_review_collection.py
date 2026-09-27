"""Fake-session/VM tests of independent review retrieval and cleanup."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from night_shifts.execution_policy import WorkerExecutionPolicy
from night_shifts.final_workspace import FinalWorkspace, encode_final_workspace
from night_shifts.models import NightShiftJob, SandboxRecord, SandboxSpec
from night_shifts.protocol import CleanupStatus, WorkerOutcome, WorkerResult, WorkerTask
from night_shifts.review_bundle import ReviewBundleStore
from night_shifts.review_collection import collect_after_worker
from night_shifts.review_retrieval import retrieve_final_workspace
from night_shifts.snapshot import Snapshot, SnapshotFile


def _context():
    job = NightShiftJob("fixture", "fix", "coding-worker", job_id="a" * 32,
                        repository_id="fixture", starting_revision="b" * 40)
    policy = WorkerExecutionPolicy.snapshot(job, image_sha256="c" * 64,
                                            provider_id="approved", model_id="approved")
    task = WorkerTask.from_job(job)
    base = Snapshot(job.job_id, "fixture", "b" * 40, "c" * 64,
                    (SnapshotFile("old.txt", "100644", b"old\n"),))
    sandbox = SandboxRecord(job.job_id, "hyperv", sandbox_id="d" * 32,
                            external_id="night-shift-" + "d" * 32)
    return policy, task, base, sandbox


class FakeSession:
    def __init__(self, base: Snapshot, *, corrupt: bool = False):
        self.job_id = base.job_id
        self.profile = "coding-worker"
        self.sandbox_id = "d" * 32
        self.session_id = "e" * 32
        self.data = encode_final_workspace(FinalWorkspace(
            base, self.sandbox_id, self.session_id,
            (SnapshotFile("new.txt", "100644", b"new\n"),),
        ))
        if corrupt:
            self.data = self.data[:-1]
        self.finalized = False
        self.closed = False

    def finalize(self) -> None:
        self.finalized = True

    def export_chunk(self, *, offset: int, limit_bytes: int) -> tuple[bytes, bool]:
        assert self.finalized and not self.closed
        end = min(offset + limit_bytes, len(self.data))
        return self.data[offset:end], end == len(self.data)

    def close(self) -> None:
        self.closed = True


class FakeProvider:
    def __init__(self, *, fails: bool = False):
        self.fails = fails
        self.destroyed: list[str] = []

    def destroy(self, sandbox: SandboxRecord) -> None:
        self.destroyed.append(sandbox.sandbox_id)
        if self.fails:
            raise RuntimeError("destroy failed")


def _collect(store: ReviewBundleStore, provider: FakeProvider,
             session: FakeSession | None, *, sandbox: SandboxRecord | None = None):
    policy, task, base, owned = _context()
    return collect_after_worker(
        store=store, provider=provider, policy=policy, task=task, base=base,
        sandbox=owned if sandbox is None else sandbox,
        session=session, result=WorkerResult(task.job_id, WorkerOutcome.SUBMITTED, "submitted",
                                             metrics={"usage": {"unknown_requests": 0}}),
    )  # type: ignore[arg-type]


def test_retrieve_complete_final_workspace_closes_after_success_or_corruption() -> None:
    _, _, base, _ = _context()
    good = FakeSession(base)
    assert retrieve_final_workspace(good, base).files[0].content == b"new\n"  # type: ignore[arg-type]
    assert good.closed
    bad = FakeSession(base, corrupt=True)
    with pytest.raises(ValueError):
        retrieve_final_workspace(bad, base)  # type: ignore[arg-type]
    assert bad.closed


def test_orchestrator_exports_before_exact_id_destroy_and_persists_result(tmp_path: Path) -> None:
    _, _, base, _ = _context()
    session = FakeSession(base)
    provider = FakeProvider()
    store = ReviewBundleStore(tmp_path / "bundles")
    saved = _collect(store, provider, session)
    assert provider.destroyed == ["d" * 32] and session.closed
    assert saved.state == "evidence_only"  # no real second-sandbox replay
    report = json.loads((saved.path / "report.json").read_bytes())
    assert report["cleanup_status"] == CleanupStatus.CLEAN.value
    assert report["missing_guest_evidence"] is False
    assert (saved.path / "patch.diff").is_file()
    assert ReviewBundleStore(tmp_path / "bundles").read("a" * 32)[0].state == saved.state


def test_failed_export_still_destroys_and_persists_missing_evidence(tmp_path: Path) -> None:
    _, _, base, _ = _context()
    provider = FakeProvider()
    saved = _collect(ReviewBundleStore(tmp_path / "bundles"), provider,
                     FakeSession(base, corrupt=True))
    assert provider.destroyed == ["d" * 32]
    report = json.loads((saved.path / "report.json").read_bytes())
    assert saved.state == "incomplete" and report["missing_guest_evidence"] is True
    assert report["cleanup_status"] == CleanupStatus.CLEAN.value
    assert not (saved.path / "patch.diff").exists()


def test_cleanup_failure_remains_distinct_from_worker_submission(tmp_path: Path) -> None:
    _, _, base, _ = _context()
    provider = FakeProvider(fails=True)
    saved = _collect(ReviewBundleStore(tmp_path / "bundles"), provider, FakeSession(base))
    report = json.loads((saved.path / "report.json").read_bytes())
    assert saved.state != "ready_for_review"
    assert report["worker"]["outcome"] == "submitted"
    assert report["cleanup_status"] == CleanupStatus.FAILED.value
    assert any("reconciliation" in reason for reason in report["reasons"])


def test_bundle_store_failure_never_skips_vm_destroy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, _, base, _ = _context()
    store = ReviewBundleStore(tmp_path / "bundles")
    provider = FakeProvider()

    def fails(**_kwargs: object) -> None:
        raise OSError("out of space")

    monkeypatch.setattr(store, "collect", fails)
    with pytest.raises(OSError, match="out of space"):
        _collect(store, provider, FakeSession(base))
    assert provider.destroyed == ["d" * 32]


def test_network_policy_mismatch_is_destroyed_but_never_exported(tmp_path: Path) -> None:
    _, _, base, owned = _context()
    owned.spec = SandboxSpec(network_enabled=True)
    session = FakeSession(base)
    provider = FakeProvider()
    saved = _collect(ReviewBundleStore(tmp_path / "bundles"), provider,
                     session, sandbox=owned)
    assert provider.destroyed == [owned.sandbox_id] and session.closed
    report = json.loads((saved.path / "report.json").read_bytes())
    assert report["missing_guest_evidence"] is True
    assert any("network policy" in reason for reason in report["reasons"])


def test_never_destroy_an_unbound_sandbox(tmp_path: Path) -> None:
    _, _, base, _ = _context()
    provider = FakeProvider()
    unbound = SandboxRecord("another-job", "hyperv", sandbox_id="f" * 32,
                            external_id="night-shift-" + "f" * 32)
    saved = _collect(ReviewBundleStore(tmp_path / "bundles"), provider,
                     FakeSession(base), sandbox=unbound)
    assert not provider.destroyed
    report = json.loads((saved.path / "report.json").read_bytes())
    assert report["cleanup_status"] == CleanupStatus.UNKNOWN.value
    assert report["missing_guest_evidence"] is True
