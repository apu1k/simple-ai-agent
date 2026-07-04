from types import SimpleNamespace

from tools.knowledge.capabilities.local import SearchRecentChatsCapability
from tools.knowledge.config import QdrantConfig, QdrantDataCollectionConfig
from tools.knowledge.embeddings.hashing import HashingEmbeddingModel
from tools.knowledge.models import KnowledgeSearchRequest


class FakeQdrantClient:
    def __init__(self, results=None, error=None):
        self.results = results or []
        self.error = error
        self.queried = False

    def query_points(self, collection_name, query, limit, with_payload):
        self.queried = True
        if self.error is not None:
            raise self.error
        return SimpleNamespace(points=self.results[:limit])


def make_config(enabled=True):
    return QdrantConfig(
        enabled=enabled,
        vector_size=8,
        data_collections={
            "chat_history": QdrantDataCollectionConfig(
                key="chat_history",
                collection="agent_chat_history",
                source_type="chats",
                sensitivity="personal",
            )
        },
    )


def make_request(tmp_path, query="Qdrant"):
    return KnowledgeSearchRequest(
        query=query,
        cwd=str(tmp_path),
        max_results=5,
    )


def test_recent_chats_capability_uses_qdrant_when_enabled(tmp_path):
    client = FakeQdrantClient(
        results=[
            {
                "score": 0.86,
                "payload": {
                    "index_kind": "evidence_collection",
                    "source_key": "chat_history",
                    "source_type": "chats",
                    "type": "chat_match",
                    "source": "chat_history",
                    "title": "history.jsonl:1",
                    "path": "history.jsonl",
                    "line": 1,
                    "content": "User: Qdrant evidence search",
                    "metadata": {"session_id": "session-1"},
                },
            }
        ]
    )
    capability = SearchRecentChatsCapability(
        qdrant_config=make_config(enabled=True),
        qdrant_client=client,
        embedding_model=HashingEmbeddingModel(dimensions=8),
    )

    bundle = capability.search(make_request(tmp_path))

    assert client.queried is True
    assert bundle.capability_id == "search.recent_chats"
    assert bundle.items[0].content == "User: Qdrant evidence search"
    assert bundle.items[0].metadata["source_key"] == "chat_history"
    assert bundle.confidence == 0.86


def test_recent_chats_capability_falls_back_to_keyword_when_qdrant_fails(tmp_path):
    chat_dir = tmp_path / ".agent_chat_history"
    chat_dir.mkdir()
    (chat_dir / "turns_original.jsonl").write_text(
        '{"user":"Qdrant fallback question","assistant_final":"keyword fallback answer"}\n',
        encoding="utf-8",
    )
    client = FakeQdrantClient(error=RuntimeError("missing collection"))
    capability = SearchRecentChatsCapability(
        qdrant_config=make_config(enabled=True),
        qdrant_client=client,
        embedding_model=HashingEmbeddingModel(dimensions=8),
    )

    bundle = capability.search(make_request(tmp_path, query="fallback"))

    assert client.queried is True
    assert len(bundle.items) == 1
    assert "Qdrant fallback question" in bundle.items[0].content
    assert bundle.items[0].metadata["path"].endswith("turns_original.jsonl")


def test_recent_chats_capability_does_not_use_qdrant_when_disabled(tmp_path):
    chat_dir = tmp_path / ".agent_chat_history"
    chat_dir.mkdir()
    (chat_dir / "turns_original.jsonl").write_text(
        '{"user":"Qdrant local keyword","assistant_final":"disabled vector search"}\n',
        encoding="utf-8",
    )
    client = FakeQdrantClient(
        results=[
            {
                "score": 0.99,
                "payload": {
                    "index_kind": "evidence_collection",
                    "source_key": "chat_history",
                    "content": "wrong vector result",
                },
            }
        ]
    )
    capability = SearchRecentChatsCapability(
        qdrant_config=make_config(enabled=False),
        qdrant_client=client,
        embedding_model=HashingEmbeddingModel(dimensions=8),
    )

    bundle = capability.search(make_request(tmp_path, query="keyword"))

    assert client.queried is False
    assert len(bundle.items) == 1
    assert "Qdrant local keyword" in bundle.items[0].content
