"""
io/cli/logger.py

Rich-based terminal logging. Migrated from utils/logger.py.
"""

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text


console = Console()
error_console = Console(stderr=True)

_DEBUG_ENABLED = False


def set_debug(enabled: bool) -> None:
    global _DEBUG_ENABLED
    _DEBUG_ENABLED = bool(enabled)


def is_debug_enabled() -> bool:
    return _DEBUG_ENABLED


def ai_response(msg) -> None:
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


def debug(msg) -> None:
    if not _DEBUG_ENABLED:
        return
    console.print(Panel(Text(str(msg)), title="DEBUG", border_style="yellow", expand=False))


def tool_log(msg) -> None:
    if not _DEBUG_ENABLED:
        return
    console.print(Panel(Text(str(msg)), title="TOOL", border_style="green", expand=False))


def raw(msg) -> None:
    if not _DEBUG_ENABLED:
        return
    console.print(Panel(Text(str(msg)), title="RAW MODEL RESPONSE", border_style="blue", expand=False))


def error(msg) -> None:
    error_console.print(Panel(Text(str(msg)), title="ERROR", border_style="red", expand=False))
