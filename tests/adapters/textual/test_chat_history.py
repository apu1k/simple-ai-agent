"""Regression tests for the context and preview used when loading a chat."""

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from rich.text import Text

from adapters.textual.app import AgentTextualApp
from runtime.chat_store import ChatStore
from tests.runtime_helpers import make_runtime


@pytest.fixture
def chat_history(tmp_path):
    store = ChatStore(tmp_path / "history")
    session_id = store.new_session()
    for index in range(1, 41):
        store.append_turn(
            session_id=session_id,
            user_text=f"u{index}",
            assistant_text=f"a{index}",
        )
    return store, store.list_sessions()[0]


def test_load_chat_restores_latest_32_turns_to_ui_and_agent(chat_history, tmp_path):
    store, session = chat_history
    runtime, agent = make_runtime(tmp_path)
    runtime.state.chat_store = store
    agent.messages.append({"role": "user", "content": "stale context"})

    async def run_test():
        app = AgentTextualApp(runtime=runtime)
        async with app.run_test() as pilot:
            app._selected_chat_summary = lambda: session
            app._submit_chat_selection()
            await pilot.pause()
            expected = [
                (role, text)
                for index in range(9, 41)
                for role, text in (("You", f"u{index}"), ("AI", f"a{index}"))
            ]
            assert app.state.chat_session_id == session.session_id
            assert app._messages[:-1] == expected
            assert app._messages[-1] == ("System", f"Loaded chat session: {session.session_id}")
            assert agent.messages[0]["role"] == "system"
            assert agent.messages[1:] == [
                {"role": "user" if role == "You" else "assistant", "content": text}
                for role, text in expected
            ]
            assert app._mode == "chat"

    try:
        asyncio.run(run_test())
    finally:
        runtime.close()


def test_reload_context_command_replaces_both_clients_with_clean_last_32_turns(chat_history, tmp_path):
    store, session = chat_history
    runtime, agent = make_runtime(tmp_path)
    runtime.state.chat_store = store
    runtime.state.chat_session_id = session.session_id
    agent.messages.append({"role": "tool", "content": "old intermediate result"})
    runtime._message("System", "old progress")

    async def run_test():
        first = AgentTextualApp(runtime=runtime)
        async with first.run_test():
            second = AgentTextualApp(runtime=runtime)
            async with second.run_test():
                assert "\\reload_context" in first.INPUT_COMMANDS
                first._handle_command("\\help")
                assert "\\reload_context: reload the last 32 saved turns" in first._messages[-1][1]
                first._handle_command("\\reload_context")
                second._drain_runtime_events()
                expected = [
                    (role, text)
                    for index in range(9, 41)
                    for role, text in (("You", f"u{index}"), ("AI", f"a{index}"))
                ]
                assert first._messages[:-1] == second._messages[:-1] == expected
                assert first._messages[-1] == second._messages[-1]
                assert first._messages[-1][1].startswith("Reloaded clean context: 32 saved turns")
                assert agent.messages[1:] == [
                    {"role": "user" if role == "You" else "assistant", "content": text}
                    for role, text in expected
                ]
                assert runtime.state.chat_session_id == session.session_id
                assert store.list_sessions()[0].turn_count == 40

    try:
        asyncio.run(run_test())
    finally:
        runtime.close()


def test_chat_preview_shows_latest_32_turns_and_matching_heading(chat_history):
    store, session = chat_history
    widgets = {
        selector: Mock()
        for selector in ("#chat_detail", "#chat_detail_scroll", "#chat_history")
    }
    app = SimpleNamespace(
        runtime=SimpleNamespace(load_original_turns=store.load_original_turns),
        _selected_chat_summary=lambda: session,
        query_one=lambda selector, widget_type: widgets[selector],
        _message_renderable=lambda role, text: Text(f"{role}: {text}"),
        _scroll_chat_history_to_bottom=Mock(),
    )

    AgentTextualApp._render_chat_detail(app)

    preview = widgets["#chat_history"].update.call_args.args[0]
    parts = [part.plain for part in preview.renderables]
    assert parts[0] == "History preview (last 32 turns)\n"
    assert [part for part in parts[1:] if part] == [
        text
        for index in range(9, 41)
        for text in (f"You: u{index}", f"AI: a{index}")
    ]
    app._scroll_chat_history_to_bottom.assert_called_once_with()
