"""
adapters/base.py

Abstract IO adapter protocol.

Swap the entire UI (CLI → voice → web) by implementing this protocol
and passing the new adapter to runtime/loop.py.
"""

from contextlib import contextmanager
from typing import Iterator, Protocol, runtime_checkable


@runtime_checkable
class IOAdapter(Protocol):
    def read_input(self) -> str:
        """Read the next user input. Blocks until available."""
        ...

    def show_response(self, text: str) -> None:
        """Display a final AI response to the user."""
        ...

    def show_display_items(self, items: list) -> None:
        """Render a list of DisplayItem objects (e.g. file panels)."""
        ...

    def show_error(self, message: str) -> None:
        """Show an error message."""
        ...

    def show_debug(self, message: str) -> None:
        """Show a debug message (may be a no-op if debug is off)."""
        ...

    def show_tool(self, message: str) -> None:
        """Show a tool call log message."""
        ...

    def show_raw(self, message: str) -> None:
        """Show the raw LLM response string."""
        ...

    def show_processing(self, message: str = "") -> Iterator[None]:
        """Context manager shown while the agent is processing."""
        ...