"""
adapters/cli/adapter.py

CLIAdapter — implements adapters/base.py IOAdapter for the terminal.

Wires together: logger, display, input.
Passed to runtime/loop.py as the IO implementation.
"""

from contextlib import contextmanager

from adapters.cli import display, logger
from adapters.cli.input import read_user_input


class CLIAdapter:
    """Terminal IO adapter using Rich for output and prompt_toolkit for input."""

    def read_input(self) -> str:
        return read_user_input()

    def show_response(self, text: str) -> None:
        logger.ai_response(text)

    def show_display_items(self, items: list) -> None:
        display.show_display_items(items)

    def show_error(self, message: str) -> None:
        logger.error(message)

    def show_debug(self, message: str) -> None:
        logger.debug(message)

    def show_tool(self, message: str) -> None:
        logger.tool_log(message)

    def show_raw(self, message: str) -> None:
        logger.raw(message)

    @contextmanager
    def show_processing(self, message="AI is processing..."):
        with display.show_processing(message):
            yield