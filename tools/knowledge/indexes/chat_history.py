from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Iterable
from uuid import NAMESPACE_URL, uuid5

from tools.knowledge.config import QdrantConfig, QdrantDataCollectionConfig
from tools.knowledge.embeddings.base import EmbeddingModel
from tools.knowledge.models import EvidenceItem
from tools.knowledge.stores.local import _parse_chat_line
from tools.knowledge.stores.qdrant import QdrantUnavailableError

CHAT_HISTORY_SCHEMA_VERSION = 1
DEFAULT_CHAT_HISTORY_SOURCE_KEY = "chat_history"
BATCH_SIZE = 128
CHAT_TURN_FILE_PREFIX = "turns_"
CHAT_TURN_FILE_SUFFIX = ".jsonl"


def iter_chat_history_records(root: Path) -> Iterable[dict[str, Any]]:
    """Yield parsed chat-history records suitable for evidence indexing."""
    if not root.exists() or not root.is_dir():
        return

    seen_content: set[str] = set()
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if not _is_chat_turn_file(path):
            continue

        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                for line_number, line in enumerate(handle, start=1):
                    parsed = _parse_chat_line(line)
                    if not _is_chat_turn_record(parsed):
                        continue

                    content = str(parsed["display_content"]).strip()
                    # Embed only the readable conversation text, not the raw JSONL
                    # record. The raw record contains metadata such as cwd/model/state
                    # that is useful for provenance but harmful noise for semantic search.
                    search_text = content
                    if not content or not search_text:
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
                        "embedding_text": search_text,
                        "metadata": parsed["metadata"],
                    }
        except OSError:
            continue


