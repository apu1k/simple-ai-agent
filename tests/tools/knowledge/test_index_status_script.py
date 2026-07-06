import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "knowledge_index_status.py"


def load_status_script_module():
    spec = importlib.util.spec_from_file_location(
        "knowledge_index_status",
        SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_config(path, enabled=False, vector_size=1024):
    path.write_text(
        "qdrant:\n"
        f"  enabled: {str(enabled).lower()}\n"
        "  mode: local\n"
        "  local_path: runtime/knowledge/qdrant\n"
        "  capability_collection: agent_capability_router\n"
        "  embedding_backend: hashing\n"
        f"  vector_size: {vector_size}\n"
        "  distance: Cosine\n"
        "  data_collections:\n"
        "    chat_history:\n"
        "      collection: agent_chat_history\n"
        "      source_type: chats\n"
        "    long_term_memory:\n"
        "      collection: agent_long_term_memory\n"
        "      source_type: memory\n",
        encoding="utf-8",
    )


class FakeQdrantClient:
    def __init__(self, collections):
        self.collections = collections

    def collection_exists(self, collection_name):
        return collection_name in self.collections

    def get_collection(self, collection_name):
        return self.collections[collection_name]


def collection_info(size=1024, points_count=7, distance="Cosine"):
    return SimpleNamespace(
        points_count=points_count,
        config=SimpleNamespace(
            params=SimpleNamespace(
                vectors=SimpleNamespace(size=size, distance=distance),
            )
        ),
    )


def test_status_lists_expected_collections_without_inspecting_disabled_config(tmp_path):
    module = load_status_script_module()
    config_path = tmp_path / "knowledge.yaml"
    write_config(config_path, enabled=False)

    status = module.build_index_status(config_path)

    assert status["ok"] is True
    assert status["qdrant"]["enabled"] is False
    assert [item["collection"] for item in status["collections"]] == [
        "agent_capability_router",
        "agent_chat_history",
        "agent_long_term_memory",
    ]
    assert {item["status"] for item in status["collections"]} == {"not_inspected"}
    assert status["warnings"]


def test_status_reports_point_counts_and_vector_size_matches(tmp_path):
    module = load_status_script_module()
    config_path = tmp_path / "knowledge.yaml"
    write_config(config_path, enabled=True, vector_size=1024)
    client = FakeQdrantClient(
        {
            "agent_capability_router": collection_info(points_count=2),
            "agent_chat_history": collection_info(points_count=5),
            "agent_long_term_memory": collection_info(points_count=1),
        }
    )

    status = module.build_index_status(config_path, client=client)

    assert status["ok"] is True
    assert [item["point_count"] for item in status["collections"]] == [2, 5, 1]
    assert {item["status"] for item in status["collections"]} == {"ok"}


def test_status_warns_about_missing_and_vector_size_mismatch(tmp_path):
    module = load_status_script_module()
    config_path = tmp_path / "knowledge.yaml"
    write_config(config_path, enabled=True, vector_size=384)
    client = FakeQdrantClient(
        {
            "agent_capability_router": collection_info(size=1024, points_count=2),
            "agent_chat_history": collection_info(size=384, points_count=5),
        }
    )

    status = module.build_index_status(config_path, client=client)

    by_collection = {item["collection"]: item for item in status["collections"]}
    assert status["ok"] is False
    assert by_collection["agent_capability_router"]["status"] == "vector_size_mismatch"
    assert by_collection["agent_long_term_memory"]["status"] == "missing"
    assert len(status["warnings"]) >= 2


def test_status_script_writes_json_output(tmp_path):
    module = load_status_script_module()
    config_path = tmp_path / "knowledge.yaml"
    output_path = tmp_path / "status" / "knowledge.json"
    write_config(config_path, enabled=False)

    return_code = module.main(
        [
            "--config",
            str(config_path),
            "--output",
            str(output_path),
        ]
    )

    assert return_code == 0
    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert data["collections"][0]["collection"] == "agent_capability_router"
