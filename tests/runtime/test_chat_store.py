import json
from pathlib import Path

import pytest

from runtime.chat_store import ChatStore, ensure_chat_session, record_final_turn, start_new_chat
from runtime.state import AgentState, ModelConfig


def make_state(tmp_path: Path) -> AgentState:
    return AgentState(
        cwd=tmp_path,
        model_config=ModelConfig(
            provider_key="test-provider",
            provider_label="Test Provider",
            model="test-model",
            api_key="secret-api-key-must-not-be-stored",
            base_url="https://example.invalid",
            api_type="chat_completions",
        ),
        chat_store=ChatStore(tmp_path / "history"),
    )


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_new_session_writes_session_record_with_state_snapshot(tmp_path: Path):
    state = make_state(tmp_path)

    session_id = start_new_chat(state, title="Test chat")

    assert state.chat_session_id == session_id

    records = read_jsonl(state.chat_store.sessions_path)
    assert len(records) == 1
    record = records[0]

    assert record["type"] == "session_created"
    assert record["session_id"] == session_id
    assert record["title"] == "Test chat"
    assert record["state"]["cwd"] == str(tmp_path)
    assert record["state"]["provider_key"] == "test-provider"
    assert record["state"]["provider_label"] == "Test Provider"
    assert record["state"]["model"] == "test-model"
    assert record["state"]["api_type"] == "chat_completions"
    assert "api_key" not in record["state"]
    assert "secret-api-key-must-not-be-stored" not in json.dumps(record)


def test_record_final_turn_writes_original_and_working_streams(tmp_path: Path):
    state = make_state(tmp_path)
    session_id = start_new_chat(state)

    turn_index = record_final_turn(state, "hello", "hi there")

    assert turn_index == 1

    original = read_jsonl(state.chat_store.original_turns_path)
    working = read_jsonl(state.chat_store.working_turns_path)

    assert len(original) == 1
    assert len(working) == 1

    original_turn = original[0]
    working_turn = working[0]

    assert original_turn["type"] == "turn"
    assert original_turn["stream"] == "original"
    assert original_turn["session_id"] == session_id
    assert original_turn["turn_index"] == 1
    assert original_turn["user"] == "hello"
    assert original_turn["assistant_final"] == "hi there"

    assert working_turn["type"] == "turn"
    assert working_turn["stream"] == "working"
    assert working_turn["session_id"] == session_id
    assert working_turn["turn_index"] == 1
    assert working_turn["source"] == "original"
    assert working_turn["source_turn_index"] == 1
    assert working_turn["user"] == "hello"
    assert working_turn["assistant_final"] == "hi there"


def test_record_final_turn_creates_session_if_missing(tmp_path: Path):
    state = make_state(tmp_path)

    assert state.chat_session_id is None

    turn_index = record_final_turn(state, "question", "answer")

    assert turn_index == 1
    assert state.chat_session_id
    assert state.chat_store.sessions_path.exists()
    assert state.chat_store.original_turns_path.exists()
    assert state.chat_store.working_turns_path.exists()


def test_append_turn_increments_turn_index_per_session(tmp_path: Path):
    state = make_state(tmp_path)
    first_session = start_new_chat(state)

    assert record_final_turn(state, "u1", "a1") == 1
    assert record_final_turn(state, "u2", "a2") == 2

    second_session = start_new_chat(state)
    assert second_session != first_session
    assert record_final_turn(state, "u3", "a3") == 1

    original = read_jsonl(state.chat_store.original_turns_path)
    first_turns = [turn for turn in original if turn["session_id"] == first_session]
    second_turns = [turn for turn in original if turn["session_id"] == second_session]

    assert [turn["turn_index"] for turn in first_turns] == [1, 2]
    assert [turn["turn_index"] for turn in second_turns] == [1]


def test_list_sessions_returns_turn_counts_and_recent_first(tmp_path: Path):
    state = make_state(tmp_path)

    older_session = start_new_chat(state, title="older")
    record_final_turn(state, "old", "old answer")

    newer_session = start_new_chat(state, title="newer")
    record_final_turn(state, "new 1", "new answer 1")
    record_final_turn(state, "new 2", "new answer 2")

    sessions = state.chat_store.list_sessions(limit=10)

    assert [session.session_id for session in sessions] == [newer_session, older_session]
    assert sessions[0].title == "newer"
    assert sessions[0].turn_count == 2
    assert sessions[1].title == "older"
    assert sessions[1].turn_count == 1


def test_load_original_turns_returns_last_turns_in_order(tmp_path: Path):
    state = make_state(tmp_path)
    session_id = start_new_chat(state)

    record_final_turn(state, "u1", "a1")
    record_final_turn(state, "u2", "a2")
    record_final_turn(state, "u3", "a3")

    turns = state.chat_store.load_original_turns(session_id, limit=2)

    assert [turn["turn_index"] for turn in turns] == [2, 3]
    assert [turn["user"] for turn in turns] == ["u2", "u3"]


def test_format_session_list_handles_empty_and_non_empty_history(tmp_path: Path):
    state = make_state(tmp_path)

    assert state.chat_store.format_session_list() == "No chat history yet."

    session_id = start_new_chat(state, title="hello title")
    record_final_turn(state, "hello", "hi")

    text = state.chat_store.format_session_list()

    assert "Recent chat sessions:" in text
    assert session_id[:12] in text
    assert "turns=1" in text
    assert "Test Provider / test-model" in text
    assert "hello title" in text


def test_ensure_chat_session_reuses_existing_session(tmp_path: Path):
    state = make_state(tmp_path)
    session_id = start_new_chat(state)

    assert ensure_chat_session(state) == session_id
    assert ensure_chat_session(state) == session_id

    records = read_jsonl(state.chat_store.sessions_path)
    assert len(records) == 1


def test_append_turn_rejects_unhandled_tool_call_markup(tmp_path: Path):
    store = ChatStore(root=tmp_path)
    session_id = store.new_session(title="test")

    with pytest.raises(RuntimeError) as exc:
        store.append_turn(
            session_id=session_id,
            user_text="please call a tool",
            assistant_text='<tool_call>{"recipient_name":"functions.pwd","parameters":{}}</tool_call>',
        )

    assert "Unhandled <tool_call> markup" in str(exc.value)
