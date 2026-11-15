from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, replace
from threading import Barrier, Event
from types import SimpleNamespace

import pytest

from core.tool_progress import approval_ui_available
from llm.request_progress import notify_request_retry
from runtime.elevated_commands import await_approval
from runtime.privileged_turn import ELEVATED_OPERATION
from runtime.service import EventHistoryExpired, RuntimeBusyError
from tests.runtime_helpers import make_runtime


def test_run_outlives_clients_and_reconnect_gets_history_and_ordered_events(tmp_path):
    runtime, agent = make_runtime(tmp_path)
    first = runtime.attach_client(can_approve=True)
    second = runtime.attach_client()
    started, release = Event(), Event()

    def step(text):
        started.set()
        assert release.wait(5)
        return "finished without a UI"

    agent.behavior = step
    try:
        run_id = runtime.submit("hello")
        assert started.wait(2)
        snapshot = runtime.snapshot()
        assert snapshot.processing
        assert snapshot.run.run_id == run_id
        assert snapshot.messages == (("You", "hello"),)
        runtime.detach_client(first)
        runtime.detach_client(second)
        assert runtime.snapshot().processing
        release.set()
        assert runtime.wait_for_idle(2)
        third = runtime.attach_client()
        events = runtime.events_since(snapshot.sequence)
        assert [e.sequence for e in events] == list(range(snapshot.sequence + 1, runtime.snapshot().sequence + 1))
        assert events == runtime.events_since(snapshot.sequence)
        assert all(e.run_id == run_id for e in events)
        assert runtime.snapshot().run.status == "completed"
        assert runtime.snapshot().messages[-1] == ("AI", "finished without a UI")
        turns = runtime.state.chat_store.load_original_turns(runtime.state.chat_session_id)
        assert [(t["user"], t["assistant_final"]) for t in turns] == [("hello", "finished without a UI")]
        runtime.detach_client(third)
    finally:
        release.set()
        runtime.close()


def test_busy_guard_is_server_side_for_all_context_mutations(tmp_path):
    runtime, agent = make_runtime(tmp_path)
    started, release = Event(), Event()

    def step(text):
        started.set()
        assert release.wait(5)
        return "done"

    agent.behavior = step
    try:
        runtime.submit("first")
        assert started.wait(2)
        operations = (
            lambda: runtime.submit("second"),
            runtime.new_chat,
            runtime.reset_context,
            lambda: runtime.load_chat("missing"),
            lambda: runtime.change_directory(".."),
            lambda: runtime.switch_model("missing", "missing"),
            lambda: runtime.set_model_setting("openai_flex", True),
        )
        for operation in operations:
            with pytest.raises(RuntimeBusyError):
                operation()
        runtime.set_model_setting("elevated_commands", False)
        assert runtime.snapshot().messages == (("You", "first"),)
    finally:
        release.set()
        runtime.close()


def test_concurrent_submissions_accept_only_one_message(tmp_path):
    runtime, agent = make_runtime(tmp_path)
    barrier, release = Barrier(2), Event()
    agent.behavior = lambda text: "done" if release.wait(5) else "fixture timed out"

    def submit(text):
        barrier.wait(timeout=2)
        try:
            return runtime.submit(text)
        except RuntimeBusyError:
            return None

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(submit, ("one", "two")))
        assert sum(result is not None for result in results) == 1
        assert len(runtime.snapshot().messages) == 1
    finally:
        release.set()
        runtime.close()


def test_replay_is_bounded_and_snapshot_and_events_are_immutable(tmp_path):
    runtime, _ = make_runtime(tmp_path, event_limit=2)
    try:
        runtime.submit("hello")
        assert runtime.wait_for_idle(2)
        with pytest.raises(EventHistoryExpired):
            runtime.events_since(0)
        snapshot = runtime.snapshot()
        assert snapshot.messages == (("You", "hello"), ("AI", "answer: hello"))
        assert runtime.events_since(snapshot.sequence) == ()
        event = runtime.events_since(snapshot.sequence - 1)[0]
        with pytest.raises(FrozenInstanceError):
            event.text = "changed"
        for cursor in (-1, snapshot.sequence + 1):
            with pytest.raises(ValueError):
                runtime.events_since(cursor)
    finally:
        runtime.close()


def test_worker_failure_is_visible_and_not_automatically_retried(tmp_path):
    runtime, agent = make_runtime(tmp_path)
    attempts = []

    def fail(text):
        attempts.append(text)
        raise RuntimeError("fixture tool outcome unknown")

    agent.behavior = fail
    try:
        runtime.submit("do not repeat")
        assert runtime.wait_for_idle(2)
        snapshot = runtime.snapshot()
        assert snapshot.run.status == "failed"
        assert snapshot.run.error == "fixture tool outcome unknown"
        assert snapshot.messages[-1] == ("Error", "fixture tool outcome unknown")
        assert attempts == ["do not repeat"]
        assert runtime.state.chat_store.load_original_turns(runtime.state.chat_session_id) == []
    finally:
        runtime.close()


