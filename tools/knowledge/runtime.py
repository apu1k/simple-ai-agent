from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Callable

from tools.knowledge.config import QdrantConfig, load_knowledge_config
from tools.knowledge.embeddings.factory import create_embedding_model
from tools.knowledge.indexes.chat_history import index_chat_history_turn
from tools.knowledge.stores.qdrant import create_qdrant_client

_LOGGER = logging.getLogger(__name__)
_KNOWLEDGE_WORK_LOCK = threading.Lock()


def warmup_embeddings(config: QdrantConfig | None = None) -> bool:
    """Synchronously load and exercise the configured embedding backend."""
    qdrant_config = config or load_knowledge_config().qdrant
    if not qdrant_config.enabled:
        return False

    with _KNOWLEDGE_WORK_LOCK:
        create_embedding_model(qdrant_config).embed_text("embedding warmup")
    return True


def index_persisted_chat_turn(
    path: Path,
    session_id: str,
    turn_index: int,
    config: QdrantConfig | None = None,
) -> int:
    """Synchronously index one persisted chat turn into Qdrant."""
    qdrant_config = config or load_knowledge_config().qdrant
    if not qdrant_config.enabled:
        return 0

    with _KNOWLEDGE_WORK_LOCK:
        embedding_model = create_embedding_model(qdrant_config)
        client = create_qdrant_client(qdrant_config)
        try:
            return index_chat_history_turn(
                client=client,
                config=qdrant_config,
                path=path,
                session_id=session_id,
                turn_index=turn_index,
                embedding_model=embedding_model,
            )
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                close()


def start_embedding_warmup() -> threading.Thread:
    """Start non-blocking embedding warmup in a daemon thread."""
    return _start_daemon(
        name="knowledge-embedding-warmup",
        action=warmup_embeddings,
    )


def schedule_chat_turn_index(
    path: Path,
    session_id: str,
    turn_index: int,
) -> threading.Thread:
    """Schedule non-blocking incremental indexing for one persisted turn."""
    return _start_daemon(
        name=f"knowledge-chat-index-{session_id[:8]}-{turn_index}",
        action=lambda: index_persisted_chat_turn(path, session_id, turn_index),
    )


def _start_daemon(name: str, action: Callable[[], object]) -> threading.Thread:
    def run() -> None:
        try:
            action()
        except Exception:
            _LOGGER.exception("Background knowledge task failed: %s", name)

    thread = threading.Thread(target=run, name=name, daemon=True)
    thread.start()
    return thread
