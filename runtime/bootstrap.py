"""
runtime/bootstrap.py

Composition helpers shared by agent runtimes and frontend adapters.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Callable

from core.agent import Agent
from core.tool_registry import ToolRegistry, autodiscover
from llm.base import LLMClient
from llm.providers import create_llm_client, ProviderConfig, PROVIDERS
from config.settings import DEBUG_LOGS, OPERATIONAL_DATABASE, RUNTIME_DATABASE
from night_shifts.storage import ToolCallStore

# Debug: print loaded providers (gated)
import sys
if DEBUG_LOGS:
    print("=== BOOTSTRAP PROVIDERS ===", file=sys.stderr)
    for key, p in PROVIDERS.items():
        print(f"  {key}: api_type={p.api_type}, model={p.default_model}", file=sys.stderr)
    print("===========================", file=sys.stderr)
from runtime.chat_store import ChatStore
from runtime.prompt import build_system_prompt
from runtime.state import AgentState, ModelConfig, ModelSettings
from runtime.tool_profiles import AgentProfile, build_profile_registry

if TYPE_CHECKING:
    from runtime.service import AgentRuntime


def _startup_provider() -> ProviderConfig:
    if not PROVIDERS:
        raise ValueError("No providers configured.")
    preferred = PROVIDERS.get("openai") or next(iter(PROVIDERS.values()))
    has_credentials = (
        preferred.project and preferred.location if preferred.api_type == "gemini_vertex"
        else preferred.api_key
    )
    if preferred.default_model and has_credentials:
        return preferred
    # Allow backend startup with only a Claude key even with older example TOML.
    return next((p for p in PROVIDERS.values()
                 if p.api_type == "anthropic_messages" and p.api_key and p.default_model), preferred)


def create_default_runtime(*, durable: bool = False) -> "AgentRuntime":
    """Compose the agent host independently of a frontend."""
    from runtime.service import AgentRuntime
    from tools.knowledge.runtime import start_embedding_warmup

    provider = _startup_provider()
    if not provider.default_model:
        raise ValueError(f"Provider '{provider.label}' has no default_model configured.")
    initialize_tools()
    config, llm = build_model_config_and_client(provider, provider.default_model)
    state = create_initial_state(config)
    start_embedding_warmup()
    return AgentRuntime(
        state=state, llm=llm,
        persistence_path=RUNTIME_DATABASE if durable else None,
    )


def create_conversation_manager(*, durable: bool = True, max_parallel_runs: int = 4):
    """Share infrastructure, never mutable model clients or conversation state."""
    from dataclasses import replace
    from runtime.conversations import ConversationManager
    from runtime.service import AgentRuntime
    from tools.knowledge.runtime import start_embedding_warmup

    default_provider = _startup_provider()
    if not default_provider.default_model:
        raise ValueError("Configure a default model before starting the backend")
    initialize_tools()
    history = ChatStore(background_indexing_enabled=True)
    audit = ToolCallStore(OPERATIONAL_DATABASE)
    audit.purge_expired()
    start_embedding_warmup()

    def factory(identity, store, source):
        provider = PROVIDERS[source.model_config.provider_key] if source else default_provider
        model = source.model_config.model if source else provider.default_model
        config, llm = build_model_config_and_client(provider, model)
        state = AgentState(
            cwd=source.cwd if source else Path.cwd(), model_config=config,
            model_settings=replace(source.model_settings) if source else ModelSettings(),
            chat_store=history, chat_session_id=identity, tool_call_store=audit,
        )
        return AgentRuntime(state=state, llm=llm, persistence_store=store)

    return ConversationManager(
        history=history, runtime_factory=factory,
        persistence_path=RUNTIME_DATABASE if durable else None,
        max_parallel_runs=max_parallel_runs,
    )


def initialize_tools() -> None:
    """Autodiscover all @tool-decorated functions."""
    autodiscover("tools")


def build_model_config_and_client(provider, model) -> tuple[ModelConfig, LLMClient]:
    """Create ModelConfig and LLM client from selected provider/model."""
    if provider.api_type == "gemini_vertex":
        if not provider.project:
            raise ValueError(
                f"Missing Google Cloud project ID for provider '{provider.label}'."
            )
        if not provider.location:
            raise ValueError(
                f"Missing Google Cloud location for provider '{provider.label}'."
            )
    elif not provider.api_key:
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
        project=provider.project,
        location=provider.location,
    )

    effective_provider = ProviderConfig(
        key=config.provider_key,
        label=config.provider_label,
        api_key=config.api_key,
        base_url=config.base_url,
        api_type=config.api_type,
        default_model=config.model,
        supports_model_listing=provider.supports_model_listing,
        api_key_envs=provider.api_key_envs,
        project=config.project,
        location=config.location,
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
    """Create initial runtime state and remove expired operational audit rows."""
    tool_call_store = ToolCallStore(OPERATIONAL_DATABASE)
    tool_call_store.purge_expired()
    return AgentState(
        cwd=Path.cwd(),
        model_config=model_config,
        chat_store=ChatStore(background_indexing_enabled=True),
        tool_call_store=tool_call_store,
    )


def create_agent(
    *,
    state: AgentState,
    llm: LLMClient,
    on_debug: Callable[[str], None] | None = None,
    on_tool: Callable[[str], None] | None = None,
    on_raw: Callable[[str], None] | None = None,
    on_error: Callable[[str], None] | None = None,
    profile: AgentProfile | str = AgentProfile.HEAD,
    tool_registry: ToolRegistry | None = None,
) -> Agent:
    """Create an Agent wired with frontend callbacks.
    
    Automatically detects if the LLM supports native tool calling
    and builds the system prompt accordingly.
    """
    # A caller may inject a registry for tests or specialized composition.
    # Normal runtimes always derive one from an explicit, fail-closed profile.
    active_registry = (
        tool_registry if tool_registry is not None else build_profile_registry(profile)
    )

    # Detect native tool support
    use_native_tools = getattr(llm, 'supports_native_tools', False)

    # Build prompt from the exact registry that the Agent will execute against.
    system_prompt = build_system_prompt(
        state,
        use_native_tools=use_native_tools,
        tool_registry=active_registry,
    )
    
    return Agent(
        system_prompt=system_prompt,
        state=state,
        llm=llm,
        on_debug=on_debug,
        on_tool=on_tool,
        on_raw=on_raw,
        on_error=on_error,
        tool_registry=active_registry,
        agent_profile=AgentProfile(profile).value,
    )
