"""Restart checkpoints, write-ahead execution, and fail-closed storage tests."""
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from core.agent import Agent
from core.tool_registry import ToolRegistry, ToolSpec
from llm.base import LLMResponse, NativeToolCall
from llm.openai_responses import OpenAIResponsesClient
from llm.providers import ProviderConfig
from runtime.events import RunInfo
from runtime.persistence import PersistenceError, RuntimeStore
from runtime.server import create_server
from runtime.service import AgentRuntime
from tests.runtime_helpers import make_runtime

TOKEN = "offline-recovery-token-" + "x" * 32
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


def durable(tmp_path, **kwargs):
    return make_runtime(tmp_path, persistence_path=tmp_path / "state.sqlite3", **kwargs)


def completed(runtime, text="hello"):
    runtime.submit(text)
    assert runtime.wait_for_idle(5)
    assert runtime.snapshot().run.status == "completed"


def test_completed_state_events_settings_and_proposals_survive_restart(tmp_path):
    runtime, agent = durable(tmp_path)
    runtime.state.model_config.api_key = "CREDENTIAL_MUST_NOT_BE_SAVED"
    completed(runtime)
    session, context = runtime.state.chat_session_id, list(agent.messages[1:])
    proposal, _ = runtime.state.edit_store.propose_create(tmp_path / "created.txt", "approved later")
    runtime.set_model_setting("include_diff", "model")
    runtime.set_model_setting("openai_flex", True)
    runtime.set_model_setting("openai_reasoning_effort", "high")
    runtime.set_model_setting("anthropic_reasoning_effort", "xhigh")
    approver = runtime.attach_client(can_approve=True)
    runtime.set_model_setting("elevated_commands", True, client_id=approver)
    cursor = runtime.snapshot().sequence
    runtime.close()
    restored, agent = durable(tmp_path)
    try:
        assert restored.state.chat_session_id == session
        assert agent.messages[1:] == context
        assert restored.snapshot().run.reply == "answer: hello"
        assert not restored.snapshot().closed and not restored.snapshot().processing
        assert restored.state.model_settings.include_diff == "model"
        assert restored.state.model_settings.openai_flex is True
        assert restored.state.model_settings.openai_reasoning_effort == "high"
        assert restored.state.model_settings.anthropic_reasoning_effort == "xhigh"
        assert restored.state.privileged_turn.status == "disabled"
        assert restored.events_since(cursor)
        assert restored.snapshot().sequence > cursor
        assert restored.pending()[proposal.id].new_content == "approved later"
        assert not proposal.path.exists()
        payload = json.dumps(restored._store.load())
        assert "CREDENTIAL_MUST_NOT_BE_SAVED" not in payload and "api_key" not in payload
        restored.decide_pending(proposal.id, accept=True)
        assert proposal.path.read_text(encoding="utf-8") == "approved later"
    finally:
        restored.close()
    again, _ = durable(tmp_path)
    try:
        assert not again.pending()
        second, _ = again.state.edit_store.propose_create(tmp_path / "second.txt", "second")
        assert second.id > proposal.id
    finally:
        again.close()


def test_rejected_ids_are_not_reused_and_approvals_revalidate_current_files(tmp_path):
    path = tmp_path / "original.txt"
    path.write_text("original", encoding="utf-8")
    runtime, _ = durable(tmp_path)
    first, _ = runtime.state.edit_store.propose_replace(path, "replacement")
    second, _ = runtime.state.edit_store.propose_create(tmp_path / "rejected.txt", "no")
    runtime.decide_pending(second.id, accept=False)
    runtime.close()
    path.write_text("externally modified", encoding="utf-8")
    restored, _ = durable(tmp_path)
    try:
        with pytest.raises(ValueError, match="stale"):
            restored.decide_pending(first.id, accept=True)
        assert path.read_text(encoding="utf-8") == "externally modified"
        assert restored.state.edit_store.get(first.id).status == "outcome_unknown"
        with pytest.raises(ValueError, match="outcome_unknown"):
            restored.decide_pending(first.id, accept=True)
        third, _ = restored.state.edit_store.propose_create(tmp_path / "third.txt", "three")
        assert third.id > second.id
    finally:
        restored.close()


