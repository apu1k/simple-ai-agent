from __future__ import annotations

from typing import Protocol


class EmbeddingModel(Protocol):
    """Small local embedding interface used by Qdrant indexes.

    Implementations must be fully local. The default test/dev implementation is
    deterministic hashing; later implementations can wrap local BGE-M3 or other
    sentence-transformer models without changing the index/search pipeline.
    """

    @property
    def vector_size(self) -> int:
        """Number of dimensions returned for each embedded text."""

    def embed_text(self, text: str) -> list[float]:
        """Embed one text into a dense vector."""

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts into dense vectors."""
