from __future__ import annotations

from tools.knowledge.config import QdrantConfig
from tools.knowledge.embeddings.base import EmbeddingModel
from tools.knowledge.embeddings.hashing import HashingEmbeddingModel
from tools.knowledge.embeddings.sentence_transformers import (
    SentenceTransformerEmbeddingModel,
)


class EmbeddingBackendUnavailableError(RuntimeError):
    """Raised when a configured local embedding backend is unavailable."""


def create_embedding_model(config: QdrantConfig) -> EmbeddingModel:
    """Create the configured local embedding model.

    The default hashing backend is deterministic and dependency-free. The
    sentence_transformers backend is opt-in and intended for already-installed
    local models only.
    """
    backend = config.embedding_backend.strip().lower()
    if backend == "hashing":
        return HashingEmbeddingModel(dimensions=config.vector_size)

    if backend in {"sentence_transformers", "sentence-transformers"}:
        model_name_or_path = config.embedding_model.strip()
        if not model_name_or_path:
            raise EmbeddingBackendUnavailableError(
                "embedding_model must be set for sentence_transformers backend"
            )
        return SentenceTransformerEmbeddingModel(
            model_name_or_path=model_name_or_path,
            expected_vector_size=config.vector_size,
            device=config.embedding_device,
            local_files_only=config.embedding_local_files_only,
            batch_size=config.embedding_batch_size,
        )

    raise EmbeddingBackendUnavailableError(
        f"Unsupported local embedding backend: {config.embedding_backend}"
    )
