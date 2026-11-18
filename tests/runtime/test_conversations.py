"""Independent execution, scoped persistence, migration and host-wide draining."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import sqlite3
from threading import Barrier, Event
from uuid import uuid4

import pytest

from runtime.events import RunInfo
from runtime.persistence import PersistenceError, RuntimeStore
from runtime.service import RuntimeBusyError
from runtime.wire import public_frame
from tests.runtime.conversation_helpers import make_manager
from tests.runtime_helpers import make_runtime


def submit(manager, identity, text):
    return manager.execute(identity, "submit", {"text": text})


def finish(manager, identity, text="hello"):
    submit(manager, identity, text)
    runtime = manager.get(identity)
    assert runtime.wait_for_idle(3)
    assert runtime.snapshot().run.status == "completed"


def test_two_chats_really_run_at_once_and_keep_independent_context(tmp_path):
    manager, agents = make_manager(tmp_path)
    first = manager.default_chat_id
    second = manager.new_chat()
    started = {first: Event(), second: Event()}
    release = Event()

    def behavior(identity):
        def step(text):
            started[identity].set()
            assert release.wait(5)
            return f"{identity}: {text}"
        return step

    try:
        for identity in (first, second):
            agents[identity].behavior = behavior(identity)
            submit(manager, identity, f"task for {identity}")
        assert all(event.wait(2) for event in started.values())
        assert all(manager.get(identity).snapshot().processing for identity in started)
        assert agents[first].llm is not agents[second].llm
        assert manager.get(first).state.edit_store is not manager.get(second).state.edit_store
        assert manager.get(first).state.privileged_turn is not manager.get(second).state.privileged_turn
        with pytest.raises(RuntimeBusyError):
            submit(manager, first, "same chat must not race")
        third = manager.new_chat(source_id=first)
        assert third not in (first, second)
    finally:
        release.set()
        manager.close()
    for identity, other in ((first, second), (second, first)):
        assert any(f"task for {identity}" == m.get("content") for m in agents[identity].messages)
        assert not any(f"task for {other}" == m.get("content") for m in agents[identity].messages)


def test_parallel_limit_is_host_wide_but_idle_chats_remain_accessible(tmp_path):
    manager, agents = make_manager(tmp_path, max_parallel_runs=1)
    first = manager.default_chat_id
    release = Event()
    agents[first].behavior = lambda text: "done" if release.wait(5) else "timeout"
    try:
        submit(manager, first, "hold")
        second = manager.new_chat(source_id=first)
        with pytest.raises(RuntimeBusyError, match="parallel-run limit"):
            submit(manager, second, "wait")
        assert manager.get(second).snapshot().run is None
        release.set()
        assert manager.get(first).wait_for_idle(2)
        finish(manager, second)
    finally:
        release.set()
        manager.close()


def test_selecting_live_chat_never_rebuilds_context_or_changes_other_settings(tmp_path):
    manager, agents = make_manager(tmp_path)
    first = manager.default_chat_id
    try:
        finish(manager, first)
        agents[first].messages.append({"role": "tool", "content": "live tool context"})
        context = deepcopy(agents[first].messages)
        manager.execute(first, "set_model_setting", {"key": "include_diff", "value": True})
        child = tmp_path / "child"
        child.mkdir()
        manager.execute(first, "change_directory", {"path": str(child)})
        second = manager.new_chat(source_id=first)
        assert manager.get(second).state.cwd == child
        assert manager.get(second).state.model_settings.include_diff is True
        manager.execute(second, "set_model_setting", {"key": "include_diff", "value": False})
        assert manager.get(first).state.model_settings.include_diff is True
        assert manager.execute(second, "load_chat", {"session_id": first}) == first
        assert agents[first].messages == context
        assert manager.get(second).state.chat_session_id == second
        manager.execute(second, "reset_context", {})
        assert agents[first].messages == context
    finally:
        manager.close()


def test_old_history_is_hydrated_once_and_only_explicit_reload_trims_context(tmp_path):
    manager, agents = make_manager(tmp_path)
    try:
        identity = manager.history.new_session()
        for index in range(40):
            manager.history.append_turn(session_id=identity, user_text=f"u{index}", assistant_text=f"a{index}")
        runtime = manager.get(identity)
        assert len(agents[identity].messages) == 65
        agents[identity].messages.append({"role": "tool", "content": "keep until reload"})
        assert manager.get(identity) is runtime
        assert agents[identity].messages[-1]["content"] == "keep until reload"
        manager.execute(identity, "reload_context", {})
        assert len(agents[identity].messages) == 65
        assert agents[identity].messages[1]["content"] == "u8"
        assert not any(m.get("content") == "keep until reload" for m in agents[identity].messages)
    finally:
        manager.close()


def test_every_chat_and_overlapping_proposal_ids_survive_restart(tmp_path):
    manager, agents = make_manager(tmp_path, durable=True)
    first = manager.default_chat_id
    second = manager.new_chat()
    for identity in (first, second):
        finish(manager, identity, identity)
        runtime = manager.get(identity)
        runtime.state.edit_store.propose_create(tmp_path / f"{identity}.txt", identity)
    manager.execute(first, "set_model_setting", {"key": "openai_flex", "value": True})
    contexts = {identity: deepcopy(agent.messages[1:]) for identity, agent in agents.items()}
    manager.close()
    restored, restored_agents = make_manager(tmp_path, durable=True)
    try:
        assert restored.default_chat_id == first
        assert set(restored.activity()) == {first, second}
        for identity in (first, second):
            runtime = restored.get(identity)
            assert restored_agents[identity].messages[1:] == contexts[identity]
            assert runtime.pending()[1].new_content == identity
            assert runtime.state.privileged_turn.status == "disabled"
        assert restored.get(first).state.model_settings.openai_flex is True
        assert restored.get(second).state.model_settings.openai_flex is False
        frame = public_frame(restored.get(first), uuid4().hex)
        restored.execute(first, "decide_pending", {"identity": 1, "accept": True,
                                                  "revision": frame["pending"][0]["revision"]})
        assert (tmp_path / f"{first}.txt").read_text(encoding="utf-8") == first
        assert 1 in restored.get(second).pending()
        assert not (tmp_path / f"{second}.txt").exists()
    finally:
        restored.close()


def test_identical_proposals_have_chat_bound_revisions_and_conflicts_revalidate(tmp_path):
    target = tmp_path / "shared.txt"
    target.write_text("original", encoding="utf-8")
    manager, _ = make_manager(tmp_path)
    first, second = manager.default_chat_id, manager.new_chat()
    try:
        for identity in (first, second):
            manager.get(identity).state.edit_store.propose_replace(target, "replacement")
        frames = {identity: public_frame(manager.get(identity), "a" * 32) for identity in (first, second)}
        first_revision = frames[first]["pending"][0]["revision"]
        second_revision = frames[second]["pending"][0]["revision"]
        assert first_revision != second_revision
        with pytest.raises(ValueError, match="changed"):
            manager.execute(second, "decide_pending", {"identity": 1, "accept": True, "revision": first_revision})
        assert target.read_text(encoding="utf-8") == "original"
        manager.execute(first, "decide_pending", {"identity": 1, "accept": True, "revision": first_revision})
        with pytest.raises(ValueError, match="stale"):
            manager.execute(second, "decide_pending", {"identity": 1, "accept": True, "revision": second_revision})
        assert target.read_text(encoding="utf-8") == "replacement"
        assert manager.get(first)._file_decision_lock is manager.get(second)._file_decision_lock
    finally:
        manager.close()


def test_single_chat_database_migrates_context_proposals_and_execution_evidence(tmp_path):
    legacy, agent = make_runtime(tmp_path, persistence_path=tmp_path / "state.sqlite3")
    legacy.submit("legacy completed")
    assert legacy.wait_for_idle(2)
    identity = legacy.state.chat_session_id
    context = deepcopy(agent.messages[1:])
    legacy.state.edit_store.propose_create(tmp_path / "legacy.txt", "pending")
    legacy._store.execution("tool", "run", {"status": "success", "observation": "already done"})
    legacy.close()
    manager, agents = make_manager(tmp_path, durable=True)
    try:
        assert manager.default_chat_id == identity
        assert agents[identity].messages[1:] == context
        assert manager.get(identity).pending()[1].new_content == "pending"
        assert manager.get(identity)._store.recover_executions("run")[0]["observation"] == "already done"
        with manager.storage.root.transaction() as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == 3
            assert db.execute("SELECT count(*) FROM checkpoint").fetchone()[0] == 0
            assert db.execute("SELECT count(*) FROM proposals").fetchone()[0] == 0
    finally:
        manager.close()


def test_each_interrupted_chat_recovers_its_own_tool_evidence_without_retry(tmp_path):
    manager, _ = make_manager(tmp_path, durable=True)
    identities = [manager.default_chat_id, manager.new_chat()]
    for identity in identities:
        finish(manager, identity, "safe")
        runtime = manager.get(identity)
        runtime._run = RunInfo(uuid4().hex, f"interrupted {identity}")
        runtime._message("You", f"interrupted {identity}")
        runtime._on_execution("tool_started", {"id": "same-tool-id", "tool": identity, "status": "running"})
    manager.close()
    restored, agents = make_manager(tmp_path, durable=True)
    try:
        for identity in identities:
            runtime = restored.get(identity)
            assert runtime.snapshot().run.status == "interrupted"
            evidence = runtime._store.recover_executions(runtime.snapshot().run.run_id)
            assert len(evidence) == 1 and evidence[0]["tool"] == identity
            assert evidence[0]["status"] == "outcome_unknown"
            assert identity in agents[identity].messages[-1]["content"]
            assert all(other not in agents[identity].messages[-1]["content"] for other in identities if other != identity)
    finally:
        restored.close()


def test_corrupt_chat_refuses_startup_without_rewriting_any_checkpoint(tmp_path):
    manager, _ = make_manager(tmp_path, durable=True)
    first, second = manager.default_chat_id, manager.new_chat()
    finish(manager, first)
    manager.close()
    with sqlite3.connect(tmp_path / "state.sqlite3") as db:
        db.execute("UPDATE chat_checkpoints SET payload='{}' WHERE chat_id=?", (second,))
        before = db.execute("SELECT chat_id,payload FROM chat_checkpoints ORDER BY chat_id").fetchall()
    with pytest.raises(PersistenceError):
        make_manager(tmp_path, durable=True)
    with sqlite3.connect(tmp_path / "state.sqlite3") as db:
        assert db.execute("SELECT chat_id,payload FROM chat_checkpoints ORDER BY chat_id").fetchall() == before
    store = RuntimeStore(tmp_path / "state.sqlite3")
    store.close()


def test_one_storage_failure_prevents_work_in_other_chats(tmp_path):
    manager, _ = make_manager(tmp_path, durable=True)
    first, second = manager.default_chat_id, manager.new_chat()
    try:
        with manager.storage.root.transaction() as db:
            db.execute("CREATE TRIGGER deny_checkpoint BEFORE INSERT ON chat_checkpoints BEGIN SELECT RAISE(ABORT,'offline storage failure'); END")
        with pytest.raises(PersistenceError):
            manager.execute(first, "set_model_setting", {"key": "openai_flex", "value": True})
        with pytest.raises(PersistenceError):
            submit(manager, second, "must not run with unhealthy persistence")
        assert manager.get(second).snapshot().run is None
    finally:
        manager.close()


def test_restart_checks_background_runs_and_all_chat_revisions(tmp_path):
    manager, agents = make_manager(tmp_path)
    first, second = manager.default_chat_id, manager.new_chat()
    release = Event()
    agents[second].behavior = lambda text: "done" if release.wait(5) else "timeout"
    try:
        reviewed = manager.maintenance_status()["sequence"]
        submit(manager, second, "background")
        with pytest.raises(RuntimeBusyError):
            manager.prepare_restart(reviewed)
        release.set()
        assert manager.get(second).wait_for_idle(2)
        with pytest.raises(ValueError, match="changed"):
            manager.prepare_restart(reviewed)
        reviewed = manager.maintenance_status()["sequence"]
        manager.get(first).state.edit_store.propose_create(tmp_path / "new.txt", "pending")
        with pytest.raises(ValueError, match="changed"):
            manager.prepare_restart(reviewed)
        status = manager.maintenance_status()
        assert status["pending_count"] == 1
        manager.prepare_restart(status["sequence"])
        with pytest.raises(RuntimeError, match="closed"):
            submit(manager, first, "blocked")
        with pytest.raises(RuntimeError, match="closed"):
            manager.new_chat()
        assert all(manager.get(identity).snapshot().closed for identity in (first, second))
    finally:
        release.set()
        manager.close()


def test_submit_in_any_chat_and_host_drain_are_atomic(tmp_path):
    manager, agents = make_manager(tmp_path)
    identity = manager.new_chat()
    release, barrier = Event(), Barrier(2)
    agents[identity].behavior = lambda text: "done" if release.wait(5) else "timeout"
    sequence = manager.maintenance_status()["sequence"]

    def start():
        barrier.wait(2)
        try:
            submit(manager, identity, "race")
            return "submitted"
        except RuntimeError:
            return "closed"

    def drain():
        barrier.wait(2)
        try:
            manager.prepare_restart(sequence)
            return "drained"
        except RuntimeBusyError:
            return "busy"

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            a, b = pool.submit(start), pool.submit(drain)
            assert (a.result(), b.result()) in {("submitted", "busy"), ("closed", "drained")}
    finally:
        release.set()
        manager.close()


@pytest.mark.parametrize("identity", ["", "../state", "A" * 32, "x" * 32])
def test_invalid_chat_ids_are_never_used_as_storage_or_execution_targets(tmp_path, identity):
    manager, _ = make_manager(tmp_path)
    try:
        with pytest.raises(ValueError):
            manager.get(identity)
    finally:
        manager.close()
