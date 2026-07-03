import math

import pytest

from tools.knowledge.embeddings import HashingEmbeddingModel


def test_hashing_embedding_is_deterministic_and_normalized():
    model = HashingEmbeddingModel(dimensions=64)

    first = model.embed_text("Search recent chats for Qdrant")
    second = model.embed_text("Search recent chats for Qdrant")

    assert first == second
    assert len(first) == 64
    assert math.isclose(sum(value * value for value in first), 1.0)


def test_hashing_embedding_empty_text_returns_zero_vector():
    model = HashingEmbeddingModel(dimensions=8)

    assert model.embed_text("") == [0.0] * 8


def test_hashing_embedding_rejects_invalid_dimension():
    model = HashingEmbeddingModel(dimensions=0)

    with pytest.raises(ValueError, match="dimensions"):
        model.embed_text("hello")


def test_hashing_embedding_batch_matches_single_embeddings():
    model = HashingEmbeddingModel(dimensions=32)
    texts = ["chat history", "long term memory"]

    assert model.embed_texts(texts) == [model.embed_text(text) for text in texts]
