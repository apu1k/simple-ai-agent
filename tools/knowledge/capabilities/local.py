from __future__ import annotations

from pathlib import Path

from tools.knowledge.models import EvidenceBundle, EvidenceItem, KnowledgeSearchRequest
from tools.knowledge.stores.local import JsonChatStore, SimpleMemoryStore


class SearchRecentChatsCapability:
    def search(self, request: KnowledgeSearchRequest) -> EvidenceBundle:
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
                },
            )
            for hit in hits
        ]

        return EvidenceBundle(
            capability_id="search.recent_chats",
            source="chat_history",
            status="success",
            confidence=max((item.confidence for item in items), default=0.0),
            items=items,
        )


class SearchLongTermMemoryCapability:
    def search(self, request: KnowledgeSearchRequest) -> EvidenceBundle:
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

        return EvidenceBundle(
            capability_id="search.long_term_memory",
            source="long_term_memory",
            status="success",
            confidence=max((item.confidence for item in items), default=0.0),
            items=items,
        )
