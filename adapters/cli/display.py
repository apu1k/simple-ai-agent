"""
io/cli/display.py

Rich-based terminal display. Renders DisplayItems, panels, banners, etc.
Migrated from utils/ui.py.
"""

from contextlib import contextmanager

from rich.panel import Panel
from rich.spinner import SPINNERS
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from adapters.cli.logger import console, is_debug_enabled
from tools._base import DisplayItem


PROCESSING_SPINNER = "star2" if "star2" in SPINNERS else "dots"


def show_startup_banner(state) -> None:
    debug_status = "on" if is_debug_enabled() else "off"
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold cyan", no_wrap=True)
    table.add_column(style="white")
    table.add_row("cwd", str(state.cwd))
    table.add_row("provider", state.model_config.provider_label)
    table.add_row("model", state.model_config.model)
    table.add_row("api_type", state.model_config.api_type)
    table.add_row("debug", debug_status)
    console.print()
    console.print(Panel(table, title="simple-ai-agent", subtitle="Local AI Agent", border_style="green", expand=False))
    console.print()


def show_help() -> None:
    table = Table(title="Available Commands", show_header=True, header_style="bold cyan", border_style="blue")
    table.add_column("Command", style="cyan", no_wrap=True)
    table.add_column("Description", style="white")
    rows = [
        ("\\help", "Show this help message"),
        ("\\state", "Show current agent state"),
        ("\\pwd", "Show current working directory"),
        ("\\cd <path>", "Change working directory without using the LLM"),
        ("\\models", "Select a different provider/model"),
        ("\\debug", "Show current debug status"),
        ("\\debug on", "Enable debug output"),
        ("\\debug off", "Disable debug output"),
        ("\\reset", "Reset conversation context"),
        ("\\exit / \\quit", "Exit the agent"),
        ("\\pending", "Show pending file edits"),
        ("\\pending <id>", "Show git-style diff for a proposed edit (any status)"),
        ("\\pending diff <id>", "Alias for showing edit diff"),
        ("\\approve <id>", "Approve and apply a pending edit"),
        ("\\reject <id>", "Reject a pending edit"),
    ]
    for row in rows:
        table.add_row(*row)
    console.print(table)


def show_input_help() -> None:
    from adapters.cli.input import is_advanced_input_available
    table = Table(title="Input Shortcuts", show_header=True, header_style="bold magenta", border_style="magenta")
    table.add_column("Shortcut", style="magenta", no_wrap=True)
    table.add_column("Action", style="white")
    if is_advanced_input_available():
        table.add_row("Enter", "Submit input")
        table.add_row("Shift+Enter", "Insert newline (if terminal supports it)")
        table.add_row("Esc then Enter", "Insert newline fallback")
        table.add_row("Ctrl+O", "Insert newline fallback")
        table.add_row("Arrow Up/Down", "Navigate input history")
    else:
        table.add_row("Enter", "Submit input")
        table.add_row("Multiline", "Unavailable. Install prompt_toolkit to enable.")
    console.print(table)


def show_state(state) -> None:
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold cyan", no_wrap=True)
    table.add_column(style="white")
    table.add_row("cwd", str(state.cwd))
    table.add_row("provider", state.model_config.provider_label)
    table.add_row("model", state.model_config.model)
    table.add_row("api_type", state.model_config.api_type)
    table.add_row("debug", "on" if is_debug_enabled() else "off")
    console.print(Panel(table, title="Agent State", border_style="cyan", expand=False))


def show_debug_status() -> None:
    enabled = is_debug_enabled()
    status = "on" if enabled else "off"
    style = "green" if enabled else "yellow"
    console.print(Panel(Text(f"Debug is currently {status}."), title="Debug", border_style=style, expand=False))


def show_debug_changed(enabled: bool) -> None:
    status = "enabled" if enabled else "disabled"
    style = "green" if enabled else "yellow"
    console.print(Panel(Text(f"Debug output {status}."), title="Debug", border_style=style, expand=False))


def show_model_changed(state) -> None:
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold cyan", no_wrap=True)
    table.add_column(style="white")
    table.add_row("provider", state.model_config.provider_label)
    table.add_row("model", state.model_config.model)
    table.add_row("api_type", state.model_config.api_type)
    console.print(Panel(table, title="Model Changed", border_style="green", expand=False))


def show_command_error(message: str) -> None:
    console.print(Panel(Text(str(message)), title="Command Error", border_style="red", expand=False))


def show_command_message(message: str, title="Info", border_style="white") -> None:
    console.print(Panel(Text(str(message)), title=str(title), border_style=border_style, expand=False))


def show_pending_diff(edit_id: int, path: str, status: str, diff_text: str) -> None:
    title = f"Edit #{edit_id} [{status}]"
    subtitle = path
    content = diff_text if diff_text.strip() else "(no diff)"

    try:
        renderable = Syntax(
            content,
            "diff",
            line_numbers=False,
            word_wrap=False,
        )
    except Exception:
        renderable = Text(content)

    console.print(Panel(renderable, title=title, subtitle=subtitle, border_style="cyan", expand=False))


def show_display_item(item: DisplayItem) -> None:
    if item.kind != "file":
        show_command_error(f"Unsupported display item kind: {item.kind}")
        return

    if not item.content:
        renderable = Text("(empty file)", style="dim")
    else:
        try:
            renderable = Syntax(
                item.content,
                item.language or "text",
                line_numbers=True,
                start_line=max(item.start_line, 1),
                word_wrap=False,
            )
        except Exception:
            renderable = Text(item.content)

    console.print()
    console.print(Panel(renderable, title=item.title, border_style="cyan", expand=False))
    console.print()


def show_display_items(items: list[DisplayItem]) -> None:
    for item in items:
        show_display_item(item)


@contextmanager
def show_processing(message="AI is processing..."):
    with console.status(f"[bold cyan]{message}[/bold cyan]", spinner=PROCESSING_SPINNER):
        yield
