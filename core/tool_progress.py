"""Context-local UI notifications; never tool results or execution authority."""
from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar

PRIVILEGED_EVIDENCE_PREFIX = '[privileged-evidence] '
PRIVILEGED_APPROVAL_PREFIX = '[privileged-approval] '
_listener: ContextVar[Callable[[str], None] | None] = ContextVar('tool_progress_listener', default=None)
_approval_ui: ContextVar[bool] = ContextVar('privileged_approval_ui', default=False)


@contextmanager
def approval_ui_context() -> Iterator[None]:
    """Only the interactive frontend installs this during its worker turn."""
    token = _approval_ui.set(True)
    try:
        yield
    finally:
        _approval_ui.reset(token)


def approval_ui_available() -> bool:
    return _approval_ui.get()


@contextmanager
def tool_progress_listener(callback: Callable[[str], None] | None) -> Iterator[None]:
    token = _listener.set(callback)
    try:
        yield
    finally:
        _listener.reset(token)


def approval_progress(identity: str) -> None:
    """UI notice only. Headless callers fail closed rather than wait indefinitely."""
    if not approval_ui_available():
        raise PermissionError('Interactive Textual approval is required')
    callback = _listener.get()
    if callback is None:
        raise PermissionError('Approval display is unavailable')
    callback(PRIVILEGED_APPROVAL_PREFIX + identity)


def evidence_progress(message: str) -> None:
    """Best-effort display only. A broken frontend must not change execution."""
    callback = _listener.get()
    if callback is not None:
        try:
            callback(PRIVILEGED_EVIDENCE_PREFIX + message)
        except Exception:
            pass
