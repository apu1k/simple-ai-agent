"""
runtime/loop.py

Backward-compatible wrapper for the old CLI runtime import path.

New code should import from runtime.cli_loop.
"""

from runtime.cli_loop import run_cli_agent


def run_agent() -> None:
    """Backward-compatible alias for the CLI agent entrypoint."""
    run_cli_agent()
