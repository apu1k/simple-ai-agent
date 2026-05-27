"""
runtime/bootstrap.py

Shared composition helpers for all frontends.

This module contains setup code needed by both:
- CLI runtime
- future Textual/web runtime

It must not contain terminal-specific input/output code.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from core.agent import Agent
from core.tool_registry import autodiscover
from llm.providers import create_llm_client
from runtime.prompt import build_system_prompt
from runtime.state import AgentState, ModelConfig


def initialize_tools() -> None:
    """Autodiscover all @tool-decorated functions."""
    autodiscover("tools")


def build_model_config_and_client(provider, model) -> tuple[ModelConfig, object]:
    """Create ModelConfig and LLM client from selected provider/model."""
    if not provider.api_key:
        envs = ", ".join(provider.api_key_envs) if provider.api_key_envs else "none configured"
        raise ValueError(
            f"Missing API key for provider '{provider.label}'. "
            f"Expected one of these environment variables: {envs}"
        )

    config = ModelConfig(
        provider_key=provider.key,
        provider_label=provider.label,
        model=model,
        api_key=provider.api_key,
        base_url=provider.base_url,
        api_type=provider.api_type,
    )

    llm = create_llm_client(provider, model)
    return config, llm


def create_initial_state(model_config: ModelConfig) -> AgentState:
    """Create initial runtime state."""
    return AgentState(
        cwd=Path.cwd(),
        model_config=model_config,
    )


def create_agent(
    *,
    state: AgentState,
    llm: object,
    on_debug: Callable[[str], None] | None = None,
    on_tool: Callable[[str], None] | None = None,
    on_raw: Callable[[str], None] | None = None,
    on_error: Callable[[str], None] | None = None,
    on_display: Callable[[list], None] | None = None,
) -> Agent:
    """Create an Agent wired with frontend callbacks."""
    return Agent(
        system_prompt=build_system_prompt(),
        state=state,
        llm=llm,
        on_debug=on_debug,
        on_tool=on_tool,
        on_raw=on_raw,
        on_error=on_error,
        on_display=on_display,
    )
