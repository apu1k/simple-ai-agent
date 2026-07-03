from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass


TOKEN_RE = re.compile(r"[a-zA-Z0-9_äöüÄÖÜß-]+")


@dataclass(frozen=True)
class HashingEmbeddingModel:
    """Deterministic local embedding model for tests and pipeline bring-up.

    This is not a semantic model. It is a dependency-free feature-hashing
    embedder that lets us build and test the complete local Qdrant indexing and
    search flow before adding a real local model such as BGE-M3.
    """

    dimensions: int = 1024

    @property
    def vector_size(self) -> int:
        return self.dimensions

    def embed_text(self, text: str) -> list[float]:
        if self.dimensions <= 0:
            raise ValueError("dimensions must be greater than zero")

        vector = [0.0] * self.dimensions
        tokens = _tokens(text)
        if not tokens:
            return vector

        for token in tokens:
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=16).digest()
            bucket = int.from_bytes(digest[:8], "big") % self.dimensions
            sign = 1.0 if digest[8] & 1 else -1.0
            vector[bucket] += sign

        return _l2_normalize(vector)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_text(text) for text in texts]


def _tokens(text: str) -> list[str]:
    return [match.group(0).lower() for match in TOKEN_RE.finditer(text)]


def _l2_normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        return vector
    return [value / norm for value in vector]
