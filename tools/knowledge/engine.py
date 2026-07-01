from __future__ import annotations

from tools.knowledge.executor import CapabilityExecutor
from tools.knowledge.models import (
    EvidenceBundle,
    KnowledgeSearchRequest,
    KnowledgeSearchResult,
)
from tools.knowledge.planner import SimpleCapabilityPlanner
from tools.knowledge.registry import CapabilityRegistry


class KnowledgeEngine:
    def __init__(
        self,
        registry: CapabilityRegistry | None = None,
        planner: SimpleCapabilityPlanner | None = None,
        executor: CapabilityExecutor | None = None,
    ):
        self.registry = registry or CapabilityRegistry()
        self.planner = planner or SimpleCapabilityPlanner()
        self.executor = executor or CapabilityExecutor()

    def search(self, request: KnowledgeSearchRequest) -> KnowledgeSearchResult:
        candidates = self.registry.search(
            request,
            top_k=max(5, int(request.max_capabilities)),
        )
        plan = self.planner.plan(request, candidates)

        bundles: list[EvidenceBundle] = []
        for candidate in plan.candidates:
            try:
                bundles.append(self.executor.execute(candidate, request))
            except Exception as exc:
                bundles.append(
                    EvidenceBundle(
                        capability_id=candidate.capability.id,
                        source=candidate.capability.name,
                        status="error",
                        confidence=0.0,
                        errors=[str(exc)],
                    )
                )

        trace = None
        if request.include_trace:
            trace = {
                "candidate_count": len(candidates),
                "planned_capability_count": len(plan.candidates),
                "candidates": [candidate.to_dict() for candidate in candidates],
            }

        return KnowledgeSearchResult(
            query=request.query,
            selected_capabilities=plan.candidates,
            evidence_bundles=bundles,
            trace=trace,
        )
