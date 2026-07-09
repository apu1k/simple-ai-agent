from __future__ import annotations

from dataclasses import replace
from time import perf_counter

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
        total_started = perf_counter()
        timings_ms: dict[str, int] = {}

        started = perf_counter()
        candidates = self.registry.search(
            request,
            top_k=max(5, int(request.max_capabilities)),
        )
        timings_ms["registry_search"] = _elapsed_ms(started)
        registry_diagnostics = self.registry.diagnostics()

        started = perf_counter()
        plan = self.planner.plan(request, candidates)
        timings_ms["planner"] = _elapsed_ms(started)

        bundles: list[EvidenceBundle] = []
        capability_timings: dict[str, int] = {}
        capability_diagnostics: dict[str, dict[str, object]] = {}
        for candidate in plan.candidates:
            started = perf_counter()
            try:
                bundle = self.executor.execute(candidate, request)
                latency_ms = _elapsed_ms(started)
                if bundle.latency_ms is None:
                    bundle = replace(bundle, latency_ms=latency_ms)
                bundles.append(bundle)
            except Exception as exc:
                latency_ms = _elapsed_ms(started)
                bundles.append(
                    EvidenceBundle(
                        capability_id=candidate.capability.id,
                        source=candidate.capability.name,
                        status="error",
                        confidence=0.0,
                        errors=[str(exc)],
                        latency_ms=latency_ms,
                    )
                )
            capability_timings[candidate.capability.id] = latency_ms
            capability_diagnostics[candidate.capability.id] = self.executor.diagnostics(candidate)

        timings_ms["capability_execution_total"] = sum(capability_timings.values())
        timings_ms["total"] = _elapsed_ms(total_started)

        trace = None
        if request.include_trace:
            trace = {
                "candidate_count": len(candidates),
                "planned_capability_count": len(plan.candidates),
                "candidates": [candidate.to_dict() for candidate in candidates],
                "qdrant": {
                    "router": registry_diagnostics,
                    "capabilities": capability_diagnostics,
                },
                "timings_ms": timings_ms,
                "capability_timings_ms": capability_timings,
            }

        return KnowledgeSearchResult(
            query=request.query,
            selected_capabilities=plan.candidates,
            evidence_bundles=bundles,
            trace=trace,
        )


def _elapsed_ms(started: float) -> int:
    return int(round((perf_counter() - started) * 1000))
