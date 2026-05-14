from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text


console = Console()
error_console = Console(stderr=True)


_DEBUG_ENABLED = False


def set_debug(enabled: bool):
    global _DEBUG_ENABLED
    _DEBUG_ENABLED = bool(enabled)


def is_debug_enabled():
    return _DEBUG_ENABLED


def user(msg):
    console.print(Text(str(msg), style="cyan"))


def ai(msg):
    console.print(Text(str(msg), style="white"))


def ai_response(msg):
    text = "" if msg is None else str(msg)

    console.print()
    console.print(Rule("AI", style="white"))

    if not text.strip():
        console.print(Text("(empty response)", style="dim white"))
        console.print()
        return

    try:
        console.print(Markdown(text))
    except Exception:
        console.print(Text(text, style="white"))

    console.print()


def debug(msg):
    if not _DEBUG_ENABLED:
        return

    console.print(
        Panel(
            Text(str(msg)),
            title="DEBUG",
            border_style="yellow",
            expand=False,
        )
    )


def tool(msg):
    if not _DEBUG_ENABLED:
        return

    console.print(
        Panel(
            Text(str(msg)),
            title="TOOL",
            border_style="green",
            expand=False,
        )
    )


def raw(msg):
    if not _DEBUG_ENABLED:
        return

    console.print(
        Panel(
            Text(str(msg)),
            title="RAW MODEL RESPONSE",
            border_style="blue",
            expand=False,
        )
    )


def error(msg):
    error_console.print(
        Panel(
            Text(str(msg)),
            title="ERROR",
            border_style="red",
            expand=False,
        )
    )