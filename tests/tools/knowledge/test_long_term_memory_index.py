from __future__ import annotations

import json
from types import SimpleNamespace

from tools.knowledge.config import QdrantConfig, QdrantDataCollectionConfig
from tools.knowledge.embeddings.hashing import HashingEmbeddingModel
from tools.knowledge.indexes.long_term_memory import (
    build_long_term_memory_points,
    index_long_term_memory_collection,
    iter_long_term_memory_records,
    memory_payload,
    memory_point_id,
    search_long_term_memory_collection,
)


class FakeQdrantClient:
    def __init__(self):
        self.created_collections = []
        self.upserts = []
        self.results = []
        self.last_query = None

    def collection_exists(self, collection_name):
        return False

    def create_collection(self, collection_name, vectors_config):
        self.created_collections.append(
            {"collection_name": collection_name, "vectors_config": vectors_config}
        )

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


def make_collection():
    return QdrantDataCollectionConfig(
        key="long_term_memory",
        collection="agent_long_term_memory",
        description="Durable user/agent memory.",
        sensitivity="personal",
        source_type="memory",
    )


def make_config():
    return QdrantConfig(
        enabled=True,
        vector_size=8,
        data_collections={"long_term_memory": make_collection()},
    )


def write_memory(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "content": "The user prefers local-only semantic search.",
                "tags": ["preferences", "privacy"],
                "created_at": "2026-07-05T00:00:00Z",
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_iter_long_term_memory_records_returns_clean_embedding_text(tmp_path):
    memory_path = tmp_path / "runtime" / "knowledge" / "memory.jsonl"
    write_memory(memory_path)

    records = list(iter_long_term_memory_records(memory_path))

    assert len(records) == 1
    record = records[0]
    assert record["path"] == str(memory_path)
    assert record["line"] == 1
    assert record["content"] == "The user prefers local-only semantic search."
    assert record["embedding_text"] == record["content"]
    assert record["metadata"] == {
        "tags": ["preferences", "privacy"],
        "created_at": "2026-07-05T00:00:00Z",
        "format": "jsonl",
    }


def test_iter_long_term_memory_records_supports_plain_text_and_dedupes(tmp_path):
    memory_path = tmp_path / "memory.jsonl"
    memory_path.write_text(
        "Remember Qdrant is local.\n"
        "  Remember   Qdrant is local.  \n",
        encoding="utf-8",
    )

    records = list(iter_long_term_memory_records(memory_path))

    assert len(records) == 1
    assert records[0]["content"] == "Remember Qdrant is local."
    assert records[0]["metadata"] == {"format": "text"}


def test_build_long_term_memory_points_uses_evidence_collection_payload(tmp_path):
    memory_path = tmp_path / "memory.jsonl"
    write_memory(memory_path)
    model = HashingEmbeddingModel(dimensions=8)

    points = build_long_term_memory_points(memory_path, make_collection(), model)

    assert len(points) == 1
    point = points[0]
    assert point["id"] == memory_point_id(str(memory_path), 1)
    assert len(point["vector"]) == 8
    assert point["payload"]["index_kind"] == "evidence_collection"
    assert point["payload"]["source_key"] == "long_term_memory"
    assert point["payload"]["collection"] == "agent_long_term_memory"
    assert point["payload"]["type"] == "memory_match"
    assert point["payload"]["content"] == "The user prefers local-only semantic search."


def test_memory_payload_preserves_source_metadata():
    record = {
        "path": "memory.jsonl",
        "line": 12,
        "title": "memory.jsonl:12",
        "content": "User likes YAML.",
        "metadata": {"tags": ["preferences"]},
    }

    payload = memory_payload(record, make_collection())

    assert payload["index_kind"] == "evidence_collection"
    assert payload["source_key"] == "long_term_memory"
    assert payload["source_type"] == "memory"
    assert payload["path"] == "memory.jsonl"
    assert payload["line"] == 12
    assert payload["metadata"] == {"tags": ["preferences"]}


def test_index_long_term_memory_collection_creates_collection_and_upserts(tmp_path):
    memory_path = tmp_path / "memory.jsonl"
    write_memory(memory_path)
    client = FakeQdrantClient()
    model = HashingEmbeddingModel(dimensions=8)

    count = index_long_term_memory_collection(client, make_config(), memory_path, model)

    assert count == 1
    assert client.created_collections[0]["collection_name"] == "agent_long_term_memory"
    assert client.upserts[0]["collection_name"] == "agent_long_term_memory"
    assert len(client.upserts[0]["points"]) == 1


def test_search_long_term_memory_collection_returns_evidence_items():
    client = FakeQdrantClient()
    client.results = [
        {
            "score": 0.91,
            "payload": {
                "index_kind": "evidence_collection",
                "source_key": "long_term_memory",
                "source_type": "memory",
                "type": "memory_match",
                "source": "long_term_memory",
                "title": "memory.jsonl:1",
                "path": "memory.jsonl",
                "line": 1,
                "content": "User prefers local-only search.",
                "metadata": {"tags": ["privacy"]},
            },
        }
    ]
    model = HashingEmbeddingModel(dimensions=8)

    items = search_long_term_memory_collection(
        client=client,
        config=make_config(),
        query="local-only search",
        embedding_model=model,
        limit=5,
    )

    assert len(items) == 1
    item = items[0]
    assert item.type == "memory_match"
    assert item.source == "long_term_memory"
    assert item.title == "memory.jsonl:1"
    assert item.content == "User prefers local-only search."
    assert item.confidence == 0.91
    assert item.metadata["tags"] == ["privacy"]
    assert item.metadata["score"] == 0.91
    assert client.last_query["collection_name"] == "agent_long_term_memory"
    assert client.last_query["limit"] == 5
