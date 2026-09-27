"""Fail-closed one-job final export, exact-ID cleanup and durable host report.

A trusted backend calls this after the worker loop, while the VM still exists.
It cannot launch a VM, prove isolation, or supply second-VM replay evidence.
"""

from __future__ import annotations

import re
from typing import Sequence

from night_shifts.contracts.sandbox import SandboxProvider
from night_shifts.execution_policy import WorkerExecutionPolicy
from night_shifts.models import SandboxRecord
from night_shifts.protocol import CleanupStatus, WorkerResult, WorkerTask
from night_shifts.review_bundle import ObservedOperation, ReviewBundleStore, SavedReviewBundle
from night_shifts.review_retrieval import retrieve_final_workspace
from night_shifts.snapshot import Snapshot, SnapshotFile
from night_shifts.tool_session import SandboxToolSession

_SANDBOX = re.compile(r"[0-9a-f]{32}\Z")


def collect_after_worker(
    *,
    store: ReviewBundleStore,
    provider: SandboxProvider,
    policy: WorkerExecutionPolicy,
    task: WorkerTask,
    base: Snapshot,
    sandbox: SandboxRecord | None,
    session: SandboxToolSession | None,
    result: WorkerResult | None,
    configured_checks: Sequence[str] = (),
    checks: Sequence[ObservedOperation] = (),
    commands: Sequence[ObservedOperation] = (),
) -> SavedReviewBundle:
    """Always attempt safe owned-VM destruction before persisting a review.

    This does not start sessions or replay a patch. A failed export must never
    become a no-op final workspace. A failed destroy is reported separately.
    The caller must reconcile a create() that failed before returning an ID.
    """
    valid_sandbox = (sandbox is not None and sandbox.backend == "hyperv"
                     and sandbox.job_id == policy.job_id
                     and _SANDBOX.fullmatch(sandbox.sandbox_id) is not None
                     and sandbox.external_id == f"night-shift-{sandbox.sandbox_id}")
    final_files: tuple[SnapshotFile, ...] | None = None
    diagnostics: list[str] = []
    cleanup = CleanupStatus.UNKNOWN
    sandbox_id = sandbox.sandbox_id if valid_sandbox and sandbox is not None else None
    try:
        if not valid_sandbox:
            diagnostics.append("persisted execution sandbox identity is unavailable or unsafe")
        elif sandbox is not None and sandbox.spec != policy.sandbox:
            diagnostics.append("execution sandbox resource or network policy does not match the approved job")
        elif session is None:
            diagnostics.append("sandbox tool session was unavailable at finalization")
        elif (session.job_id != policy.job_id or session.sandbox_id != sandbox_id
              or session.profile != policy.worker_profile):
            diagnostics.append("sandbox tool session identity or profile does not match the approved job")
        else:
            try:
                final_files = retrieve_final_workspace(session, base).files
            except Exception as exc:
                diagnostics.append(f"guest export failed: {type(exc).__name__}")
    finally:
        # A mismatched tool session must still be closed; it is never used for
        # export. A close error must not skip destruction of the owned VM.
        if session is not None:
            try:
                session.close()
            except Exception:
                diagnostics.append("sandbox tool session close failed")
        if valid_sandbox and sandbox is not None:
            try:
                provider.destroy(sandbox)
            except Exception:
                cleanup = CleanupStatus.FAILED
                diagnostics.append("owned sandbox destruction failed; operator reconciliation required")
            else:
                cleanup = CleanupStatus.CLEAN
    return store.collect(
        policy=policy, task=task, base=base, final_files=final_files, result=result,
        execution_sandbox_id=sandbox_id, configured_checks=configured_checks,
        checks=checks, commands=commands, cleanup_status=cleanup, diagnostics=diagnostics,
    )
