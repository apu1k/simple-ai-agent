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
from llm.providers import create_llm_client, PROVIDERS
from config.settings import DEBUG_LOGS

# Debug: print loaded providers (gated)
import sys
if DEBUG_LOGS:
    print("=== BOOTSTRAP PROVIDERS ===", file=sys.stderr)
    for key, p in PROVIDERS.items():
        print(f"  {key}: api_type={p.api_type}, model={p.default_model}", file=sys.stderr)
    print("===========================", file=sys.stderr)
from runtime.chat_store import ChatStore
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

    from llm.providers import ProviderConfig

    effective_provider = ProviderConfig(
        key=config.provider_key,
        label=config.provider_label,
        api_key=config.api_key,
        base_url=config.base_url,
        api_type=config.api_type,
        default_model=config.model,
        supports_model_listing=provider.supports_model_listing,
        api_key_envs=provider.api_key_envs,
    )

    llm = create_llm_client(effective_provider, config.model)

    # Hard runtime diagnostics: confirms actual selected provider/client/api_type
    if DEBUG_LOGS:
        import sys
        print("=== MODEL CLIENT CREATED ===", file=sys.stderr)
        print(f"provider.key={provider.key}", file=sys.stderr)
        print(f"provider.label={provider.label}", file=sys.stderr)
        print(f"provider.api_type={provider.api_type}", file=sys.stderr)
        print(f"selected_model={model}", file=sys.stderr)
        print(f"llm.class={llm.__class__.__module__}.{llm.__class__.__name__}", file=sys.stderr)
        print(f"llm.api_type={getattr(llm, 'api_type', '<missing>')}", file=sys.stderr)
        print(f"llm.supports_native_tools={getattr(llm, 'supports_native_tools', False)}", file=sys.stderr)
        print(
            f"llm.supports_native_tool_outputs={getattr(llm, 'supports_native_tool_outputs', False)}",
            file=sys.stderr,
        )
        print("============================", file=sys.stderr)

    return config, llm


def create_initial_state(model_config: ModelConfig) -> AgentState:
    """Create initial runtime state."""
    return AgentState(
        cwd=Path.cwd(),
        model_config=model_config,
        chat_store=ChatStore(background_indexing_enabled=True),
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
    """Create an Agent wired with frontend callbacks.
    
    Automatically detects if the LLM supports native tool calling
    and builds the system prompt accordingly.
    """
    # Detect native tool support
    use_native_tools = getattr(llm, 'supports_native_tools', False)
    
    # Build prompt with appropriate tool instructions
    system_prompt = build_system_prompt(state, use_native_tools=use_native_tools)
    
    return Agent(
        system_prompt=system_prompt,
        state=state,
        llm=llm,
        on_debug=on_debug,
        on_tool=on_tool,
        on_raw=on_raw,
        on_error=on_error,
        on_display=on_display,
    )
