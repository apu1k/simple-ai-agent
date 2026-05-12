from pathlib import Path

from agent.agent import Agent
from agent.prompt import build_system_prompt
from agent.state import AgentState
from llm.models import select_model_config
from tools.file_tools import cd as tool_cd
from utils.logger import ai, error


def format_state(state: AgentState):
    return (
        "Current agent state:\n"
        f"- cwd: {state.cwd}\n"
        f"- provider: {state.model_config.provider_label}\n"
        f"- model: {state.model_config.model}\n"
        f"- api_type: {state.model_config.api_type}"
    )


def print_help():
    ai(
        "AI: Available commands:\n"
        "\\help              Show this help message\n"
        "\\state             Show current agent state\n"
        "\\pwd               Show current working directory\n"
        "\\cd <path>         Change current working directory without using the LLM\n"
        "\\models            Select a different provider/model without restarting\n"
        "\\reset             Reset conversation context but keep current state\n"
        "\\exit / \\quit      Exit the agent"
    )


def handle_command(user_input, agent: Agent, state: AgentState):
    stripped = user_input.strip()

    if not stripped.startswith("\\"):
        return False, agent

    command_parts = stripped.split(maxsplit=1)
    command = command_parts[0].lower()
    argument = command_parts[1] if len(command_parts) > 1 else ""

    if command == "\\help":
        print_help()
        return True, agent

    if command == "\\reset":
        agent.reset(build_system_prompt())
        ai("AI: Context has been reset.")
        return True, agent

    if command in ["\\exit", "\\quit"]:
        ai("AI: Goodbye.")
        return True, None

    if command == "\\state":
        ai("AI: " + format_state(state))
        return True, agent

    if command == "\\pwd":
        ai(f"AI: {state.cwd}")
        return True, agent

    if command == "\\cd":
        path = argument.strip()

        if not path:
            ai("AI: Usage: \\cd <path>")
            return True, agent

        result = tool_cd(state, path)
        ai("AI: " + result)
        return True, agent

    if command == "\\models":
        try:
            new_model_config = select_model_config()
        except Exception as e:
            error(f"Model selection failed: {e}")
            ai(f"AI: Error: Model selection failed: {e}")
            return True, agent

        state.model_config = new_model_config
        ai(
            "AI: Model changed.\n"
            f"- provider: {state.model_config.provider_label}\n"
            f"- model: {state.model_config.model}\n"
            f"- api_type: {state.model_config.api_type}"
        )
        return True, agent

    ai("AI: Unknown command. Type \\help to see available commands.")
    return True, agent


def run_agent():
    model_config = select_model_config()

    state = AgentState(
        cwd=Path.cwd(),
        model_config=model_config,
    )

    agent = Agent(build_system_prompt(), state)

    print_help()

    while True:
        user_input = input("You: ")

        handled, new_agent = handle_command(user_input, agent, state)

        if handled:
            if new_agent is None:
                break

            agent = new_agent
            continue

        reply = agent.step(user_input)
        ai("AI: " + reply)