"""Immutable job policy snapshot and conservative, offline execution limits.

This is not a live-worker launcher. A live backend must supply a killable inference
transport and trusted pricing/reservations before the preflight can succeed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from night_shifts.executor import ModelExecutorLimits
from night_shifts.inference import InferenceLimits
from night_shifts.models import AgentPlan, JobBudget, NightShiftJob, SandboxSpec
from night_shifts.worker_capabilities import worker_tool_names

_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_EFFORTS = frozenset({"none", "minimal", "low", "medium", "high", "xhigh", "max"})


class ExecutionPolicyBlocked(RuntimeError):
    """A live job cannot dispatch until the missing guarantee is provided."""


@dataclass(frozen=True)
class WorkerExecutionPolicy:
    """Value-only snapshot: never retain mutable runtime settings or provider objects."""

    job_id: str
    repository_id: str
    base_revision: str
    image_sha256: str
    provider_id: str
    model_id: str
    worker_profile: str
    plan: AgentPlan
    reasoning_effort: str | None
    service_tier: str
    sandbox: SandboxSpec
    budget: JobBudget

    @classmethod
    def snapshot(
        cls,
        job: NightShiftJob,
        *,
        image_sha256: str,
        provider_id: str,
        model_id: str,
        reasoning_effort: str | None = None,
        service_tier: str = "default",
        sandbox: SandboxSpec | None = None,
    ) -> WorkerExecutionPolicy:
        if not job.job_id or not job.repository_id or not job.starting_revision:
            raise ValueError("job, approved repository and immutable revision are required")
        if not _SHA256.fullmatch(image_sha256):
            raise ValueError("reviewed image SHA-256 must be a lowercase digest")
        if not _ID.fullmatch(provider_id) or not _ID.fullmatch(model_id):
            raise ValueError("provider and model must be trusted stable IDs")
        worker_tool_names(job.worker_profile)
        if reasoning_effort is not None and reasoning_effort not in _EFFORTS:
            raise ValueError("unsupported reasoning effort")
        if service_tier not in {"default", "flex"}:
            raise ValueError("unsupported service tier")
        if service_tier == "flex" and job.plan is not AgentPlan.FLEX:
            raise ValueError("service tier conflicts with the job plan")
        selected_sandbox = sandbox or SandboxSpec()
        if selected_sandbox.network_enabled:
            raise ValueError("network-enabled worker sandboxes are not approved")
        return cls(
            job_id=job.job_id,
            repository_id=job.repository_id,
            base_revision=job.starting_revision,
            image_sha256=image_sha256,
            provider_id=provider_id,
            model_id=model_id,
            worker_profile=job.worker_profile,
            plan=job.plan,
            reasoning_effort=reasoning_effort,
            service_tier=service_tier,
            sandbox=selected_sandbox,
            budget=job.budget,
        )

    def executor_limits(self) -> ModelExecutorLimits:
        return ModelExecutorLimits(
            max_turns=self.budget.max_model_requests,
            max_tool_calls=min(self.budget.max_tool_calls, 256),
            max_summary_bytes=min(self.budget.max_output_bytes, 256 * 1024),
        )

    def inference_limits(self) -> InferenceLimits:
        return InferenceLimits(
            max_requests=self.budget.max_model_requests,
            max_input_bytes=self.budget.max_input_bytes,
            max_output_bytes=self.budget.max_output_bytes,
            ttl_seconds=min(self.budget.timeout_seconds, 86_400),
        )

    def require_live_guarantees(
        self, *, inference_cancellable: bool = False, tool_cancellable: bool = False
    ) -> None:
        """Trusted composition must prove BOTH cancellation boundaries before dispatch.

        A real backend must not treat caller-provided booleans as proof: these
        describe administrator-constructed components, not task-selected values.
        Strict USD remains unsupported without audited pricing and reservations.
        """
        if self.budget.max_cost_usd is not None:
            raise ExecutionPolicyBlocked(
                "strict USD ceiling has no trusted pricing and pre-call reservation"
            )
        if not inference_cancellable or not tool_cancellable:
            raise ExecutionPolicyBlocked(
                "host inference and tool transport are not hard-cancellable yet"
            )
