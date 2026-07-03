import pytest

from tools.knowledge.config import QdrantConfig
from tools.knowledge.embeddings.factory import (
    EmbeddingBackendUnavailableError,
    create_embedding_model,
)
from tools.knowledge.embeddings.hashing import HashingEmbeddingModel


def test_create_embedding_model_returns_hashing_backend():
    model = create_embedding_model(
        QdrantConfig(embedding_backend="hashing", vector_size=16)
    )

    assert isinstance(model, HashingEmbeddingModel)
    assert model.vector_size == 16


def test_create_embedding_model_rejects_unknown_backend():
    with pytest.raises(EmbeddingBackendUnavailableError):
        create_embedding_model(QdrantConfig(embedding_backend="bge-m3"))
