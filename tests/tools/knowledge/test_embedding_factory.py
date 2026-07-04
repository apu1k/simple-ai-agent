import pytest

from tools.knowledge.config import QdrantConfig
from tools.knowledge.embeddings.factory import (
    EmbeddingBackendUnavailableError,
    create_embedding_model,
)
from tools.knowledge.embeddings.hashing import HashingEmbeddingModel
from tools.knowledge.embeddings.sentence_transformers import (
    SentenceTransformerEmbeddingModel,
)


def test_create_embedding_model_returns_hashing_backend():
    model = create_embedding_model(
        QdrantConfig(embedding_backend="hashing", vector_size=16)
    )

    assert isinstance(model, HashingEmbeddingModel)
    assert model.vector_size == 16


def test_create_embedding_model_returns_sentence_transformers_backend():
    model = create_embedding_model(
        QdrantConfig(
            embedding_backend="sentence_transformers",
            embedding_model="C:/models/bge-small-en-v1.5",
            embedding_device="cpu",
            embedding_local_files_only=True,
            embedding_batch_size=8,
            vector_size=384,
        )
    )

    assert isinstance(model, SentenceTransformerEmbeddingModel)
    assert model.model_name_or_path == "C:/models/bge-small-en-v1.5"
    assert model.vector_size == 384
    assert model.device == "cpu"
    assert model.local_files_only is True
    assert model.batch_size == 8


def test_create_embedding_model_requires_model_for_sentence_transformers_backend():
    with pytest.raises(EmbeddingBackendUnavailableError, match="embedding_model"):
        create_embedding_model(QdrantConfig(embedding_backend="sentence_transformers"))


def test_create_embedding_model_rejects_unknown_backend():
    with pytest.raises(EmbeddingBackendUnavailableError):
        create_embedding_model(QdrantConfig(embedding_backend="bge-m3"))
