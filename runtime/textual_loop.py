"""
runtime/textual_loop.py

Textual composition root.

Creates the Textual app using shared bootstrap helpers. This module intentionally
avoids terminal input/output and is the starting point for the future browser UI.
"""

from __future__ import annotations

from adapters.textual.app import AgentTextualApp
from llm.providers import PROVIDERS
from runtime.bootstrap import (
    build_model_config_and_client,
    create_initial_state,
    initialize_tools,
)


def _select_default_model_config():
    """
    Select the first configured provider and its default model.

    This is intentionally simple for Textual Phase 2. A real provider/model
    selector modal belongs in a later phase.
    """
    if not PROVIDERS:
        raise ValueError("No providers configured.")

    # Prefer OpenAI for default startup if configured; fallback to first provider.
    provider = PROVIDERS.get("openai") or next(iter(PROVIDERS.values()))
    model = provider.default_model

    if not model:
        raise ValueError(
            f"Provider '{provider.label}' has no default_model configured. "
            "Configure default_model for Textual Phase 2."
        )

    return build_model_config_and_client(provider, model)


def create_textual_app() -> AgentTextualApp:
    """Create and return the Textual application instance."""
    initialize_tools()

    model_config, llm = _select_default_model_config()
    state = create_initial_state(model_config)

    return AgentTextualApp(
        state=state,
        llm=llm,
    )
