import asyncio
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

from textual.widgets import Static, Tree

from adapters.textual.app import AgentTextualApp
from core.tool_progress import PRIVILEGED_EVIDENCE_PREFIX
from tests.runtime_helpers import make_runtime


def test_two_textual_clients_share_run_pending_decisions_and_reconnect(tmp_path):
    runtime, agent = make_runtime(tmp_path)
    started, release = Event(), Event()
    target = tmp_path / "reviewed.txt"

    def step(text):
        runtime.state.edit_store.propose_create(target, "reviewed content")
        agent.on_tool("fixture proposal created")
        agent.on_tool(PRIVILEGED_EVIDENCE_PREFIX + "fixture display-only progress")
        started.set()
        assert release.wait(10)
        return "completed after initiating client disconnected"

    agent.behavior = step

    async def run_test():
        second = AgentTextualApp(runtime=runtime)
        async with second.run_test(size=(120, 40)) as second_pilot:
            first = AgentTextualApp(runtime=runtime)
            async with first.run_test(size=(120, 40)):
                first._start_agent_step("shared request")
                assert await asyncio.to_thread(started.wait, 2)
                first._drain_runtime_events()
                second._drain_runtime_events()
                assert first._processing and second._processing
                assert first._messages == second._messages
                assert first._privileged_evidence_progress == second._privileged_evidence_progress
                assert len(second._pending_entries()) == 1
            # Only the first UI has gone away. No worker belongs to that UI.
            assert runtime.snapshot().processing
            assert second._runtime_client_id is not None
            second._enter_pending_select_mode()
            second._approve_selected_pending()
            assert target.read_text(encoding="utf-8") == "reviewed content"
            assert not runtime.pending()
            release.set()
            assert await asyncio.to_thread(runtime.wait_for_idle, 2)
            second._drain_runtime_events()
            await second_pilot.pause()
            assert not second._processing
            assert second._privileged_evidence_progress == ""
            assert second.query_one("#privileged_progress", Static).has_class("hidden")
            assert ("AI", "completed after initiating client disconnected") in second._messages
            reconnected = AgentTextualApp(runtime=runtime)
            async with reconnected.run_test(size=(120, 40)):
                assert not reconnected._processing
                assert reconnected._messages == second._messages
                assert not reconnected._pending_entries()
        assert runtime.snapshot().run.status == "completed"

    try:
        asyncio.run(run_test())
    finally:
        release.set()
        runtime.close()


def test_textual_recovers_expired_event_cursor_from_snapshot_without_duplicates(tmp_path):
    runtime, agent = make_runtime(tmp_path, event_limit=2)

    async def run_test():
        app = AgentTextualApp(runtime=runtime)
        async with app.run_test():
            app._start_agent_step("snapshot request")
            assert await asyncio.to_thread(runtime.wait_for_idle, 2)
            # Simulate an arbitrarily slow client that missed the replay window.
            for index in range(8):
                agent.on_tool(f"fixture event {index}")
            app._runtime_cursor = 0
            app._messages = [("You", "stale local content")]
            app._drain_runtime_events()
            expected = [("You", "snapshot request"), ("AI", "answer: snapshot request")]
            assert app._messages == expected
            assert not app._processing
            app._drain_runtime_events()
            assert app._messages == expected
            assert app._runtime_cursor == runtime.snapshot().sequence

    try:
        asyncio.run(run_test())
    finally:
        runtime.close()


def test_late_runtime_and_focus_timers_do_not_touch_widgets_during_shutdown():
    closing = SimpleNamespace(
        is_running=False,
        _runtime_client_id="not-yet-unmounted",
        runtime=Mock(),
        query_one=Mock(side_effect=AssertionError("Widgets have already been removed")),
    )
    AgentTextualApp._drain_runtime_events(closing)
    AgentTextualApp._focus_input(closing)
    closing.runtime.events_since.assert_not_called()
    closing.query_one.assert_not_called()


def test_external_setting_change_refreshes_open_settings_without_losing_search(tmp_path):
    runtime, _ = make_runtime(tmp_path)

    async def run_test():
        app = AgentTextualApp(runtime=runtime)
        async with app.run_test() as pilot:
            app._enter_model_settings_mode()
            app._model_settings_search = "OpenAI Flex"
            app._render_model_settings_tree()
            runtime.set_model_setting("openai_flex", True)
            app._drain_runtime_events()
            await pilot.pause()
            assert app._mode == "model_settings_select"
            assert app._model_settings_search == "OpenAI Flex"
            assert set(app._visible_model_setting_matches) == {("openai_flex", True), ("openai_flex", False)}
            tree = app.query_one("#model_settings_tree", Tree)
            enabled = next(node for node in tree.root.children if node.data == ("model_setting", "openai_flex", True))
            disabled = next(node for node in tree.root.children if node.data == ("model_setting", "openai_flex", False))
            assert str(enabled.label).startswith("✓ ")
            assert not str(disabled.label).startswith("✓ ")

    try:
        asyncio.run(run_test())
    finally:
        runtime.close()
