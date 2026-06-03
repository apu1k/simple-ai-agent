"""
adapters/textual/app.py

Minimal Textual frontend for simple-ai-agent.

Phase 2 goals:
- start a Textual app
- send messages to the existing Agent
- show assistant replies
- show debug/tool/raw/error callback output
- keep the CLI frontend untouched
"""

from __future__ import annotations

from typing import Any, Callable, Literal

from rich.console import Group
from rich.markdown import Markdown
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Container, VerticalScroll
from textual.suggester import SuggestFromList
from textual.widgets import Footer, Input, Static, Tree

from llm.providers import PROVIDERS, list_provider_models
from runtime.bootstrap import build_model_config_and_client, create_agent
from runtime.prompt import build_system_prompt



class AgentTextualApp(App):
    """Minimal Textual UI around the existing synchronous Agent."""

    ENABLE_COMMAND_PALETTE = False

    CSS_PATH = [
        "styles/base.tcss",
        "styles/theme-dark.tcss",
        "styles/theme-light.tcss",
    ]

    BINDINGS = [
        ("ctrl+c", "quit", "Quit"),
        ("ctrl+r", "toggle_theme", "Theme"),
    ]

    COMMANDS = [
        "\\help",
        "\\models",
        "\\reset",
        "\\pwd",
        "\\state",
        "\\theme",
        "\\quit",
    ]

    def __init__(self, *, state: Any, llm: Any):
        super().__init__()
        self.state = state
        self.llm = llm
        self.agent = None
        self._theme_dark = True
        self._processing = False
        self._mode: Literal["chat", "model_select"] = "chat"

        self._messages: list[tuple[str, str]] = []
        self._models_by_provider: dict[str, list[str]] = {}
        self._model_tree_loaded = False
        self._model_tree_loading = False
        self._model_search = ""
        self._visible_model_matches: list[tuple[str, str]] = []

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="chat_scroll"):
            yield Static("", id="chat")
        with Container(id="model_select", classes="hidden"):
            yield Static("Model selection is loading...", id="model_header")
            yield Tree("Models", id="model_tree")
        yield Input(
            placeholder="Type a message and press Enter...",
            suggester=SuggestFromList(self.COMMANDS, case_sensitive=True),
            id="input",
        )
        yield Footer(compact=True, show_command_palette=False)

    def on_mount(self) -> None:
        self.screen.add_class("theme-dark")
        self.agent = create_agent(
            state=self.state,
            llm=self.llm,
            on_debug=self._on_debug,
            on_tool=self._on_tool,
            on_raw=self._on_raw,
            on_error=self._on_error,
            on_display=self._on_display,
        )
        self.query_one("#input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if self._mode == "model_select":
            self._submit_model_selection()
            return

        text = event.value.strip()
        input_widget = self.query_one("#input", Input)

        if not text:
            return

        if self._processing:
            return

        input_widget.value = ""

        if text.startswith("\\"):
            self._handle_command(text)
            return

        self._append_chat("You", text)
        self._start_agent_step(text)

    def on_input_changed(self, event: Input.Changed) -> None:
        if self._mode != "model_select" or event.input.id != "input":
            return
        self._model_search = event.value.strip()
        self._render_model_tree()

    def on_key(self, event) -> None:
        if self._mode == "model_select" and event.key == "escape":
            event.stop()
            self._exit_model_select_mode()

    def _handle_command(self, text: str) -> None:
        command = text.strip().lower()

        if command == "\\help":
            self._append_chat(
                "System",
                "Supported Textual commands: \\help, \\models, \\reset, \\pwd, \\state, \\theme, \\quit",
            )
            return

        if command == "\\models":
            self._enter_model_select_mode()
            return

        if command == "\\reset":
            if self.agent is not None:
                self.agent.reset(build_system_prompt())
            self._append_chat("System", "Conversation context reset.")
            return

        if command == "\\pwd":
            self._append_chat("System", str(self.state.cwd))
            return

        if command == "\\state":
            self._append_chat("System", self._state_text())
            return

        if command == "\\theme":
            self.action_toggle_theme()
            self._append_chat("System", "Theme changed.")
            return

        if command == "\\quit":
            self.exit()
            return

        self._append_chat(
            "System",
            "Command not yet supported in Textual.",
        )

    def _enter_model_select_mode(self) -> None:
        if self._processing:
            self._append_chat("System", "Cannot switch models while AI is processing.")
            return

        self._mode = "model_select"
        self._model_search = ""
        self.query_one("#chat_scroll", VerticalScroll).add_class("hidden")
        self.query_one("#model_select", Container).remove_class("hidden")
        self.screen.add_class("model-select-mode")

        input_widget = self.query_one("#input", Input)
        input_widget.value = ""
        input_widget.placeholder = "Search models... Enter selects one match, Esc cancels"
        input_widget.focus()

        if self._model_tree_loaded:
            self._render_model_tree()
            return

        self._set_model_header("Loading provider model lists...")
        self._show_model_loading_tree()
        if not self._model_tree_loading:
            self._model_tree_loading = True
            self._load_models_worker()

    def _exit_model_select_mode(self) -> None:
        self._mode = "chat"
        self.query_one("#model_select", Container).add_class("hidden")
        self.query_one("#chat_scroll", VerticalScroll).remove_class("hidden")
        self.screen.remove_class("model-select-mode")

        input_widget = self.query_one("#input", Input)
        input_widget.value = ""
        input_widget.placeholder = "Type a message and press Enter..."
        input_widget.focus()
        self.query_one("#chat_scroll", VerticalScroll).scroll_end(animate=False)

    def action_cancel_model_select(self) -> None:
        if self._mode == "model_select":
            self._exit_model_select_mode()

    def _set_model_header(self, text: str) -> None:
        self.query_one("#model_header", Static).update(text)

    def _show_model_loading_tree(self) -> None:
        tree = self.query_one("#model_tree", Tree)
        root = tree.root
        root.set_label("Models")
        root.remove_children()
        root.add_leaf("Loading models...")
        root.expand()

    @work(thread=True, exclusive=True)
    def _load_models_worker(self) -> None:
        models_by_provider: dict[str, list[str]] = {}

        for key, provider in PROVIDERS.items():
            models: list[str] = []
            try:
                models = list_provider_models(provider)
            except Exception as e:
                print(f"[model-listing] {provider.label}: {e}", flush=True)

            unique_models = list(dict.fromkeys(models))
            if provider.default_model:
                unique_models = [provider.default_model] + [
                    model for model in unique_models if model != provider.default_model
                ]
            models_by_provider[key] = unique_models

        self._from_any_thread(self._finish_model_loading, models_by_provider)

    def _finish_model_loading(self, models_by_provider: dict[str, list[str]]) -> None:
        self._models_by_provider = models_by_provider
        self._model_tree_loaded = True
        self._model_tree_loading = False
        if self._mode == "model_select":
            self._render_model_tree()

    def _render_model_tree(self) -> None:
        if self._mode != "model_select":
            return

        tree = self.query_one("#model_tree", Tree)
        root = tree.root
        root.set_label("Models")
        root.remove_children()
        root.expand()

        query = self._model_search.lower()
        current_provider = self.state.model_config.provider_key
        current_model = self.state.model_config.model
        visible_matches: list[tuple[str, str]] = []

        for key, provider in PROVIDERS.items():
            models = self._models_by_provider.get(key, [])
            provider_matches = query in key.lower() or query in provider.label.lower()
            filtered_models = [
                model for model in models
                if not query or provider_matches or query in model.lower()
            ]

            if query and not filtered_models:
                continue

            provider_node = root.add(f"{provider.label} [{key}]")
            provider_node.expand()

            if not filtered_models:
                provider_node.add_leaf("No models available; configure default_model")
                continue

            for model in filtered_models:
                visible_matches.append((key, model))
                marker = "✓ " if key == current_provider and model == current_model else ""
                node = provider_node.add_leaf(f"{marker}{model}")
                node.data = ("model", key, model)

        self._visible_model_matches = visible_matches

        if not visible_matches:
            root.add_leaf("No models match your search.")
            self._set_model_header("No matching models. Change the search text or press Esc to cancel.")
        elif query:
            self._set_model_header(
                f"{len(visible_matches)} matching model(s). Narrow to one and press Enter, or select a tree item."
            )
        else:
            self._set_model_header(
                "Select a model from the tree. Type to search; Enter selects one match; Esc cancels."
            )

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        if self._mode != "model_select":
            return

        data = getattr(event.node, "data", None)
        if not data or data[0] != "model":
            try:
                event.node.toggle()
            except Exception:
                pass
            return

        _, provider_key, model = data
        self._switch_model(provider_key, model)

    def _submit_model_selection(self) -> None:
        if len(self._visible_model_matches) == 1:
            provider_key, model = self._visible_model_matches[0]
            self._switch_model(provider_key, model)
            return

        if not self._visible_model_matches:
            self._set_model_header("No matching models. Change the search text or press Esc to cancel.")
            return

        self._set_model_header(
            f"{len(self._visible_model_matches)} matches. Narrow search to one model or select a tree item."
        )

    def _switch_model(self, provider_key: str, model: str) -> None:
        provider = PROVIDERS.get(provider_key)
        if provider is None:
            self._set_model_header(f"Unknown provider: {provider_key}")
            return

        try:
            config, llm = build_model_config_and_client(provider, model)
        except Exception as e:
            self._set_model_header(f"Model switch failed: {e}")
            return

        self.state.model_config = config
        self.llm = llm
        if self.agent is not None:
            self.agent.llm = llm

        self._exit_model_select_mode()
        self._append_chat(
            "System",
            f"Model changed to {config.provider_label} / {config.model}.",
        )

    def action_toggle_theme(self) -> None:
        self._theme_dark = not self._theme_dark
        if self._theme_dark:
            self.screen.remove_class("theme-light")
            self.screen.add_class("theme-dark")
        else:
            self.screen.remove_class("theme-dark")
            self.screen.add_class("theme-light")

    def _start_agent_step(self, text: str) -> None:
        self._set_processing(True)
        self._run_agent_step(text)

    @work(thread=True, exclusive=True)
    def _run_agent_step(self, text: str) -> None:
        try:
            if self.agent is None:
                raise RuntimeError("Agent is not initialized.")

            reply = self.agent.step(text)
            self._from_any_thread(self._append_chat, "AI", reply)
        except Exception as e:
            print(f"[error] {e}", flush=True)
            self._from_any_thread(self._append_chat, "Error", str(e))
        finally:
            self._from_any_thread(self._finish_agent_step)

    def _finish_agent_step(self) -> None:
        self._set_processing(False)

    def _set_processing(self, processing: bool) -> None:
        self._processing = processing
        input_widget = self.query_one("#input", Input)
        input_widget.disabled = False
        if self._mode == "model_select":
            input_widget.placeholder = "Search models... Enter selects one match, Esc cancels"
        elif processing:
            input_widget.placeholder = "AI is processing... you can type, then press Enter when done."
        else:
            input_widget.placeholder = "Type a message and press Enter..."
        input_widget.focus()

    def _append_chat(self, who: str, text: str) -> None:
        self._messages.append((who, text))
        self._render_chat()

    def _render_chat(self) -> None:
        renderables = []
        for index, (who, text) in enumerate(self._messages):
            if index > 0:
                renderables.append(Text(""))
            renderables.append(self._message_renderable(who, text))

        chat = self.query_one("#chat", Static)
        chat.update(Group(*renderables) if renderables else "")
        self.query_one("#chat_scroll", VerticalScroll).scroll_end(animate=False)

    def _message_renderable(self, who: str, text: str):
        if who == "You":
            return Text(text, style="dim")
        if who == "AI":
            return self._format_ai_markdown(text)
        if who == "Error":
            return Text(text, style="red")
        return Text(text)

    def _format_ai_markdown(self, text: str):
        try:
            return Markdown(text)
        except Exception:
            return Text(text)


    def _append_log(self, kind: str, text: str) -> None:
        print(f"[{kind}] {text}", flush=True)

    def _refresh_state(self) -> None:
        # Kept for command/worker compatibility; the minimal UI has no state panel.
        return

    def _state_text(self) -> str:
        return (
            f"cwd: {self.state.cwd}\n"
            f"provider: {self.state.model_config.provider_label}\n"
            f"model: {self.state.model_config.model}\n"
            f"api_type: {self.state.model_config.api_type}"
        )

    def _from_any_thread(self, callback: Callable[..., None], *args: Any) -> None:
        """
        Schedule a UI update from a worker thread, but still work if called
        during normal UI lifecycle methods.
        """
        try:
            self.call_from_thread(callback, *args)
        except RuntimeError:
            callback(*args)

    def _on_debug(self, message: str) -> None:
        print(f"[debug] {message}", flush=True)

    def _on_tool(self, message: str) -> None:
        print(f"[tool] {message}", flush=True)

    def _on_raw(self, message: str) -> None:
        print(f"[raw] {message}", flush=True)

    def _on_error(self, message: str) -> None:
        print(f"[error] {message}", flush=True)

    def _on_display(self, items: list) -> None:
        for item in items:
            title = getattr(item, "title", "Display item")
            path = getattr(item, "display_path", getattr(item, "path", ""))
            self._append_log("display", f"{title}\n{path}")
