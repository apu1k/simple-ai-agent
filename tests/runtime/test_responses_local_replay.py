"""Test durable Responses replay using the real SDK and an offline HTTP transport."""
from copy import deepcopy
import json

import httpx
from openai import OpenAI
import pytest

from core.tool_registry import ToolRegistry, ToolSpec
from llm.openai_responses import OpenAIResponsesClient
from llm.providers import PROVIDERS, ProviderConfig
from llm.responses_transcript import EXECUTION_REFS_KEY, SEQUENCE_KEY
from runtime.bootstrap import create_agent
from runtime.chat_store import ChatStore
from runtime.conversations import ConversationManager
from runtime.events import RunInfo
from runtime.service import AgentRuntime
from runtime.state import AgentState, ModelConfig

OPENAI = ProviderConfig(key="replay-openai", label="OpenAI", api_key="offline", base_url=None,
                        api_type="responses", default_model="gpt-6.2-sol", supports_model_listing=False)
CLAUDE = ProviderConfig(key="replay-claude", label="Claude", api_key="offline", base_url=None,
                        api_type="anthropic_messages", default_model="test-claude", supports_model_listing=False)
CIPHER = "opaque-reasoning-do-not-expose"
RESULT = "complete tool observation from the recovery journal"
REASONING = {"type": "reasoning", "id": "rs_1", "summary": [], "encrypted_content": CIPHER}
CALL = {"type": "function_call", "id": "fc_1", "call_id": "call_fixture", "name": "fixture_tool",
        "arguments": "{}", "status": "completed"}
TOOL_OUTPUT = {"type": "function_call_output", "call_id": "call_fixture", "output": RESULT}


def answer(index, text):
    return {"type": "message", "role": "assistant", "id": f"msg_{index}", "status": "completed",
            "phase": "final_answer", "content": [{"type": "output_text", "text": text, "annotations": []}]}


class Wire:
    def __init__(self):
        self.requests = []
        self.replies = []
        self.effects = []
        self.transports = []
        self.claude_requests = []

    def close(self):
        for client in self.transports:
            client.close()

    def handler(self, request):
        self.requests.append(json.loads(request.content))
        status, output = self.replies.pop(0)
        return httpx.Response(200, json={
            "id": f"resp_{len(self.requests)}", "object": "response", "created_at": 0.0,
            "status": status, "model": OPENAI.default_model, "output": output,
        })

    def compose(self, provider, model):
        config = ModelConfig(provider.key, provider.label, model, provider.api_key,
                             provider.base_url, provider.api_type)
        if provider == OPENAI:
            llm = OpenAIResponsesClient(provider)
            llm._client = OpenAI(api_key="offline", max_retries=0,
                http_client=httpx.Client(transport=httpx.MockTransport(self.handler)))
            self.transports.append(llm._client)
        else:
            wire = self

            class FakeClaude:
                api_type = "anthropic_messages"
                supports_native_tools = True

                def chat(self, messages, tools=None, tool_choice=None):
                    wire.claude_requests.append(deepcopy(messages))
                    return "from Claude"

            llm = FakeClaude()
        return config, llm

    def manager(self, path):
        history = ChatStore(path / "history")
        registry = ToolRegistry()

        def tool():
            self.effects.append("ran")
            return RESULT

        registry.register(ToolSpec("fixture_tool", tool, "fixture tool", {}))

        def factory(chat, store, _source):
            config, llm = self.compose(OPENAI, OPENAI.default_model)
            return AgentRuntime(
                state=AgentState(path, config, chat_store=history, chat_session_id=chat),
                llm=llm, persistence_store=store,
                agent_factory=lambda **kwargs: create_agent(tool_registry=registry, **kwargs),
            )

        return ConversationManager(history=history, runtime_factory=factory, persistence_path=path / "runtime.sqlite3")


@pytest.fixture
def wire():
    instance = Wire()
    yield instance
    instance.close()


def finish(runtime, text):
    runtime.submit(text)
    assert runtime.wait_for_idle(5)
    return runtime.snapshot().run.reply


