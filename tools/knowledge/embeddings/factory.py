from __future__ import annotations

from tools.knowledge.config import QdrantConfig
from tools.knowledge.embeddings.base import EmbeddingModel
from tools.knowledge.embeddings.hashing import HashingEmbeddingModel


class EmbeddingBackendUnavailableError(RuntimeError):
    """Raised when a configured local embedding backend is unavailable."""


def create_embedding_model(config: QdrantConfig) -> EmbeddingModel:
    """Create the configured local embedding model.

    Only the deterministic hashing backend is implemented for now. Real local
    semantic backends, e.g. BGE-M3, should be added behind this factory later.
    """
    backend = config.embedding_backend.strip().lower()
    if backend == "hashing":
        return HashingEmbeddingModel(dimensions=config.vector_size)

    raise EmbeddingBackendUnavailableError(
        f"Unsupported local embedding backend: {config.embedding_backend}"
    )
