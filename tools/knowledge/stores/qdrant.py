from __future__ import annotations

from typing import Any

from tools.knowledge.config import QdrantConfig


class QdrantUnavailableError(RuntimeError):
    """Raised when Qdrant support is requested but unavailable."""


def qdrant_client_available() -> bool:
    try:
        import qdrant_client  # noqa: F401
    except ImportError:
        return False
    return True


def create_qdrant_client(config: QdrantConfig) -> Any:
    """Create a Qdrant client from config.

    By default this uses qdrant-client local persistent storage at
    config.local_path. That keeps embeddings, search, and vector storage fully on
    this PC and does not require Qdrant Cloud, an API key, or a server process.

    If config.mode == "http", this connects to a Qdrant server via config.url.
    That is intended for an optional local server only, not a hosted service.
    """
    try:
        from qdrant_client import QdrantClient
    except ImportError as exc:  # pragma: no cover - depends on local env
        raise QdrantUnavailableError(
            "qdrant-client is not installed. Install requirements.txt before "
            "enabling Qdrant integration."
        ) from exc

    if config.mode == "http":
        return QdrantClient(url=config.url, timeout=config.timeout_seconds)

    config.local_path.mkdir(parents=True, exist_ok=True)
    return QdrantClient(path=str(config.local_path))
