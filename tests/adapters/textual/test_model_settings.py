"""Headless tests of the settings command, search and tree selection."""

import asyncio
from pathlib import Path
from types import SimpleNamespace

from textual.widgets import Input, Tree

from adapters.textual.app import AgentTextualApp
from runtime.state import ModelSettings


class SettingsTestApp(AgentTextualApp):
    # Textual resolves inherited relative CSS paths against the subclass module.
    CSS_PATH = [
        Path(__file__).resolve().parents[3] / "adapters" / "textual" / path
        for path in AgentTextualApp.CSS_PATH
    ]

    def on_mount(self) -> None:
        # No agent, API requests, tools or chat storage needed for UI tests.
        self._refresh_state()
        self.query_one("#input", Input).focus()

    def _append_chat(self, role: str, text: str) -> None:
        self._messages.append((role, text))


def make_app(tmp_path):
    return SettingsTestApp(
        state=SimpleNamespace(
            cwd=tmp_path,
            model_settings=ModelSettings(),
            model_config=SimpleNamespace(
                provider_label="OpenAI", model="o3", api_type="responses",
            ),
            edit_store=SimpleNamespace(pending=lambda: []),
            chat_session_id=None,
        ),
        llm=SimpleNamespace(),
    )


def test_settings_command_search_and_tree_selection(tmp_path):
    async def run_test():
        app = make_app(tmp_path)
        async with app.run_test(size=(120, 40)) as pilot:
            input_widget = app.query_one("#input", Input)
            input_widget.value = "\\settings"
            await pilot.press("enter")
            await pilot.pause()
            assert app._mode == "model_settings_select"
            assert len(app._visible_model_setting_matches) == 5

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
            app._processing = False

    asyncio.run(run_test())
