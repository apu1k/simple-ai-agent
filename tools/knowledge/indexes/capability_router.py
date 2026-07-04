from __future__ import annotations

from typing import Any, Iterable

from tools.knowledge.config import QdrantConfig
from tools.knowledge.embeddings.base import EmbeddingModel
from tools.knowledge.indexes.qdrant_payloads import capability_router_index_record
from tools.knowledge.models import CapabilityCandidate, CapabilityDefinition
from tools.knowledge.stores.qdrant import QdrantUnavailableError


def build_capability_router_points(
    capabilities: Iterable[CapabilityDefinition],
    embedding_model: EmbeddingModel,
) -> list[dict[str, Any]]:
    """Build vector points for the small capability-router index.

    The capability router is deliberately separate from ordinary evidence/data
    collections. It contains one point per capability definition and is used only
    to decide which capability/source should answer a query.
    """
    points: list[dict[str, Any]] = []
    for capability in capabilities:
        record = capability_router_index_record(capability)
        points.append(
            {
                "id": record["id"],
                "vector": embedding_model.embed_text(record["embedding_text"]),
                "payload": record["payload"]
                | {"embedding_text": record["embedding_text"]},
            }
        )
    return points


def ensure_capability_router_collection(client: Any, config: QdrantConfig) -> None:
    """Create the capability-router collection if it is missing.

    This function imports qdrant-client models lazily so the rest of the
    knowledge engine can still run without Qdrant installed.
    """
    try:
        from qdrant_client import models
    except ImportError as exc:  # pragma: no cover - depends on local env
        raise QdrantUnavailableError(
            "qdrant-client is required to create Qdrant collections."
        ) from exc

    collection_name = config.capability_collection
    if _collection_exists(client, collection_name):
        return

    client.create_collection(
        collection_name=collection_name,
        vectors_config=models.VectorParams(
            size=config.vector_size,
            distance=_qdrant_distance(models, config.distance),
        ),
    )


def index_capability_router(
    client: Any,
    config: QdrantConfig,
    capabilities: Iterable[CapabilityDefinition],
    embedding_model: EmbeddingModel,
) -> int:
    """Upsert capability definitions into the local Qdrant router index."""
    points = build_capability_router_points(capabilities, embedding_model)
    if not points:
        return 0

    qdrant_points = [_to_qdrant_point(point) for point in points]
    client.upsert(collection_name=config.capability_collection, points=qdrant_points)
    return len(points)


def search_capability_router(
    client: Any,
    config: QdrantConfig,
    query: str,
    capabilities: Iterable[CapabilityDefinition],
    embedding_model: EmbeddingModel,
    top_k: int = 5,
    allow_network: bool = False,
    sources: list[str] | None = None,
) -> list[CapabilityCandidate]:
    """Search the capability-router index and return capability candidates."""
    capability_by_id = {capability.id: capability for capability in capabilities}
    query_vector = embedding_model.embed_text(query)
    limit = max(1, int(top_k))

    raw_results = _query_points(
        client=client,
        collection_name=config.capability_collection,
        query_vector=query_vector,
        limit=limit,
    )

    requested_sources = {source.strip().lower() for source in sources or [] if source.strip()}
    candidates: list[CapabilityCandidate] = []
    for point in raw_results:
        payload = _point_payload(point)
        capability_id = str(payload.get("capability_id", ""))
        capability = capability_by_id.get(capability_id)
        if capability is None:
            continue
        if capability.allow_network and not allow_network:
            continue
        if requested_sources and not _matches_source_filter(capability, requested_sources):
            continue

        candidates.append(
            CapabilityCandidate(
                capability=capability,
                score=round(max(0.0, min(float(_point_score(point)), 1.0)), 4),
                reason="Matched by local Qdrant capability router",
            )
        )

    return candidates[:limit]


def _collection_exists(client: Any, collection_name: str) -> bool:
    collection_exists = getattr(client, "collection_exists", None)
    if collection_exists is not None:
        return bool(collection_exists(collection_name))

    try:
        client.get_collection(collection_name)
    except Exception:
        return False
    return True


def _qdrant_distance(models: Any, distance: str) -> Any:
    normalized = distance.strip().lower()
    if normalized == "dot":
        return models.Distance.DOT
    if normalized in {"euclid", "euclidean"}:
        return models.Distance.EUCLID
    return models.Distance.COSINE


def _to_qdrant_point(point: dict[str, Any]) -> Any:
    try:
        from qdrant_client.models import PointStruct
    except ImportError:
        # Useful for fake-client tests and dry environments. A real qdrant-client
        # installation accepts PointStruct and will use the branch above.
        return point

    return PointStruct(
        id=point["id"],
        vector=point["vector"],
        payload=point["payload"],
    )


def _query_points(
    client: Any,
    collection_name: str,
    query_vector: list[float],
    limit: int,
) -> list[Any]:
    query_points = getattr(client, "query_points", None)
    if query_points is not None:
        result = query_points(
            collection_name=collection_name,
            query=query_vector,
            limit=limit,
            with_payload=True,
        )
        return list(getattr(result, "points", result))

    search = getattr(client, "search", None)
    if search is None:
        raise QdrantUnavailableError(
            "Qdrant client does not provide query_points() or search()."
        )

    return list(
        search(
            collection_name=collection_name,
            query_vector=query_vector,
            limit=limit,
            with_payload=True,
        )
    )


def _point_payload(point: Any) -> dict[str, Any]:
    if isinstance(point, dict):
        payload = point.get("payload", {})
    else:
        payload = getattr(point, "payload", {})
    return payload if isinstance(payload, dict) else {}


def _point_score(point: Any) -> float:
    if isinstance(point, dict):
        return float(point.get("score", 0.0))
    return float(getattr(point, "score", 0.0))


def _matches_source_filter(
    capability: CapabilityDefinition,
    requested_sources: set[str],
) -> bool:
    aliases = {capability.id, capability.name.lower(), *capability.tags}

    if "chat" in capability.tags or "chats" in capability.tags:
        aliases.update({"chat", "chats", "history", "recent_chats"})

    if "memory" in capability.tags:
        aliases.update({"memory", "memories", "long_term_memory"})

    return bool(aliases & requested_sources)
