"""Compose Textual as a client of an independently owned agent runtime."""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

from adapters.textual.app import AgentTextualApp

if TYPE_CHECKING:
    from runtime.remote import RemoteRuntimeClient
    from runtime.service import AgentRuntime


def create_textual_app(
    *, runtime: AgentRuntime | RemoteRuntimeClient | None = None,
) -> AgentTextualApp:
    """Remote by default; local mode is explicit and retains live UAC review."""
    if runtime is None:
        mode = os.environ.get("AI_AGENT_MODE", "remote")
        if mode == "local":
            from runtime.bootstrap import create_default_runtime
            runtime = create_default_runtime()
        elif mode == "remote":
            from runtime.remote import RemoteRuntimeClient
            runtime = RemoteRuntimeClient.from_environment()
        else:
            raise ValueError("AI_AGENT_MODE must be remote or local")
    return AgentTextualApp(runtime=runtime)
