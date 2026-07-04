from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5

from tools.knowledge.config import QdrantDataCollectionConfig
from tools.knowledge.indexes.capability_text import capability_embedding_text
from tools.knowledge.models import CapabilityDefinition


CAPABILITY_ROUTER_SCHEMA_VERSION = 1
DATA_COLLECTION_SCHEMA_VERSION = 1


def capability_router_point_id(capability_id: str) -> str:
    """Return a stable Qdrant-compatible UUID for a capability id."""
    return str(uuid5(NAMESPACE_URL, f"ai-agent:knowledge:capability:{capability_id}"))


def capability_router_payload(capability: CapabilityDefinition) -> dict:
    """Return payload metadata for the Qdrant capability router index.

    This index is small and is used only to choose which capability/source should
    be asked. It is not the place where full chat history or documents live.
    """
    return {
        "schema_version": CAPABILITY_ROUTER_SCHEMA_VERSION,
        "index_kind": "capability_router",
        "capability_id": capability.id,
        "name": capability.name,
        "handler": capability.handler,
        "capability_type": capability.capability_type,
        "tags": capability.tags,
        "required_permissions": capability.required_permissions,
        "sensitivity": capability.sensitivity,
        "allow_network": capability.allow_network,
        "expected_confidence": capability.expected_confidence,
    }


def capability_router_index_record(capability: CapabilityDefinition) -> dict:
    """Return the pre-embedding record for the capability router index."""
    return {
        "id": capability_router_point_id(capability.id),
        "payload": capability_router_payload(capability),
        "embedding_text": capability_embedding_text(capability),
    }


def data_collection_payload(collection: QdrantDataCollectionConfig) -> dict:
    """Return payload metadata describing a normal Qdrant evidence collection."""
    return {
        "schema_version": DATA_COLLECTION_SCHEMA_VERSION,
        "index_kind": "evidence_collection",
        "source_key": collection.key,
        "collection": collection.collection,
        "description": collection.description,
        "sensitivity": collection.sensitivity,
        "source_type": collection.source_type,
    }
