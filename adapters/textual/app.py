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
from rich.syntax import Syntax
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, VerticalScroll
from textual.events import Paste
from textual.suggester import SuggestFromList
from textual.widgets import Footer, Input, Static, Tree


class ClipboardInput(Input):
    """Input with reliable paste — uses terminal's Paste event when available."""

    def on_paste(self, event: Paste) -> None:
        """Handle terminal-provided paste (right-click or terminal paste event)."""
        event.stop()  # Prevent Input.on_paste from also handling it (double-paste)
        if event.text:
            text = " ".join(event.text.split())
            current = self.value
            cp = self.cursor_position
            self.value = current[:cp] + text + current[cp:]

    def action_paste(self) -> None:
        """Fallback when terminal doesn't send Paste event (Ctrl+V).

        Uses PowerShell Get-Clipboard as the most reliable Windows API.
        """
        try:
            import subprocess

            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "$OutputEncoding = [Console]::OutputEncoding = [Text.Encoding]::UTF8; Get-Clipboard -Raw"],
                capture_output=True,
                timeout=5,
            )
            text = r.stdout.decode("utf-8", errors="replace").strip() if r.stdout else ""
            if text:
                text = " ".join(text.split())
                current = self.value
                cp = self.cursor_position
                self.value = current[:cp] + text + current[cp:]
        except Exception:
            pass


from llm.providers import PROVIDERS, list_provider_models
from runtime.bootstrap import build_model_config_and_client, create_agent
from runtime.chat_store import record_final_turn, start_new_chat
from runtime.prompt import build_system_prompt



