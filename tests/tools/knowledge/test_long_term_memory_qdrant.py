from types import SimpleNamespace

from tools.knowledge.capabilities.local import SearchLongTermMemoryCapability
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
            "long_term_memory": QdrantDataCollectionConfig(
                key="long_term_memory",
                collection="agent_long_term_memory",
                source_type="memory",
                sensitivity="personal",
            )
        },
    )


def make_request(tmp_path, query="local search"):
    return KnowledgeSearchRequest(
        query=query,
        cwd=str(tmp_path),
        max_results=5,
    )


def test_long_term_memory_capability_uses_qdrant_when_enabled(tmp_path):
    client = FakeQdrantClient(
        results=[
            {
                "score": 0.88,
                "payload": {
                    "index_kind": "evidence_collection",
                    "source_key": "long_term_memory",
                    "source_type": "memory",
                    "type": "memory_match",
                    "source": "long_term_memory",
                    "title": "memory.jsonl:1",
                    "path": "memory.jsonl",
                    "line": 1,
                    "content": "The user prefers local semantic search.",
                    "metadata": {"tags": ["preferences"]},
                },
            }
        ]
    )
    capability = SearchLongTermMemoryCapability(
        qdrant_config=make_config(enabled=True),
        qdrant_client=client,
        embedding_model=HashingEmbeddingModel(dimensions=8),
    )

    bundle = capability.search(make_request(tmp_path))

    assert client.queried is True
    assert bundle.capability_id == "search.long_term_memory"
    assert bundle.items[0].content == "The user prefers local semantic search."
    assert bundle.items[0].metadata["source_key"] == "long_term_memory"
    assert bundle.confidence == 0.88


def test_long_term_memory_capability_falls_back_to_keyword_when_qdrant_fails(tmp_path):
    memory_dir = tmp_path / "runtime" / "knowledge"
    memory_dir.mkdir(parents=True)
    (memory_dir / "memory.jsonl").write_text(
        '{"content":"Qdrant fallback memory","tags":["test"]}\n',
        encoding="utf-8",
    )
    client = FakeQdrantClient(error=RuntimeError("missing collection"))
    capability = SearchLongTermMemoryCapability(
        qdrant_config=make_config(enabled=True),
        qdrant_client=client,
        embedding_model=HashingEmbeddingModel(dimensions=8),
    )

    bundle = capability.search(make_request(tmp_path, query="fallback"))

    assert client.queried is True
    assert len(bundle.items) == 1
    assert bundle.items[0].content == "Qdrant fallback memory"
    assert bundle.items[0].metadata["path"].endswith("memory.jsonl")


def test_long_term_memory_capability_does_not_use_qdrant_when_disabled(tmp_path):
    memory_dir = tmp_path / "runtime" / "knowledge"
    memory_dir.mkdir(parents=True)
    (memory_dir / "memory.jsonl").write_text(
        '{"content":"local keyword memory search"}\n',
        encoding="utf-8",
    )
    client = FakeQdrantClient(
        results=[
            {
                "score": 0.99,
                "payload": {
                    "index_kind": "evidence_collection",
                    "source_key": "long_term_memory",
                    "content": "wrong vector result",
                },
            }
        ]
    )
    capability = SearchLongTermMemoryCapability(
        qdrant_config=make_config(enabled=False),
        qdrant_client=client,
        embedding_model=HashingEmbeddingModel(dimensions=8),
    )

    bundle = capability.search(make_request(tmp_path, query="keyword"))

    assert client.queried is False
    assert len(bundle.items) == 1
    assert bundle.items[0].content == "local keyword memory search"
