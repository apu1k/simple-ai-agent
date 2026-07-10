from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import threading
from typing import Any


@dataclass
class SentenceTransformerEmbeddingModel:
    """Local sentence-transformers embedding backend.

    This backend is intentionally opt-in and local-first. With
    local_files_only=True, model_name_or_path should point to an already present
    local model directory, avoiding accidental downloads or cloud/API usage.
    """

    model_name_or_path: str
    expected_vector_size: int
    device: str = "cpu"
    local_files_only: bool = True
    batch_size: int = 32
    _model: Any | None = field(default=None, init=False, repr=False)
    _model_load_lock: threading.Lock = field(
        default_factory=threading.Lock,
        init=False,
        repr=False,
    )

    @property
    def vector_size(self) -> int:
        return self.expected_vector_size

    def embed_text(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        model = self._load_model()
        vectors = model.encode(
            texts,
            batch_size=max(1, int(self.batch_size)),
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        if hasattr(vectors, "tolist"):
            vectors = vectors.tolist()

        result = [[float(value) for value in vector] for vector in vectors]
        self._validate_vector_sizes(result)
        return result

    def _load_model(self) -> Any:
        if self._model is not None:
            return self._model

        with self._model_load_lock:
            if self._model is not None:
                return self._model

            if self.local_files_only and not Path(self.model_name_or_path).exists():
                raise RuntimeError(
                    "Local embedding model path does not exist: "
                    f"{self.model_name_or_path!r}. Download/install the model locally "
                    "or set embedding_local_files_only=false explicitly."
                )

            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:  # pragma: no cover - depends on local env
                raise RuntimeError(
                    "sentence-transformers is not installed. Install it before using "
                    "embedding_backend=sentence_transformers."
                ) from exc

            try:
                self._model = SentenceTransformer(
                    self.model_name_or_path,
                    device=self.device,
                    local_files_only=self.local_files_only,
                )
            except TypeError as exc:
                if self.local_files_only:
                    raise RuntimeError(
                        "Installed sentence-transformers version does not support "
                        "local_files_only; refusing to risk a model download."
                    ) from exc
                self._model = SentenceTransformer(
                    self.model_name_or_path,
                    device=self.device,
                )

            return self._model

    def _validate_vector_sizes(self, vectors: list[list[float]]) -> None:
        for vector in vectors:
            if len(vector) != self.expected_vector_size:
                raise ValueError(
                    "Embedding vector size mismatch: expected "
                    f"{self.expected_vector_size}, got {len(vector)}. Update "
                    "qdrant.vector_size or use a matching local model."
                )