class AgentTextualApp(App):
    """Minimal Textual UI around the existing synchronous Agent."""

    ENABLE_COMMAND_PALETTE = False
    AUTO_FOCUS = "#input"

    CSS_PATH = [
        "styles/base.tcss",
        "styles/theme-dark.tcss",
        "styles/theme-light.tcss",
    ]

    BINDINGS = [
        ("ctrl+c", "quit", "Quit"),

        ("f8", "toggle_theme", "Theme"),
        ("ctrl+g", "cancel_overlay", "Back"),

        Binding("tab", "input_complete_command", show=False),
        Binding("ctrl+v", "input_paste", show=False),
        Binding("ctrl+w", "input_delete_word_left", show=False),
        Binding("alt+backspace", "input_delete_word_left", show=False),
        Binding("alt+delete", "input_delete_word_right", show=False),

        ("f9", "open_pending", "Pending"),
        ("f2", "open_models", "Models"),
    ]

    COMMANDS = [
        "\\help",
        "\\models",
        "\\pending",
        "\\chats",
        "\\new_chat",
        "\\history",
        "\\reset",
        "\\pwd",
        "\\cd",
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
        self._mode: Literal["chat", "model_select", "pending_select", "chat_select"] = "chat"

        self._messages: list[tuple[str, str]] = []
        self._models_by_provider: dict[str, list[str]] = {}
        self._model_tree_loaded = False
        self._model_tree_loading = False
        self._model_search = ""
        self._visible_model_matches: list[tuple[str, str]] = []

        self._pending_search = ""
        self._visible_pending_ids: list[int] = []
        self._selected_pending_id: int | None = None

        self._chat_search = ""
        self._visible_chat_sessions: list[Any] = []
        self._selected_chat_session_id: str | None = None

        self._command_completion_prefix = ""
        self._command_completion_matches: list[str] = []
        self._command_completion_index = -1

    def compose(self) -> ComposeResult:
        with Container(id="top_status"):
            yield Static("", id="status_cwd")
            yield Static("", id="status_model")
            yield Static("", id="status_edits")
        with VerticalScroll(id="chat_scroll"):
            yield Static("", id="chat")
        with Container(id="model_select", classes="hidden"):
            yield Static("Model selection is loading...", id="model_header")
            yield Tree("Models", id="model_tree")
        with Container(id="pending_select", classes="hidden"):
            yield Static("Pending edits", id="pending_header")
            with Container(id="pending_body"):
                with Container(id="pending_list_pane"):
                    yield Static("", id="pending_list")
                with VerticalScroll(id="pending_diff_scroll"):
                    yield Static("", id="pending_diff")
        with Container(id="chat_select", classes="hidden"):
            yield Static("Chat sessions", id="chat_header")
            with Container(id="chat_body"):
                with VerticalScroll(id="chat_list_scroll"):
                    with Container(id="chat_list_pane"):
                        yield Static("", id="chat_list")
                with VerticalScroll(id="chat_detail_scroll"):
                    yield Static("", id="chat_detail")
                with VerticalScroll(id="chat_history_scroll"):
                    yield Static("", id="chat_history")
        yield ClipboardInput(
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
        self._refresh_state()
        self._schedule_initial_input_focus()

    def _schedule_initial_input_focus(self) -> None:
        """
        Apply best-effort startup focus to the command input.

        AUTO_FOCUS is the canonical Textual-side startup focus declaration.
        The explicit retries below handle normal layout/startup timing in both
        terminal and Serve modes.

        In Textual Serve/browser mode, the browser may still withhold keyboard
        events from the app until the page receives user activation, such as Tab
        or a mouse click. Python-side widget focus cannot fully override that
        browser focus boundary, so this remains best-effort rather than a hard
        guarantee for browser startup.
        """
        self._focus_input()
        self.call_after_refresh(self._focus_input)
        for delay in (0.05, 0.20, 0.50, 1.00):
            self.set_timer(delay, self._focus_input)

    def _focus_input(self) -> None:
        input_widget = self.query_one("#input", Input)
        input_widget.disabled = False
        input_widget.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if self._mode == "model_select":
            self._submit_model_selection()
            return

        if self._mode == "pending_select":
            self._approve_selected_pending()
            return

        if self._mode == "chat_select":
            self._submit_chat_selection()
            return

        text = event.value.strip()
        input_widget = self.query_one("#input", Input)

        if not text:
            return

        if self._processing:
            return

        input_widget.value = ""
        self._reset_command_completion()

        if text.startswith("\\"):
            self._handle_command(text)
            return

        self._append_chat("You", text)
        self._start_agent_step(text)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "input":
            return

        if self._mode == "model_select":
            self._model_search = event.value.strip()
            self._render_model_tree()
            return

        if self._mode == "pending_select":
            self._pending_search = event.value.strip()
            self._render_pending_view()
            return

        if self._mode == "chat_select":
            self._chat_search = event.value.strip()
            self._render_chat_select_view()

    def on_key(self, event) -> None:
        if event.key in {"tab", "shift+tab"}:
            try:
                input_widget = self.query_one("#input", Input)
                if self.focused is input_widget:
                    event.stop()
                    event.prevent_default()
                    if self._mode == "chat" and event.key == "tab":
                        self.action_input_complete_command()
                    input_widget.focus()
                    return
            except Exception:
                pass


        if self._mode == "chat_select":
            key = event.key
            if key == "up":
                event.stop()
                self._move_chat_selection(-1)
                return
            if key == "down":
                event.stop()
                self._move_chat_selection(1)
                return
            if key == "home":
                event.stop()
                self._select_chat_index(0)
                return
            if key == "end":
                event.stop()
                self._select_chat_index(len(self._visible_chat_sessions) - 1)
                return
            if key == "pageup":
                event.stop()
                try:
                    self.query_one("#chat_detail_scroll", VerticalScroll).scroll_relative(y=-10, animate=False)
                except Exception:
                    pass
                return
            if key == "pagedown":
                event.stop()
                try:
                    self.query_one("#chat_detail_scroll", VerticalScroll).scroll_relative(y=10, animate=False)
                except Exception:
                    pass
                return

        if self._mode != "pending_select":
            return

        key = event.key
        if key == "up":
            event.stop()
            self._move_pending_selection(-1)
            return
        if key == "down":
            event.stop()
            self._move_pending_selection(1)
            return
        if key == "home":
            event.stop()
            self._select_pending_index(0)
            return
        if key == "end":
            event.stop()
            self._select_pending_index(len(self._visible_pending_ids) - 1)
            return
        if key == "pageup":
            event.stop()
            self._scroll_pending_diff(-10)
            return
        if key == "pagedown":
            event.stop()
            self._scroll_pending_diff(10)
            return
        if key in {"delete", "backspace"}:
            event.stop()
            self._reject_selected_pending()
            return

    def _handle_command(self, text: str) -> None:
        command = text.strip().lower()

        if command == "\\help":
            self._append_chat(
                "System",
                "Supported Textual commands: \\help, \\models, \\pending, \\chats, \\new_chat, \\history, \\reset, \\pwd, \\cd, \\state, \\theme, \\quit",
            )
            return

        if command == "\\models":
            self._enter_model_select_mode()
            return

        if command == "\\pending":
            self._enter_pending_select_mode()
            return

        if command == "\\chats":
            self._enter_chat_select_mode()
            return

        if command == "\\new_chat":
            session_id = start_new_chat(self.state)
            if self.agent is not None:
                self.agent.reset(build_system_prompt())
            self._messages.clear()
            self._render_chat()
            self._append_chat("System", f"Started new chat session: {session_id}")
            return

        if command == "\\history":
            self._append_chat("System", self.state.chat_store.format_session_list(limit=20))
            return

        if command == "\\reset":
            if self.agent is not None:
                self.agent.reset(build_system_prompt())
            self._append_chat("System", "Conversation context reset.")
            return

        if command == "\\pwd":
            self._append_chat("System", str(self.state.cwd))
            return

        if command.startswith("\\cd"):
            path = text.strip()[3:].strip()
            if not path:
                self._append_chat("System", "Usage: \\cd <path>")
                return
            from tools.fs.read import cd
            result = cd(self.state, path)
            if isinstance(result, str) and result.startswith("Error:"):
                self._append_chat("Error", result)
            else:
                self._append_chat("System", result)
            self._refresh_state()
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
            "Unknown command. Type \\help to see available commands.",
        )

    def _enter_model_select_mode(self) -> None:
        if self._processing:
            self._append_chat("System", "Cannot switch models while AI is processing.")
            return

        self._mode = "model_select"
        self._refresh_footer_bindings()
        self._model_search = ""
        self.query_one("#chat_scroll", VerticalScroll).add_class("hidden")
        self.query_one("#model_select", Container).remove_class("hidden")
        self.screen.add_class("model-select-mode")

        input_widget = self.query_one("#input", Input)
        input_widget.value = ""
        input_widget.placeholder = "Search models... Enter selects one match, Ctrl+G cancels"
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
        self._refresh_footer_bindings()
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

    def action_cancel_overlay(self) -> None:
        if self._mode == "model_select":
            self._exit_model_select_mode()
            return
        if self._mode == "pending_select":
            self._exit_pending_select_mode()
            return
        if self._mode == "chat_select":
            self._exit_chat_select_mode()
            return

    def _enter_pending_select_mode(self) -> None:
        self._mode = "pending_select"
        self._refresh_footer_bindings()
        self._pending_search = ""
        self.query_one("#chat_scroll", VerticalScroll).add_class("hidden")
        self.query_one("#model_select", Container).add_class("hidden")
        self.query_one("#pending_select", Container).remove_class("hidden")
        self.screen.add_class("pending-select-mode")

        input_widget = self.query_one("#input", Input)
        input_widget.value = ""
        input_widget.placeholder = "Search pending edits... Enter approve, Delete/Backspace reject, Ctrl+G cancels"
        input_widget.focus()
        self._render_pending_view()

    def _exit_pending_select_mode(self) -> None:
        self._mode = "chat"
        self._refresh_footer_bindings()
        self.query_one("#pending_select", Container).add_class("hidden")
        self.query_one("#chat_scroll", VerticalScroll).remove_class("hidden")
        self.screen.remove_class("pending-select-mode")

        input_widget = self.query_one("#input", Input)
        input_widget.value = ""
        input_widget.placeholder = "Type a message and press Enter..."
        input_widget.focus()
        self.query_one("#chat_scroll", VerticalScroll).scroll_end(animate=False)

    def _set_pending_header(self, text: str) -> None:
        self.query_one("#pending_header", Static).update(text)

    def _render_pending_view(self) -> None:
        if self._mode != "pending_select":
            return

        pending = self.state.edit_store.pending()
        query = self._pending_search.lower()
        visible = []
        for edit_id, edit in sorted(pending.items()):
            haystack = f"{edit.id} {edit.kind} {edit.status} {edit.path}".lower()
            if not query or query in haystack:
                visible.append(edit_id)

        self._visible_pending_ids = visible

        if not visible:
            self._selected_pending_id = None
            self._set_pending_header("No pending edits match your search. Ctrl+G returns to chat.")
            self.query_one("#pending_list", Static).update(Text("No pending edits.", style="dim"))
            self.query_one("#pending_diff", Static).update(Text("", style="dim"))
            return

        if self._selected_pending_id not in visible:
            self._selected_pending_id = visible[0]

        self._set_pending_header(
            f"{len(visible)} pending edit(s) — Up/Down select, Enter approve, Delete/Backspace reject, PageUp/PageDown scroll diff, Ctrl+G back."
        )
        self._render_pending_list()
        self._render_pending_diff()

    def _render_pending_list(self) -> None:
        text = Text()
        pending = self.state.edit_store.pending()
        for edit_id in self._visible_pending_ids:
            edit = pending.get(edit_id)
            if edit is None:
                continue
            marker = ">" if edit_id == self._selected_pending_id else " "
            path = str(edit.path)
            line = f"{marker} #{edit.id} [{edit.kind}] {path}\n"
            if edit_id == self._selected_pending_id:
                text.append(line, style="bold reverse")
            else:
                text.append(line)
        self.query_one("#pending_list", Static).update(text)

    def _render_pending_diff(self) -> None:
        edit = self._selected_pending_edit()
        if edit is None:
            self.query_one("#pending_diff", Static).update(Text("No pending edit selected.", style="dim"))
            return

        metadata = Text(
            f"Edit #{edit.id} [{edit.kind}] {edit.status}\n{edit.path}\n\n",
            style="bold",
        )
        diff_text = edit.diff if edit.diff.strip() else "(no diff)"
        diff_render = Text(no_wrap=False, overflow="fold")

        if self._theme_dark:
            add_style = "#7BC47F"
            del_style = "#E08A8A"
            hunk_style = "#E3A35C"
            file_style = "#66B8FF"
            meta_style = "#B8AFA7"
        else:
            add_style = "#2E7D32"
            del_style = "#B23A48"
            hunk_style = "#8A5A32"
            file_style = "#1565A0"
            meta_style = "#666666"

        for line in diff_text.splitlines(keepends=True):
            if line.startswith("+++") or line.startswith("---"):
                diff_render.append(line, style=file_style)
            elif line.startswith("@@"):
                diff_render.append(line, style=hunk_style)
            elif line.startswith("+"):
                diff_render.append(line, style=add_style)
            elif line.startswith("-"):
                diff_render.append(line, style=del_style)
            elif line.startswith("diff ") or line.startswith("index "):
                diff_render.append(line, style=meta_style)
            else:
                diff_render.append(line)

        renderable = Group(metadata, diff_render)
        self.query_one("#pending_diff", Static).update(renderable)
        self.query_one("#pending_diff_scroll", VerticalScroll).scroll_home(animate=False)

    def _selected_pending_edit(self):
        if self._selected_pending_id is None:
            return None
        return self.state.edit_store.get(self._selected_pending_id)

    def _select_pending_index(self, index: int) -> None:
        if not self._visible_pending_ids:
            return
        index = max(0, min(index, len(self._visible_pending_ids) - 1))
        self._selected_pending_id = self._visible_pending_ids[index]
        self._render_pending_list()
        self._render_pending_diff()

    def _move_pending_selection(self, delta: int) -> None:
        if not self._visible_pending_ids:
            return
        try:
            index = self._visible_pending_ids.index(self._selected_pending_id)
        except ValueError:
            index = 0
        self._select_pending_index(index + delta)

    def _scroll_pending_diff(self, amount: int) -> None:
        try:
            self.query_one("#pending_diff_scroll", VerticalScroll).scroll_relative(y=amount, animate=False)
        except Exception:
            pass

    def _approve_selected_pending(self) -> None:
        edit = self._selected_pending_edit()
        if edit is None:
            self._set_pending_header("No pending edit selected.")
            return
        try:
            message = self.state.edit_store.approve(edit.id)
            self._append_chat("System", message)
        except (KeyError, ValueError) as e:
            self._append_chat("Error", str(e))
        self._render_pending_view()
        self._refresh_state()

    def _reject_selected_pending(self) -> None:
        edit = self._selected_pending_edit()
        if edit is None:
            self._set_pending_header("No pending edit selected.")
            return
        try:
            message = self.state.edit_store.reject(edit.id)
            self._append_chat("System", message)
        except (KeyError, ValueError) as e:
            self._append_chat("Error", str(e))
        self._render_pending_view()
        self._refresh_state()

    def _set_chat_header(self, text: str) -> None:
        self.query_one("#chat_header", Static).update(text)

    def _enter_chat_select_mode(self) -> None:
        if self._processing:
            self._append_chat("System", "Cannot switch chats while AI is processing.")
            return

        self._mode = "chat_select"
        self._refresh_footer_bindings()
        self._chat_search = ""
        self.query_one("#chat_scroll", VerticalScroll).add_class("hidden")
        self.query_one("#model_select", Container).add_class("hidden")
        self.query_one("#pending_select", Container).add_class("hidden")
        self.query_one("#chat_select", Container).remove_class("hidden")
        self.screen.add_class("chat-select-mode")

        input_widget = self.query_one("#input", Input)
        input_widget.value = ""
        input_widget.placeholder = "Search chats... Enter loads selected chat, Ctrl+G cancels"
        input_widget.focus()

        self._render_chat_select_view()

    def _exit_chat_select_mode(self) -> None:
        self._mode = "chat"
        self._refresh_footer_bindings()
        self.query_one("#chat_select", Container).add_class("hidden")
        self.query_one("#chat_scroll", VerticalScroll).remove_class("hidden")
        self.screen.remove_class("chat-select-mode")

        input_widget = self.query_one("#input", Input)
        input_widget.value = ""
        input_widget.placeholder = "Type a message and press Enter..."
        input_widget.focus()
        self.query_one("#chat_scroll", VerticalScroll).scroll_end(animate=False)

    def _render_chat_select_view(self) -> None:
        if self._mode != "chat_select":
            return

        sessions = self.state.chat_store.list_sessions(limit=200)
        query = self._chat_search.lower()
        visible = []
        for session in sessions:
            haystack = (
                f"{session.session_id} {session.title} {session.updated_at} "
                f"{session.provider_label} {session.model}"
            ).lower()
            if not query or query in haystack:
                visible.append(session)

        self._visible_chat_sessions = visible

        if not visible:
            self._selected_chat_session_id = None
            self._set_chat_header("No chat sessions match your search. Ctrl+G returns to chat.")
            self.query_one("#chat_list", Static).update(Text("No chat sessions.", style="dim"))
            self.query_one("#chat_detail", Static).update(Text("", style="dim"))
            self.query_one("#chat_history", Static).update(Text("", style="dim"))
            return

        visible_ids = {s.session_id for s in visible}
        if self._selected_chat_session_id not in visible_ids:
            self._selected_chat_session_id = visible[0].session_id

        self._set_chat_header(
            f"{len(visible)} chat session(s) — Up/Down select, Enter load, PageUp/PageDown scroll panes, Ctrl+G back."
        )
        self._render_chat_list()
        self._render_chat_detail()

    def _render_chat_list(self) -> None:
        text = Text(no_wrap=True, overflow="ellipsis")
        selected_index = 0
        for index, session in enumerate(self._visible_chat_sessions):
            selected = session.session_id == self._selected_chat_session_id
            if selected:
                selected_index = index
            marker = ">" if selected else " "

            # Keep each chat entry to exactly one visual row. The detail pane
            # contains the full timestamp/provider/model/title; the list must
            # stay compact so scroll math can map one session to one row.
            title = str(session.title or "").strip()
            title_text = f" {title[:10]}" if title else ""
            line = f"{marker} {session.session_id[:10]} {session.turn_count}t{title_text}\n"

            if selected:
                text.append(line, style="bold reverse")
            else:
                text.append(line)
        self.query_one("#chat_list", Static).update(text)
        self.call_after_refresh(self._scroll_chat_list_to_selected, selected_index)

    def _scroll_chat_list_to_selected(self, selected_index: int) -> None:
        if selected_index < 0:
            return
        try:
            scroll = self.query_one("#chat_list_scroll", VerticalScroll)
        except Exception:
            return

        # Keep the selected row roughly centered. This avoids fragile edge
        # detection against Textual scroll internals while keeping the selected
        # chat visible when navigating long lists.
        visible_rows = max(1, getattr(scroll.size, "height", 1) - 2)
        target_y = max(0, selected_index - (visible_rows // 2))
        scroll.scroll_to(y=target_y, animate=False)

    def _selected_chat_summary(self):
        if not self._selected_chat_session_id:
            return None
        for session in self._visible_chat_sessions:
            if session.session_id == self._selected_chat_session_id:
                return session
        return None

    def _render_chat_detail(self) -> None:
        session = self._selected_chat_summary()
        if session is None:
            self.query_one("#chat_detail", Static).update(Text("No chat selected.", style="dim"))
            return

        turns = self.state.chat_store.load_original_turns(session.session_id, limit=20)

        detail = Text(
            f"Session details\n"
            f"id: {session.session_id}\n"
            f"created: {session.created_at}\n"
            f"updated: {session.updated_at}\n"
            f"provider/model: {session.provider_label} / {session.model}\n"
            f"turns: {session.turn_count}",
            style="bold",
        )
        self.query_one("#chat_detail", Static).update(detail)
        self.query_one("#chat_detail_scroll", VerticalScroll).scroll_home(animate=False)

        history_parts: list[Any] = [Text("History preview (last 20 turns)\n", style="bold")]
        if not turns:
            history_parts.append(Text("No turns recorded yet.", style="dim"))
        else:
            first = True
            for turn in turns:
                user_text = str(turn.get("user", ""))
                assistant_text = str(turn.get("assistant_final", ""))

                if not first:
                    history_parts.append(Text(""))
                history_parts.append(self._message_renderable("You", user_text))
                history_parts.append(Text(""))
                history_parts.append(self._message_renderable("AI", assistant_text))
                first = False

        self.query_one("#chat_history", Static).update(Group(*history_parts))
        self._scroll_chat_history_to_bottom()

    def _scroll_chat_history_to_bottom(self) -> None:
        self._scroll_chat_history_to_bottom_once()
        self.call_after_refresh(self._scroll_chat_history_to_bottom_once)
        self.set_timer(0.05, self._scroll_chat_history_to_bottom_once)

    def _scroll_chat_history_to_bottom_once(self) -> None:
        try:
            self.query_one("#chat_history_scroll", VerticalScroll).scroll_end(animate=False)
        except Exception:
            pass

    def _select_chat_index(self, index: int) -> None:
        if not self._visible_chat_sessions:
            return
        index = max(0, min(index, len(self._visible_chat_sessions) - 1))
        self._selected_chat_session_id = self._visible_chat_sessions[index].session_id
        self._render_chat_list()
        self._render_chat_detail()

    def _move_chat_selection(self, delta: int) -> None:
        if not self._visible_chat_sessions:
            return
        ids = [s.session_id for s in self._visible_chat_sessions]
        try:
            index = ids.index(self._selected_chat_session_id)
        except ValueError:
            index = 0
        self._select_chat_index(index + delta)

    def _submit_chat_selection(self) -> None:
        session = self._selected_chat_summary()
        if session is None:
            self._set_chat_header("No chat selected.")
            return

        turns = self.state.chat_store.load_original_turns(session.session_id, limit=20)

        self.state.chat_session_id = session.session_id

        latest_state = None
        if turns:
            maybe_state = turns[-1].get("state")
            if isinstance(maybe_state, dict):
                latest_state = maybe_state

        provider_key = str((latest_state or {}).get("provider_key", "")).strip()
        model = str((latest_state or {}).get("model", "")).strip()
        provider = PROVIDERS.get(provider_key) if provider_key else None
        if provider is not None and model:
            try:
                self._rebuild_runtime_for_provider_model(provider, model)
            except Exception as e:
                self._append_chat("Error", f"Failed to restore provider/model from chat state: {e}")
                self._append_log("error", f"chat restore failed for provider={provider_key}, model={model}: {e}")

        self._messages.clear()
        for turn in turns:
            user_text = str(turn.get("user", ""))
            assistant_text = str(turn.get("assistant_final", ""))
            self._messages.append(("You", user_text))
            self._messages.append(("AI", assistant_text))
        self._render_chat()

        if self.agent is not None:
            self.agent.reset(build_system_prompt())
            for turn in turns:
                self.agent.messages.append({"role": "user", "content": str(turn.get("user", ""))})
                self.agent.messages.append({"role": "assistant", "content": str(turn.get("assistant_final", ""))})

        self._exit_chat_select_mode()
        self._refresh_state()
        self._append_chat("System", f"Loaded chat session: {session.session_id}")

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
            self._set_model_header("No matching models. Change the search text or press Ctrl+G to cancel.")
        elif query:
            self._set_model_header(
                f"{len(visible_matches)} matching model(s). Narrow to one and press Enter, or select a tree item."
            )
        else:
            self._set_model_header(
                "Select a model from the tree. Type to search; Enter selects one match; Ctrl+G cancels."
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
            self._set_model_header("No matching models. Change the search text or press Ctrl+G to cancel.")
            return

        self._set_model_header(
            f"{len(self._visible_model_matches)} matches. Narrow search to one model or select a tree item."
        )

    def _rebuild_runtime_for_provider_model(self, provider, model: str) -> None:
        """Atomically rebuild model config, llm client, and agent for a provider/model."""
        config, llm = build_model_config_and_client(provider, model)

        # Replace runtime bundle atomically: state config + llm + fresh agent.
        self.state.model_config = config
        self.llm = llm
        if self.agent is None:
            self.agent = create_agent(
                state=self.state,
                llm=self.llm,
                on_debug=self._on_debug,
                on_tool=self._on_tool,
                on_raw=self._on_raw,
                on_error=self._on_error,
                on_display=self._on_display,
            )
        else:
            self.agent.set_llm(
                self.llm,
                system_prompt=build_system_prompt(
                    self.state,
                    use_native_tools=getattr(self.llm, 'supports_native_tools', False),
                ),
            )
        self._refresh_state()

    def _switch_model(self, provider_key: str, model: str) -> None:
        provider = PROVIDERS.get(provider_key)
        if provider is None:
            self._set_model_header(f"Unknown provider: {provider_key}")
            return

        try:
            self._rebuild_runtime_for_provider_model(provider, model)
        except Exception as e:
            self._set_model_header(f"Model switch failed: {e}")
            return

        self._exit_model_select_mode()
        self._append_chat(
            "System",
            f"Model changed to {self.state.model_config.provider_label} / {self.state.model_config.model}.",
        )

    def action_toggle_theme(self) -> None:
        self._theme_dark = not self._theme_dark
        if self._theme_dark:
            self.screen.remove_class("theme-light")
            self.screen.add_class("theme-dark")
        else:
            self.screen.remove_class("theme-dark")
            self.screen.add_class("theme-light")

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action in {"toggle_theme", "open_pending", "open_models", "open_chats"}:
            return self._mode == "chat"

        if action == "cancel_overlay":
            return self._mode in {"model_select", "pending_select", "chat_select"}

        return True

    def _refresh_footer_bindings(self) -> None:
        try:
            self.refresh_bindings()
        except AttributeError:
            try:
                self.query_one(Footer).refresh()
            except Exception:
                pass

    def action_open_pending(self) -> None:
        if self._mode != "chat":
            return
        self._enter_pending_select_mode()

    def action_open_models(self) -> None:
        if self._mode != "chat":
            return
        self._enter_model_select_mode()

    def action_open_chats(self) -> None:
        if self._mode != "chat":
            return
        self._enter_chat_select_mode()

    def _start_agent_step(self, text: str) -> None:
        self._set_processing(True)
        self._run_agent_step(text)

    @work(thread=True, exclusive=True)
    def _run_agent_step(self, text: str) -> None:
        try:
            if self.agent is None:
                raise RuntimeError("Agent is not initialized.")

            reply = self.agent.step(text)
            try:
                record_final_turn(self.state, text, reply)
            except Exception as history_error:
                print(f"[history] write failed: {history_error}", flush=True)
            self._from_any_thread(self._append_chat, "AI", reply)
        except Exception as e:
            print(f"[error] {e}", flush=True)
            self._from_any_thread(self._append_chat, "Error", str(e))
        finally:
            self._from_any_thread(self._finish_agent_step)

    def _finish_agent_step(self) -> None:
        self._set_processing(False)
        self._refresh_state()

    def _set_processing(self, processing: bool) -> None:
        self._processing = processing
        input_widget = self.query_one("#input", Input)
        input_widget.disabled = False
        if self._mode == "model_select":
            input_widget.placeholder = "Search models... Enter selects one match, Ctrl+G cancels"
        elif self._mode == "pending_select":
            input_widget.placeholder = "Search pending edits... Enter approve, Delete/Backspace reject, Ctrl+G cancels"
        elif self._mode == "chat_select":
            input_widget.placeholder = "Search chats... Enter loads selected chat, Ctrl+G cancels"
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
        if who == "System":
            return Text(text, style="dim")
        return Text(text)

    def _format_ai_markdown(self, text: str):
        try:
            from textual.reactive import Reactive
            # Light theme -> no code background (avoids black boxes on white)
            # Dark theme -> use a dark syntax theme for proper highlighting
            code_theme = "" if not self._theme_dark else "dracula"
            return Markdown(text, code_theme=code_theme)
        except Exception:
            return Text(text)


    def _append_log(self, kind: str, text: str) -> None:
        print(f"[{kind}] {text}", flush=True)

    def _refresh_header(self) -> None:
        model_text = (
            f"{self.state.model_config.provider_label} / "
            f"{self.state.model_config.model}"
        )
        pending_count = len(self.state.edit_store.pending())

        self.query_one("#status_cwd", Static).update(str(self.state.cwd))
        self.query_one("#status_model", Static).update(model_text)
        self.query_one("#status_edits", Static).update(f"pending edits: {pending_count}")

    def _refresh_state(self) -> None:
        self._refresh_header()

    def _state_text(self) -> str:
        session_text = self.state.chat_session_id or "no active chat"
        return (
            f"cwd: {self.state.cwd}\n"
            f"provider: {self.state.model_config.provider_label}\n"
            f"model: {self.state.model_config.model}\n"
            f"api_type: {self.state.model_config.api_type}\n"
            f"chat_session: {session_text}"
        )

    def action_input_complete_command(self) -> None:
        input_widget = self.query_one("#input", Input)
        if self.focused is not input_widget:
            return

        if self._mode != "chat":
            return

        value = input_widget.value
        cursor = input_widget.cursor_position

        # Command completion is intentionally scoped to simple command input at
        # the end of the line. This avoids surprising edits inside normal chat
        # messages or partially typed arguments.
        if cursor != len(value) or not value.startswith("\\") or any(ch.isspace() for ch in value):
            self._reset_command_completion()
            return

        if (
            len(self._command_completion_matches) > 1
            and (value == self._command_completion_prefix or value in self._command_completion_matches)
        ):
            if value in self._command_completion_matches:
                current_index = self._command_completion_matches.index(value)
                next_index = (current_index + 1) % len(self._command_completion_matches)
            else:
                next_index = 0
            self._command_completion_index = next_index
            self._apply_command_completion(self._command_completion_matches[next_index])
            return

        matches = [command for command in self.COMMANDS if command.startswith(value)]
        if not matches:
            self._reset_command_completion()
            return

        if len(matches) == 1:
            self._command_completion_prefix = matches[0]
            self._command_completion_matches = matches
            self._command_completion_index = 0
            self._apply_command_completion(matches[0])
            return

        common_prefix = self._longest_common_prefix(matches)
        self._command_completion_prefix = common_prefix
        self._command_completion_matches = matches
        self._command_completion_index = -1

        if len(common_prefix) > len(value):
            self._apply_command_completion(common_prefix)
            return

        self._command_completion_index = 0
        self._apply_command_completion(matches[0])

    def _apply_command_completion(self, text: str) -> None:
        input_widget = self.query_one("#input", Input)
        input_widget.value = text
        input_widget.cursor_position = len(text)
        input_widget.focus()

    def _reset_command_completion(self) -> None:
        self._command_completion_prefix = ""
        self._command_completion_matches = []
        self._command_completion_index = -1

    def _longest_common_prefix(self, values: list[str]) -> str:
        if not values:
            return ""

        prefix = values[0]
        for value in values[1:]:
            while not value.startswith(prefix):
                prefix = prefix[:-1]
                if not prefix:
                    return ""
        return prefix



    def action_input_delete_word_left(self) -> None:
        input_widget = self.query_one("#input", Input)
        if self.focused is not input_widget:
            return

        value = input_widget.value
        cursor = input_widget.cursor_position

        if cursor <= 0:
            return

        left = value[:cursor]
        right = value[cursor:]

        i = len(left)
        while i > 0 and left[i - 1].isspace():
            i -= 1
        while i > 0 and not left[i - 1].isspace():
            i -= 1

        input_widget.value = left[:i] + right
        input_widget.cursor_position = i

    def action_input_delete_word_right(self) -> None:
        input_widget = self.query_one("#input", Input)
        if self.focused is not input_widget:
            return

        value = input_widget.value
        cursor = input_widget.cursor_position

        if cursor >= len(value):
            return

        left = value[:cursor]
        right = value[cursor:]

        j = 0
        while j < len(right) and right[j].isspace():
            j += 1
        while j < len(right) and not right[j].isspace():
            j += 1

        input_widget.value = left + right[j:]
        input_widget.cursor_position = cursor

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
