from tools.knowledge.engine import KnowledgeEngine
from tools.knowledge.models import (
    CapabilityCandidate,
    CapabilityDefinition,
    EvidenceBundle,
    KnowledgeSearchRequest,
)


CAPABILITY = CapabilityDefinition(
    id="search.test",
    name="Search Test",
    description="Test capability.",
    handler="tests.tools.knowledge.test_engine_trace.TestCapability",
)


class FakeRegistry:
    def search(self, request, top_k=5):
        return [CapabilityCandidate(CAPABILITY, score=0.9, reason="test")]

    def diagnostics(self):
        return {
            "qdrant_enabled": True,
            "qdrant_attempted": True,
            "qdrant_used": True,
            "fallback_used": False,
            "qdrant_error": None,
        }


class FakePlanner:
    def plan(self, request, candidates):
        return type("Plan", (), {"candidates": candidates})()


class FakeExecutor:
    def execute(self, candidate, request):
        return EvidenceBundle(
            capability_id=candidate.capability.id,
            source="test",
            status="success",
            confidence=1.0,
        )

    def diagnostics(self, candidate):
        return {
            "qdrant_enabled": True,
            "qdrant_attempted": True,
            "qdrant_used": False,
            "fallback_used": True,
            "qdrant_error": "missing collection",
        }


def test_engine_trace_includes_qdrant_diagnostics():
    engine = KnowledgeEngine(
        registry=FakeRegistry(),
        planner=FakePlanner(),
        executor=FakeExecutor(),
    )

    result = engine.search(KnowledgeSearchRequest(query="test", include_trace=True))

    assert result.trace is not None
    assert result.trace["qdrant"]["router"]["qdrant_used"] is True
    assert result.trace["qdrant"]["capabilities"]["search.test"]["fallback_used"] is True
