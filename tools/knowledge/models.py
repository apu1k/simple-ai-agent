from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


CapabilityType = Literal["search", "read", "write", "delete", "action"]


@dataclass(frozen=True)
class KnowledgeSearchRequest:
    query: str
    max_results: int = 10
    max_capabilities: int = 3
    sources: list[str] | None = None
    allow_network: bool = False
    include_trace: bool = False
    cwd: str = "."


@dataclass(frozen=True)
class CapabilityDefinition:
    id: str
    name: str
    description: str
    handler: str
    capability_type: CapabilityType = "search"
    tags: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
    required_permissions: list[str] = field(default_factory=list)
    sensitivity: str = "local"
    allow_network: bool = False
    expected_latency_ms: int | None = None
    expected_confidence: float = 0.5


@dataclass(frozen=True)
class CapabilityCandidate:
    capability: CapabilityDefinition
    score: float
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.capability.id,
            "name": self.capability.name,
            "score": self.score,
            "reason": self.reason,
            "tags": self.capability.tags,
            "sensitivity": self.capability.sensitivity,
        }


@dataclass(frozen=True)
class EvidenceItem:
    type: str
    source: str
    content: str
    title: str | None = None
    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvidenceBundle:
    capability_id: str
    source: str
    status: Literal["success", "partial", "error"]
    confidence: float
    items: list[EvidenceItem] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    latency_ms: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "source": self.source,
            "status": self.status,
            "confidence": self.confidence,
            "items": [item.to_dict() for item in self.items],
            "errors": self.errors,
            "latency_ms": self.latency_ms,
        }


@dataclass(frozen=True)
class KnowledgeSearchResult:
    query: str
    selected_capabilities: list[CapabilityCandidate]
    evidence_bundles: list[EvidenceBundle]
    trace: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        evidence_items: list[dict[str, Any]] = []
        for bundle in self.evidence_bundles:
            evidence_items.extend(item.to_dict() for item in bundle.items)

        data: dict[str, Any] = {
            "query": self.query,
            "selected_capabilities": [
                candidate.to_dict() for candidate in self.selected_capabilities
            ],
            "evidence": evidence_items,
            "evidence_bundles": [
                bundle.to_dict() for bundle in self.evidence_bundles
            ],
        }

        if self.trace is not None:
            data["trace"] = self.trace

        return data
