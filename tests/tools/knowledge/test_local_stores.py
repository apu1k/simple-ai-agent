import json

from tools.knowledge.stores.local import JsonChatStore, SimpleMemoryStore


def test_json_chat_store_returns_readable_jsonl_turn_content(tmp_path):
    chat_dir = tmp_path / ".agent_chat_history"
    chat_dir.mkdir()
    turns_path = chat_dir / "turns_original.jsonl"
    turns_path.write_text(
        json.dumps(
            {
                "type": "turn",
                "stream": "original",
                "session_id": "session-1",
                "turn_index": 7,
                "created_at": "2026-07-02T00:00:00Z",
                "user": "Should we use Qdrant for capability search?",
                "assistant_final": "Yes, Qdrant can be used as the semantic index later.",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    hits = JsonChatStore(chat_dir).search("Qdrant", max_results=10)

    assert len(hits) == 1
    hit = hits[0]
    assert hit["line"] == 1
    assert hit["score"] == 1.0
    assert hit["content"].startswith("User: Should we use Qdrant")
    assert "Assistant: Yes, Qdrant" in hit["content"]
    assert '"assistant_final"' not in hit["content"]
    assert hit["metadata"] == {
        "format": "jsonl",
        "session_id": "session-1",
        "turn_index": 7,
        "stream": "original",
        "type": "turn",
        "created_at": "2026-07-02T00:00:00Z",
    }


def test_json_chat_store_streams_large_files_without_skipping(tmp_path):
    chat_dir = tmp_path / ".agent_chat_history"
    chat_dir.mkdir()
    turns_path = chat_dir / "turns_working.jsonl"
    large_prefix = "x" * 2_100_000
    turns_path.write_text(
        large_prefix
        + "\n"
        + json.dumps(
            {
                "type": "turn",
                "user": "Find information about Qdrant.",
                "assistant_final": "Qdrant was discussed as a future capability index.",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    hits = JsonChatStore(chat_dir).search("Qdrant", max_results=5)

    assert len(hits) == 1
    assert hits[0]["line"] == 2
    assert "User: Find information about Qdrant." in hits[0]["content"]


def test_json_chat_store_deduplicates_same_turn_content(tmp_path):
    chat_dir = tmp_path / ".agent_chat_history"
    chat_dir.mkdir()
    record = {
        "type": "turn",
        "user": "Qdrant routing question",
        "assistant_final": "Qdrant routing answer",
    }
    line = json.dumps(record) + "\n"
    (chat_dir / "turns_original.jsonl").write_text(line, encoding="utf-8")
    (chat_dir / "turns_working.jsonl").write_text(line, encoding="utf-8")

    hits = JsonChatStore(chat_dir).search("Qdrant", max_results=10)

    assert len(hits) == 1


def test_simple_memory_store_searches_jsonl_content_and_preserves_metadata(tmp_path):
    memory_path = tmp_path / "memory.jsonl"
    memory_path.write_text(
        json.dumps(
            {
                "content": "The user prefers YAML capability definitions.",
                "tags": ["knowledge", "capabilities"],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    hits = SimpleMemoryStore(memory_path).search("YAML capability", max_results=5)

    assert len(hits) == 1
    assert hits[0]["content"] == "The user prefers YAML capability definitions."
    assert hits[0]["metadata"] == {"tags": ["knowledge", "capabilities"]}
    assert hits[0]["score"] > 0
