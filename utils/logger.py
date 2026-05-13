from rich.console import Console
from rich.panel import Panel


console = Console()
error_console = Console(stderr=True)


_DEBUG_ENABLED = False


def set_debug(enabled: bool):
    global _DEBUG_ENABLED
    _DEBUG_ENABLED = bool(enabled)


def is_debug_enabled():
    return _DEBUG_ENABLED


def user(msg):
    console.print(str(msg), style="cyan", markup=False)


def ai(msg):
    console.print(str(msg), style="white", markup=False)


def debug(msg):
    if not _DEBUG_ENABLED:
        return

    console.print(
        Panel(
            str(msg),
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
            str(msg),
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
            str(msg),
            title="RAW MODEL RESPONSE",
            border_style="blue",
            expand=False,
        )
    )


def error(msg):
    error_console.print(
        Panel(
            str(msg),
            title="ERROR",
            border_style="red",
            expand=False,
        )
    )