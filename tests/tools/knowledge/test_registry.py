from pathlib import Path

from tools.knowledge.models import KnowledgeSearchRequest
from tools.knowledge.registry import CapabilityRegistry, load_capability_definitions


def test_load_capability_definitions_from_yaml(tmp_path):
    capabilities_dir = tmp_path / "capabilities"
    capabilities_dir.mkdir()
    (capabilities_dir / "search_example.yaml").write_text(
        "\n".join(
            [
                "id: search.example",
                "name: Search Example",
                "capability_type: search",
                "description: Searches example data.",
                "handler: tests.example.SearchExampleCapability",
                "tags:",
                "  - example",
                "  - data",
                "examples:",
                "  - Find example data",
                "required_permissions:",
                "  - example.read",
                "sensitivity: local",
                "allow_network: false",
                "expected_latency_ms: 123",
                "expected_confidence: 0.8",
            ]
        ),
        encoding="utf-8",
    )

    capabilities = load_capability_definitions(capabilities_dir)

    assert len(capabilities) == 1
    capability = capabilities[0]
    assert capability.id == "search.example"
    assert capability.name == "Search Example"
    assert capability.handler == "tests.example.SearchExampleCapability"
    assert capability.tags == ["example", "data"]
    assert capability.examples == ["Find example data"]
    assert capability.required_permissions == ["example.read"]
    assert capability.sensitivity == "local"
    assert capability.allow_network is False
    assert capability.expected_latency_ms == 123
    assert capability.expected_confidence == 0.8


def test_load_capability_definitions_falls_back_when_directory_missing(tmp_path):
    capabilities = load_capability_definitions(tmp_path / "missing")

    assert {capability.id for capability in capabilities} == {
        "search.recent_chats",
        "search.long_term_memory",
    }


def test_capability_registry_routes_by_source_filter():
    registry = CapabilityRegistry()
    request = KnowledgeSearchRequest(
        query="Qdrant",
        sources=["chats"],
        max_capabilities=2,
    )

    candidates = registry.search(request, top_k=5)

    assert [candidate.capability.id for candidate in candidates] == [
        "search.recent_chats"
    ]
    assert candidates[0].score > 0
    assert "qdrant" in candidates[0].reason.lower()


def test_capability_registry_respects_allow_network_flag(tmp_path):
    capabilities_dir = tmp_path / "capabilities"
    capabilities_dir.mkdir()
    (capabilities_dir / "internet.yaml").write_text(
        "\n".join(
            [
                "id: search.internet",
                "name: Search Internet",
                "capability_type: search",
                "description: Searches the internet for fresh information.",
                "handler: tests.example.SearchInternetCapability",
                "tags:",
                "  - internet",
                "  - web",
                "examples:",
                "  - Search the web",
                "allow_network: true",
            ]
        ),
        encoding="utf-8",
    )
    capabilities = load_capability_definitions(capabilities_dir)
    registry = CapabilityRegistry(capabilities=capabilities)

    blocked = registry.search(
        KnowledgeSearchRequest(query="search internet", allow_network=False),
        top_k=5,
    )
    allowed = registry.search(
        KnowledgeSearchRequest(query="search internet", allow_network=True),
        top_k=5,
    )

    assert blocked == []
    assert [candidate.capability.id for candidate in allowed] == ["search.internet"]
