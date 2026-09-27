"""Trusted-host persistence of bounded review evidence, independent of model artifacts.

The live backend (not this module) must retrieve a *complete*, job-bound final
workspace and validate patch replay in a different disposable sandbox. A guest
report is data, never an attestation. Bundles are never applied to a checkout.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

from night_shifts.execution_policy import WorkerExecutionPolicy
from night_shifts.protocol import CheckStatus, CleanupStatus, WorkerOutcome, WorkerResult, WorkerTask
from night_shifts.review_patch import ReviewPatchError, build_review_patch
from night_shifts.snapshot import Snapshot, SnapshotError, SnapshotFile, encode_snapshot

_ID = re.compile(r"[0-9a-f]{32}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_REPORT_LIMIT = 256 * 1024
_PATCH_LIMIT = 4 * 1024 * 1024
_META_LIMIT = 4096
_LOG_LIMIT = 16 * 1024


class ReviewBundleError(RuntimeError):
    """A review bundle is incomplete, tampered with or cannot be saved safely."""


@dataclass(frozen=True)
class ObservedOperation:
    """Host-recorded request and bounded, untrusted guest response."""

    name: str
    argv: tuple[str, ...]
    exit_code: int | None
    output: str
    timed_out: bool = False
    output_truncated: bool = False


@dataclass(frozen=True)
class ReplayEvidence:
    """Receipt supplied by a trusted runner, never by the worker or guest model.

    'matches_final' means the host compared two bounded guest exports. It is
    not proof that a compromised guest reported true filesystem contents.
    """

    sandbox_id: str
    base_snapshot_sha256: str
    patch_sha256: str
    final_manifest_sha256: str
    matches_final: bool
    cleanup_status: CleanupStatus


@dataclass(frozen=True)
class SavedReviewBundle:
    job_id: str
    state: str  # ready_for_review, incomplete, or evidence_only
    path: Path
    reasons: tuple[str, ...]


def _json(value: Any, *, limit: int) -> bytes:
    try:
        encoded = json.dumps(value, sort_keys=True, ensure_ascii=True,
                             separators=(",", ":"), allow_nan=False).encode("ascii")
    except (TypeError, ValueError, RecursionError, UnicodeError) as exc:
        raise ReviewBundleError("review metadata is not bounded JSON") from exc
    if len(encoded) > limit:
        raise ReviewBundleError("review metadata exceeds byte limit")
    return encoded


def _text(value: str, *, limit: int) -> str:
    if not isinstance(value, str) or len(value.encode("utf-8")) > limit:
        raise ReviewBundleError("review text is invalid or exceeds byte limit")
    return value


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _manifest_digest(files: Sequence[SnapshotFile]) -> str:
    items = [{"path": item.path, "mode": item.mode, "sha256": _sha(item.content)}
             for item in files]
    return _sha(_json(items, limit=_REPORT_LIMIT))


def _operation(item: ObservedOperation) -> dict[str, Any]:
    if (not isinstance(item, ObservedOperation) or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", item.name)
            or not isinstance(item.argv, tuple) or not 0 < len(item.argv) <= 16
            or any(not isinstance(arg, str) or len(arg.encode("utf-8")) > 1024 for arg in item.argv)
            or (item.exit_code is not None and (type(item.exit_code) is not int
                                               or not -65535 <= item.exit_code <= 65535))
            or type(item.timed_out) is not bool or type(item.output_truncated) is not bool):
        raise ReviewBundleError("operation evidence is invalid")
    if not isinstance(item.output, str):
        raise ReviewBundleError("operation output must be text")
    try:
        encoded = item.output.encode("utf-8")
    except UnicodeError as exc:
        raise ReviewBundleError("operation output is invalid UTF-8") from exc
    truncated = len(encoded) > _LOG_LIMIT
    output = encoded[:_LOG_LIMIT].decode("utf-8", errors="ignore") if truncated else item.output
    return {**asdict(item), "output": output,
            "output_truncated": item.output_truncated or truncated,
            "source": "host-request/guest-response"}


def _safe_path(path: Path) -> None:
    if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
        raise ReviewBundleError("review storage path is a link or reparse point")


def _read(path: Path, limit: int) -> bytes:
    _safe_path(path)
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                raise ReviewBundleError("review bundle file is unsafe or oversized")
            data = stream.read(limit + 1)
    except OSError as exc:
        raise ReviewBundleError("review bundle file is missing or unsafe") from exc
    if len(data) > limit:
        raise ReviewBundleError("review bundle file grew beyond limit")
    return data


class ReviewBundleStore:
    """Write once per job; no overwrite or automatic display/execution of content.

    The destination must be administrator-controlled. On Windows chmod does not
    replace an ACL review; the runner must protect this directory independently.
    """

    def __init__(self, root: Path) -> None:
        _safe_path(root)
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        _safe_path(root)
        self.root = root.resolve()

    @staticmethod
    def _write(directory: Path, name: str, data: bytes) -> None:
        if name not in {"incomplete.json", "patch.diff", "report.json", "manifest.json", "complete.json"}:
            raise ReviewBundleError("unapproved bundle file name")
        path = directory / name
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(path, flags, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        except OSError as exc:
            raise ReviewBundleError("review bundle write failed; inspect incomplete marker") from exc

    def collect(
        self,
        *,
        policy: WorkerExecutionPolicy,
        task: WorkerTask,
        base: Snapshot,
        final_files: Sequence[SnapshotFile] | None,
        result: WorkerResult | None,
        execution_sandbox_id: str | None = None,
        configured_checks: Sequence[str] = (),
        checks: Sequence[ObservedOperation] = (),
        commands: Sequence[ObservedOperation] = (),
        cleanup_status: CleanupStatus = CleanupStatus.UNKNOWN,
        replay: ReplayEvidence | None = None,
        diagnostics: Sequence[str] = (),
    ) -> SavedReviewBundle:
        """Persist host diagnostics even if the guest vanished; never infer success.

        This must be called by the orchestrator's cleanup path, not the model.
        A completed bundle marker means *stored and hash-checked*, not that a
        task passed. A failed write retains an incomplete marker for recovery.
        """
        job_id = policy.job_id
        if (not _ID.fullmatch(job_id) or not isinstance(cleanup_status, CleanupStatus)
                or (execution_sandbox_id is not None and not _ID.fullmatch(execution_sandbox_id))):
            raise ReviewBundleError("unbound review identity or cleanup status")
        directory = self.root / job_id
        _safe_path(directory)
        try:
            directory.mkdir(mode=0o700)
        except OSError as exc:
            raise ReviewBundleError("review job directory already exists or cannot be created") from exc
        self._write(directory, "incomplete.json", _json(
            {"version": 1, "job_id": job_id, "state": "incomplete"}, limit=_META_LIMIT,
        ))
        # No guest data is needed to retain the host's missing-evidence report.
        if (task.job_id != job_id or task.repository_id != policy.repository_id
                or task.starting_revision != policy.base_revision
                or task.worker_profile != policy.worker_profile or task.plan != policy.plan
                or base.job_id != job_id or base.repository_id != policy.repository_id
                or base.revision != policy.base_revision or base.image_sha256 != policy.image_sha256):
            raise ReviewBundleError("review task, policy or base identity mismatch")
        base_digest = _sha(encode_snapshot(base))
        _text(task.objective, limit=32 * 1024)
        if len(task.acceptance_criteria) > 32:
            raise ReviewBundleError("too many review acceptance criteria")
        for criterion in task.acceptance_criteria:
            _text(criterion, limit=4096)
        if len(configured_checks) > 16 or len(set(configured_checks)) != len(configured_checks):
            raise ReviewBundleError("configured check list is invalid")
        for name in configured_checks:
            if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", name):
                raise ReviewBundleError("configured check name is invalid")
        if len(checks) > 16 or len(commands) > 64 or len(diagnostics) > 16:
            raise ReviewBundleError("review operation or diagnostic count exceeds limit")
        check_data = [_operation(item) for item in checks]
        command_data = [_operation(item) for item in commands]
        reasons = [_text(item, limit=2048) for item in diagnostics]
        observed = {item["name"]: item for item in check_data}
        if len(observed) != len(check_data) or set(observed) != set(configured_checks):
            check_status = CheckStatus.INCOMPLETE if configured_checks or check_data else CheckStatus.NOT_RUN
            if configured_checks or check_data:
                reasons.append("configured checks have missing, duplicate or unexpected evidence")
        elif not configured_checks:
            check_status = CheckStatus.NOT_RUN
        elif any(item["timed_out"] or item["output_truncated"] or item["exit_code"] is None
                 for item in check_data):
            check_status = CheckStatus.INCOMPLETE
        elif any(item["exit_code"] != 0 for item in check_data):
            check_status = CheckStatus.FAILED
        else:
            check_status = CheckStatus.PASSED
        if result is None or result.job_id != job_id:
            reasons.append("worker result is missing or has the wrong job ID")
            outcome = WorkerOutcome.FAILED
            summary = "Worker result unavailable."
            error = None
            metrics: dict[str, Any] = {"usage": {"unknown": True}}
        else:
            outcome = result.outcome
            try:
                summary = _text(result.summary, limit=16 * 1024)
            except (ReviewBundleError, UnicodeError):
                summary = "Worker summary omitted: invalid or oversized."
                reasons.append("worker summary was invalid or oversized")
            try:
                error = _text(result.error, limit=4096) if result.error is not None else None
            except (ReviewBundleError, UnicodeError):
                error = "Worker error omitted: invalid or oversized."
                reasons.append("worker error was invalid or oversized")
            try:
                if not isinstance(result.metrics, dict):
                    raise ReviewBundleError("worker metrics must be an object")
                _json(result.metrics, limit=32 * 1024)
            except ReviewBundleError:
                metrics = {"usage": {"unknown": True}}
                reasons.append("worker metrics were invalid or oversized")
            else:
                metrics = dict(result.metrics)
                if not isinstance(metrics.get("usage"), dict):
                    metrics["usage"] = {"unknown": True}
                    reasons.append("provider usage is unavailable")
        patch = None
        final_digest = None
        changes: list[dict[str, Any]] = []
        if final_files is None:
            reasons.append("complete final workspace export is missing")
        else:
            try:
                final_files = tuple(final_files)
                review_patch = build_review_patch(base, final_files)
                patch = review_patch.patch
                final_digest = _manifest_digest(final_files)
                changes = [asdict(change) for change in review_patch.changes]
            except (SnapshotError, ReviewPatchError, ValueError, TypeError):
                reasons.append("final workspace is unsafe, incomplete or unrepresentable")
        if execution_sandbox_id is None:
            reasons.append("execution sandbox identity is missing")
        if cleanup_status is not CleanupStatus.CLEAN:
            reasons.append("execution sandbox cleanup is not confirmed clean")
        if outcome is not WorkerOutcome.SUBMITTED:
            reasons.append("worker did not submit a reviewable result")
        if policy.budget.max_cost_usd is not None:
            reasons.append("strict USD ceiling has no trusted pre-call enforcement")
        if policy.worker_profile == "coding-worker" and not changes:
            reasons.append("coding task has no reviewable changes")
        if policy.worker_profile == "coding-worker" and not configured_checks:
            reasons.append("coding task has no configured checks")
        if check_status is not CheckStatus.PASSED and configured_checks:
            reasons.append("configured checks did not all pass")
        replay_data: dict[str, Any] | None = None
        if replay is not None:
            replay_data = {**asdict(replay), "cleanup_status": replay.cleanup_status.value}
        replay_ok = (patch is not None and replay is not None
                     and _ID.fullmatch(replay.sandbox_id) is not None
                     and replay.sandbox_id != execution_sandbox_id
                     and replay.base_snapshot_sha256 == base_digest
                     and replay.patch_sha256 == _sha(patch)
                     and replay.final_manifest_sha256 == final_digest
                     and replay.matches_final is True
                     and replay.cleanup_status is CleanupStatus.CLEAN)
        if not replay_ok:
            reasons.append("patch replay in a separate clean disposable sandbox is unverified")
        # Only trusted orchestration can supply a replay receipt. This offline
        # contract cannot attest an actual VM: the live backend must remain off.
        ready = not reasons and check_status is CheckStatus.PASSED
        state = "ready_for_review" if ready else ("incomplete" if patch is None else "evidence_only")
        configuration = asdict(policy)
        configuration["plan"] = policy.plan.value
        report = {
            "version": 1, "job_id": job_id, "state": state, "reasons": reasons,
            "configuration": configuration,
            "task": {"objective": task.objective, "acceptance_criteria": list(task.acceptance_criteria)},
            "base_snapshot_sha256": base_digest, "final_manifest_sha256": final_digest,
            "image_sha256": base.image_sha256, "execution_sandbox_id": execution_sandbox_id,
            "changes": changes, "check_status": check_status.value,
            "review_status": "not_reviewed", "cleanup_status": cleanup_status.value,
            "checks": check_data, "commands": command_data, "replay": replay_data,
            "worker": {"outcome": outcome.value, "summary": summary, "error": error,
                       "metrics": metrics, "checks_are_untrusted": True},
            "missing_guest_evidence": final_files is None,
        }
        report_bytes = _json(report, limit=_REPORT_LIMIT)
        files: dict[str, bytes] = {"report.json": report_bytes}
        if patch is not None:
            files["patch.diff"] = patch
        for name, data in files.items():
            self._write(directory, name, data)
        manifest_bytes = _json({"version": 1, "job_id": job_id,
                                "files": {name: {"size": len(data), "sha256": _sha(data)}
                                          for name, data in files.items()}}, limit=_META_LIMIT)
        self._write(directory, "manifest.json", manifest_bytes)
        self._write(directory, "complete.json", _json({
            "version": 1, "job_id": job_id, "manifest_sha256": _sha(manifest_bytes),
        }, limit=_META_LIMIT))
        return SavedReviewBundle(job_id, state, directory, tuple(reasons))

    def read(self, job_id: str) -> tuple[SavedReviewBundle, bytes | None]:
        """Verify stored hashes; callers must render untrusted JSON with escaping."""
        if not _ID.fullmatch(job_id):
            raise ReviewBundleError("review job ID is invalid")
        directory = self.root / job_id
        _safe_path(directory)
        if not directory.is_dir():
            raise ReviewBundleError("review bundle is unavailable")
        _read(directory / "incomplete.json", _META_LIMIT)
        if not (directory / "complete.json").exists():
            return SavedReviewBundle(job_id, "incomplete", directory, ("write interrupted",)), None
        marker = json.loads(_read(directory / "complete.json", _META_LIMIT))
        manifest_bytes = _read(directory / "manifest.json", _META_LIMIT)
        if (not isinstance(marker, dict) or marker.get("job_id") != job_id
                or marker.get("version") != 1 or marker.get("manifest_sha256") != _sha(manifest_bytes)):
            raise ReviewBundleError("review completion marker is invalid")
        manifest = json.loads(manifest_bytes)
        if (not isinstance(manifest, dict) or manifest.get("job_id") != job_id
                or manifest.get("version") != 1 or not isinstance(manifest.get("files"), dict)
                or not {"report.json"} <= set(manifest["files"])
                or set(manifest["files"]) - {"report.json", "patch.diff"}):
            raise ReviewBundleError("review manifest is invalid")
        content: dict[str, bytes] = {}
        for name, limit in (("report.json", _REPORT_LIMIT), ("patch.diff", _PATCH_LIMIT)):
            if name not in manifest["files"]:
                continue
            entry = manifest["files"][name]
            data = _read(directory / name, limit)
            if (not isinstance(entry, dict) or set(entry) != {"size", "sha256"}
                    or type(entry["size"]) is not int or entry["size"] != len(data)
                    or not isinstance(entry["sha256"], str) or not _DIGEST.fullmatch(entry["sha256"])
                    or _sha(data) != entry["sha256"]):
                raise ReviewBundleError("review file hash or size mismatch")
            content[name] = data
        report = json.loads(content["report.json"])
        if not isinstance(report, dict) or report.get("job_id") != job_id or report.get("state") not in {
            "ready_for_review", "incomplete", "evidence_only",
        }:
            raise ReviewBundleError("review report identity or state is invalid")
        # Return JSON bytes, not terminal-rendered guest text.
        return SavedReviewBundle(job_id, report["state"], directory,
                                 tuple(report.get("reasons", ()))), content.get("patch.diff")
