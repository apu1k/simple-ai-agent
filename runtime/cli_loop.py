"""
runtime/cli_loop.py

CLI composition root.

Wires together:
  - runtime/bootstrap.py       (shared setup helpers)
  - llm/providers.py           (interactive provider/model selection)
  - adapters/cli/adapter.py    (terminal IO)
  - adapters/cli/commands.py   (backslash commands)
  - adapters/cli/display.py    (startup UI)
  - runtime/prompt.py          (system prompt builder)

Future non-CLI frontends should use their own runtime module and share common
setup through runtime/bootstrap.py.
"""

from core.agent import Agent
from adapters.cli.adapter import CLIAdapter
from adapters.cli import display
from adapters.cli.commands import handle_command
from llm.providers import PROVIDERS, choose_model, choose_provider
from runtime.bootstrap import (
    build_model_config_and_client,
    create_agent,
    create_initial_state,
    initialize_tools,
)
from runtime.prompt import build_system_prompt
from runtime.state import AgentState, ModelConfig


# ---------------------------------------------------------------------------
# Provider / model selection
# ---------------------------------------------------------------------------


def _select_model_config() -> tuple[ModelConfig, object]:
    """Interactive startup provider + model selection."""
    provider = choose_provider(PROVIDERS)
    model = choose_model(provider)
    return build_model_config_and_client(provider, model)


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
        config, llm = build_model_config_and_client(provider, model)
        state.model_config = config
        agent.llm = llm
    return on_model_switch


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_cli_agent() -> None:
    """
    CLI entry point. Called from main.py.

    1. Autodiscovers all @tool-decorated functions.
    2. Prompts the user to select a provider + model.
    3. Runs the interactive agent loop.
    """
    initialize_tools()

    model_config, llm = _select_model_config()
    state = create_initial_state(model_config)

    io = CLIAdapter()

    agent = create_agent(
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