def test_interrupted_approval_is_never_restored_as_pending(tmp_path):
    runtime, _ = durable(tmp_path)
    proposal, _ = runtime.state.edit_store.propose_create(tmp_path / "maybe.txt", "effect")
    runtime._store.save_proposal(replace(proposal, status="applying"))
    proposal.path.write_text("effect", encoding="utf-8")
    runtime.close()
    restored, _ = durable(tmp_path)
    try:
        assert proposal.id not in restored.pending()
        assert restored.state.edit_store.get(proposal.id).status == "outcome_unknown"
        assert any("Proposal #1 has outcome UNKNOWN" in text for _, text in restored.snapshot().messages)
        with pytest.raises(ValueError, match="outcome_unknown"):
            restored.decide_pending(proposal.id, accept=True)
        assert proposal.path.read_text(encoding="utf-8") == "effect"
    finally:
        restored.close()


def test_interrupted_run_retains_evidence_without_reexecuting_or_restoring_authority(tmp_path):
    runtime, _ = durable(tmp_path)
    completed(runtime, "safe boundary")
    runtime._run = RunInfo(run_id="a" * 32, user_text="interrupted request")
    runtime._message("You", "interrupted request")
    runtime._on_execution("tool_started", {
        "id": "b" * 32, "tool": "fixture_command", "arguments": {"label": "scratch only"}, "status": "running",
    })
    session = runtime.state.chat_session_id
    runtime.close()
    restored, agent = durable(tmp_path)
    try:
        assert restored.state.chat_session_id == session
        assert restored.snapshot().run.status == "interrupted" and not restored.snapshot().processing
        assert restored._store.recover_executions("a" * 32)[0]["status"] == "outcome_unknown"
        assert "interrupted request" in agent.messages[-1]["content"]
        assert "not a request to execute" in agent.messages[-1]["content"]
        assert "outcome_unknown" in agent.messages[-1]["content"]
        assert "external processes may still be running" in restored.snapshot().run.error
        assert restored.state.privileged_turn.status == "disabled"
        first_sequence = restored.snapshot().sequence
    finally:
        restored.close()
    again, _ = durable(tmp_path)
    try:
        assert again.snapshot().run.status == "interrupted" and not again.snapshot().processing
        assert again.snapshot().sequence > first_sequence
        assert len(again.state.chat_store.load_original_turns(session)) == 1
    finally:
        again.close()


def test_completed_reply_before_history_export_is_recovered_not_repeated(tmp_path):
    runtime, _ = durable(tmp_path)
    runtime.new_chat()
    runtime._run = RunInfo(run_id="c" * 32, user_text="accepted", reply="saved before export")
    runtime._message("You", "accepted")
    runtime.close()
    restored, _ = durable(tmp_path)
    try:
        assert restored.snapshot().run.status == "interrupted"
        assert ("AI", "saved before export") in restored.snapshot().messages
        assert "history export may be incomplete" in restored.snapshot().run.error
    finally:
        restored.close()


@pytest.mark.parametrize("operation", ["reset", "reload", "new"])
def test_explicit_context_boundaries_survive_restart(tmp_path, operation):
    runtime, agent = durable(tmp_path)
    completed(runtime, "old turn")
    if operation == "reset":
        runtime.reset_context()
    elif operation == "reload":
        agent.messages.append({"role": "user", "content": "not a final turn"})
        runtime.reload_context()
    else:
        runtime.new_chat()
    expected, session = list(agent.messages[1:]), runtime.state.chat_session_id
    runtime.close()
    restored, agent = durable(tmp_path)
    try:
        assert agent.messages[1:] == expected and restored.state.chat_session_id == session
    finally:
        restored.close()


