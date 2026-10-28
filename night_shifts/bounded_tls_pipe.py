"""Unwired controller-side TLS/pipe adapter; not a live VM authorization.

The existing inspection-only TLS prototype supplies authentication and framing.
One authoritative IOBudget covers opening, handshake and all message traffic.
No credentials are provisioned, no endpoint identity is discovered, and no
production transport, protected payload, ACL or Hyper-V resource is changed.
"""
from __future__ import annotations

import ssl
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from night_shifts.maintenance_tls_prototype import (
    AttemptBinding,
    OfflineTlsEndpoint,
    PrototypeRefused,
)
from night_shifts.serial_pipe_io import (
    BoundedPipe,
    IOBudget,
    PipeCleanupUnknown,
    PipeIOError,
)


class BoundedTlsPipe:
    """Connect and authenticate one controller-owned experimental session.

    Construction opens the canonical local pipe and completes pinned mutual TLS
    before returning. Context/binding/pin and budget callbacks are trusted inputs.
    Use a context manager or explicit finally/close; there is no GC cleanup,
    reconnect, plaintext fallback, command dispatcher or background I/O thread.

    Cancellation/timeout cannot retract bytes already delivered. A failed send
    must not be replayed automatically. Cleanup has BoundedPipe's separate drain
    allowance, and cleanup_unknown always takes precedence over a traffic error.
    """

    def __init__(
        self,
        path: str,
        context: ssl.SSLContext,
        binding: AttemptBinding,
        *,
        peer_sha256: str,
        timeout_seconds: float = 30.0,
        cancelled: Callable[[], bool] = lambda: False,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._owner = threading.get_ident()
        self._busy = False
        self._closed = False
        self._pipe: BoundedPipe | None = None
        self._budget = IOBudget(timeout_seconds, cancelled=cancelled, clock=clock)
        # The endpoint retains its own defensive checks. Its local timeout can
        # never extend the authoritative outer budget, checked around every
        # endpoint/native operation and before returning an application result.
        self._endpoint = OfflineTlsEndpoint(
            context, binding, role="controller", peer_sha256=peer_sha256,
            timeout_seconds=self._budget.remaining(), clock=clock, cancelled=cancelled,
        )
        with self._operation():
            self._pipe = BoundedPipe.connect(path, self._budget)
            self._budget.remaining()
            while not self._endpoint.authenticated:
                self._endpoint.step()
                self._drain()
                if not self._endpoint.authenticated:
                    self._read()

    @property
    def closed(self) -> bool:
        return self._closed

    def _require_owner(self) -> None:
        if threading.get_ident() != self._owner:
            raise PipeIOError("wrong_thread")

    @contextmanager
    def _operation(self) -> Iterator[None]:
        # Wrong-owner/reentrant use must not dispose someone else's active I/O.
        self._require_owner()
        if self._busy:
            raise PipeIOError("busy")
        if self._closed:
            raise PipeIOError("closed")
        self._busy = True
        try:
            self._budget.remaining()
            yield
            self._budget.remaining()
        except PipeCleanupUnknown:
            # Do not implicitly retry an uncertain native cancellation/release.
            self._closed = True
            self._endpoint.close()
            raise
        except (PipeIOError, PrototypeRefused):
            self._dispose()
            raise
        except Exception:
            self._dispose()
            raise PipeIOError("channel_failure") from None
        except BaseException:
            self._dispose()
            raise
        finally:
            self._busy = False

    def _drain(self) -> bool:
        assert self._pipe is not None
        wrote = False
        while self._endpoint.pending_ciphertext:
            self._budget.remaining()
            data = self._endpoint.take_ciphertext()
            self._budget.remaining()
            self._pipe.write_all(data)
            self._budget.remaining()
            wrote = True
        return wrote

    def _read(self) -> None:
        assert self._pipe is not None
        self._budget.remaining()
        data = self._pipe.read(16384)
        self._budget.remaining()
        if type(data) is not bytes or len(data) > 16384:
            raise PipeIOError("invalid_read")
        if not data:
            raise PipeIOError("channel_closed")
        self._endpoint.feed_ciphertext(data)
        self._budget.remaining()

    def send_message(self, payload: dict[str, Any]) -> None:
        """Send one bound frame, never automatically replaying a failed write."""
        with self._operation():
            self._endpoint.queue_message(payload)
            while True:
                self._endpoint.step()
                wrote = self._drain()
                if not self._endpoint.write_pending:
                    return
                if not wrote:
                    self._read()

    def receive_message(self) -> dict[str, Any]:
        """Receive one authenticated frame, under the original session budget."""
        with self._operation():
            while True:
                self._endpoint.step()
                message = self._endpoint.receive_message()
                wrote = self._drain()
                if message is not None:
                    return message
                if not wrote:
                    self._read()

    def _dispose(self) -> None:
        self._closed = True
        self._endpoint.close()
        if self._pipe is not None:
            self._pipe.close()

    def close(self) -> None:
        """Release exact-owned resources; explicit uncertainty recheck is allowed.

        No budget check prevents cleanup after expiry. This is not confirmation
        that a guest stopped or a VM/disk disappeared. PipeCleanupUnknown retains
        the underlying exact channel for a same-owner re-observation, not retry.
        """
        self._require_owner()
        if self._busy:
            raise PipeIOError("busy")
        self._dispose()

    def __enter__(self) -> BoundedTlsPipe:
        with self._operation():
            return self

    def __exit__(self, *_: object) -> None:
        self.close()