def test_ordered_replay_survives_restart_without_reexecuting_tools(tmp_path, wire):
    final = answer(1, "first answer")
    wire.replies.extend([("completed", [REASONING, CALL]), ("completed", [final])])
    manager = wire.manager(tmp_path)
    try:
        chat = manager.default_chat_id
        runtime = manager.get(chat)
        assert finish(runtime, "first task") == "first answer"
        first, second = wire.requests
        assert second["input"] == [*first["input"], REASONING, CALL, TOOL_OUTPUT]
        assert second["instructions"] == first["instructions"]
        assert all(r["store"] is False and "previous_response_id" not in r for r in wire.requests)
        assert CIPHER not in repr(runtime.snapshot()) and CIPHER not in repr(runtime.events_since(0))
        with manager.storage.root.transaction() as db:
            checkpoint = json.loads(db.execute("SELECT payload FROM chat_checkpoints").fetchone()[0])
            assert CIPHER not in repr(checkpoint)
            assert len(checkpoint["context"]["messages"]) == 5
            assert all(SEQUENCE_KEY in m for m in checkpoint["context"]["messages"])
            transcript = db.execute("SELECT payload FROM chat_transcript ORDER BY sequence").fetchall()
            assert CIPHER in repr(transcript) and RESULT not in repr(transcript)
            assert EXECUTION_REFS_KEY in repr(transcript)
        assert CIPHER not in (tmp_path / "history" / "turns_original.jsonl").read_text(encoding="utf-8")
        child = tmp_path / "new-cwd"
        child.mkdir()
        runtime.change_directory(str(child))
    finally:
        manager.close()
    wire.replies.append(("completed", [answer(2, "second answer")]))
    manager = wire.manager(tmp_path)
    try:
        runtime = manager.get(chat)
        assert finish(runtime, "next task") == "second answer"
        third = wire.requests[-1]
        assert third["instructions"] == second["instructions"]
        assert third["input"][:-2] == [*second["input"], final]
        assert third["input"][-2]["role"] == "developer"
        assert str(child) in third["input"][-2]["content"]
        assert third["input"][-1] == {"role": "user", "content": "next task"}
        assert wire.effects == ["ran"]
    finally:
        manager.close()


def test_provider_switch_keeps_tool_facts_and_original_openai_items(tmp_path, wire, monkeypatch):
    monkeypatch.setitem(PROVIDERS, OPENAI.key, OPENAI)
    monkeypatch.setitem(PROVIDERS, CLAUDE.key, CLAUDE)
    monkeypatch.setattr("runtime.service.build_model_config_and_client", wire.compose)
    wire.replies.extend([("completed", [REASONING, CALL]), ("completed", [answer(1, "OpenAI answer")])])
    manager = wire.manager(tmp_path)
    try:
        runtime = manager.get(manager.default_chat_id)
        assert finish(runtime, "first task") == "OpenAI answer"
        runtime.switch_model(CLAUDE.key, CLAUDE.default_model)
        assert finish(runtime, "for Claude") == "from Claude"
        sent = repr(wire.claude_requests[-1])
        assert RESULT in sent and "fixture_tool" in sent and "OpenAI answer" in sent
        assert CIPHER not in sent and "_responses_replay" not in sent
        runtime.switch_model(OPENAI.key, OPENAI.default_model)
        wire.replies.append(("completed", [answer(2, "back to OpenAI")]))
        assert finish(runtime, "back to OpenAI") == "back to OpenAI"
        assert REASONING in wire.requests[-1]["input"] and TOOL_OUTPUT in wire.requests[-1]["input"]
        assert {"role": "assistant", "content": "from Claude"} in wire.requests[-1]["input"]
        assert wire.effects == ["ran"]
    finally:
        manager.close()


def test_incomplete_response_does_not_replay_or_redispatch_the_failed_turn(tmp_path, wire):
    wire.replies.extend([
        ("completed", [answer(1, "safe answer")]),
        ("completed", [REASONING, CALL]),
        ("incomplete", [answer(2, "PARTIAL_OUTPUT")]),
        ("completed", [answer(3, "continued")]),
    ])
    manager = wire.manager(tmp_path)
    try:
        runtime = manager.get(manager.default_chat_id)
        assert finish(runtime, "safe task") == "safe answer"
        assert finish(runtime, "failed task").startswith("Error:")
        assert CIPHER in repr(wire.requests[-1]["input"])
        assert finish(runtime, "new task") == "continued"
        replay = repr(wire.requests[-1]["input"])
        for value in (CIPHER, "PARTIAL_OUTPUT", "failed task", "call_fixture"):
            assert value not in replay
        assert "safe answer" in replay and wire.effects == ["ran"]
        with manager.storage.root.transaction() as db:
            results = db.execute("SELECT payload FROM chat_transcript").fetchall()
            assert "PARTIAL_OUTPUT" in repr(results) and CIPHER in repr(results)
    finally:
        manager.close()


def test_uncommitted_rows_remain_evidence_not_replay_input(tmp_path, wire):
    wire.replies.append(("completed", [answer(1, "safe answer")]))
    manager = wire.manager(tmp_path)
    try:
        chat = manager.default_chat_id
        runtime = manager.get(chat)
        assert finish(runtime, "safe task") == "safe answer"
        runtime._run = RunInfo(run_id="a" * 32, user_text="interrupted request")
        runtime._checkpoint()
        runtime._on_transcript({"role": "user", "content": "STAGED_NOT_REPLAYABLE"})
    finally:
        manager.close()
    wire.replies.append(("completed", [answer(2, "recovered")]))
    manager = wire.manager(tmp_path)
    try:
        runtime = manager.get(chat)
        assert runtime.snapshot().run.status == "interrupted"
        assert finish(runtime, "recover") == "recovered"
        assert "STAGED_NOT_REPLAYABLE" not in repr(wire.requests[-1]["input"])
        assert "safe task" in repr(wire.requests[-1]["input"])
        with manager.storage.root.transaction() as db:
            assert "STAGED_NOT_REPLAYABLE" in db.execute(
                "SELECT payload FROM chat_transcript WHERE run_id=?", ("a" * 32,),
            ).fetchone()[0]
    finally:
        manager.close()
