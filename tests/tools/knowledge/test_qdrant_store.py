from tools.knowledge.config import QdrantConfig
from tools.knowledge.stores.qdrant import create_qdrant_client, qdrant_client_available


def test_qdrant_client_available_returns_bool():
    assert isinstance(qdrant_client_available(), bool)


def test_create_qdrant_client_uses_local_path_by_default(tmp_path):
    if not qdrant_client_available():
        return

    config = QdrantConfig(enabled=True, mode="local", local_path=tmp_path / "qdrant")

    client = create_qdrant_client(config)

    assert client is not None
    assert config.local_path.exists()
