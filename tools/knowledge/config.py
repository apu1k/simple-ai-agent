from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

try:
    import yaml
except ImportError:  # pragma: no cover - PyYAML is a runtime dependency now.
    yaml = None


DEFAULT_KNOWLEDGE_CONFIG_PATH = Path("config") / "knowledge.yaml"
QdrantMode = Literal["local", "http"]


@dataclass(frozen=True)
class KnowledgeSynthesisConfig:
    """Settings for reducing retrieved evidence with a dedicated LLM."""

    enabled: bool = True
    provider_key: str = ""
    model: str = "gpt-5.6-luna"
    fallback_to_raw: bool = True


@dataclass(frozen=True)
class QdrantDataCollectionConfig:
    """Configuration for a normal Qdrant evidence/data collection."""

    key: str
    collection: str
    description: str = ""
    sensitivity: str = "local"
    source_type: str = "generic"


@dataclass(frozen=True)
class QdrantConfig:
    """Qdrant settings for router indexes and ordinary data collections.

    mode="local" uses qdrant-client's local persistent storage and does not
    require a hosted service, API key, or HTTP server. mode="http" is available
    for a locally running Qdrant server if we ever want that later.
    """

    enabled: bool = False
    mode: QdrantMode = "local"
    local_path: Path = Path("runtime") / "knowledge" / "qdrant"
    url: str = "http://localhost:6333"
    timeout_seconds: float = 10.0
    capability_collection: str = "agent_capability_router"
    embedding_backend: str = "hashing"
    embedding_model: str = ""
    embedding_device: str = "cpu"
    embedding_local_files_only: bool = True
    embedding_batch_size: int = 32
    vector_size: int = 1024
    distance: str = "Cosine"
    data_collections: dict[str, QdrantDataCollectionConfig] = field(default_factory=dict)


@dataclass(frozen=True)
class KnowledgeConfig:
    qdrant: QdrantConfig = field(default_factory=QdrantConfig)
    synthesis: KnowledgeSynthesisConfig = field(default_factory=KnowledgeSynthesisConfig)


def load_knowledge_config(path: Path = DEFAULT_KNOWLEDGE_CONFIG_PATH) -> KnowledgeConfig:
    """Load knowledge-engine configuration with safe defaults.

    Missing or invalid config files intentionally fall back to a disabled,
    fully-local Qdrant config so local keyword search keeps working.
    """
    if not path.exists() or not path.is_file() or yaml is None:
        return KnowledgeConfig()

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError:
        return KnowledgeConfig()

    if not isinstance(raw, dict):
        return KnowledgeConfig()

    return KnowledgeConfig(
        qdrant=_parse_qdrant_config(raw.get("qdrant", {})),
        synthesis=_parse_synthesis_config(raw.get("synthesis", {})),
    )


def _parse_synthesis_config(data: Any) -> KnowledgeSynthesisConfig:
    if not isinstance(data, dict):
        return KnowledgeSynthesisConfig()

    return KnowledgeSynthesisConfig(
        enabled=bool(data.get("enabled", True)),
        provider_key=str(data.get("provider_key", "")).strip(),
        model=str(data.get("model", "gpt-5.6-luna")).strip() or "gpt-5.6-luna",
        fallback_to_raw=bool(data.get("fallback_to_raw", True)),
    )


def _parse_qdrant_config(data: Any) -> QdrantConfig:
    if not isinstance(data, dict):
        return QdrantConfig()

    return QdrantConfig(
        enabled=bool(data.get("enabled", False)),
        mode=_parse_qdrant_mode(data.get("mode", "local")),
        local_path=Path(str(data.get("local_path", "runtime/knowledge/qdrant"))),
        url=str(data.get("url", "http://localhost:6333")),
        timeout_seconds=float(data.get("timeout_seconds", 10.0)),
        capability_collection=str(
            data.get("capability_collection", "agent_capability_router")
        ),
        embedding_backend=str(data.get("embedding_backend", "hashing")),
        embedding_model=str(data.get("embedding_model", "")),
        embedding_device=str(data.get("embedding_device", "cpu")),
        embedding_local_files_only=bool(data.get("embedding_local_files_only", True)),
        embedding_batch_size=int(data.get("embedding_batch_size", 32)),
        vector_size=int(data.get("vector_size", 1024)),
        distance=str(data.get("distance", "Cosine")),
        data_collections=_parse_data_collections(data.get("data_collections", {})),
    )


def _parse_qdrant_mode(value: Any) -> QdrantMode:
    mode = str(value).strip().lower()
    if mode == "http":
        return "http"
    return "local"


def _parse_data_collections(data: Any) -> dict[str, QdrantDataCollectionConfig]:
    if not isinstance(data, dict):
        return {}

    collections: dict[str, QdrantDataCollectionConfig] = {}
    for key, value in data.items():
        if not isinstance(value, dict):
            continue
        normalized_key = str(key).strip()
        collection = str(value.get("collection", "")).strip()
        if not normalized_key or not collection:
            continue
        collections[normalized_key] = QdrantDataCollectionConfig(
            key=normalized_key,
            collection=collection,
            description=str(value.get("description", "")),
            sensitivity=str(value.get("sensitivity", "local")),
            source_type=str(value.get("source_type", normalized_key)),
        )

    return collections
