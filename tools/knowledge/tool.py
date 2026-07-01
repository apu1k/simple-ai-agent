from __future__ import annotations

import json

from tools._base import tool
from tools.knowledge.engine import KnowledgeEngine
from tools.knowledge.models import KnowledgeSearchRequest


_ENGINE = KnowledgeEngine()


@tool(
    description=(
        "Search the agent knowledge engine. This is the unified entry point for "
        "searching memories, previous chats, and future knowledge sources. "
        "Returns structured evidence, not a final answer."
    ),
    params={
        "query": "Natural language search query.",
        "sources": (
            "Optional comma-separated source filter. Examples: "
            "'memory', 'chats', 'search.long_term_memory', 'search.recent_chats'."
        ),
        "max_results": "Maximum evidence items per capability. Defaults to 10.",
        "max_capabilities": "Maximum capabilities to execute. Defaults to 3.",
        "include_trace": "Whether to include routing/debug trace. Defaults to false.",
        "allow_network": "Whether network-backed capabilities may run. Defaults to false.",
    },
    requires_state=True,
    example={
        "action": "knowledge_search",
        "input": {
            "query": "What did we decide about the knowledge engine?",
            "sources": "chats,memory",
            "max_results": 10,
            "max_capabilities": 2,
        },
    },
)
def knowledge_search(
    state,
    query: str,
    sources: str | list[str] | None = None,
    max_results=10,
    max_capabilities=3,
    include_trace=False,
    allow_network=False,
) -> str:
    request = KnowledgeSearchRequest(
        query=query,
        max_results=int(max_results),
        max_capabilities=int(max_capabilities),
        sources=_parse_sources(sources),
        include_trace=_parse_bool(include_trace, default=False),
        allow_network=_parse_bool(allow_network, default=False),
        cwd=str(state.cwd),
    )

    result = _ENGINE.search(request)
    return json.dumps(result.to_dict(), ensure_ascii=False, indent=2)


def _parse_bool(value, default: bool = False) -> bool:
    if value is None:
        return default

    if isinstance(value, bool):
        return value

    if isinstance(value, (int, float)):
        return bool(value)

    text = str(value).strip().lower()

    if text in {"1", "true", "yes", "y", "on"}:
        return True

    if text in {"0", "false", "no", "n", "off"}:
        return False

    return default


def _parse_sources(sources: str | list[str] | None) -> list[str] | None:
    if sources is None or sources == "":
        return None

    if isinstance(sources, list):
        parsed = [str(source).strip().lower() for source in sources if str(source).strip()]
        return parsed or None

    parsed = [part.strip().lower() for part in str(sources).split(",") if part.strip()]
    return parsed or None