def test_history_failure_does_not_lose_reply_and_is_visible_to_every_client(tmp_path):
    def fail_history(*args):
        raise OSError("fixture disk full")

    runtime, _ = make_runtime(tmp_path, history_recorder=fail_history)
    try:
        runtime.submit("hello")
        assert runtime.wait_for_idle(2)
        snapshot = runtime.snapshot()
        assert snapshot.run.status == "completed"
        assert any(role == "System" and "fixture disk full" in text for role, text in snapshot.messages)
        assert snapshot.messages[-1] == ("AI", "answer: hello")
    finally:
        runtime.close()


def test_headless_run_has_no_interactive_approval_context(tmp_path):
    runtime, agent = make_runtime(tmp_path)
    agent.behavior = lambda text: str(approval_ui_available())
    try:
        observer = runtime.attach_client()
        with pytest.raises(PermissionError):
            runtime.set_model_setting("elevated_commands", True, client_id=observer)
        runtime.submit("headless")
        assert runtime.wait_for_idle(2)
        assert runtime.snapshot().run.reply == "False"
    finally:
        runtime.close()


@pytest.mark.parametrize("keep_second_approver", [False, True])
def test_privilege_revokes_on_last_approver_disconnect_but_other_client_can_decide(
    tmp_path, keep_second_approver,
):
    runtime, agent = make_runtime(tmp_path)
    first = runtime.attach_client(can_approve=True)
    second = runtime.attach_client(can_approve=keep_second_approver)
    runtime.set_model_setting("elevated_commands", True, client_id=first)
    requested = Event()

    def step(text):
        gate = runtime.state.privileged_turn
        # await_approval emits the normal progress callback through StubAgent.
        claim = gate.claim(ELEVATED_OPERATION)
        original_submit = gate.submit

        def submit(*args):
            request = original_submit(*args)
            requested.set()
            return request

        gate.submit = submit
        try:
            request, decision = await_approval(gate, claim, {"script": "fixture only", "timeout": 1})
            if decision == "accepted":
                gate.require_accepted(request)
            return decision
        finally:
            gate.submit = original_submit

    agent.behavior = step
    try:
        runtime.submit("fixture only; no UAC")
        assert requested.wait(2)
        # Acquiring the service lock also waits for the callback to publish.
        pending = runtime.pending()
        assert len(pending) == 1
        identity = next(iter(pending))
        with pytest.raises(PermissionError):
            runtime.decide_pending(identity, accept=True)
        runtime.detach_client(first)
        if keep_second_approver:
            runtime.decide_pending(identity, accept=True, client_id=second)
            expected = "accepted"
        else:
            expected = "expired"
        assert runtime.wait_for_idle(2)
        assert runtime.snapshot().run.reply == expected
        assert not runtime.pending()
        with pytest.raises((ValueError, PermissionError)):
            runtime.decide_pending(identity, accept=True, client_id=second)
    finally:
        runtime.close(wait=False)
        assert runtime.wait_for_idle(2)


def test_pending_decisions_are_serialized_and_snapshots_cannot_modify_proposals(tmp_path):
    runtime, _ = make_runtime(tmp_path)
    path = tmp_path / "proposal.txt"
    proposal, _ = runtime.state.edit_store.propose_create(path, "approved content")
    runtime.pending()[proposal.id].new_content = "tampered client snapshot"
    barrier = Barrier(2)

    def decide(accept):
        barrier.wait(timeout=2)
        try:
            runtime.decide_pending(proposal.id, accept=accept)
            return True
        except ValueError:
            return False

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sum(pool.map(decide, (True, False))) == 1
        assert not runtime.pending()
        if path.exists():
            assert path.read_text(encoding="utf-8") == "approved content"
    finally:
        runtime.close()


def test_close_stops_accepting_work_without_claiming_to_cancel_active_tool(tmp_path):
    runtime, agent = make_runtime(tmp_path)
    started, release = Event(), Event()

    def step(text):
        started.set()
        assert release.wait(5)
        return "ordinary work completed"

    agent.behavior = step
    try:
        runtime.submit("first")
        assert started.wait(2)
        runtime.close(wait=False)
        assert runtime.snapshot().closed and runtime.snapshot().processing
        with pytest.raises(RuntimeError, match="closed"):
            runtime.submit("second")
        with pytest.raises(RuntimeError, match="closed"):
            runtime.attach_client()
        release.set()
        assert runtime.wait_for_idle(2)
        assert runtime.snapshot().run.reply == "ordinary work completed"
    finally:
        release.set()
        runtime.close()


