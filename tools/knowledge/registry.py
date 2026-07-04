from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - optional dependency fallback
    yaml = None

from tools.knowledge.config import QdrantConfig, load_knowledge_config
from tools.knowledge.embeddings import create_embedding_model
from tools.knowledge.embeddings.base import EmbeddingModel
from tools.knowledge.indexes.capability_router import search_capability_router
from tools.knowledge.models import (
    CapabilityCandidate,
    CapabilityDefinition,
    KnowledgeSearchRequest,
)
from tools.knowledge.stores.qdrant import create_qdrant_client


DEFAULT_CAPABILITIES_DIR = Path("config") / "capabilities"


DEFAULT_CAPABILITIES = [
    CapabilityDefinition(
        id="search.recent_chats",
        name="Search Recent Chats",
        description=(
            "Searches local previous chat history for relevant messages, decisions, "
            "preferences, project discussions, and facts mentioned by the user."
        ),
        handler="tools.knowledge.capabilities.local.SearchRecentChatsCapability",
        tags=["chats", "chat", "conversation", "history", "memory", "decisions"],
        examples=[
            "What did we decide about the knowledge engine?",
            "Search my recent chats for Qdrant.",
            "Did I mention my preferred project structure?",
        ],
        required_permissions=["chats.read"],
        sensitivity="personal",
        expected_confidence=0.7,
    ),
    CapabilityDefinition(
        id="search.long_term_memory",
        name="Search Long-Term Memory",
        description=(
            "Searches the agent's explicit long-term memory store for important "
            "saved facts, preferences, personal notes, and durable information."
        ),
        handler="tools.knowledge.capabilities.local.SearchLongTermMemoryCapability",
        tags=["memory", "facts", "preferences", "personal", "notes"],
        examples=[
            "What do you remember about me?",
            "Search your memory for my coding preferences.",
            "Find saved facts about this project.",
        ],
        required_permissions=["memory.read"],
        sensitivity="personal",
        expected_confidence=0.75,
    ),
]


class CapabilityRegistry:
    def __init__(
        self,
        capabilities: list[CapabilityDefinition] | None = None,
        qdrant_config: QdrantConfig | None = None,
        qdrant_client: Any | None = None,
        embedding_model: EmbeddingModel | None = None,
    ):
        self.capabilities = capabilities or load_capability_definitions()
        self.qdrant_config = qdrant_config or load_knowledge_config().qdrant
        self._qdrant_client = qdrant_client
        self._embedding_model = embedding_model
        self._qdrant_failed = False

    def search(
        self,
        request: KnowledgeSearchRequest,
        top_k: int = 5,
    ) -> list[CapabilityCandidate]:
        if self.qdrant_config.enabled and not self._qdrant_failed:
            qdrant_candidates = self._search_qdrant(request, top_k=top_k)
            if qdrant_candidates:
                return qdrant_candidates

        return self._search_keyword(request, top_k=top_k)

    def _search_qdrant(
        self,
        request: KnowledgeSearchRequest,
        top_k: int,
    ) -> list[CapabilityCandidate]:
        try:
            client = self._get_qdrant_client()
            embedding_model = self._get_embedding_model()
            return search_capability_router(
                client=client,
                config=self.qdrant_config,
                query=request.query,
                capabilities=self.capabilities,
                embedding_model=embedding_model,
                top_k=top_k,
                allow_network=request.allow_network,
                sources=request.sources,
            )
        except Exception:
            # Router search is an optimization. If local Qdrant is missing, the
            # collection has not been indexed yet, or any backend error occurs,
            # keep the knowledge tool usable by falling back to keyword routing.
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

    def _search_keyword(
        self,
        request: KnowledgeSearchRequest,
        top_k: int = 5,
    ) -> list[CapabilityCandidate]:
        query_tokens = _tokens(request.query)
        requested_sources = set(request.sources or [])
        candidates: list[CapabilityCandidate] = []

        for capability in self.capabilities:
            if capability.allow_network and not request.allow_network:
                continue

            if requested_sources and not _matches_source_filter(capability, requested_sources):
                continue

            searchable_text = " ".join(
                [
                    capability.id,
                    capability.name,
                    capability.description,
                    " ".join(capability.tags),
                    " ".join(capability.examples),
                ]
            )
            capability_tokens = _tokens(searchable_text)
            overlap = query_tokens & capability_tokens

            score = 0.0
            if query_tokens:
                score = len(overlap) / len(query_tokens)

            if "memory" in capability.tags:
                score += 0.05
            if "chats" in capability.tags or "conversation" in capability.tags:
                score += 0.05
            if requested_sources:
                score += 0.25

            if score > 0:
                candidates.append(
                    CapabilityCandidate(
                        capability=capability,
                        score=round(min(score, 1.0), 4),
                        reason=f"Matched terms: {', '.join(sorted(overlap)) or 'source filter'}",
                    )
                )

        candidates.sort(key=lambda candidate: candidate.score, reverse=True)
        return candidates[:top_k]


def load_capability_definitions(
    capabilities_dir: Path = DEFAULT_CAPABILITIES_DIR,
) -> list[CapabilityDefinition]:
    loaded: list[CapabilityDefinition] = []

    if capabilities_dir.exists() and capabilities_dir.is_dir():
        for path in sorted(capabilities_dir.glob("*.yaml")):
            try:
                loaded.append(_load_capability_file(path))
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue

    return loaded or DEFAULT_CAPABILITIES


def _load_capability_file(path: Path) -> CapabilityDefinition:
    raw = path.read_text(encoding="utf-8")
    if yaml is not None:
        data = yaml.safe_load(raw)
    else:
        data = json.loads(raw)

    if not isinstance(data, dict):
        raise ValueError(f"Capability file must contain an object: {path}")

    return CapabilityDefinition(
        id=_required_str(data, "id", path),
        name=_required_str(data, "name", path),
        description=_required_str(data, "description", path),
        handler=_required_str(data, "handler", path),
        capability_type=data.get("capability_type", "search"),
        tags=_string_list(data.get("tags", [])),
        examples=_string_list(data.get("examples", [])),
        required_permissions=_string_list(data.get("required_permissions", [])),
        sensitivity=str(data.get("sensitivity", "local")),
        allow_network=bool(data.get("allow_network", False)),
        expected_latency_ms=_optional_int(data.get("expected_latency_ms")),
        expected_confidence=float(data.get("expected_confidence", 0.5)),
    )


def _required_str(data: dict[str, Any], key: str, path: Path) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Capability file missing required string field {key!r}: {path}")
    return value.strip()


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _matches_source_filter(
    capability: CapabilityDefinition,
    requested_sources: set[str],
) -> bool:
    aliases = {
        capability.id,
        capability.name.lower(),
        *capability.tags,
    }

    if "chat" in capability.tags or "chats" in capability.tags:
        aliases.update({"chat", "chats", "history", "recent_chats"})

    if "memory" in capability.tags:
        aliases.update({"memory", "memories", "long_term_memory"})

    normalized = {source.strip().lower() for source in requested_sources}
    return bool(aliases & normalized)


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-zA-Z0-9_äöüÄÖÜß-]+", text.lower())
        if len(token) >= 2
    }
