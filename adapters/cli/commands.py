"""
adapters/cli/commands.py

Handles all backslash commands: \help, \approve, \reject, \pending,
\cd, \models, \debug, \reset, \new_chat, \history, \state, \pwd,
\exit, \quit.

Allowed imports:
  - adapters/cli/display  (rendering)
  - adapters/cli/logger   (debug toggle)
  - tools/fs/read         (cd tool, called directly for \cd)

Everything else is injected by runtime/loop.py so this file stays
free of llm/, runtime/, and core/ imports.

Returns (handled: bool, should_exit: bool).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from adapters.cli import display, logger

if TYPE_CHECKING:
    from core.agent import Agent
    from runtime.state import AgentState


def handle_command(
    user_input: str,
    agent: "Agent",
    state: "AgentState",
    on_reset: Callable[[], str],
    on_model_switch: Callable[["Agent", "AgentState"], None],
    on_new_chat: Callable[["Agent", "AgentState"], str],
    on_history: Callable[["AgentState"], str],
) -> tuple[bool, bool]:
    """
    Try to handle user_input as a backslash command.

    Args:
        user_input:       Raw text typed by the user.
        agent:            The running Agent instance.
        state:            Current AgentState.
        on_reset:         Callback that returns a fresh system prompt string.
                          Provided by runtime/loop.py — keeps runtime/ out of here.
        on_model_switch:  Callback that runs interactive provider/model selection
                          and updates agent.llm and state.model_config in place.
                          Provided by runtime/loop.py — keeps llm/ out of here.
        on_new_chat:      Callback that starts a new persistent chat session and
                          resets the agent context.
        on_history:       Callback that formats recent persistent chat sessions.

    Returns:
        (handled, should_exit)
        handled:     True if the input was a command (even an unknown one).
        should_exit: True if the agent loop should stop.
    """
    stripped = user_input.strip()
    if not stripped.startswith("\\"):
        return False, False

    parts = stripped.split(maxsplit=1)
    command = parts[0].lower()
    argument = parts[1] if len(parts) > 1 else ""

    # ------------------------------------------------------------------ help
    if command == "\\help":
        display.show_help()
        display.show_input_help()
        return True, False

    # ----------------------------------------------------------------- reset
    if command == "\\reset":
        agent.reset(on_reset())
        display.show_command_message(
            "Conversation context has been reset.",
            title="Reset",
            border_style="green",
        )
        return True, False

    # ------------------------------------------------------------ new chat
    if command == "\\new_chat":
        session_id = on_new_chat(agent, state)
        display.show_command_message(
            f"Started new chat session: {session_id}",
            title="New Chat",
            border_style="green",
        )
        return True, False

    # --------------------------------------------------------------- history
    if command == "\\history":
        if argument.strip():
            display.show_command_error("Usage: \\history")
            return True, False
        display.show_command_message(
            on_history(state),
            title="Chat History",
            border_style="cyan",
        )
        return True, False

    # ------------------------------------------------------------ exit / quit
    if command in {"\\exit", "\\quit"}:
        display.show_command_message("Goodbye.", title="Exit", border_style="green")
        return True, True

    # ----------------------------------------------------------------- state
    if command == "\\state":
        display.show_state(state)
        return True, False

    # ------------------------------------------------------------------- pwd
    if command == "\\pwd":
        display.show_command_message(
            str(state.cwd),
            title="Current Working Directory",
            border_style="cyan",
        )
        return True, False

    # ------------------------------------------------------------------- cd
    if command == "\\cd":
        path = argument.strip()
        if not path:
            display.show_command_error("Usage: \\cd <path>")
            return True, False

        from tools.fs.read import cd
        result = cd(state, path)
        if isinstance(result, str) and result.startswith("Error:"):
            display.show_command_error(result)
        else:
            display.show_command_message(result, title="Changed Directory", border_style="green")
        return True, False

    # --------------------------------------------------------------- pending
    if command == "\\pending":
        _handle_pending(state, argument)
        return True, False

    # --------------------------------------------------------------- approve
    if command == "\\approve":
        _handle_approve(state, argument)
        return True, False

    # ---------------------------------------------------------------- reject
    if command == "\\reject":
        _handle_reject(state, argument)
        return True, False

    # --------------------------------------------------------------- models
    if command == "\\models":
        try:
            on_model_switch(agent, state)
            display.show_model_changed(state)
        except Exception as e:
            display.show_command_error(f"Model selection failed: {e}")
        return True, False

    # ----------------------------------------------------------------- debug
    if command == "\\debug":
        _handle_debug(argument)
        return True, False

    display.show_command_error("Unknown command. Type \\help to see available commands.")
    return True, False


# ---------------------------------------------------------------------------
# Sub-handlers (only display + state, no external imports)
# ---------------------------------------------------------------------------

def _handle_pending(state: "AgentState", argument: str) -> None:
    arg = argument.strip()

    # \pending  -> list pending edits
    if not arg:
        pending = state.edit_store.pending()
        if not pending:
            display.show_command_message("No pending edits.", title="Pending Edits", border_style="yellow")
            return
        lines = []
        for e in pending.values():
            if e.destination_path is not None:
                lines.append(f"#{e.id} | {e.status} | {e.kind} | {e.path} -> {e.destination_path}")
            else:
                lines.append(f"#{e.id} | {e.status} | {e.kind} | {e.path}")
        display.show_command_message("\n".join(lines), title="Pending Changes", border_style="cyan")
        return

    # \pending <id>
    # \pending diff <id>
    edit_id: int | None = None
    if arg.isdigit():
        edit_id = int(arg)
    else:
        tokens = arg.split()
        if len(tokens) == 2 and tokens[0].lower() == "diff" and tokens[1].isdigit():
            edit_id = int(tokens[1])

    if edit_id is None:
        display.show_command_error("Usage: \\pending  |  \\pending <id>  |  \\pending diff <id>")
        return

    edit = state.edit_store.get(edit_id)
    if edit is None:
        display.show_command_error(f"Pending edit #{edit_id} does not exist.")
        return

    display.show_pending_diff(
        edit_id=edit.id,
        path=str(edit.path),
        status=edit.status,
        diff_text=edit.diff,
        kind=edit.kind,
    )


def _handle_approve(state: "AgentState", argument: str) -> None:
    argument = argument.strip()
    if not argument.isdigit():
        display.show_command_error("Usage: \\approve <id>")
        return
    edit_id = int(argument)
    try:
        message = state.edit_store.approve(edit_id)
        display.show_command_message(message, title="Approved", border_style="green")
    except KeyError as e:
        display.show_command_error(str(e))
    except ValueError as e:
        display.show_command_error(str(e))


def _handle_reject(state: "AgentState", argument: str) -> None:
    argument = argument.strip()
    if not argument.isdigit():
        display.show_command_error("Usage: \\reject <id>")
        return
    edit_id = int(argument)
    try:
        message = state.edit_store.reject(edit_id)
        display.show_command_message(message, title="Rejected", border_style="yellow")
    except KeyError as e:
        display.show_command_error(str(e))
    except ValueError as e:
        display.show_command_error(str(e))


def _handle_debug(argument: str) -> None:
    value = argument.strip().lower()
    if not value:
        display.show_debug_status()
        return
    if value in {"on", "true", "1", "yes", "y"}:
        logger.set_debug(True)
        display.show_debug_changed(True)
        return
    if value in {"off", "false", "0", "no", "n"}:
        logger.set_debug(False)
        display.show_debug_changed(False)
        return
    display.show_command_error("Usage: \\debug on  or  \\debug off")