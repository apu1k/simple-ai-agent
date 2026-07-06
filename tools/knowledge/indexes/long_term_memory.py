from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Iterable
from uuid import NAMESPACE_URL, uuid5

from tools.knowledge.config import QdrantConfig, QdrantDataCollectionConfig
from tools.knowledge.embeddings.base import EmbeddingModel
from tools.knowledge.indexes.chat_history import ensure_evidence_collection
from tools.knowledge.models import EvidenceItem
from tools.knowledge.stores.qdrant import QdrantUnavailableError

LONG_TERM_MEMORY_SCHEMA_VERSION = 1
DEFAULT_MEMORY_SOURCE_KEY = "long_term_memory"
BATCH_SIZE = 128
CONTENT_KEYS = {"content", "text", "memory"}


def iter_long_term_memory_records(path: Path) -> Iterable[dict[str, Any]]:
    """Yield parsed long-term-memory records suitable for evidence indexing."""
    if not path.exists() or not path.is_file():
        return

    seen_content: set[str] = set()
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line_number, line in enumerate(handle, start=1):
                record = _parse_memory_line(line)
                content = record["content"].strip()
                if not content:
                    continue

                dedupe_key = _normalize_for_dedup(content)
                if dedupe_key in seen_content:
                    continue
                seen_content.add(dedupe_key)

                yield {
                    "path": str(path),
                    "line": line_number,
                    "title": f"{path}:{line_number}",
                    "content": content,
                    "embedding_text": content,
                    "metadata": record["metadata"],
                }
    except OSError:
        return


def memory_point_id(path: str, line: int) -> str:
    """Return a stable Qdrant-compatible UUID for one memory record."""
    return str(uuid5(NAMESPACE_URL, f"ai-agent:knowledge:long-term-memory:{path}:{line}"))


def memory_payload(
    record: dict[str, Any],
    collection: QdrantDataCollectionConfig,
) -> dict[str, Any]:
    """Return payload metadata for a long-term-memory evidence collection."""
    return {
        "schema_version": LONG_TERM_MEMORY_SCHEMA_VERSION,
        "index_kind": "evidence_collection",
        "source_key": collection.key,
        "source_type": collection.source_type,
        "collection": collection.collection,
        "type": "memory_match",
        "source": "long_term_memory",
        "title": record["title"],
        "path": record["path"],
        "line": record["line"],
        "content": record["content"],
        "metadata": record.get("metadata", {}),
    }


def build_long_term_memory_points(
    path: Path,
    collection: QdrantDataCollectionConfig,
    embedding_model: EmbeddingModel,
) -> list[dict[str, Any]]:
    """Build vector points for the long-term-memory evidence collection."""
    records = list(iter_long_term_memory_records(path))
    vectors = embedding_model.embed_texts(
        [str(record["embedding_text"]) for record in records]
    )
    return [
        {
            "id": memory_point_id(record["path"], int(record["line"])),
            "vector": vector,
            "payload": memory_payload(record, collection),
        }
        for record, vector in zip(records, vectors, strict=True)
    ]


def index_long_term_memory_collection(
    client: Any,
    config: QdrantConfig,
    path: Path,
    embedding_model: EmbeddingModel,
    source_key: str = DEFAULT_MEMORY_SOURCE_KEY,
    progress: Callable[[int], None] | None = None,
) -> int:
    """Index local long-term memory into its normal Qdrant evidence collection."""
    collection = config.data_collections.get(source_key)
    if collection is None:
        raise ValueError(f"Missing Qdrant data collection config: {source_key}")

    ensure_evidence_collection(
        client=client,
        collection_name=collection.collection,
        vector_size=config.vector_size,
        distance=config.distance,
    )

    points = build_long_term_memory_points(path, collection, embedding_model)
    for batch in _batches(points, BATCH_SIZE):
        client.upsert(
            collection_name=collection.collection,
            points=[_to_qdrant_point(point) for point in batch],
        )
        if progress is not None:
            progress(len(batch))
    return len(points)


def search_long_term_memory_collection(
    client: Any,
    config: QdrantConfig,
    query: str,
    embedding_model: EmbeddingModel,
    limit: int = 10,
    source_key: str = DEFAULT_MEMORY_SOURCE_KEY,
) -> list[EvidenceItem]:
    """Search the long-term-memory evidence collection and return evidence items."""
    collection = config.data_collections.get(source_key)
    if collection is None:
        raise ValueError(f"Missing Qdrant data collection config: {source_key}")

    raw_results = _query_points(
        client=client,
        collection_name=collection.collection,
        query_vector=embedding_model.embed_text(query),
        limit=max(1, int(limit)),
    )

    items: list[EvidenceItem] = []
    for point in raw_results:
        payload = _point_payload(point)
        if payload.get("index_kind") != "evidence_collection":
            continue
        if payload.get("source_key") != source_key:
            continue

        metadata = dict(payload.get("metadata", {}))
        metadata.update(
            {
                "path": payload.get("path"),
                "line": payload.get("line"),
                "score": _point_score(point),
                "source_key": payload.get("source_key"),
                "source_type": payload.get("source_type"),
            }
        )
        items.append(
            EvidenceItem(
                type=str(payload.get("type", "memory_match")),
                source=str(payload.get("source", "long_term_memory")),
                title=payload.get("title"),
                content=str(payload.get("content", "")),
                confidence=round(max(0.0, min(_point_score(point), 1.0)), 4),
                metadata=metadata,
            )
        )

    return items


def _parse_memory_line(line: str) -> dict[str, Any]:
    stripped = line.strip()
    if not stripped:
        return {"content": "", "metadata": {}}

    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return {"content": stripped, "metadata": {"format": "text"}}

    if not isinstance(parsed, dict):
        return {"content": str(parsed), "metadata": {"format": "json"}}

    content = ""
    for key in CONTENT_KEYS:
        value = parsed.get(key)
        if value is not None:
            content = _string_value(value)
            if content:
                break

    metadata = {key: value for key, value in parsed.items() if key not in CONTENT_KEYS}
    metadata.setdefault("format", "jsonl")
    return {"content": content or stripped, "metadata": metadata}


def _string_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _to_qdrant_point(point: dict[str, Any]) -> Any:
    try:
        from qdrant_client.models import PointStruct
    except ImportError:
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

    raise QdrantUnavailableError("Qdrant client does not provide query_points().")


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


def _batches(items: list[dict[str, Any]], batch_size: int) -> Iterable[list[dict[str, Any]]]:
    for index in range(0, len(items), batch_size):
        yield items[index : index + batch_size]


def _normalize_for_dedup(content: str) -> str:
    return re.sub(r"\s+", " ", content).strip().lower()
