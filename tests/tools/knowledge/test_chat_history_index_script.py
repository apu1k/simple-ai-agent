import importlib.util
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "knowledge_index_chat_history.py"


def load_index_script_module():
    spec = importlib.util.spec_from_file_location(
        "knowledge_index_chat_history",
        SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_chat_turn(chat_history_dir):
    chat_history_dir.mkdir()
    (chat_history_dir / "turns_original.jsonl").write_text(
        json.dumps(
            {
                "session_id": "session-1",
                "turn_index": 1,
                "user": "Should chat history be indexed in Qdrant?",
                "assistant_final": "Yes, as an evidence collection.",
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_chat_history_index_script_builds_dry_run_preview(tmp_path):
    module = load_index_script_module()
    chat_history_dir = tmp_path / ".agent_chat_history"
    write_chat_turn(chat_history_dir)

    preview = module.count_chat_history_preview(chat_history_dir)

    assert preview["chat_history_dir"] == str(chat_history_dir)
    assert preview["record_count"] == 1
    assert preview["sample"][0]["content"].startswith("User: Should chat history")
    assert preview["sample"][0]["metadata"]["session_id"] == "session-1"


def test_chat_history_index_script_writes_preview_json(tmp_path):
    module = load_index_script_module()
    chat_history_dir = tmp_path / ".agent_chat_history"
    output_path = tmp_path / "preview" / "chat_history.json"
    write_chat_turn(chat_history_dir)

    return_code = module.main(
        [
            "--chat-history-dir",
            str(chat_history_dir),
            "--output",
            str(output_path),
        ]
    )

    assert return_code == 0
    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert data["record_count"] == 1
    assert data["sample"][0]["line"] == 1


def test_chat_history_index_script_write_qdrant_is_opt_in(tmp_path, monkeypatch):
    module = load_index_script_module()
    chat_history_dir = tmp_path / ".agent_chat_history"
    output_path = tmp_path / "chat_history.json"
    write_chat_turn(chat_history_dir)
    called = False

    def fail_if_called(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("Qdrant should not be used without --write-qdrant")

    monkeypatch.setattr(module, "create_qdrant_client", fail_if_called)

    return_code = module.main(
        [
            "--chat-history-dir",
            str(chat_history_dir),
            "--output",
            str(output_path),
        ]
    )

    assert return_code == 0
    assert called is False
