"""Host-side single-job loop composition; not a VM lifecycle/backend implementation.

A trusted backend owns VM destruction and must record that cleanup separately.
Only a sandbox-backed model tool provider can be supplied to this component.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from night_shifts.contracts.inference import WorkerInferenceClient
from night_shifts.execution_policy import WorkerExecutionPolicy
from night_shifts.executor import ExecutionControl, MediatedModelExecutor
from night_shifts.inference import TrustedInferenceGateway
from night_shifts.protocol import CleanupStatus, WorkerOutcome, WorkerResult, WorkerTask
from night_shifts.tool_session import SandboxToolSession


class HostJobExecution:
    """Bind the one model loop to a pre-validated sandbox tool session.

    Does not start, validate or destroy a VM. A future backend must enforce
    Gate A/B, provision and destroy the sandbox even when this method fails.
    """

    def __init__(
        self,
        policy: WorkerExecutionPolicy,
        gateway: TrustedInferenceGateway,
        client: WorkerInferenceClient,
        tools: SandboxToolSession,
        *,
        deadline: float,
        cancellation_requested: Callable[[], bool],
    ) -> None:
        self._policy = policy
        self._gateway = gateway
        self._client = client
        self._tools = tools
        self._deadline = deadline
        self._cancel = cancellation_requested

    def run(
        self,
        task: WorkerTask,
        emit_event: Callable[[str, dict[str, Any]], None],
    ) -> WorkerResult:
        result: WorkerResult
        try:
            if (
                type(self._deadline) not in (int, float)
                or not math.isfinite(self._deadline)
            ):
                result = WorkerResult(
                    self._policy.job_id, WorkerOutcome.FAILED,
                    "Worker deadline is invalid.", error="invalid monotonic job deadline",
                )
            elif (
                self._policy.job_id != self._tools.job_id
                or self._policy.worker_profile != self._tools.profile
                or task.job_id != self._policy.job_id
                or task.worker_profile != self._policy.worker_profile
                or task.repository_id != self._policy.repository_id
                or task.starting_revision != self._policy.base_revision
            ):
                result = WorkerResult(
                    self._policy.job_id, WorkerOutcome.FAILED,
                    "Worker task did not match its approved job policy.",
                    error="task or sandbox identity does not match frozen worker policy",
                )
            elif (
                self._tools.deadline > self._deadline
                or self._tools.max_command_seconds > self._policy.budget.max_command_seconds
            ):
                result = WorkerResult(
                    self._policy.job_id, WorkerOutcome.FAILED,
                    "Sandbox tool session exceeds the approved job policy.",
                    error="sandbox tool deadline or command limit exceeds job policy",
                )
            else:
                self._gateway.authorize_client(
                    self._client, job_id=self._policy.job_id,
                    worker_profile=self._policy.worker_profile,
                    model_id=self._policy.model_id,
                )
                result = MediatedModelExecutor(
                    self._client, limits=self._policy.executor_limits(),
                ).execute(
                    task, self._tools.model_tools(), emit_event,
                    control=ExecutionControl(self._deadline, self._cancel),
                )
        except Exception:
            # SDK/tool/callback exceptions may arrive after a cancellation or
            # deadline. A killed call cannot be mistaken for a successful result.
            try:
                cancelled = self._cancel()
            except Exception:
                cancelled = False
            if cancelled:
                outcome = WorkerOutcome.CANCELLED
            elif time.monotonic() >= self._deadline:
                outcome = WorkerOutcome.TIMED_OUT
            else:
                outcome = WorkerOutcome.FAILED
            result = WorkerResult(
                self._policy.job_id, outcome,
                "Worker stopped without a verified submission.",
                error="Worker execution or event reporting failed",
            )
        errors: list[str] = []
        for label, cleanup in (
            ("tool session", self._tools.cancel),
            ("inference child", lambda: self._gateway.close_client(self._client)),
        ):
            try:
                cleanup()
            except Exception:
                errors.append(f"{label} cleanup failed")
        if errors:
            result = replace(
                result, outcome=WorkerOutcome.FAILED,
                error="; ".join(errors), cleanup_status=CleanupStatus.FAILED,
            )
        elif result.outcome is WorkerOutcome.SUBMITTED:
            # Cancellation after a late model response still wins before return.
            try:
                cancelled = self._cancel()
            except Exception:
                cancelled = False
            if cancelled:
                result = replace(result, outcome=WorkerOutcome.CANCELLED)
        if result.outcome not in {WorkerOutcome.SUBMITTED, WorkerOutcome.BLOCKED}:
            if "usage" not in result.metrics:
                result = replace(result, metrics={
                    **result.metrics, "usage": {"unknown": True},
                })
        # A clean model/tool shutdown is not proof the VM or staging was removed.
        return result
