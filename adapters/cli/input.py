"""
io/cli/input.py

Terminal input with optional prompt_toolkit support.
Migrated from utils/input.py.
"""

from pathlib import Path

HISTORY_FILE = Path(".agent_history")

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.key_binding import KeyBindings
    PROMPT_TOOLKIT_AVAILABLE = True
except ModuleNotFoundError:
    PromptSession = None
    FileHistory = None
    KeyBindings = None
    PROMPT_TOOLKIT_AVAILABLE = False


def _add_binding_safely(bindings, keys, handler):
    try:
        bindings.add(*keys)(handler)
    except Exception:
        pass


def _create_key_bindings():
    bindings = KeyBindings()

    def submit(event):
        event.app.current_buffer.validate_and_handle()

    def newline(event):
        event.app.current_buffer.insert_text("\n")

    _add_binding_safely(bindings, ("enter",), submit)
    _add_binding_safely(bindings, ("s-enter",), newline)
    _add_binding_safely(bindings, ("escape", "enter"), newline)
    _add_binding_safely(bindings, ("c-o",), newline)
    return bindings


def _prompt_continuation(width, line_number, is_soft_wrap):
    return " " * max(width - 4, 0) + "... "


def _create_session():
    if not PROMPT_TOOLKIT_AVAILABLE:
        return None
    return PromptSession(
        history=FileHistory(str(HISTORY_FILE)),
        multiline=True,
        key_bindings=_create_key_bindings(),
        prompt_continuation=_prompt_continuation,
        enable_history_search=True,
    )


_SESSION = _create_session()


def is_advanced_input_available() -> bool:
    return PROMPT_TOOLKIT_AVAILABLE and _SESSION is not None


def read_user_input() -> str:
    if _SESSION is not None:
        return _SESSION.prompt("You: ")
    return input("You: ")
