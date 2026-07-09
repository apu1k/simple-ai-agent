from types import SimpleNamespace

from tools.knowledge.config import QdrantConfig
from tools.knowledge.embeddings.hashing import HashingEmbeddingModel
from tools.knowledge.models import CapabilityDefinition, KnowledgeSearchRequest
from tools.knowledge.registry import CapabilityRegistry


class FakeRouterClient:
    def __init__(self, results=None, error=None):
        self.results = results or []
        self.error = error
        self.queried = False

    def query_points(self, collection_name, query, limit, with_payload):
        self.queried = True
        if self.error is not None:
            raise self.error
        return SimpleNamespace(points=self.results[:limit])


def make_capabilities():
    return [
        CapabilityDefinition(
            id="search.recent_chats",
            name="Search Recent Chats",
            description="Search previous chat history.",
            handler="tools.knowledge.capabilities.local.SearchRecentChatsCapability",
            tags=["chats", "history"],
            required_permissions=["chats.read"],
            sensitivity="personal",
        ),
        CapabilityDefinition(
            id="search.long_term_memory",
            name="Search Long-Term Memory",
            description="Search durable memories.",
            handler="tools.knowledge.capabilities.local.SearchLongTermMemoryCapability",
            tags=["memory"],
            required_permissions=["memory.read"],
            sensitivity="personal",
        ),
    ]


def test_registry_uses_qdrant_router_when_enabled():
    client = FakeRouterClient(
        results=[
            {
                "score": 0.91,
                "payload": {"capability_id": "search.recent_chats"},
            }
        ]
    )
    registry = CapabilityRegistry(
        capabilities=make_capabilities(),
        qdrant_config=QdrantConfig(
            enabled=True,
            capability_collection="agent_capability_router",
            vector_size=8,
        ),
        qdrant_client=client,
        embedding_model=HashingEmbeddingModel(dimensions=8),
    )

    candidates = registry.search(
        KnowledgeSearchRequest(query="what did we decide in chats?"),
        top_k=3,
    )

    assert client.queried is True
    assert [candidate.capability.id for candidate in candidates] == ["search.recent_chats"]
    assert candidates[0].reason == "Matched by local Qdrant capability router"
    assert registry.diagnostics()["qdrant_attempted"] is True
    assert registry.diagnostics()["qdrant_used"] is True
    assert registry.diagnostics()["fallback_used"] is False


def test_registry_falls_back_to_keyword_router_when_qdrant_fails():
    client = FakeRouterClient(error=RuntimeError("missing collection"))
    registry = CapabilityRegistry(
        capabilities=make_capabilities(),
        qdrant_config=QdrantConfig(enabled=True, vector_size=8),
        qdrant_client=client,
        embedding_model=HashingEmbeddingModel(dimensions=8),
    )

    candidates = registry.search(
        KnowledgeSearchRequest(query="search memory", sources=["memory"]),
        top_k=3,
    )

    assert client.queried is True
    assert [candidate.capability.id for candidate in candidates] == [
        "search.long_term_memory"
    ]
    assert candidates[0].reason.startswith("Matched terms:")
    assert registry.diagnostics()["qdrant_attempted"] is True
    assert registry.diagnostics()["qdrant_used"] is False
    assert registry.diagnostics()["fallback_used"] is True
    assert registry.diagnostics()["qdrant_error"] == "missing collection"


def test_registry_does_not_use_qdrant_router_when_disabled():
    client = FakeRouterClient(
        results=[
            {
                "score": 0.99,
                "payload": {"capability_id": "search.recent_chats"},
            }
        ]
    )
    registry = CapabilityRegistry(
        capabilities=make_capabilities(),
        qdrant_config=QdrantConfig(enabled=False, vector_size=8),
        qdrant_client=client,
        embedding_model=HashingEmbeddingModel(dimensions=8),
    )

    candidates = registry.search(
        KnowledgeSearchRequest(query="search memory", sources=["memory"]),
        top_k=3,
    )

    assert client.queried is False
    assert [candidate.capability.id for candidate in candidates] == [
        "search.long_term_memory"
    ]
