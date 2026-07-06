from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.knowledge.config import DEFAULT_KNOWLEDGE_CONFIG_PATH, QdrantConfig, load_knowledge_config
from tools.knowledge.stores.qdrant import (
    QdrantUnavailableError,
    create_qdrant_client,
    qdrant_client_available,
)


def expected_qdrant_collections(config: QdrantConfig) -> list[dict[str, str]]:
    """Return the Qdrant collections expected by the current knowledge config."""
    collections = [
        {
            "key": "capability_router",
            "collection": config.capability_collection,
            "index_kind": "capability_router",
            "source_type": "capability_router",
        }
    ]
    for key, collection in sorted(config.data_collections.items()):
        collections.append(
            {
                "key": key,
                "collection": collection.collection,
                "index_kind": "evidence_collection",
                "source_type": collection.source_type,
            }
        )
    return collections


def build_index_status(
    config_path: Path = DEFAULT_KNOWLEDGE_CONFIG_PATH,
    *,
    client: Any | None = None,
    inspect_disabled: bool = False,
) -> dict[str, Any]:
    """Build a JSON-serializable health report for knowledge Qdrant indexes."""
    config = load_knowledge_config(config_path).qdrant
    should_inspect = config.enabled or inspect_disabled or client is not None
    status: dict[str, Any] = {
        "config_path": str(config_path),
        "qdrant": {
            "enabled": config.enabled,
            "mode": config.mode,
            "local_path": str(config.local_path),
            "url": config.url if config.mode == "http" else None,
            "client_available": qdrant_client_available(),
        },
        "embedding": {
            "backend": config.embedding_backend,
            "model": config.embedding_model,
            "device": config.embedding_device,
            "local_files_only": config.embedding_local_files_only,
            "batch_size": config.embedding_batch_size,
            "vector_size": config.vector_size,
            "distance": config.distance,
        },
        "collections": [],
        "warnings": [],
        "ok": True,
    }

    if not config.enabled:
        status["warnings"].append(
            "Qdrant is disabled in config; knowledge search will use keyword fallback."
        )

    if not should_inspect:
        for expected in expected_qdrant_collections(config):
            status["collections"].append(
                _not_inspected_collection_status(expected, config.vector_size)
            )
        return status

    if client is None:
        try:
            client = create_qdrant_client(config)
        except QdrantUnavailableError as exc:
            status["ok"] = False
            status["warnings"].append(str(exc))
            for expected in expected_qdrant_collections(config):
                item = _not_inspected_collection_status(expected, config.vector_size)
                item["status"] = "unavailable"
                item["error"] = str(exc)
                status["collections"].append(item)
            return status
        except Exception as exc:  # pragma: no cover - depends on local Qdrant state
            status["ok"] = False
            status["warnings"].append(f"Could not create Qdrant client: {exc}")
            for expected in expected_qdrant_collections(config):
                item = _not_inspected_collection_status(expected, config.vector_size)
                item["status"] = "unavailable"
                item["error"] = str(exc)
                status["collections"].append(item)
            return status

    for expected in expected_qdrant_collections(config):
        item = inspect_qdrant_collection(client, expected, config)
        status["collections"].append(item)
        if item["status"] in {"missing", "error", "vector_size_mismatch"}:
            status["ok"] = False
            if item["status"] == "missing":
                status["warnings"].append(
                    f"Missing Qdrant collection: {item['collection']}"
                )
            elif item["status"] == "vector_size_mismatch":
                status["warnings"].append(
                    f"Collection {item['collection']} vector size "
                    f"{item['vector_size']} does not match configured "
                    f"size {config.vector_size}."
                )
            elif item.get("error"):
                status["warnings"].append(
                    f"Could not inspect collection {item['collection']}: {item['error']}"
                )

    return status


def inspect_qdrant_collection(
    client: Any,
    expected: dict[str, str],
    config: QdrantConfig,
) -> dict[str, Any]:
    """Inspect one expected Qdrant collection using a real or fake client."""
    collection_name = expected["collection"]
    item: dict[str, Any] = {
        **expected,
        "expected_vector_size": config.vector_size,
        "exists": False,
        "status": "missing",
        "point_count": None,
        "vector_size": None,
        "distance": None,
    }

    try:
        if not _collection_exists(client, collection_name):
            return item
        info = client.get_collection(collection_name)
    except Exception as exc:
        item["status"] = "error"
        item["error"] = str(exc)
        return item

    vector_size = _extract_vector_size(info)
    item.update(
        {
            "exists": True,
            "status": "ok",
            "point_count": _extract_point_count(info),
            "vector_size": vector_size,
            "distance": _extract_distance(info),
        }
    )
    if vector_size is not None and int(vector_size) != int(config.vector_size):
        item["status"] = "vector_size_mismatch"
    return item


def _not_inspected_collection_status(
    expected: dict[str, str],
    expected_vector_size: int,
) -> dict[str, Any]:
    return {
        **expected,
        "expected_vector_size": expected_vector_size,
        "exists": None,
        "status": "not_inspected",
        "point_count": None,
        "vector_size": None,
        "distance": None,
    }


def _collection_exists(client: Any, collection_name: str) -> bool:
    collection_exists = getattr(client, "collection_exists", None)
    if collection_exists is not None:
        return bool(collection_exists(collection_name))

    try:
        client.get_collection(collection_name)
    except Exception:
        return False
    return True


def _extract_point_count(info: Any) -> int | None:
    for name in ("points_count", "vectors_count"):
        value = _nested_get(info, name)
        if value is not None:
            return int(value)
    return None


def _extract_vector_size(info: Any) -> int | None:
    vectors = _nested_get(info, "config", "params", "vectors")
    if vectors is None:
        vectors = _nested_get(info, "vectors_config")

    size = _extract_vector_field(vectors, "size")
    return int(size) if size is not None else None


def _extract_distance(info: Any) -> str | None:
    vectors = _nested_get(info, "config", "params", "vectors")
    if vectors is None:
        vectors = _nested_get(info, "vectors_config")

    distance = _extract_vector_field(vectors, "distance")
    return str(distance) if distance is not None else None


def _extract_vector_field(vectors: Any, field: str) -> Any:
    if vectors is None:
        return None

    direct = _nested_get(vectors, field)
    if direct is not None:
        return direct

    if isinstance(vectors, dict):
        for value in vectors.values():
            nested = _nested_get(value, field)
            if nested is not None:
                return nested
    return None


def _nested_get(value: Any, *names: str) -> Any:
    current = value
    for name in names:
        if current is None:
            return None
        if isinstance(current, dict):
            current = current.get(name)
        else:
            current = getattr(current, name, None)
    return current


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Report health/status for local knowledge Qdrant indexes."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_KNOWLEDGE_CONFIG_PATH,
        help="Knowledge config path.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path to write status JSON. Defaults to stdout.",
    )
    parser.add_argument(
        "--inspect-disabled",
        action="store_true",
        help=(
            "Inspect Qdrant collections even when qdrant.enabled is false. "
            "By default disabled configs are reported without touching Qdrant."
        ),
    )
    args = parser.parse_args(argv)

    status = build_index_status(
        args.config,
        inspect_disabled=args.inspect_disabled,
    )
    text = json.dumps(status, ensure_ascii=False, indent=2)
    if args.output is None:
        print(text)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")

    return 0 if status["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
