"""Headless tests of the settings command, search and tree selection."""

import asyncio
from pathlib import Path
from types import SimpleNamespace

from textual.events import Mount
from textual.widgets import Input, Tree

from adapters.textual.app import AgentTextualApp
from runtime.state import ModelSettings, OPENAI_REASONING_EFFORTS
from runtime.privileged_turn import PrivilegedTurn


class SettingsTestApp(AgentTextualApp):
    # Textual resolves inherited relative CSS paths against the subclass module.
    CSS_PATH = [
        Path(__file__).resolve().parents[3] / "adapters" / "textual" / path
        for path in AgentTextualApp.CSS_PATH
    ]

    def on_mount(self, event: Mount) -> None:
        # Textual dispatches base-class handlers too unless default is prevented.
        # No agent, API requests, tools or chat storage needed for UI tests.
        event.prevent_default()
        self._refresh_state()
        self.query_one("#input", Input).focus()

    def _append_chat(self, role: str, text: str) -> None:
        self._messages.append((role, text))


def make_app(tmp_path):
    return SettingsTestApp(
        state=SimpleNamespace(
            cwd=tmp_path,
            model_settings=ModelSettings(),
            privileged_turn=PrivilegedTurn(),
            model_config=SimpleNamespace(
                provider_label="OpenAI", model="o3", api_type="responses",
            ),
            edit_store=SimpleNamespace(pending=lambda: []),
            chat_session_id=None,
        ),
        llm=SimpleNamespace(),
    )


def test_privileged_progress_updates_while_worker_waits_and_input_remains_responsive(tmp_path, monkeypatch):
    from threading import Event
    from core.tool_progress import PRIVILEGED_EVIDENCE_PREFIX

    started = Event()
    release = Event()
    monkeypatch.setattr('adapters.textual.app.record_final_turn', lambda *args: None)
    async def run_test():
        app = make_app(tmp_path)
        async with app.run_test(size=(160, 40)) as pilot:
            def step(text):
                app._on_tool(PRIVILEGED_EVIDENCE_PREFIX + 'Hashing source VHDX — 5s elapsed')
                started.set()
                assert release.wait(5), 'Test worker was not released'
                app._on_tool(PRIVILEGED_EVIDENCE_PREFIX + 'Validating protected receipt')
                return 'verified fixture result'
            app.agent = SimpleNamespace(step=step)
            app._start_agent_step('fixture only; no UAC')
            try:
                assert await asyncio.to_thread(started.wait, 2)
                await pilot.press('a', 'b', 'c')
                assert app.query_one('#input', Input).value == 'abc'
                assert app._processing
                assert app._privileged_evidence_progress == 'Hashing source VHDX — 5s elapsed'
                assert not any(role == 'AI' for role, _ in app._messages)
            finally:
                release.set()
            for _ in range(30):
                await pilot.pause()
                if not app._processing:
                    break
                await asyncio.sleep(0.05)
            assert not app._processing
            assert app._privileged_evidence_progress == ''
            assert sum(role == 'System' for role, _ in app._messages) == 1
            assert ('AI', 'verified fixture result') in app._messages
    asyncio.run(run_test())


def test_settings_command_search_and_tree_selection(tmp_path):
    async def run_test():
        app = make_app(tmp_path)
        async with app.run_test(size=(120, 40)) as pilot:
            input_widget = app.query_one("#input", Input)
            input_widget.value = "\\settings"
            await pilot.press("enter")
            await pilot.pause()
            assert app._mode == "model_settings_select"
            assert len(app._visible_model_setting_matches) == 15

            input_widget.value = "OpenAI Flex: Enabled"
            await pilot.pause()
            assert app._visible_model_setting_matches == [("openai_flex", True)]
            await pilot.press("enter")
            await pilot.pause()
            assert app.state.model_settings.openai_flex is True
            assert app.state.model_settings.include_diff is False
            assert app._mode == "chat"
            assert "openai_flex (OpenAI only): True" in app._state_text()

            app._handle_command("\\settings")
            await pilot.pause()
            tree = app.query_one("#model_settings_tree", Tree)
            enabled = next(n for n in tree.root.children if n.data == ("model_setting", "openai_flex", True))
            assert str(enabled.label).startswith("✓ ")
            disabled = next(n for n in tree.root.children if n.data == ("model_setting", "openai_flex", False))
            app.on_tree_node_selected(Tree.NodeSelected(disabled))
            await pilot.pause()
            assert app.state.model_settings.openai_flex is False

            app._handle_command("\\settings")
            input_widget.value = "Model choice"
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert app.state.model_settings.include_diff == "model"
            assert app.state.model_settings.openai_flex is False

    asyncio.run(run_test())


def test_privileged_progress_is_full_width_plain_text_and_not_a_model_answer(tmp_path):
    from textual.widgets import Static
    from core.tool_progress import PRIVILEGED_EVIDENCE_PREFIX

    async def run_test():
        app = make_app(tmp_path)
        async with app.run_test(size=(80, 24)) as pilot:
            progress = app.query_one('#privileged_progress', Static)
            assert progress.has_class('hidden')
            message = 'Hashing source VHDX — 125s elapsed [not markup]'
            app._on_tool(PRIVILEGED_EVIDENCE_PREFIX + message)
            await pilot.pause()
            assert not progress.has_class('hidden')
            assert progress.region.width == 80  # Includes the two padding columns.
            assert progress.render_line(0).text.strip() == message
            assert len(app._messages) == 1 and app._messages[0][0] == 'System'
            app._on_tool(PRIVILEGED_EVIDENCE_PREFIX + 'Rechecking source VM state — 130s elapsed')
            await pilot.pause()
            assert len(app._messages) == 1
            app._finish_agent_step()
            await pilot.pause()
            assert progress.has_class('hidden')
            assert app._privileged_evidence_progress == ''
    asyncio.run(run_test())


