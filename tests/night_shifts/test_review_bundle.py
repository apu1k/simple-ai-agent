"""Offline review persistence tests; fake receipts never satisfy real VM gates."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from night_shifts.execution_policy import WorkerExecutionPolicy
from night_shifts.models import NightShiftJob
from night_shifts.protocol import CleanupStatus, WorkerOutcome, WorkerResult, WorkerTask
from night_shifts.review_bundle import (
    ObservedOperation, ReplayEvidence, ReviewBundleError, ReviewBundleStore,
)
from night_shifts.review_patch import build_review_patch
from night_shifts.snapshot import MAX_FILE_BYTES, Snapshot, SnapshotFile, encode_snapshot


def _fixture() -> tuple[WorkerExecutionPolicy, WorkerTask, Snapshot]:
    job = NightShiftJob("fixture", "Fix a fixture", "coding-worker", job_id="a" * 32,
                        repository_id="fixture", starting_revision="b" * 40)
    policy = WorkerExecutionPolicy.snapshot(job, image_sha256="c" * 64,
                                            provider_id="approved", model_id="approved")
    base = Snapshot(job.job_id, "fixture", job.starting_revision or "", "c" * 64,
                    (SnapshotFile("old.txt", "100644", b"old\n"),))
    return policy, WorkerTask.from_job(job), base


def _check(*, code: int = 0, text: str = "ok", truncated: bool = False) -> ObservedOperation:
    return ObservedOperation("unit", ("pytest", "-q"), code, text,
                             output_truncated=truncated)


def _replay(base: Snapshot, after: tuple[SnapshotFile, ...]) -> ReplayEvidence:
    patch = build_review_patch(base, after)
    files = [{"path": item.path, "mode": item.mode,
              "sha256": hashlib.sha256(item.content).hexdigest()} for item in after]
    digest = hashlib.sha256(json.dumps(files, ensure_ascii=True, sort_keys=True,
                                       separators=(",", ":")).encode("ascii")).hexdigest()
    return ReplayEvidence("e" * 32, patch.base_snapshot_sha256, patch.patch_sha256,
                          digest, True, CleanupStatus.CLEAN)


def _save(store: ReviewBundleStore, **overrides: object):
    policy, task, base = _fixture()
    after = (SnapshotFile("new.txt", "100644", b"new\n"),)
    options = dict(policy=policy, task=task, base=base, final_files=after,
                   result=WorkerResult(task.job_id, WorkerOutcome.SUBMITTED, "submitted",
                                       artifacts=("guest-artifact/ignored",),
                                       metrics={"usage": {"unknown_requests": 0}}),
                   execution_sandbox_id="d" * 32, configured_checks=("unit",),
                   checks=(_check(),), cleanup_status=CleanupStatus.CLEAN)
    options.update(overrides)
    return store.collect(**options)  # type: ignore[arg-type]


def test_bundle_records_patch_without_model_artifact_and_is_readable_after_restart(tmp_path: Path) -> None:
    root = tmp_path / "bundles"
    store = ReviewBundleStore(root)
    saved = _save(store)
    assert saved.state == "evidence_only"  # a real replay receipt is still missing
    reopened, patch = ReviewBundleStore(root).read("a" * 32)
    assert reopened.state == saved.state
    assert patch is not None and b"new file mode" in patch and b"deleted file mode" in patch
    report = json.loads((saved.path / "report.json").read_bytes())
    assert report["review_status"] == "not_reviewed"
    assert report["check_status"] == "passed"
    assert report["configuration"]["image_sha256"] == "c" * 64
    assert report["worker"]["checks_are_untrusted"] is True
    assert report["changes"][0]["path"] == "new.txt"
    assert report["changes"][1]["path"] == "old.txt"
    with pytest.raises(ReviewBundleError, match="already exists"):
        _save(store)


def test_fake_replay_receipt_is_explicit_and_bound_to_different_identity(tmp_path: Path) -> None:
    policy, task, base = _fixture()
    after = (SnapshotFile("new.txt", "100644", b"new\n"),)
    receipt = _replay(base, after)
    saved = _save(ReviewBundleStore(tmp_path / "ok"), replay=receipt)
    assert saved.state == "ready_for_review"  # contract test ONLY; no VM used
    bad_receipt = ReplayEvidence("d" * 32, receipt.base_snapshot_sha256,
                                 receipt.patch_sha256, receipt.final_manifest_sha256,
                                 True, CleanupStatus.CLEAN)
    rejected = _save(ReviewBundleStore(tmp_path / "bad"), replay=bad_receipt)
    assert rejected.state == "evidence_only"
    assert any("replay" in reason for reason in rejected.reasons)
    _ = policy, task


@pytest.mark.parametrize("override", [
    {"result": None, "final_files": None, "cleanup_status": CleanupStatus.UNKNOWN},
    {"result": WorkerResult("a" * 32, WorkerOutcome.TIMED_OUT, "timeout"), "final_files": None},
    {"final_files": (SnapshotFile("bad", "100644", b"\0"),)},
    {"final_files": (SnapshotFile("large", "100644", b"x" * (MAX_FILE_BYTES + 1)),)},
    {"checks": (_check(code=1),)},
    {"checks": (_check(truncated=True),)},
    {"checks": ()},
    {"final_files": (SnapshotFile("old.txt", "100644", b"old\n"),)},
])
def test_failure_and_noop_report_never_claim_ready(tmp_path: Path, override: dict) -> None:
    saved = _save(ReviewBundleStore(tmp_path / "reports"), **override)
    assert saved.state != "ready_for_review"
    report = json.loads((saved.path / "report.json").read_bytes())
    assert report["cleanup_status"] == override.get("cleanup_status", CleanupStatus.CLEAN).value
    if override.get("final_files", "present") is None:
        assert report["missing_guest_evidence"] is True
        assert not (saved.path / "patch.diff").exists()
    assert (saved.path / "complete.json").exists()  # stored report, not task success


def test_oversized_untrusted_text_retains_host_report_with_truncation_markers(
    tmp_path: Path,
) -> None:
    _, task, _ = _fixture()
    saved = _save(
        ReviewBundleStore(tmp_path / "large"),
        result=WorkerResult(task.job_id, WorkerOutcome.SUBMITTED, "x" * 17000,
                            error="e" * 5000, metrics={"usage": {"unknown_requests": 0}}),
        checks=(_check(text="y" * 20000),),
    )
    report = json.loads((saved.path / "report.json").read_bytes())
    assert saved.state == "evidence_only"
    assert report["worker"]["summary"].startswith("Worker summary omitted")
    assert report["worker"]["error"].startswith("Worker error omitted")
    assert report["checks"][0]["output_truncated"] is True
    assert len(report["checks"][0]["output"].encode("utf-8")) <= 16 * 1024
    assert report["check_status"] == "incomplete"
    assert (saved.path / "complete.json").exists()


def test_interrupted_write_keeps_incomplete_marker_and_does_not_claim_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ReviewBundleStore(tmp_path / "bundles")
    original = store._write

    def interrupted(directory: Path, name: str, data: bytes) -> None:
        if name == "manifest.json":
            raise OSError("simulated disk interruption")
        original(directory, name, data)

    monkeypatch.setattr(store, "_write", interrupted)
    with pytest.raises(OSError, match="disk interruption"):
        _save(store)
    saved, patch = ReviewBundleStore(tmp_path / "bundles").read("a" * 32)
    assert saved.state == "incomplete" and patch is None
    assert not (saved.path / "complete.json").exists()


def test_tampered_patch_and_hostile_log_are_not_silent(tmp_path: Path) -> None:
    store = ReviewBundleStore(tmp_path / "bundles")
    saved = _save(store, commands=(ObservedOperation("command", ("pytest",), 0, "\x1b[2J"),))
    assert b"\\u001b" in (saved.path / "report.json").read_bytes()
    (saved.path / "patch.diff").write_bytes(b"changed")
    with pytest.raises(ReviewBundleError, match="hash or size mismatch"):
        store.read("a" * 32)


def test_missing_usage_or_sandbox_identity_is_explicit_even_with_fake_receipt(tmp_path: Path) -> None:
    _, task, base = _fixture()
    final = (SnapshotFile("new.txt", "100644", b"new\n"),)
    receipt = _replay(base, final)
    missing_usage = _save(
        ReviewBundleStore(tmp_path / "usage"), replay=receipt,
        result=WorkerResult(task.job_id, WorkerOutcome.SUBMITTED, "summary"),
    )
    assert missing_usage.state != "ready_for_review"
    assert any("usage" in reason for reason in missing_usage.reasons)
    usage_report = json.loads((missing_usage.path / "report.json").read_bytes())
    assert usage_report["worker"]["metrics"]["usage"]["unknown"] is True
    missing_id = _save(ReviewBundleStore(tmp_path / "identity"), replay=receipt,
                       execution_sandbox_id=None)
    assert missing_id.state != "ready_for_review"
    assert any("sandbox identity" in reason for reason in missing_id.reasons)


def test_fixture_patch_applies_only_inside_test_owned_temporary_workspace(tmp_path: Path) -> None:
    """Offline syntax/round-trip smoke, not isolated guest replay evidence."""
    if shutil.which("git") is None:
        pytest.skip("Git unavailable for offline test fixture")
    _, _, base = _fixture()
    final = (SnapshotFile("new.txt", "100644", b"new\n"),)
    patch = build_review_patch(base, final).patch
    destination = tmp_path / "disposable-fixture"
    destination.mkdir()
    (destination / "old.txt").write_bytes(base.files[0].content)
    env = {key: value for key, value in os.environ.items()
           if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR"}}
    env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_NO_LAZY_FETCH": "1", "GIT_ALLOW_PROTOCOL": "file"})
    for command in (("apply", "--check", "-"), ("apply", "-")):
        result = subprocess.run(["git", "-c", "core.fsmonitor=false", *command],
                                cwd=destination, input=patch, capture_output=True,
                                timeout=10, env=env, check=False)
        assert result.returncode == 0, result.stderr[:500]
    assert not (destination / "old.txt").exists()
    assert (destination / "new.txt").read_bytes() == final[0].content
    assert hashlib.sha256(encode_snapshot(base)).hexdigest() == build_review_patch(
        base, final,
    ).base_snapshot_sha256
