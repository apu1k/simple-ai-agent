from pathlib import Path

from tools.knowledge.config import load_knowledge_config


def test_load_knowledge_config_with_local_qdrant_router_and_data_collections(tmp_path):
    config_path = tmp_path / "knowledge.yaml"
    config_path.write_text(
        "\n".join(
            [
                "qdrant:",
                "  enabled: true",
                "  mode: local",
                "  local_path: runtime/test-qdrant",
                "  url: http://localhost:6333",
                "  timeout_seconds: 3.5",
                "  capability_collection: test_capability_router",
                "  vector_size: 1024",
                "  distance: Cosine",
                "  data_collections:",
                "    chat_history:",
                "      collection: test_chat_history",
                "      description: Complete chat history.",
                "      sensitivity: personal",
                "      source_type: chats",
            ]
        ),
        encoding="utf-8",
    )

    config = load_knowledge_config(config_path)

    assert config.qdrant.enabled is True
    assert config.qdrant.mode == "local"
    assert config.qdrant.local_path == Path("runtime/test-qdrant")
    assert config.qdrant.url == "http://localhost:6333"
    assert config.qdrant.timeout_seconds == 3.5
    assert config.qdrant.capability_collection == "test_capability_router"
    assert config.qdrant.vector_size == 1024
    assert config.qdrant.distance == "Cosine"
    assert config.qdrant.data_collections["chat_history"].collection == "test_chat_history"
    assert config.qdrant.data_collections["chat_history"].source_type == "chats"


def test_load_knowledge_config_falls_back_when_missing(tmp_path):
    config = load_knowledge_config(Path(tmp_path / "missing.yaml"))

    assert config.qdrant.enabled is False
    assert config.qdrant.mode == "local"
    assert config.qdrant.local_path == Path("runtime/knowledge/qdrant")
    assert config.qdrant.capability_collection == "agent_capability_router"
    assert config.qdrant.data_collections == {}


def test_invalid_qdrant_mode_falls_back_to_local(tmp_path):
    config_path = tmp_path / "knowledge.yaml"
    config_path.write_text(
        "qdrant:\n  mode: cloud\n",
        encoding="utf-8",
    )

    config = load_knowledge_config(config_path)

    assert config.qdrant.mode == "local"
