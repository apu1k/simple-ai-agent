from pathlib import Path

from agent.agent import Agent
from agent.prompt import build_system_prompt
from agent.state import AgentState
from llm.models import select_model_config
from tools.file_tools import cd as tool_cd
from utils.input import read_user_input
from utils.logger import ai_response, set_debug
from utils.ui import (
    show_command_error,
    show_command_message,
    show_debug_changed,
    show_debug_status,
    show_help,
    show_input_help,
    show_model_changed,
    show_processing,
    show_startup_banner,
    show_state,
)


def handle_pending_command(state):
    if not state.pending_edits:
        show_command_message(
            "No pending edits.",
            title="Pending Edits",
            border_style="yellow",
        )
        return

    lines = []

    for edit_id, edit in state.pending_edits.items():
        lines.append(
            f"#{edit_id} | {edit.status} | {edit.path}"
        )

    show_command_message(
        "\n".join(lines),
        title="Pending Edits",
        border_style="cyan",
    )

def handle_approve_command(state, argument):
    argument = argument.strip()

    if not argument.isdigit():
        show_command_error("Usage: \\approve <id>")
        return

    edit_id = int(argument)

    if edit_id not in state.pending_edits:
        show_command_error(
            f"Pending edit #{edit_id} does not exist."
        )
        return

    pending_edit = state.pending_edits[edit_id]

    current_content = pending_edit.path.read_text(
        encoding="utf-8"
    )

    if current_content != pending_edit.original_content:
        show_command_error(
            "File changed since edit proposal. "
            "Edit is stale and cannot be applied safely."
        )
        return

    pending_edit.path.write_text(
        pending_edit.new_content,
        encoding="utf-8"
    )

    pending_edit.status = "applied"

    show_command_message(
        f"Applied pending edit #{edit_id}.",
        title="Approved",
        border_style="green",
    )

def handle_reject_command(state, argument):
    argument = argument.strip()

    if not argument.isdigit():
        show_command_error("Usage: \\reject <id>")
        return

    edit_id = int(argument)

    if edit_id not in state.pending_edits:
        show_command_error(
            f"Pending edit #{edit_id} does not exist."
        )
        return

    state.pending_edits[edit_id].status = "rejected"

    show_command_message(
        f"Rejected pending edit #{edit_id}.",
        title="Rejected",
        border_style="yellow",
    )

def handle_debug_command(argument):
    value = argument.strip().lower()

    if not value:
        show_debug_status()
        return

    if value in {"on", "true", "1", "yes", "y"}:
        set_debug(True)
        show_debug_changed(True)
        return

    if value in {"off", "false", "0", "no", "n"}:
        set_debug(False)
        show_debug_changed(False)
        return

    show_command_error("Usage: \\debug on or \\debug off")


def handle_command(user_input, agent: Agent, state: AgentState):
    stripped = user_input.strip()

    if not stripped.startswith("\\"):
        return False, agent

    command_parts = stripped.split(maxsplit=1)
    command = command_parts[0].lower()
    argument = command_parts[1] if len(command_parts) > 1 else ""

    if command == "\\help":
        show_help()
        show_input_help()
        return True, agent

    if command == "\\reset":
        agent.reset(build_system_prompt())
        show_command_message(
            "Conversation context has been reset.",
            title="Reset",
            border_style="green",
        )
        return True, agent

    if command in {"\\exit", "\\quit"}:
        show_command_message(
            "Goodbye.",
            title="Exit",
            border_style="green",
        )
        return True, None

    if command == "\\state":
        show_state(state)
        return True, agent

    if command == "\\pwd":
        show_command_message(
            str(state.cwd),
            title="Current Working Directory",
            border_style="cyan",
        )
        return True, agent
    
    if command == "\\pending":
        handle_pending_command(state)
        return True, agent

    if command == "\\approve":
        handle_approve_command(state, argument)
        return True, agent

    if command == "\\reject":
        handle_reject_command(state, argument)
        return True, agent
        
    if command == "\\cd":
        path = argument.strip()

        if not path:
            show_command_error("Usage: \\cd <path>")
            return True, agent

        result = tool_cd(state, path)

        if isinstance(result, str) and result.startswith("Error:"):
            show_command_error(result)
        else:
            show_command_message(
                result,
                title="Changed Directory",
                border_style="green",
            )

        return True, agent

    if command == "\\models":
        try:
            new_model_config = select_model_config()
        except Exception as e:
            show_command_error(f"Model selection failed: {e}")
            return True, agent

        state.model_config = new_model_config
        show_model_changed(state)
        return True, agent

    if command == "\\debug":
        handle_debug_command(argument)
        return True, agent

    show_command_error("Unknown command. Type \\help to see available commands.")
    return True, agent


def run_agent():
    model_config = select_model_config()

    state = AgentState(
        cwd=Path.cwd(),
        model_config=model_config,
    )

    agent = Agent(build_system_prompt(), state)

    show_startup_banner(state)
    show_help()
    show_input_help()

    while True:
        try:
            user_input = read_user_input()
        except KeyboardInterrupt:
            show_command_message(
                "Interrupted. Use \\exit to quit or continue typing.",
                title="Keyboard Interrupt",
                border_style="yellow",
            )
            continue
        except EOFError:
            show_command_message(
                "Goodbye.",
                title="Exit",
                border_style="green",
            )
            break

        if not user_input.strip():
            continue

        handled, new_agent = handle_command(user_input, agent, state)

        if handled:
            if new_agent is None:
                break

            agent = new_agent
            continue

        try:
            with show_processing("AI is processing..."):
                reply = agent.step(user_input)
        except KeyboardInterrupt:
            show_command_message(
                "Agent processing interrupted.",
                title="Keyboard Interrupt",
                border_style="yellow",
            )
            continue
        except Exception as e:
            show_command_error(f"Agent processing failed: {e}")
            continue

        ai_response(reply)