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

from typing import Any, Callable

from rich.console import Group
from rich.markdown import Markdown
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Input, Static

from runtime.bootstrap import create_agent
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

        self._current_suggestion: str | None = None
        self._messages: list[tuple[str, str]] = []

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="chat_scroll"):
            yield Static("", id="chat")
        yield Static("", id="command_suggestion")
        yield Input(placeholder="Type a message and press Enter...", id="input")
        yield Static("  ^C  Quit    ^R  Theme", id="footer_hint")

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
        self.query_one("#command_suggestion", Static).display = False
        self.query_one("#input", Input).focus()


    def on_input_changed(self, event: Input.Changed) -> None:
        self._update_command_suggestion(event.value)

    def on_key(self, event) -> None:
        if event.key != "tab" or self._current_suggestion is None:
            return

        input_widget = self.query_one("#input", Input)
        input_widget.value = self._current_suggestion
        input_widget.cursor_position = len(self._current_suggestion)
        self._update_command_suggestion(input_widget.value)
        event.prevent_default()
        event.stop()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        input_widget = self.query_one("#input", Input)

        if not text:
            return

        if self._processing:
            return

        input_widget.value = ""
        self._update_command_suggestion("")

        if text.startswith("\\"):
            self._handle_command(text)
            return

        self._append_chat("You", text)
        self._start_agent_step(text)

    def _handle_command(self, text: str) -> None:
        command = text.strip().lower()

        if command == "\\help":
            self._append_chat(
                "System",
                "Supported Textual Phase 2 commands: \\help, \\reset, \\pwd, \\state",
            )
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
        if processing:
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

    def _update_command_suggestion(self, value: str) -> None:
        suggestion_widget = self.query_one("#command_suggestion", Static)
        value = value.strip()

        if not value.startswith("\\") or " " in value:
            self._current_suggestion = None
            suggestion_widget.update("")
            suggestion_widget.display = False
            return

        matches = [command for command in self.COMMANDS if command.startswith(value)]
        if not matches:
            self._current_suggestion = None
            suggestion_widget.update("")
            suggestion_widget.display = False
            return

        self._current_suggestion = matches[0]
        if value == matches[0]:
            self._current_suggestion = None
            suggestion_widget.update("  Matches: " + "  ".join(matches))
            suggestion_widget.display = True
            return

        typed_length = len(value)
        completion = matches[0][typed_length:]
        hint = Text.assemble(
            "  Matches: " + "  ".join(matches) + "    ",
            value,
            (completion, "dim"),
        )
        suggestion_widget.update(hint)
        suggestion_widget.display = True

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
