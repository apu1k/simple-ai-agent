from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.knowledge.config import QdrantConfig, load_knowledge_config
from tools.knowledge.embeddings import create_embedding_model
from tools.knowledge.embeddings.base import EmbeddingModel
from tools.knowledge.indexes.chat_history import search_chat_history_collection
from tools.knowledge.indexes.long_term_memory import search_long_term_memory_collection
from tools.knowledge.models import EvidenceBundle, EvidenceItem, KnowledgeSearchRequest
from tools.knowledge.stores.local import JsonChatStore, SimpleMemoryStore
from tools.knowledge.stores.qdrant import create_qdrant_client


class SearchRecentChatsCapability:
    def __init__(
        self,
        qdrant_config: QdrantConfig | None = None,
        qdrant_client: Any | None = None,
        embedding_model: EmbeddingModel | None = None,
    ):
        self.qdrant_config = qdrant_config or load_knowledge_config().qdrant
        self._qdrant_client = qdrant_client
        self._embedding_model = embedding_model
        self._qdrant_failed = False

    def search(self, request: KnowledgeSearchRequest) -> EvidenceBundle:
        if self.qdrant_config.enabled and not self._qdrant_failed:
            items = self._search_qdrant(request)
            if items:
                return _bundle_chat_items(items)

        return _search_local_chat_history(request)

    def _search_qdrant(self, request: KnowledgeSearchRequest) -> list[EvidenceItem]:
        try:
            return search_chat_history_collection(
                client=self._get_qdrant_client(),
                config=self.qdrant_config,
                query=request.query,
                embedding_model=self._get_embedding_model(),
                limit=int(request.max_results),
            )
        except Exception:
            # The vector collection may not be indexed yet. Keep the capability
            # useful by falling back to the local keyword store.
            self._qdrant_failed = True
            return []

    def _get_qdrant_client(self) -> Any:
        if self._qdrant_client is None:
            self._qdrant_client = create_qdrant_client(self.qdrant_config)
        return self._qdrant_client

    def _get_embedding_model(self) -> EmbeddingModel:
        if self._embedding_model is None:
            self._embedding_model = create_embedding_model(self.qdrant_config)
        return self._embedding_model


def _search_local_chat_history(request: KnowledgeSearchRequest) -> EvidenceBundle:
    root = Path(request.cwd) / ".agent_chat_history"
    store = JsonChatStore(root)
    hits = store.search(request.query, max_results=int(request.max_results))

    items = [
        EvidenceItem(
            type="chat_match",
            source="chat_history",
            title=f"{hit['path']}:{hit['line']}",
            content=hit["content"],
            confidence=float(hit.get("score", 0.7)),
            metadata={
                "path": hit["path"],
                "line": hit["line"],
                "score": hit.get("score"),
                **hit.get("metadata", {}),
            },
        )
        for hit in hits
    ]

    return _bundle_chat_items(items)


def _bundle_chat_items(items: list[EvidenceItem]) -> EvidenceBundle:
    return EvidenceBundle(
        capability_id="search.recent_chats",
        source="chat_history",
        status="success",
        confidence=max((item.confidence for item in items), default=0.0),
        items=items,
    )


class SearchLongTermMemoryCapability:
    def __init__(
        self,
        qdrant_config: QdrantConfig | None = None,
        qdrant_client: Any | None = None,
        embedding_model: EmbeddingModel | None = None,
    ):
        self.qdrant_config = qdrant_config or load_knowledge_config().qdrant
        self._qdrant_client = qdrant_client
        self._embedding_model = embedding_model
        self._qdrant_failed = False

    def search(self, request: KnowledgeSearchRequest) -> EvidenceBundle:
        if self.qdrant_config.enabled and not self._qdrant_failed:
            items = self._search_qdrant(request)
            if items:
                return _bundle_memory_items(items)

        return _search_local_long_term_memory(request)

    def _search_qdrant(self, request: KnowledgeSearchRequest) -> list[EvidenceItem]:
        try:
            return search_long_term_memory_collection(
                client=self._get_qdrant_client(),
                config=self.qdrant_config,
                query=request.query,
                embedding_model=self._get_embedding_model(),
                limit=int(request.max_results),
            )
        except Exception:
            # The vector collection may not be indexed yet. Keep the capability
            # useful by falling back to the local keyword store.
            self._qdrant_failed = True
            return []

    def _get_qdrant_client(self) -> Any:
        if self._qdrant_client is None:
            self._qdrant_client = create_qdrant_client(self.qdrant_config)
        return self._qdrant_client

    def _get_embedding_model(self) -> EmbeddingModel:
        if self._embedding_model is None:
            self._embedding_model = create_embedding_model(self.qdrant_config)
        return self._embedding_model


def _search_local_long_term_memory(request: KnowledgeSearchRequest) -> EvidenceBundle:
    memory_path = Path(request.cwd) / "runtime" / "knowledge" / "memory.jsonl"
    store = SimpleMemoryStore(memory_path)
    hits = store.search(request.query, max_results=int(request.max_results))

    items = [
        EvidenceItem(
            type="memory_match",
            source="long_term_memory",
            title=f"{hit['path']}:{hit['line']}",
            content=hit["content"],
            confidence=float(hit.get("score", 0.75)),
            metadata={
                "path": hit["path"],
                "line": hit["line"],
                "score": hit.get("score"),
                **hit.get("metadata", {}),
            },
        )
        for hit in hits
    ]

    return _bundle_memory_items(items)


def _bundle_memory_items(items: list[EvidenceItem]) -> EvidenceBundle:
    return EvidenceBundle(
        capability_id="search.long_term_memory",
        source="long_term_memory",
        status="success",
        confidence=max((item.confidence for item in items), default=0.0),
        items=items,
    )
