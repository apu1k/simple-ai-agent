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
        # Some terminals/prompt_toolkit versions do not support every key name,
        # especially Shift+Enter. In that case we simply skip that binding.
        pass


def _create_key_bindings():
    bindings = KeyBindings()

    def submit_input(event):
        event.app.current_buffer.validate_and_handle()

    def insert_newline(event):
        event.app.current_buffer.insert_text("\n")

    # Normal Enter submits the whole input.
    _add_binding_safely(bindings, ("enter",), submit_input)

    # Preferred multiline shortcut.
    # Works only if the terminal can distinguish Shift+Enter from Enter.
    _add_binding_safely(bindings, ("s-enter",), insert_newline)

    # Reliable fallbacks for terminals that do not send Shift+Enter separately.
    _add_binding_safely(bindings, ("escape", "enter"), insert_newline)
    _add_binding_safely(bindings, ("c-o",), insert_newline)

    return bindings


def _prompt_continuation(width, line_number, is_soft_wrap):
    return " " * max(width - 4, 0) + "... "


def _create_prompt_session():
    if not PROMPT_TOOLKIT_AVAILABLE:
        return None

    return PromptSession(
        history=FileHistory(str(HISTORY_FILE)),
        multiline=True,
        key_bindings=_create_key_bindings(),
        prompt_continuation=_prompt_continuation,
        enable_history_search=True,
    )


_SESSION = _create_prompt_session()


def is_advanced_input_available():
    return PROMPT_TOOLKIT_AVAILABLE and _SESSION is not None


def read_user_input():
    if _SESSION is not None:
        return _SESSION.prompt("You: ")

    return input("You: ")