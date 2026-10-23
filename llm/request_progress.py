"""Context-local request notices: display only, never model conversation data."""
from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar

REQUEST_PROGRESS_PREFIX = "[request-retry] "
_listener: ContextVar[Callable[[str], None] | None] = ContextVar(
    "request_progress_listener", default=None,
)


@contextmanager
def request_progress_listener(callback: Callable[[str], None] | None) -> Iterator[None]:
    """Scope notices to one synchronous request and restore on every exit."""
    token = _listener.set(callback)
    try:
        yield
    finally:
        _listener.reset(token)


def notify_request_retry(delay_seconds: float, attempt: int, max_retries: int) -> None:
    """Best-effort notice before sleeping; never include provider payload text."""
    callback = _listener.get()
    if callback is None:
        return
    if delay_seconds >= 60 and delay_seconds % 60 == 0:
        minutes = int(delay_seconds / 60)
        unit = "minute" if minutes == 1 else "minutes"
        duration = f"{minutes} {unit} ({delay_seconds:g} seconds)"
    else:
        duration = f"{delay_seconds:.1f} seconds"
    message = (
        REQUEST_PROGRESS_PREFIX + "Flex capacity unavailable — "
        f"waiting {duration} before retry {attempt}/{max_retries}; staying on Flex."
    )
    try:
        callback(message)
    except Exception:
        # A disconnected/broken display must not fail or duplicate a request.
        pass
