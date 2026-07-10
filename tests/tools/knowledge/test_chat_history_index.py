from __future__ import annotations

import json
from types import SimpleNamespace

from tools.knowledge.config import QdrantConfig, QdrantDataCollectionConfig
from tools.knowledge.embeddings.hashing import HashingEmbeddingModel
from tools.knowledge.indexes.chat_history import (
    build_chat_history_points,
    chat_history_point_id,
    chat_history_payload,
    find_chat_history_turn,
    index_chat_history_collection,
    index_chat_history_turn,
    iter_chat_history_records,
    search_chat_history_collection,
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
        key="chat_history",
        collection="agent_chat_history",
        description="Complete chat history.",
        sensitivity="personal",
        source_type="chats",
    )


def make_config():
    return QdrantConfig(
        enabled=True,
        vector_size=8,
        data_collections={"chat_history": make_collection()},
    )


def write_chat_turn(chat_dir, filename="turns_original.jsonl"):
    chat_dir.mkdir(parents=True, exist_ok=True)
    path = chat_dir / filename
    path.write_text(
        json.dumps(
            {
                "type": "turn",
                "session_id": "session-1",
                "turn_index": 3,
                "user": "Should Qdrant index complete chat history?",
                "assistant_final": "Yes, as a normal evidence collection.",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def test_iter_chat_history_records_returns_readable_evidence_records(tmp_path):
    chat_dir = tmp_path / ".agent_chat_history"
    path = write_chat_turn(chat_dir)

    records = list(iter_chat_history_records(chat_dir))

    assert len(records) == 1
    record = records[0]
    assert record["path"] == str(path)
    assert record["line"] == 1
    assert record["title"] == f"{path}:1"
    assert record["content"].startswith("User: Should Qdrant")
    assert "Assistant: Yes" in record["content"]
    assert "complete chat history" in record["embedding_text"]
    assert record["embedding_text"] == record["content"]
    assert '"state"' not in record["embedding_text"]
    assert record["metadata"]["session_id"] == "session-1"


def test_iter_chat_history_records_ignores_session_metadata_files(tmp_path):
    chat_dir = tmp_path / ".agent_chat_history"
    chat_dir.mkdir(parents=True, exist_ok=True)
    (chat_dir / "sessions.jsonl").write_text(
        json.dumps(
            {
                "type": "session_created",
                "session_id": "session-1",
                "content": json.dumps(
                    {
                        "type": "session_created",
                        "title": "not a real chat turn",
                    }
                ),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    turns_path = write_chat_turn(chat_dir, filename="turns_original.jsonl")

    records = list(iter_chat_history_records(chat_dir))

    assert len(records) == 1
    assert records[0]["path"] == str(turns_path)
    assert records[0]["metadata"]["type"] == "turn"


def test_build_chat_history_points_uses_evidence_collection_payload(tmp_path):
    chat_dir = tmp_path / ".agent_chat_history"
    path = write_chat_turn(chat_dir)
    model = HashingEmbeddingModel(dimensions=8)

    points = build_chat_history_points(chat_dir, make_collection(), model)

    assert len(points) == 1
    point = points[0]
    assert point["id"] == chat_history_point_id(str(path), 1)
    assert len(point["vector"]) == 8
    assert point["payload"]["index_kind"] == "evidence_collection"
    assert point["payload"]["source_key"] == "chat_history"
    assert point["payload"]["collection"] == "agent_chat_history"
    assert point["payload"]["type"] == "chat_match"
    assert "Capability:" not in point["payload"]["content"]


def test_chat_history_payload_preserves_source_metadata():
    record = {
        "path": "history.jsonl",
        "line": 12,
        "title": "history.jsonl:12",
        "content": "User: hello",
        "metadata": {"session_id": "abc"},
    }

    payload = chat_history_payload(record, make_collection())

    assert payload["index_kind"] == "evidence_collection"
    assert payload["source_key"] == "chat_history"
    assert payload["source_type"] == "chats"
    assert payload["path"] == "history.jsonl"
    assert payload["line"] == 12
    assert payload["metadata"] == {"session_id": "abc"}


def test_index_chat_history_collection_creates_collection_and_upserts(tmp_path):
    chat_dir = tmp_path / ".agent_chat_history"
    write_chat_turn(chat_dir)
    client = FakeQdrantClient()
    model = HashingEmbeddingModel(dimensions=8)

    count = index_chat_history_collection(client, make_config(), chat_dir, model)

    assert count == 1
    assert client.created_collections[0]["collection_name"] == "agent_chat_history"
    assert client.upserts[0]["collection_name"] == "agent_chat_history"
    assert len(client.upserts[0]["points"]) == 1


def test_find_chat_history_turn_returns_only_requested_original_turn(tmp_path):
    chat_dir = tmp_path / ".agent_chat_history"
    path = chat_dir / "turns_original.jsonl"
    chat_dir.mkdir(parents=True)
    records = [
        {
            "type": "turn",
            "stream": "original",
            "session_id": "session-1",
            "turn_index": 1,
            "user": "first",
            "assistant_final": "answer one",
        },
        {
            "type": "turn",
            "stream": "original",
            "session_id": "session-1",
            "turn_index": 2,
            "user": "second",
            "assistant_final": "answer two",
        },
    ]
    path.write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )

    record = find_chat_history_turn(path, "session-1", 2)

    assert record is not None
    assert record["line"] == 2
    assert record["content"] == "User: second\n\nAssistant: answer two"
    assert record["metadata"]["turn_index"] == 2


def test_index_chat_history_turn_upserts_only_requested_turn(tmp_path):
    chat_dir = tmp_path / ".agent_chat_history"
    path = chat_dir / "turns_original.jsonl"
    chat_dir.mkdir(parents=True)
    records = [
        {
            "type": "turn",
            "session_id": "session-1",
            "turn_index": index,
            "user": f"user {index}",
            "assistant_final": f"assistant {index}",
        }
        for index in (1, 2)
    ]
    path.write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )
    client = FakeQdrantClient()

    count = index_chat_history_turn(
        client=client,
        config=make_config(),
        path=path,
        session_id="session-1",
        turn_index=2,
        embedding_model=HashingEmbeddingModel(dimensions=8),
    )

    assert count == 1
    assert len(client.upserts) == 1
    assert len(client.upserts[0]["points"]) == 1
    point = client.upserts[0]["points"][0]
    point_id = point["id"] if isinstance(point, dict) else point.id
    payload = point["payload"] if isinstance(point, dict) else point.payload
    assert str(point_id) == chat_history_point_id(str(path), 2)
    assert payload["content"] == "User: user 2\n\nAssistant: assistant 2"


def test_search_chat_history_collection_returns_evidence_items():
    client = FakeQdrantClient()
    client.results = [
        {
            "score": 0.87,
            "payload": {
                "index_kind": "evidence_collection",
                "source_key": "chat_history",
                "source_type": "chats",
                "type": "chat_match",
                "source": "chat_history",
                "title": "history.jsonl:1",
                "path": "history.jsonl",
                "line": 1,
                "content": "User: Qdrant chat history",
                "metadata": {"session_id": "session-1"},
            },
        }
    ]
    model = HashingEmbeddingModel(dimensions=8)

    items = search_chat_history_collection(
        client=client,
        config=make_config(),
        query="Qdrant chat history",
        embedding_model=model,
        limit=5,
    )

    assert len(items) == 1
    item = items[0]
    assert item.type == "chat_match"
    assert item.source == "chat_history"
    assert item.title == "history.jsonl:1"
    assert item.content == "User: Qdrant chat history"
    assert item.confidence == 0.87
    assert item.metadata["session_id"] == "session-1"
    assert item.metadata["score"] == 0.87
    assert client.last_query["collection_name"] == "agent_chat_history"
    assert client.last_query["limit"] == 5
