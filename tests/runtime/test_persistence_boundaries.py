"""Malformed checkpoints and restart boundary regressions; disposable data only."""
from copy import deepcopy
from dataclasses import replace
import json
import sqlite3
from types import SimpleNamespace

import pytest

from runtime.events import RunInfo
from runtime.persistence import PersistenceError, RuntimeStore
from tests.runtime_helpers import make_runtime


def durable(tmp_path):
    return make_runtime(tmp_path, persistence_path=tmp_path / "state.sqlite3")


def seed(tmp_path):
    runtime, _ = durable(tmp_path)
    runtime.submit("safe turn")
    assert runtime.wait_for_idle(5)
    runtime.close()


def rewrite(tmp_path, transform):
    with sqlite3.connect(tmp_path / "state.sqlite3") as db:
        saved = json.loads(db.execute("SELECT payload FROM checkpoint WHERE id=1").fetchone()[0])
        payload = json.dumps(transform(saved))
        db.execute("UPDATE checkpoint SET payload=? WHERE id=1", (payload,))
    return payload


def assert_not_discarded(tmp_path, payload):
    with sqlite3.connect(tmp_path / "state.sqlite3") as db:
        assert db.execute("SELECT payload FROM checkpoint WHERE id=1").fetchone()[0] == payload
    store = RuntimeStore(tmp_path / "state.sqlite3")
    store.close()


@pytest.mark.parametrize("malformed", [None, [], {}, {"version": 1}])
def test_valid_json_that_is_not_a_checkpoint_cannot_be_silently_reinitialized(tmp_path, malformed):
    seed(tmp_path)
    payload = rewrite(tmp_path, lambda saved: malformed)
    with pytest.raises(PersistenceError):
        durable(tmp_path)
    assert_not_discarded(tmp_path, payload)


def test_pre_anthropic_checkpoint_gets_default_effort(tmp_path):
    seed(tmp_path)

    def omit_effort(saved):
        del saved["model_settings"]["anthropic_reasoning_effort"]
        return saved

    rewrite(tmp_path, omit_effort)
    runtime, _ = durable(tmp_path)
    try:
        assert runtime.state.model_settings.anthropic_reasoning_effort is None
        assert runtime.snapshot().run.reply == "answer: safe turn"
    finally:
        runtime.close()


def break_field(saved, field):
    if field == "run_status":
        saved["run"]["status"] = "not-a-real-status"
    elif field == "sequence":
        saved["sequence"] = True
    elif field == "event_gap":
        saved["events"][-1]["sequence"] += 1
    elif field == "transcript":
        saved["context"]["messages"] = [{"role": "unexpected-role", "content": "bad"}]
    elif field == "settings":
        saved["model_settings"]["openai_flex"] = "yes"
    elif field == "anthropic_effort":
        saved["model_settings"]["anthropic_reasoning_effort"] = "none"
    elif field == "session":
        saved["chat_session_id"] = "not-a-session"
    return saved


@pytest.mark.parametrize("field", [
    "run_status", "sequence", "event_gap", "transcript", "settings", "anthropic_effort", "session",
])
def test_malformed_state_fields_fail_before_any_recovery_write(tmp_path, field):
    seed(tmp_path)
    payload = rewrite(tmp_path, lambda saved: break_field(saved, field))
    with pytest.raises(PersistenceError):
        durable(tmp_path)
    assert_not_discarded(tmp_path, payload)


@pytest.mark.parametrize("boundary", ["reset", "model_switch"])
def test_intentional_context_boundary_is_not_reported_as_a_failed_turn(tmp_path, monkeypatch, boundary):
    runtime, _ = durable(tmp_path)
    runtime.submit("completed turn")
    assert runtime.wait_for_idle(5)
    if boundary == "reset":
        runtime.reset_context()
    else:
        config = replace(runtime.state.model_config, model="other-offline-model")
        provider = SimpleNamespace(api_type="chat_completions")
        monkeypatch.setitem(runtime.providers, "fixture", provider)
        monkeypatch.setattr("runtime.service.build_model_config_and_client", lambda *args: (config, runtime.llm))
        runtime.switch_model("fixture", config.model)
    runtime.close()
    restored, _ = durable(tmp_path)
    try:
        assert not any("failed/incomplete turn" in text for _, text in restored.snapshot().messages)
        if boundary == "model_switch":
            assert restored.state.model_config.model == "other-offline-model"
    finally:
        restored.close()


def test_recovered_run_and_warnings_are_committed_in_one_checkpoint(tmp_path, monkeypatch):
    runtime, _ = durable(tmp_path)
    runtime._run = RunInfo("a" * 32, "interrupted input")
    runtime._message("You", "interrupted input")
    runtime.close()
    checkpoints = []
    save = RuntimeStore.save

    def observed_save(self, checkpoint):
        checkpoints.append(deepcopy(checkpoint))
        save(self, checkpoint)

    monkeypatch.setattr(RuntimeStore, "save", observed_save)
    restored, _ = durable(tmp_path)
    try:
        assert len(checkpoints) == 1
        checkpoint = checkpoints[0]
        assert checkpoint["run"]["status"] == "interrupted"
        assert any("Nothing was automatically retried" in text for _, text in checkpoint["messages"])
        assert "RECOVERY NOTICE" in checkpoint["context"]["messages"][-1]["content"]
    finally:
        restored.close()
