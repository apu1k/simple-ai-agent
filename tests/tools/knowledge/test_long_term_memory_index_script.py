import importlib.util
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "knowledge_index_long_term_memory.py"


def load_index_script_module():
    spec = importlib.util.spec_from_file_location(
        "knowledge_index_long_term_memory",
        SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_memory(memory_path):
    memory_path.parent.mkdir(parents=True, exist_ok=True)
    memory_path.write_text(
        json.dumps(
            {
                "content": "The user prefers local-only memory search.",
                "tags": ["preferences"],
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_long_term_memory_index_script_builds_dry_run_preview(tmp_path):
    module = load_index_script_module()
    memory_path = tmp_path / "runtime" / "knowledge" / "memory.jsonl"
    write_memory(memory_path)

    preview = module.count_long_term_memory_preview(memory_path)

    assert preview["memory_path"] == str(memory_path)
    assert preview["record_count"] == 1
    assert preview["sample"][0]["content"] == "The user prefers local-only memory search."
    assert preview["sample"][0]["metadata"] == {
        "tags": ["preferences"],
        "format": "jsonl",
    }


def test_long_term_memory_index_script_writes_preview_json(tmp_path):
    module = load_index_script_module()
    memory_path = tmp_path / "runtime" / "knowledge" / "memory.jsonl"
    output_path = tmp_path / "preview" / "memory.json"
    write_memory(memory_path)

    return_code = module.main(
        [
            "--memory-path",
            str(memory_path),
            "--output",
            str(output_path),
        ]
    )

    assert return_code == 0
    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert data["record_count"] == 1
    assert data["sample"][0]["line"] == 1


def test_long_term_memory_index_script_write_qdrant_is_opt_in(tmp_path, monkeypatch):
    module = load_index_script_module()
    memory_path = tmp_path / "runtime" / "knowledge" / "memory.jsonl"
    output_path = tmp_path / "memory.json"
    write_memory(memory_path)
    called = False

    def fail_if_called(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("Qdrant should not be used without --write-qdrant")

    monkeypatch.setattr(module, "create_qdrant_client", fail_if_called)

    return_code = module.main(
        [
            "--memory-path",
            str(memory_path),
            "--output",
            str(output_path),
        ]
    )

    assert return_code == 0
    assert called is False