def test_missing_saved_cwd_falls_back_without_changing_process_cwd(tmp_path):
    child = tmp_path / "removed"
    child.mkdir()
    runtime, _ = durable(tmp_path)
    runtime.change_directory(str(child))
    runtime.close()
    child.rmdir()
    original_cwd = Path.cwd()
    restored, _ = durable(tmp_path)
    try:
        assert restored.state.cwd == tmp_path and Path.cwd() == original_cwd
        assert any("Current directory was removed" in text for _, text in restored.snapshot().messages)
    finally:
        restored.close()


def test_store_lease_and_unknown_schema_fail_without_overwriting(tmp_path):
    path = tmp_path / "state.sqlite3"
    store = RuntimeStore(path)
    try:
        with pytest.raises(PersistenceError, match="another backend"):
            RuntimeStore(path)
        store.save({"keep": "original"})
    finally:
        store.close()
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA user_version=999")
    with pytest.raises(PersistenceError, match="Unsupported"):
        RuntimeStore(path)
    with sqlite3.connect(path) as db:
        assert json.loads(db.execute("SELECT payload FROM checkpoint").fetchone()[0]) == {"keep": "original"}


def test_corrupt_checkpoint_fails_closed_and_releases_lease(tmp_path):
    runtime, _ = durable(tmp_path)
    completed(runtime)
    runtime.close()
    path = tmp_path / "state.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("UPDATE checkpoint SET payload='not-json'")
    with pytest.raises(PersistenceError):
        durable(tmp_path)
    store = RuntimeStore(path)
    store.close()


def test_no_tool_or_filesystem_dispatch_if_intent_cannot_be_saved(tmp_path, monkeypatch):
    runtime, _ = durable(tmp_path)
    proposal, _ = runtime.state.edit_store.propose_create(tmp_path / "not-created.txt", "must not apply")
    calls = []
    registry = ToolRegistry()
    registry.register(ToolSpec("effect", lambda: calls.append("effect"), "scratch", {}))
    agent = Agent("offline", runtime.state, runtime.llm, tool_registry=registry, on_execution=runtime._on_execution)

    def fail(*args):
        raise PersistenceError("offline storage failure")

    try:
        runtime._run = RunInfo("d" * 32, "no effect")
        monkeypatch.setattr(runtime._store, "execution", fail)
        with pytest.raises(PersistenceError):
            agent._execute_one_tool_call("effect", {})
        assert not calls
        runtime.state.edit_store._save_proposal = fail
        with pytest.raises(PersistenceError):
            runtime.decide_pending(proposal.id, accept=True)
        assert not proposal.path.exists()
    finally:
        runtime.close()


