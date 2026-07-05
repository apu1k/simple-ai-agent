import importlib.util
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "knowledge_index_all.py"


def load_index_script_module():
    spec = importlib.util.spec_from_file_location(
        "knowledge_index_all",
        SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_capability(capabilities_dir):
    capabilities_dir.mkdir(parents=True, exist_ok=True)
    (capabilities_dir / "local.yaml").write_text(
        "id: search.recent_chats\n"
        "name: Search recent chats\n"
        "description: Search local chat history.\n"
        "handler: tools.knowledge.capabilities.local.SearchRecentChatsCapability\n"
        "capability_type: search\n"
        "tags: [chat, local]\n",
        encoding="utf-8",
    )


def write_chat_turn(chat_history_dir):
    chat_history_dir.mkdir(parents=True, exist_ok=True)
    (chat_history_dir / "turns_original.jsonl").write_text(
        json.dumps(
            {
                "type": "turn",
                "user": "Should all indexes have one script?",
                "assistant_final": "Yes, a combined dry-run script is useful.",
            }
        )
        + "\n",
        encoding="utf-8",
    )


def write_memory(memory_path):
    memory_path.parent.mkdir(parents=True, exist_ok=True)
    memory_path.write_text(
        json.dumps({"content": "The user prefers local-only indexes."}) + "\n",
        encoding="utf-8",
    )


def test_index_all_script_builds_combined_preview(tmp_path):
    module = load_index_script_module()
    capabilities_dir = tmp_path / "capabilities"
    chat_history_dir = tmp_path / ".agent_chat_history"
    memory_path = tmp_path / "runtime" / "knowledge" / "memory.jsonl"
    write_capability(capabilities_dir)
    write_chat_turn(chat_history_dir)
    write_memory(memory_path)

    preview = module.build_index_preview(capabilities_dir, chat_history_dir, memory_path)

    assert preview["capabilities"]["record_count"] == 1
    assert preview["chat_history"]["record_count"] == 1
    assert preview["long_term_memory"]["record_count"] == 1
    assert preview["total_record_count"] == 3


def test_index_all_script_writes_preview_json(tmp_path):
    module = load_index_script_module()
    capabilities_dir = tmp_path / "capabilities"
    chat_history_dir = tmp_path / ".agent_chat_history"
    memory_path = tmp_path / "runtime" / "knowledge" / "memory.jsonl"
    output_path = tmp_path / "preview" / "all.json"
    write_capability(capabilities_dir)
    write_chat_turn(chat_history_dir)
    write_memory(memory_path)

    return_code = module.main(
        [
            "--capabilities-dir",
            str(capabilities_dir),
            "--chat-history-dir",
            str(chat_history_dir),
            "--memory-path",
            str(memory_path),
            "--output",
            str(output_path),
        ]
    )

    assert return_code == 0
    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert data["total_record_count"] == 3


def test_index_all_script_write_qdrant_is_opt_in(tmp_path, monkeypatch):
    module = load_index_script_module()
    capabilities_dir = tmp_path / "capabilities"
    chat_history_dir = tmp_path / ".agent_chat_history"
    memory_path = tmp_path / "runtime" / "knowledge" / "memory.jsonl"
    output_path = tmp_path / "all.json"
    write_capability(capabilities_dir)
    write_chat_turn(chat_history_dir)
    write_memory(memory_path)
    called = False

    def fail_if_called(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("Qdrant should not be used without --write-qdrant")

    monkeypatch.setattr(module, "write_all_indexes", fail_if_called)

    return_code = module.main(
        [
            "--capabilities-dir",
            str(capabilities_dir),
            "--chat-history-dir",
            str(chat_history_dir),
            "--memory-path",
            str(memory_path),
            "--output",
            str(output_path),
        ]
    )

    assert return_code == 0
    assert called is False
