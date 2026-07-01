from __future__ import annotations

import re

from tools.knowledge.models import (
    CapabilityCandidate,
    CapabilityDefinition,
    KnowledgeSearchRequest,
)


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
        sensitivity="personal",
        expected_confidence=0.75,
    ),
]


class CapabilityRegistry:
    def __init__(self, capabilities: list[CapabilityDefinition] | None = None):
        self.capabilities = capabilities or DEFAULT_CAPABILITIES

    def search(
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