def find_chat_history_turn(
    path: Path,
    session_id: str,
    turn_index: int,
) -> dict[str, Any] | None:
    """Find one persisted chat turn and return its indexable record."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line_number, line in enumerate(handle, start=1):
                parsed = _parse_chat_line(line)
                metadata = parsed.get("metadata", {})
                if not isinstance(metadata, dict):
                    continue
                if metadata.get("session_id") != session_id:
                    continue
                if metadata.get("turn_index") != turn_index:
                    continue
                if not _is_chat_turn_record(parsed):
                    continue

                content = str(parsed.get("display_content", "")).strip()
                if not content:
                    return None
                return {
                    "path": str(path),
                    "line": line_number,
                    "title": f"{path}:{line_number}",
                    "content": content,
                    "embedding_text": content,
                    "metadata": metadata,
                }
    except OSError:
        return None

    return None


def chat_history_point_id(path: str, line: int) -> str:
    """Return a stable Qdrant-compatible UUID for one chat-history record."""
    return str(uuid5(NAMESPACE_URL, f"ai-agent:knowledge:chat-history:{path}:{line}"))


def chat_history_payload(
    record: dict[str, Any],
    collection: QdrantDataCollectionConfig,
) -> dict[str, Any]:
    """Return payload metadata for a normal chat-history evidence collection."""
    return {
        "schema_version": CHAT_HISTORY_SCHEMA_VERSION,
        "index_kind": "evidence_collection",
        "source_key": collection.key,
        "source_type": collection.source_type,
        "collection": collection.collection,
        "type": "chat_match",
        "source": "chat_history",
        "title": record["title"],
        "path": record["path"],
        "line": record["line"],
        "content": record["content"],
        "metadata": record.get("metadata", {}),
    }


def build_chat_history_points(
    root: Path,
    collection: QdrantDataCollectionConfig,
    embedding_model: EmbeddingModel,
) -> list[dict[str, Any]]:
    """Build vector points for the chat-history evidence collection."""
    records = list(iter_chat_history_records(root))
    return _build_chat_history_points_for_records(records, collection, embedding_model)


def _build_chat_history_points_for_records(
    records: list[dict[str, Any]],
    collection: QdrantDataCollectionConfig,
    embedding_model: EmbeddingModel,
) -> list[dict[str, Any]]:
    vectors = embedding_model.embed_texts(
        [str(record["embedding_text"]) for record in records]
    )
    return [
        {
            "id": chat_history_point_id(record["path"], int(record["line"])),
            "vector": vector,
            "payload": chat_history_payload(record, collection),
        }
        for record, vector in zip(records, vectors, strict=True)
    ]


def ensure_evidence_collection(
    client: Any,
    collection_name: str,
    vector_size: int,
    distance: str,
) -> None:
    """Create a normal evidence collection if it is missing."""
    try:
        from qdrant_client import models
    except ImportError as exc:  # pragma: no cover - depends on local env
        raise QdrantUnavailableError(
            "qdrant-client is required to create Qdrant collections."
        ) from exc

    collection_exists = getattr(client, "collection_exists", None)
    if collection_exists is not None and collection_exists(collection_name):
        return

    if collection_exists is None:
        try:
            client.get_collection(collection_name)
            return
        except Exception:
            pass

    client.create_collection(
        collection_name=collection_name,
        vectors_config=models.VectorParams(
            size=vector_size,
            distance=_qdrant_distance(models, distance),
        ),
    )


def index_chat_history_collection(
    client: Any,
    config: QdrantConfig,
    root: Path,
    embedding_model: EmbeddingModel,
    source_key: str = DEFAULT_CHAT_HISTORY_SOURCE_KEY,
    progress: Callable[[int], None] | None = None,
) -> int:
    """Index local chat history into its normal Qdrant evidence collection."""
    collection = config.data_collections.get(source_key)
    if collection is None:
        raise ValueError(f"Missing Qdrant data collection config: {source_key}")

    ensure_evidence_collection(
        client=client,
        collection_name=collection.collection,
        vector_size=config.vector_size,
        distance=config.distance,
    )

    count = 0
    for record_batch in _batches(list(iter_chat_history_records(root)), BATCH_SIZE):
        points = _build_chat_history_points_for_records(
            record_batch,
            collection,
            embedding_model,
        )
        if not points:
            continue
        client.upsert(
            collection_name=collection.collection,
            points=[_to_qdrant_point(point) for point in points],
        )
        count += len(points)
        if progress is not None:
            progress(count)
    return count


def index_chat_history_turn(
    client: Any,
    config: QdrantConfig,
    path: Path,
    session_id: str,
    turn_index: int,
    embedding_model: EmbeddingModel,
    source_key: str = DEFAULT_CHAT_HISTORY_SOURCE_KEY,
) -> int:
    """Embed and upsert exactly one persisted original chat turn."""
    collection = config.data_collections.get(source_key)
    if collection is None:
        raise ValueError(f"Missing Qdrant data collection config: {source_key}")

    record = find_chat_history_turn(path, session_id, turn_index)
    if record is None:
        return 0

    ensure_evidence_collection(
        client=client,
        collection_name=collection.collection,
        vector_size=config.vector_size,
        distance=config.distance,
    )
    points = _build_chat_history_points_for_records(
        [record],
        collection,
        embedding_model,
    )
    client.upsert(
        collection_name=collection.collection,
        points=[_to_qdrant_point(point) for point in points],
    )
    return len(points)


def search_chat_history_collection(
    client: Any,
    config: QdrantConfig,
    query: str,
    embedding_model: EmbeddingModel,
    limit: int = 10,
    source_key: str = DEFAULT_CHAT_HISTORY_SOURCE_KEY,
) -> list[EvidenceItem]:
    """Search the chat-history evidence collection and return evidence items."""
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
                type=str(payload.get("type", "chat_match")),
                source=str(payload.get("source", "chat_history")),
                title=payload.get("title"),
                content=str(payload.get("content", "")),
                confidence=round(max(0.0, min(_point_score(point), 1.0)), 4),
                metadata=metadata,
            )
        )

    return items


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


def _is_chat_turn_file(path: Path) -> bool:
    name = path.name.lower()
    return name.startswith(CHAT_TURN_FILE_PREFIX) and name.endswith(CHAT_TURN_FILE_SUFFIX)


def _is_chat_turn_record(parsed: dict[str, Any]) -> bool:
    metadata = parsed.get("metadata", {})
    if not isinstance(metadata, dict):
        return True

    record_type = metadata.get("type")
    return record_type in {None, "turn"}


def _normalize_for_dedup(content: str) -> str:
    return re.sub(r"\s+", " ", content).strip().lower()
