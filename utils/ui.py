from contextlib import contextmanager

from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from utils.logger import console, is_debug_enabled


try:
    from rich.spinner import SPINNERS
except Exception:
    SPINNERS = {}


PROCESSING_SPINNER = "star2" if "star2" in SPINNERS else "dots"


def show_startup_banner(state):
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
    console.print(
        Panel(
            table,
            title="simple-ai-agent",
            subtitle="Local AI Agent",
            border_style="green",
            expand=False,
        )
    )
    console.print()


def show_help():
    table = Table(
        title="Available Commands",
        show_header=True,
        header_style="bold cyan",
        border_style="blue",
    )

    table.add_column("Command", style="cyan", no_wrap=True)
    table.add_column("Description", style="white")

    table.add_row("\\help", "Show this help message")
    table.add_row("\\state", "Show current agent state")
    table.add_row("\\pwd", "Show current working directory")
    table.add_row("\\cd <path>", "Change current working directory without using the LLM")
    table.add_row("\\models", "Select a different provider/model without restarting")
    table.add_row("\\debug", "Show current debug status")
    table.add_row("\\debug on", "Enable debug output")
    table.add_row("\\debug off", "Disable debug output")
    table.add_row("\\reset", "Reset conversation context but keep current state")
    table.add_row("\\exit / \\quit", "Exit the agent")

    console.print(table)


def show_input_help():
    from utils.input import is_advanced_input_available

    table = Table(
        title="Input Shortcuts",
        show_header=True,
        header_style="bold magenta",
        border_style="magenta",
    )

    table.add_column("Shortcut", style="magenta", no_wrap=True)
    table.add_column("Action", style="white")

    if is_advanced_input_available():
        table.add_row("Enter", "Submit input")
        table.add_row("Shift+Enter", "Insert newline, if supported by your terminal")
        table.add_row("Esc then Enter", "Insert newline fallback")
        table.add_row("Ctrl+O", "Insert newline fallback")
        table.add_row("Arrow Up/Down", "Navigate input history")
    else:
        table.add_row("Enter", "Submit input")
        table.add_row(
            "Multiline input",
            "Unavailable. Install prompt_toolkit to enable Shift+Enter/history.",
        )

    console.print(table)


def show_state(state):
    debug_status = "on" if is_debug_enabled() else "off"

    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold cyan", no_wrap=True)
    table.add_column(style="white")

    table.add_row("cwd", str(state.cwd))
    table.add_row("provider", state.model_config.provider_label)
    table.add_row("model", state.model_config.model)
    table.add_row("api_type", state.model_config.api_type)
    table.add_row("debug", debug_status)

    console.print(
        Panel(
            table,
            title="Agent State",
            border_style="cyan",
            expand=False,
        )
    )


def show_debug_status():
    enabled = is_debug_enabled()
    status = "on" if enabled else "off"
    style = "green" if enabled else "yellow"

    console.print(
        Panel(
            Text(f"Debug is currently {status}."),
            title="Debug",
            border_style=style,
            expand=False,
        )
    )


def show_debug_changed(enabled):
    status = "enabled" if enabled else "disabled"
    style = "green" if enabled else "yellow"

    console.print(
        Panel(
            Text(f"Debug output {status}."),
            title="Debug",
            border_style=style,
            expand=False,
        )
    )


def show_model_changed(state):
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold cyan", no_wrap=True)
    table.add_column(style="white")

    table.add_row("provider", state.model_config.provider_label)
    table.add_row("model", state.model_config.model)
    table.add_row("api_type", state.model_config.api_type)

    console.print(
        Panel(
            table,
            title="Model Changed",
            border_style="green",
            expand=False,
        )
    )


def show_command_error(message):
    console.print(
        Panel(
            Text(str(message)),
            title="Command Error",
            border_style="red",
            expand=False,
        )
    )


def show_command_message(message, title="Info", border_style="white"):
    console.print(
        Panel(
            Text(str(message)),
            title=str(title),
            border_style=border_style,
            expand=False,
        )
    )


@contextmanager
def show_processing(message="AI is processing..."):
    with console.status(
        f"[bold cyan]{message}[/bold cyan]",
        spinner=PROCESSING_SPINNER,
    ):
        yield