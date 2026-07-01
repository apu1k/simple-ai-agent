from __future__ import annotations

from dataclasses import dataclass

from tools.knowledge.models import CapabilityCandidate, KnowledgeSearchRequest


@dataclass(frozen=True)
class ExecutionPlan:
    candidates: list[CapabilityCandidate]


class SimpleCapabilityPlanner:
    def plan(
        self,
        request: KnowledgeSearchRequest,
        candidates: list[CapabilityCandidate],
    ) -> ExecutionPlan:
        selected = candidates[: max(1, int(request.max_capabilities))]
        return ExecutionPlan(candidates=selected)
