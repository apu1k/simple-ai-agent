"""Real SQLite failure injection; no live runtime data or real tools are used."""
from dataclasses import replace
import sqlite3

import pytest

from core.agent import Agent
from core.tool_registry import ToolRegistry, ToolSpec
from runtime.events import RunInfo
from runtime.persistence import PersistenceError, RuntimeStore
from tests.runtime_helpers import make_runtime


def durable(tmp_path):
    return make_runtime(tmp_path, persistence_path=tmp_path / "state.sqlite3")


def deny_insert(store, table):
    assert table in {"checkpoint", "proposals", "executions"}
    with store.transaction() as db:
        db.execute(f"CREATE TRIGGER deny_write BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT, 'offline injected storage failure'); END")


def test_checkpoint_failure_refuses_new_work_and_close_still_releases_writer(tmp_path):
    runtime, _ = durable(tmp_path)
    deny_insert(runtime._store, "checkpoint")
    with pytest.raises(PersistenceError):
        runtime.set_model_setting("openai_flex", True)
    assert runtime.snapshot().closed
    with pytest.raises(PersistenceError):
        runtime.submit("must not start")
    runtime.close()
    path = tmp_path / "state.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("DROP TRIGGER deny_write")
    restored, _ = durable(tmp_path)
    try:
        assert restored.state.model_settings.openai_flex is False
        assert not restored.snapshot().closed
    finally:
        restored.close()


def test_filesystem_effect_does_not_begin_when_sqlite_rejects_approval_intent(tmp_path):
    runtime, _ = durable(tmp_path)
    proposal, _ = runtime.state.edit_store.propose_create(tmp_path / "no-effect.txt", "no")
    deny_insert(runtime._store, "proposals")
    with pytest.raises(PersistenceError):
        runtime.decide_pending(proposal.id, accept=True)
    assert not proposal.path.exists()
    with pytest.raises(PersistenceError):
        runtime.submit("storage is unhealthy")
    runtime.close()  # Must not mask the failure with a shutdown exception/lease leak.
    store = RuntimeStore(tmp_path / "state.sqlite3")
    try:
        assert store.recover_proposals()[0].status == "pending"
    finally:
        store.close()


def test_tool_effect_does_not_begin_when_sqlite_rejects_execution_intent(tmp_path):
    runtime, _ = durable(tmp_path)
    effects, registry = [], ToolRegistry()
    registry.register(ToolSpec("effect", lambda: effects.append("must not happen"), "offline", {}))
    agent = Agent("offline", runtime.state, runtime.llm, tool_registry=registry, on_execution=runtime._on_execution)
    runtime._run = RunInfo("f" * 32, "offline")
    deny_insert(runtime._store, "executions")
    with pytest.raises(PersistenceError):
        agent._execute_one_tool_call("effect", {})
    assert not effects
    runtime.close()
    store = RuntimeStore(tmp_path / "state.sqlite3")
    store.close()


def test_unavailable_saved_provider_does_not_silently_start_with_a_different_model(tmp_path):
    runtime, _ = durable(tmp_path)
    runtime.state.model_config = replace(runtime.state.model_config, provider_key="removed-recovery-test-provider")
    runtime.set_model_setting("openai_flex", False)
    runtime.close()
    with pytest.raises(PersistenceError, match="Saved provider is unavailable"):
        durable(tmp_path)
    store = RuntimeStore(tmp_path / "state.sqlite3")
    try:
        assert store.load()["model"]["provider_key"] == "removed-recovery-test-provider"
    finally:
        store.close()


def test_non_json_proposal_cannot_be_returned_as_a_durable_success(tmp_path):
    runtime, _ = durable(tmp_path)
    # Simulates a buggy custom proposal rather than provider-supplied JSON.
    proposal, _ = runtime.state.edit_store.propose_create(tmp_path / "pending.txt", "pending")
    proposal.new_content = object()
    with pytest.raises(PersistenceError):
        runtime._store.save_proposal(proposal)
    assert not proposal.path.exists()
    with pytest.raises(PersistenceError):
        runtime.submit("no new work")
    runtime.close()
