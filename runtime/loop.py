"""
runtime/loop.py

The composition root. The only module allowed to import from everything.

Wires together:
  - config/settings.py         (env + paths, loaded on import)
  - core/tool_registry.py      (autodiscovery)
  - core/agent.py              (agent loop)
  - llm/providers.py           (provider config, LLM client factory)
  - adapters/cli/adapter.py    (terminal IO)
  - adapters/cli/commands.py   (backslash commands)
  - adapters/cli/display.py    (startup UI)
  - runtime/state.py           (AgentState, ModelConfig)
  - runtime/prompt.py          (system prompt builder)

Nothing outside runtime/ should import from here.
"""

from pathlib import Path

from core.agent import Agent
from core.tool_registry import autodiscover
from adapters.cli.adapter import CLIAdapter
from adapters.cli import display
from adapters.cli.commands import handle_command
from llm.providers import PROVIDERS, choose_model, choose_provider, create_llm_client
from runtime.prompt import build_system_prompt
from runtime.state import AgentState, ModelConfig


# ---------------------------------------------------------------------------
# Provider / model selection
# ---------------------------------------------------------------------------

def _build_model_config_and_client(provider, model) -> tuple[ModelConfig, object]:
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


def _select_model_config() -> tuple[ModelConfig, object]:
    """Interactive startup provider + model selection."""
    provider = choose_provider(PROVIDERS)
    model = choose_model(provider)
    return _build_model_config_and_client(provider, model)


# ---------------------------------------------------------------------------
# Callbacks injected into adapters/cli/commands.py
# These keep llm/ and runtime/ imports out of the adapters layer.
# ---------------------------------------------------------------------------

def _make_on_reset() -> callable:
    """Returns a callback that builds a fresh system prompt."""
    def on_reset() -> str:
        return build_system_prompt()
    return on_reset


def _make_on_model_switch() -> callable:
    """
    Returns a callback that runs interactive model selection and updates
    agent.llm and state.model_config in place.
    Called by the \models command handler in adapters/cli/commands.py.
    """
    def on_model_switch(agent: Agent, state: AgentState) -> None:
        provider = choose_provider(PROVIDERS)
        model = choose_model(provider)
        config, llm = _build_model_config_and_client(provider, model)
        state.model_config = config
        agent.llm = llm
    return on_model_switch


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_agent() -> None:
    """
    Entry point. Called from main.py.

    1. Autodiscovers all @tool-decorated functions.
    2. Prompts the user to select a provider + model.
    3. Runs the interactive agent loop.
    """
    autodiscover("tools")

    model_config, llm = _select_model_config()

    state = AgentState(
        cwd=Path.cwd(),
        model_config=model_config,
    )

    io = CLIAdapter()

    agent = Agent(
        system_prompt=build_system_prompt(),
        state=state,
        llm=llm,
        on_debug=io.show_debug,
        on_tool=io.show_tool,
        on_raw=io.show_raw,
        on_error=io.show_error,
        on_display=io.show_display_items,
    )

    on_reset = _make_on_reset()
    on_model_switch = _make_on_model_switch()

    display.show_startup_banner(state)
    display.show_help()
    display.show_input_help()

    while True:
        try:
            user_input = io.read_input()
        except KeyboardInterrupt:
            display.show_command_message(
                "Interrupted. Use \\exit to quit or keep typing.",
                title="Keyboard Interrupt",
                border_style="yellow",
            )
            continue
        except EOFError:
            display.show_command_message("Goodbye.", title="Exit", border_style="green")
            break

        if not user_input.strip():
            continue

        handled, should_exit = handle_command(
            user_input,
            agent,
            state,
            on_reset=on_reset,
            on_model_switch=on_model_switch,
        )

        if handled:
            if should_exit:
                break
            continue

        try:
            with io.show_processing("AI is processing..."):
                reply = agent.step(user_input)
        except KeyboardInterrupt:
            display.show_command_message(
                "Agent processing interrupted.",
                title="Keyboard Interrupt",
                border_style="yellow",
            )
            continue
        except Exception as e:
            display.show_command_error(f"Agent processing failed: {e}")
            continue

        io.show_response(reply)