def test_real_agent_tool_evidence_commits_before_effect_and_after_result(tmp_path):
    fixture, _ = make_runtime(tmp_path)
    state = fixture.state
    fixture.close()
    registry, holder = ToolRegistry(), {}

    def effect():
        runtime = holder["runtime"]
        with runtime._store.transaction() as db:
            payload = db.execute("SELECT payload FROM executions WHERE run_id=?", (runtime.snapshot().run.run_id,)).fetchone()[0]
        assert json.loads(payload)["status"] == "running"
        return "observed once"

    registry.register(ToolSpec("effect", effect, "offline test", {}))

    class FakeLLM:
        supports_native_tools = True
        api_type = "chat_completions"
        calls = 0

        def chat(self, messages, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return LLMResponse(None, [NativeToolCall("offline-call", "effect", {})])
            return "done"

    llm = FakeLLM()
    runtime = AgentRuntime(state=state, llm=llm, persistence_path=tmp_path / "state.sqlite3",
                           agent_factory=lambda **kwargs: Agent("offline", tool_registry=registry, **kwargs))
    holder["runtime"] = runtime
    try:
        completed(runtime)
        records = runtime._store.recover_executions(runtime.snapshot().run.run_id)
        assert len(records) == 1 and records[0]["status"] == "success"
        assert records[0]["observation"] == "observed once" and llm.calls == 2
        assert any(event.kind == "tool_finished" for event in runtime.events_since(0))
    finally:
        runtime.close()


def responses_runtime(tmp_path, calls):
    fixture, _ = make_runtime(tmp_path)
    state = fixture.state
    fixture.close()
    state.model_config = replace(state.model_config, api_type="responses", model="offline-model")
    client = OpenAIResponsesClient(ProviderConfig(
        key="fixture", label="Fixture", api_key="offline-key", base_url=None,
        api_type="responses", default_model="offline-model", supports_model_listing=False,
    ))

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(id=f"resp_{len(calls)}", output=[], output_text="offline reply")

    client._client = SimpleNamespace(responses=SimpleNamespace(create=create))
    runtime = AgentRuntime(state=state, llm=client, persistence_path=tmp_path / "state.sqlite3",
                           agent_factory=lambda **kwargs: Agent("offline", tool_registry=ToolRegistry(), **kwargs))
    runtime.initialize()
    return runtime, client


def test_responses_continuation_survives_only_coherent_checkpoint_and_reload_stays_fresh(tmp_path):
    calls = []
    runtime, client = responses_runtime(tmp_path, calls)
    completed(runtime, "first")
    assert client._last_response_id == "resp_1"
    runtime.close()
    restored, client = responses_runtime(tmp_path, calls)
    try:
        assert len(calls) == 1
        completed(restored, "follow up")
        assert calls[-1]["previous_response_id"] == "resp_1"
        restored.reload_context()
    finally:
        restored.close()
    fresh, client = responses_runtime(tmp_path, calls)
    try:
        completed(fresh, "clean follow up")
        assert "previous_response_id" not in calls[-1]
        assert any(item.get("content") == "first" for item in calls[-1]["input"])
    finally:
        fresh.close()


def test_response_continuation_endpoint_change_rejects_restore_without_request():
    client = OpenAIResponsesClient(ProviderConfig(
        key="fixture", label="Fixture", api_key="offline", base_url=None,
        api_type="responses", default_model="offline-model", supports_model_listing=False,
    ))
    saved = client.export_conversation()
    with pytest.raises(ValueError, match="endpoint/model"):
        client.restore_conversation(dict(saved, endpoint="different"))
    assert client._last_response_id is None


def test_interrupted_responses_chain_is_not_restored(tmp_path):
    calls = []
    runtime, client = responses_runtime(tmp_path, calls)
    completed(runtime, "last safe turn")
    runtime._run = RunInfo("e" * 32, "incomplete request")
    runtime._message("You", "incomplete request")
    runtime.close()
    restored, client = responses_runtime(tmp_path, calls)
    try:
        assert client._last_response_id is None and len(calls) == 1
        assert restored.snapshot().run.status == "interrupted"
        completed(restored, "inspect only, do not retry")
        assert "previous_response_id" not in calls[-1]
    finally:
        restored.close()


def test_restart_changes_server_epoch_and_restored_proposal_requires_new_review(tmp_path):
    runtime, _ = durable(tmp_path)
    runtime.state.edit_store.propose_create(tmp_path / "reviewed.txt", "review again")
    with TestClient(create_server(runtime, token=TOKEN), headers=HEADERS, base_url="http://127.0.0.1") as first:
        old = first.get("/v1/snapshot").json()
    restored, _ = durable(tmp_path)
    with TestClient(create_server(restored, token=TOKEN), headers=HEADERS, base_url="http://127.0.0.1") as second:
        new = second.get("/v1/snapshot").json()
        assert new["server_id"] != old["server_id"] and new["pending"] == old["pending"]
        assert second.get("/v1/maintenance").status_code == 403
        decision = {"request_id": uuid4().hex, "server_id": old["server_id"],
                    "operation": "decide_pending", "arguments": {
                        "identity": old["pending"][0]["id"], "accept": True,
                        "revision": old["pending"][0]["revision"],
                    }}
        assert second.post("/v1/commands", json=decision).status_code == 409
        assert not (tmp_path / "reviewed.txt").exists()
        decision.update(request_id=uuid4().hex, server_id=new["server_id"])
        assert second.post("/v1/commands", json=decision).status_code == 200
        assert second.post("/v1/commands", json=decision).status_code == 200
