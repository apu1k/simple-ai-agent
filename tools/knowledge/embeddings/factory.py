from __future__ import annotations

from tools.knowledge.config import QdrantConfig
from tools.knowledge.embeddings.base import EmbeddingModel
from tools.knowledge.embeddings.hashing import HashingEmbeddingModel
from tools.knowledge.embeddings.sentence_transformers import (
    SentenceTransformerEmbeddingModel,
)

_MODEL_CACHE: dict[tuple[object, ...], EmbeddingModel] = {}


class EmbeddingBackendUnavailableError(RuntimeError):
    """Raised when a configured local embedding backend is unavailable."""


def create_embedding_model(config: QdrantConfig) -> EmbeddingModel:
    """Create or reuse the configured local embedding model.

    Reusing the sentence-transformers model is important for interactive search:
    loading BGE-M3 from disk can dominate latency if each capability creates its
    own backend instance.
    """
    backend = config.embedding_backend.strip().lower()
    cache_key = _cache_key(config, backend)
    cached = _MODEL_CACHE.get(cache_key)
    if cached is not None:
        return cached

    if backend == "hashing":
        model: EmbeddingModel = HashingEmbeddingModel(dimensions=config.vector_size)
        _MODEL_CACHE[cache_key] = model
        return model

    if backend in {"sentence_transformers", "sentence-transformers"}:
        model_name_or_path = config.embedding_model.strip()
        if not model_name_or_path:
            raise EmbeddingBackendUnavailableError(
                "embedding_model must be set for sentence_transformers backend"
            )
        model = SentenceTransformerEmbeddingModel(
            model_name_or_path=model_name_or_path,
            expected_vector_size=config.vector_size,
            device=config.embedding_device,
            local_files_only=config.embedding_local_files_only,
            batch_size=config.embedding_batch_size,
        )
        _MODEL_CACHE[cache_key] = model
        return model

    raise EmbeddingBackendUnavailableError(
        f"Unsupported local embedding backend: {config.embedding_backend}"
    )


def clear_embedding_model_cache() -> None:
    """Clear cached embedding backends; useful for tests and config changes."""
    _MODEL_CACHE.clear()


def _cache_key(config: QdrantConfig, backend: str) -> tuple[object, ...]:
    return (
        backend,
        config.embedding_model.strip(),
        config.embedding_device,
        config.embedding_local_files_only,
        int(config.embedding_batch_size),
        int(config.vector_size),
    )
