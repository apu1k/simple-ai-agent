import pytest

from tools.knowledge.embeddings.sentence_transformers import (
    SentenceTransformerEmbeddingModel,
)


class FakeSentenceTransformer:
    def __init__(self, vectors):
        self.vectors = vectors
        self.calls = []

    def encode(self, texts, batch_size, convert_to_numpy, normalize_embeddings, show_progress_bar):
        self.calls.append(
            {
                "texts": texts,
                "batch_size": batch_size,
                "convert_to_numpy": convert_to_numpy,
                "normalize_embeddings": normalize_embeddings,
                "show_progress_bar": show_progress_bar,
            }
        )
        return self.vectors


def test_sentence_transformer_backend_embeds_with_preloaded_local_model():
    fake_model = FakeSentenceTransformer([[0.1, 0.2], [0.3, 0.4]])
    model = SentenceTransformerEmbeddingModel(
        model_name_or_path="unused",
        expected_vector_size=2,
        batch_size=7,
    )
    model._model = fake_model

    vectors = model.embed_texts(["hello", "world"])

    assert vectors == [[0.1, 0.2], [0.3, 0.4]]
    assert fake_model.calls == [
        {
            "texts": ["hello", "world"],
            "batch_size": 7,
            "convert_to_numpy": True,
            "normalize_embeddings": True,
            "show_progress_bar": False,
        }
    ]


def test_sentence_transformer_backend_rejects_missing_local_model_path():
    model = SentenceTransformerEmbeddingModel(
        model_name_or_path="Z:/definitely/missing/model",
        expected_vector_size=384,
        local_files_only=True,
    )

    with pytest.raises(RuntimeError, match="Local embedding model path does not exist"):
        model.embed_text("hello")


def test_sentence_transformer_backend_validates_vector_size():
    model = SentenceTransformerEmbeddingModel(
        model_name_or_path="unused",
        expected_vector_size=3,
    )
    model._model = FakeSentenceTransformer([[0.1, 0.2]])

    with pytest.raises(ValueError, match="vector size mismatch"):
        model.embed_text("hello")
