"""Compose Textual as a client of an independently owned agent runtime."""
from __future__ import annotations

from adapters.textual.app import AgentTextualApp
from runtime.bootstrap import create_default_runtime
from runtime.service import AgentRuntime


def create_textual_app(*, runtime: AgentRuntime | None = None) -> AgentTextualApp:
    """An injected runtime may outlive this app and serve multiple clients."""
    return AgentTextualApp(runtime=runtime if runtime is not None else create_default_runtime())
