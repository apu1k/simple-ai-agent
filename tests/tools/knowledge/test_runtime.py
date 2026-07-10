from __future__ import annotations

import logging
from pathlib import Path

from tools.knowledge.config import QdrantConfig, QdrantDataCollectionConfig
from tools.knowledge import runtime


class FakeEmbeddingModel:
    def __init__(self):
        self.texts = []

    def embed_text(self, text):
        self.texts.append(text)
        return [0.0]


class FakeQdrantClient:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def enabled_config():
    return QdrantConfig(
        enabled=True,
        embedding_backend="hashing",
        vector_size=8,
        data_collections={
            "chat_history": QdrantDataCollectionConfig(
                key="chat_history",
                collection="agent_chat_history",
                source_type="chats",
            )
        },
    )


def test_warmup_embeddings_exercises_configured_model(monkeypatch):
    model = FakeEmbeddingModel()
    monkeypatch.setattr(runtime, "create_embedding_model", lambda config: model)

    assert runtime.warmup_embeddings(enabled_config()) is True
    assert model.texts == ["embedding warmup"]


def test_index_persisted_chat_turn_closes_qdrant_client(monkeypatch, tmp_path):
    model = object()
    client = FakeQdrantClient()
    calls = []
    monkeypatch.setattr(runtime, "create_embedding_model", lambda config: model)
    monkeypatch.setattr(runtime, "create_qdrant_client", lambda config: client)

    def fake_index(**kwargs):
        calls.append(kwargs)
        return 1

    monkeypatch.setattr(runtime, "index_chat_history_turn", fake_index)
    path = tmp_path / "turns_original.jsonl"

    count = runtime.index_persisted_chat_turn(
        path,
        "session-1",
        4,
        config=enabled_config(),
    )

    assert count == 1
    assert client.closed is True
    assert calls[0]["path"] == path
    assert calls[0]["session_id"] == "session-1"
    assert calls[0]["turn_index"] == 4
    assert calls[0]["embedding_model"] is model


def test_background_task_is_daemon_and_contains_failures(caplog):
    def fail():
        raise RuntimeError("background boom")

    with caplog.at_level(logging.ERROR, logger="tools.knowledge.runtime"):
        thread = runtime._start_daemon("test-background-task", fail)
        thread.join(timeout=2)

    assert thread.daemon is True
    assert thread.is_alive() is False
    assert "Background knowledge task failed: test-background-task" in caplog.text
    assert "background boom" in caplog.text


def test_schedule_chat_turn_index_passes_exact_turn(monkeypatch, tmp_path):
    calls = []

    def fake_index(path: Path, session_id: str, turn_index: int):
        calls.append((path, session_id, turn_index))

    monkeypatch.setattr(runtime, "index_persisted_chat_turn", fake_index)
    path = tmp_path / "turns_original.jsonl"

    thread = runtime.schedule_chat_turn_index(path, "session-1", 7)
    thread.join(timeout=2)

    assert thread.daemon is True
    assert calls == [(path, "session-1", 7)]