def test_settings_model_switch_and_new_chat_preserve_expected_context_boundaries(tmp_path, monkeypatch):
    runtime, agent = make_runtime(tmp_path)
    try:
        runtime.submit("old context")
        assert runtime.wait_for_idle(2)
        previous_session = runtime.state.chat_session_id
        previous_messages = agent.messages[1:]
        runtime.set_model_setting("include_diff", "model")
        runtime.set_model_setting("openai_reasoning_effort", "high")
        for key, value in (("include_diff", "high"), ("openai_flex", None), ("openai_reasoning_effort", True)):
            with pytest.raises(ValueError):
                runtime.set_model_setting(key, value)
        assert runtime.state.model_settings.include_diff == "model"
        assert runtime.state.model_settings.openai_reasoning_effort == "high"
        config = replace(runtime.state.model_config, model="next-model")
        llm = SimpleNamespace(supports_native_tools=False)
        monkeypatch.setitem(__import__("llm.providers", fromlist=["PROVIDERS"]).PROVIDERS,
                            "fixture", SimpleNamespace(key="fixture"))
        monkeypatch.setattr("runtime.service.build_model_config_and_client", lambda *a: (config, llm))
        runtime.switch_model("fixture", "next-model")
        assert agent.messages[1:] == previous_messages
        assert runtime.llm is llm and agent.llm is llm
        assert runtime.state.model_config.model == "next-model"
        proposal, _ = runtime.state.edit_store.propose_create(tmp_path / "pending.txt", "pending")
        runtime.new_chat()
        assert runtime.state.chat_session_id != previous_session
        assert len(agent.messages) == 1
        assert proposal.id in runtime.pending()
        assert not (tmp_path / "pending.txt").exists()
    finally:
        runtime.close()


def test_failed_model_switch_restores_previous_runtime_bundle(tmp_path, monkeypatch):
    from llm.providers import PROVIDERS

    runtime, agent = make_runtime(tmp_path)
    old_config, old_llm = runtime.state.model_config, runtime.llm
    monkeypatch.setitem(PROVIDERS, "fixture", SimpleNamespace(key="fixture"))
    monkeypatch.setattr(
        "runtime.service.build_model_config_and_client",
        lambda *a: (replace(old_config, model="broken"), SimpleNamespace(reject_configuration=True)),
    )
    try:
        with pytest.raises(ValueError, match="configuration rejected"):
            runtime.switch_model("fixture", "broken")
        assert runtime.state.model_config is old_config
        assert runtime.llm is old_llm and agent.llm is old_llm
    finally:
        runtime.close()


def test_request_retry_progress_is_replayable_without_becoming_an_assistant_answer(tmp_path):
    runtime, agent = make_runtime(tmp_path)

    def step(text):
        notify_request_retry(300.0, 1, 5)
        return "recovered"

    agent.behavior = step
    try:
        runtime.submit("hello")
        assert runtime.wait_for_idle(2)
        messages = runtime.snapshot().messages
        assert [text for role, text in messages if role == "AI"] == ["recovered"]
        assert any(role == "System" and "waiting 5 minutes" in text for role, text in messages)
        turns = runtime.state.chat_store.load_original_turns(runtime.state.chat_session_id)
        assert turns[0]["assistant_final"] == "recovered"
    finally:
        runtime.close()


def test_real_agent_tool_loop_and_runtime_approval_without_ui_or_provider_requests(tmp_path):
    from core.agent import Agent
    from core.tool_registry import ToolRegistry, ToolSpec
    from llm.base import LLMResponse, NativeToolCall
    from runtime.service import AgentRuntime

    fixture_runtime, _ = make_runtime(tmp_path)
    state = fixture_runtime.state
    fixture_runtime.close()
    target = tmp_path / "real-loop.txt"
    registry = ToolRegistry()

    def propose(state):
        proposal, _ = state.edit_store.propose_create(target, "approved through runtime")
        return f"Pending proposal #{proposal.id}"

    registry.register(ToolSpec(
        name="fixture_proposal", function=propose, description="Offline test proposal",
        parameters={}, requires_state=True,
    ))

    class FixtureLLM:
        supports_native_tools = True
        supports_native_tool_outputs = False
        api_type = "chat_completions"
        calls = 0

        def chat(self, messages, tools=None, tool_choice=None):
            self.calls += 1
            if self.calls == 1:
                return LLMResponse(content=None, tool_calls=[
                    NativeToolCall(id="fixture_call", name="fixture_proposal", arguments={}),
                ])
            return "proposal ready"

    llm = FixtureLLM()
    runtime = AgentRuntime(
        state=state, llm=llm,
        agent_factory=lambda **kwargs: Agent("fixture system", tool_registry=registry, **kwargs),
    )
    try:
        runtime.submit("propose fixture only")
        assert runtime.wait_for_idle(2)
        assert runtime.snapshot().run.status == "completed"
        assert runtime.snapshot().run.reply == "proposal ready"
        assert llm.calls == 2
        assert not target.exists()
        pending = runtime.pending()
        assert len(pending) == 1
        runtime.decide_pending(next(iter(pending)), accept=True)
        assert target.read_text(encoding="utf-8") == "approved through runtime"
        turns = state.chat_store.load_original_turns(state.chat_session_id)
        assert turns[0]["assistant_final"] == "proposal ready"
    finally:
        runtime.close()