def test_reasoning_search_tree_selection_and_default(tmp_path):
    async def run_test():
        app = make_app(tmp_path)
        async with app.run_test(size=(120, 40)) as pilot:
            app._handle_command("\\settings")
            input_widget = app.query_one("#input", Input)
            input_widget.value = "OpenAI reasoning effort: low"
            await pilot.pause()
            assert app._visible_model_setting_matches == [("openai_reasoning_effort", "low")]
            await pilot.press("enter")
            await pilot.pause()
            assert app.state.model_settings.openai_reasoning_effort == "low"
            assert app._mode == "chat"
            assert "openai_reasoning_effort (OpenAI only): low" in app._state_text()

            app._handle_command("\\settings")
            input_widget.value = "OpenAI reasoning effort: max"
            await pilot.pause()
            assert app._visible_model_setting_matches == [("openai_reasoning_effort", "max")]
            await pilot.press("enter")
            await pilot.pause()
            assert app.state.model_settings.openai_reasoning_effort == "max"

            current = "max"
            for effort in (*OPENAI_REASONING_EFFORTS, None):
                app._handle_command("\\settings")
                await pilot.pause()
                tree = app.query_one("#model_settings_tree", Tree)
                selected = next(n for n in tree.root.children
                                if n.data == ("model_setting", "openai_reasoning_effort", current))
                assert str(selected.label).startswith("✓ ")
                target = next(n for n in tree.root.children
                              if n.data == ("model_setting", "openai_reasoning_effort", effort))
                app.on_tree_node_selected(Tree.NodeSelected(target))
                await pilot.pause()
                assert app._mode == "chat"
                assert app.state.model_settings.openai_reasoning_effort == effort
                assert app.state.model_settings.openai_flex is False
                assert app.state.model_settings.include_diff is False
                current = effort
            assert "openai_reasoning_effort (OpenAI only): default" in app._state_text()

            app._handle_command("\\settings")
            input_widget.value = "reasoning"
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert app._mode == "model_settings_select"
            assert app.state.model_settings.openai_reasoning_effort is None
            await pilot.press("ctrl+g")
            await pilot.pause()
            assert app._mode == "chat"
            assert app.state.model_settings.openai_reasoning_effort is None

            # Values belonging to other settings must not corrupt include_diff.
            app._set_model_setting("include_diff", "high")
            app._set_model_setting("openai_reasoning_effort", True)
            assert app.state.model_settings.include_diff is False
            assert app.state.model_settings.openai_reasoning_effort is None

    asyncio.run(run_test())


def test_privileged_evidence_setting_is_ui_only_and_volatile(tmp_path):
    async def run_test():
        app = make_app(tmp_path)
        async with app.run_test(size=(150, 40)) as pilot:
            assert app.state.privileged_turn.status == "disabled"
            app._handle_command("\\settings")
            app.query_one("#input", Input).value = "Privileged Hyper-V evidence: Enable next turn"
            await pilot.pause()
            assert app._visible_model_setting_matches == [("privileged_host_evidence", True)]
            await pilot.press("enter")
            await pilot.pause()
            assert app.state.privileged_turn.status == "armed for next turn"
            assert "armed for next turn" in app._state_text()
            assert "UAC consent" in app._messages[-1][1]
            app._processing = True
            app._set_model_setting("privileged_host_evidence", False)
            assert app.state.privileged_turn.status == "armed for next turn"
            app._processing = False
            app._handle_command("\\settings")
            app._set_model_setting("privileged_host_evidence", False)
            assert app.state.privileged_turn.status == "disabled"
            assert not hasattr(app.state.model_settings, "privileged_host_evidence")
    asyncio.run(run_test())


def test_settings_cancel_ambiguous_search_and_processing_guard(tmp_path):
    async def run_test():
        app = make_app(tmp_path)
        async with app.run_test(size=(120, 40)) as pilot:
            app._handle_command("\\settings")
            input_widget = app.query_one("#input", Input)
            input_widget.value = "Flex"
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert app._mode == "model_settings_select"
            assert app.state.model_settings.openai_flex is False
            input_widget.value = "no-such-setting"
            await pilot.pause()
            assert app._visible_model_setting_matches == []
            await pilot.press("enter")
            await pilot.press("ctrl+g")
            await pilot.pause()
            assert app._mode == "chat"
            assert app.state.model_settings.openai_flex is False

            app._processing = True
            app._handle_command("\\settings")
            assert app._mode == "chat"
            app._set_model_setting("openai_flex", True)
            assert app.state.model_settings.openai_flex is False
            app._set_model_setting("openai_reasoning_effort", "high")
            assert app.state.model_settings.openai_reasoning_effort is None
            app._processing = False

    asyncio.run(run_test())
