"""Context-local UI notifications; never tool results or execution authority."""
from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar

PRIVILEGED_EVIDENCE_PREFIX = '[privileged-evidence] '
_listener: ContextVar[Callable[[str], None] | None] = ContextVar('tool_progress_listener', default=None)


@contextmanager
def tool_progress_listener(callback: Callable[[str], None] | None) -> Iterator[None]:
    token = _listener.set(callback)
    try:
        yield
    finally:
        _listener.reset(token)


def evidence_progress(message: str) -> None:
    """Best-effort display only. A broken frontend must not change execution."""
    callback = _listener.get()
    if callback is not None:
        try:
            callback(PRIVILEGED_EVIDENCE_PREFIX + message)
        except Exception:
            pass
