from tools.knowledge.config import QdrantDataCollectionConfig
from tools.knowledge.indexes.qdrant_payloads import (
    capability_router_index_record,
    capability_router_payload,
    capability_router_point_id,
    data_collection_payload,
)
from tools.knowledge.models import CapabilityDefinition


def test_capability_router_point_id_is_stable_uuid():
    first = capability_router_point_id("search.recent_chats")
    second = capability_router_point_id("search.recent_chats")

    assert first == second
    assert len(first) == 36


def test_capability_router_record_keeps_routing_separate_from_data_collections():
    capability = CapabilityDefinition(
        id="search.recent_chats",
        name="Search Recent Chats",
        description="Searches previous chat history.",
        handler="tools.knowledge.capabilities.local.SearchRecentChatsCapability",
        tags=["chats", "history"],
        required_permissions=["chats.read"],
        sensitivity="personal",
    )

    record = capability_router_index_record(capability)

    assert record["id"] == capability_router_point_id("search.recent_chats")
    assert "Capability: Search Recent Chats" in record["embedding_text"]
    assert record["payload"] == capability_router_payload(capability)
    assert record["payload"]["index_kind"] == "capability_router"
    assert record["payload"]["capability_id"] == "search.recent_chats"
    assert "collection" not in record["payload"]


def test_data_collection_payload_describes_normal_local_qdrant_database():
    collection = QdrantDataCollectionConfig(
        key="chat_history",
        collection="agent_chat_history",
        description="Complete persisted chat history.",
        sensitivity="personal",
        source_type="chats",
    )

    payload = data_collection_payload(collection)

    assert payload == {
        "schema_version": 1,
        "index_kind": "evidence_collection",
        "source_key": "chat_history",
        "collection": "agent_chat_history",
        "description": "Complete persisted chat history.",
        "sensitivity": "personal",
        "source_type": "chats",
    }
