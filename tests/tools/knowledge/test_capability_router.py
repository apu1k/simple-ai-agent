from types import SimpleNamespace

from tools.knowledge.config import QdrantConfig
from tools.knowledge.embeddings.hashing import HashingEmbeddingModel
from tools.knowledge.indexes.capability_router import (
    build_capability_router_points,
    index_capability_router,
    search_capability_router,
)
from tools.knowledge.indexes.qdrant_payloads import capability_router_point_id
from tools.knowledge.models import CapabilityDefinition


class FakeQdrantClient:
    def __init__(self):
        self.upserts = []
        self.results = []
        self.last_query = None

    def upsert(self, collection_name, points):
        self.upserts.append({"collection_name": collection_name, "points": points})

    def query_points(self, collection_name, query, limit, with_payload):
        self.last_query = {
            "collection_name": collection_name,
            "query": query,
            "limit": limit,
            "with_payload": with_payload,
        }
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
            id="search.internet",
            name="Search Internet",
            description="Searches the internet.",
            handler="tests.SearchInternetCapability",
            tags=["internet", "network"],
            required_permissions=["network.read"],
            sensitivity="external",
            allow_network=True,
        ),
    ]


def test_build_capability_router_points_keeps_router_payload_separate():
    model = HashingEmbeddingModel(dimensions=16)
    capability = make_capabilities()[0]

    points = build_capability_router_points([capability], model)

    assert len(points) == 1
    point = points[0]
    assert point["id"] == capability_router_point_id("search.recent_chats")
    assert len(point["vector"]) == 16
    assert point["payload"]["index_kind"] == "capability_router"
    assert point["payload"]["capability_id"] == "search.recent_chats"
    assert point["payload"]["handler"] == capability.handler
    assert "Capability: Search Recent Chats" in point["payload"]["embedding_text"]
    assert "collection" not in point["payload"]


def test_index_capability_router_upserts_points_to_configured_collection():
    client = FakeQdrantClient()
    config = QdrantConfig(capability_collection="agent_capability_router", vector_size=8)
    model = HashingEmbeddingModel(dimensions=8)

    count = index_capability_router(client, config, make_capabilities()[:1], model)

    assert count == 1
    assert len(client.upserts) == 1
    assert client.upserts[0]["collection_name"] == "agent_capability_router"
    assert len(client.upserts[0]["points"]) == 1


def test_search_capability_router_returns_candidates_from_qdrant_hits():
    client = FakeQdrantClient()
    capabilities = make_capabilities()
    client.results = [
        {
            "score": 0.92,
            "payload": {
                "index_kind": "capability_router",
                "capability_id": "search.recent_chats",
            },
        }
    ]
    config = QdrantConfig(capability_collection="agent_capability_router", vector_size=8)
    model = HashingEmbeddingModel(dimensions=8)

    candidates = search_capability_router(
        client=client,
        config=config,
        query="what did we decide about qdrant in previous chats?",
        capabilities=capabilities,
        embedding_model=model,
        top_k=3,
    )

    assert [candidate.capability.id for candidate in candidates] == ["search.recent_chats"]
    assert candidates[0].score == 0.92
    assert candidates[0].reason == "Matched by local Qdrant capability router"
    assert client.last_query["collection_name"] == "agent_capability_router"
    assert client.last_query["limit"] == 3
    assert client.last_query["with_payload"] is True


def test_search_capability_router_respects_network_and_source_filters():
    client = FakeQdrantClient()
    capabilities = make_capabilities()
    client.results = [
        {"score": 0.99, "payload": {"capability_id": "search.internet"}},
        {"score": 0.80, "payload": {"capability_id": "search.recent_chats"}},
    ]
    config = QdrantConfig(capability_collection="agent_capability_router", vector_size=8)
    model = HashingEmbeddingModel(dimensions=8)

    candidates = search_capability_router(
        client=client,
        config=config,
        query="search chats",
        capabilities=capabilities,
        embedding_model=model,
        top_k=5,
        allow_network=False,
        sources=["chats"],
    )

    assert [candidate.capability.id for candidate in candidates] == ["search.recent_chats"]
