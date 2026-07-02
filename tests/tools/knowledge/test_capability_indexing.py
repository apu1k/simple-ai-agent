import importlib.util
import json
from pathlib import Path

from tools.knowledge.indexes import capability_embedding_text
from tools.knowledge.models import CapabilityDefinition


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "knowledge_index_capabilities.py"


def load_index_script_module():
    spec = importlib.util.spec_from_file_location(
        "knowledge_index_capabilities",
        SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_capability_embedding_text_contains_routing_fields():
    capability = CapabilityDefinition(
        id="search.example",
        name="Search Example",
        capability_type="search",
        description="Searches example data for relevant evidence.",
        handler="tests.example.SearchExampleCapability",
        tags=["example", "data"],
        examples=["Find example evidence"],
        required_permissions=["example.read"],
        sensitivity="local",
        allow_network=False,
    )

    text = capability_embedding_text(capability)

    assert "Capability: Search Example" in text
    assert "ID: search.example" in text
    assert "Type: search" in text
    assert "Description: Searches example data" in text
    assert "Tags: example, data" in text
    assert "Examples:\n- Find example evidence" in text
    assert "Required permissions: example.read" in text
    assert "Sensitivity: local" in text
    assert "Network access: no" in text


def test_build_capability_index_preview_from_yaml(tmp_path):
    module = load_index_script_module()
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
                "examples:",
                "  - Find example data",
                "required_permissions:",
                "  - example.read",
                "sensitivity: local",
                "allow_network: false",
            ]
        ),
        encoding="utf-8",
    )

    preview = module.build_capability_index_preview(capabilities_dir)

    assert preview == [
        {
            "id": "search.example",
            "name": "Search Example",
            "handler": "tests.example.SearchExampleCapability",
            "tags": ["example"],
            "required_permissions": ["example.read"],
            "allow_network": False,
            "sensitivity": "local",
            "embedding_text": capability_embedding_text(
                CapabilityDefinition(
                    id="search.example",
                    name="Search Example",
                    capability_type="search",
                    description="Searches example data.",
                    handler="tests.example.SearchExampleCapability",
                    tags=["example"],
                    examples=["Find example data"],
                    required_permissions=["example.read"],
                    sensitivity="local",
                    allow_network=False,
                )
            ),
        }
    ]


def test_index_script_writes_json_preview(tmp_path):
    module = load_index_script_module()
    capabilities_dir = tmp_path / "capabilities"
    capabilities_dir.mkdir()
    output_path = tmp_path / "preview" / "capabilities.json"
    (capabilities_dir / "search_example.yaml").write_text(
        "\n".join(
            [
                "id: search.example",
                "name: Search Example",
                "description: Searches example data.",
                "handler: tests.example.SearchExampleCapability",
            ]
        ),
        encoding="utf-8",
    )

    return_code = module.main(
        [
            "--capabilities-dir",
            str(capabilities_dir),
            "--output",
            str(output_path),
        ]
    )

    assert return_code == 0
    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert data[0]["id"] == "search.example"
    assert "Capability: Search Example" in data[0]["embedding_text"]
