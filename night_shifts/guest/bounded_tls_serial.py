"""Unwired inspection-only guest TLS server over fixed bounded Linux ttyS0.

Trusted contexts, pins and per-attempt bindings are supplied by a future reviewed
bootstrap. No key discovery/provisioning, command dispatcher, CLI, service entry,
plaintext fallback or deployment integration is supplied here.
"""
from __future__ import annotations

import ssl
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from night_shifts.guest.serial_device_io import SerialCleanupUnknown, SerialDevice
from night_shifts.maintenance_tls_prototype import (
    AttemptBinding,
    OfflineTlsEndpoint,
    PrototypeRefused,
)
from night_shifts.serial_pipe_io import IOBudget, PipeIOError


class GuestTlsSerial:
    """Open the fixed guest tty and complete pinned mutual TLS before returning.

    One owning thread and one authoritative budget span open, configuration,
    handshake and every message. Cancellation cannot retract bytes already sent.
    Call close() in finally or use a context manager; no destructor or retry.
    """

    def __init__(
        self,
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
        self._serial: SerialDevice | None = None
        self._budget = IOBudget(timeout_seconds, cancelled=cancelled, clock=clock)
        self._endpoint = OfflineTlsEndpoint(
            context, binding, role="guest", peer_sha256=peer_sha256,
            timeout_seconds=self._budget.remaining(), clock=clock, cancelled=cancelled,
        )
        with self._operation():
            self._serial = SerialDevice.open(self._budget)
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
        except SerialCleanupUnknown:
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
        assert self._serial is not None
        wrote = False
        while self._endpoint.pending_ciphertext:
            self._budget.remaining()
            data = self._endpoint.take_ciphertext()
            self._budget.remaining()
            self._serial.write_all(data)
            self._budget.remaining()
            wrote = True
        return wrote

    def _read(self) -> None:
        assert self._serial is not None
        self._budget.remaining()
        data = self._serial.read(16384)
        self._budget.remaining()
        if type(data) is not bytes or len(data) > 16384:
            raise PipeIOError("invalid_read")
        if not data:
            raise PipeIOError("channel_closed")
        self._endpoint.feed_ciphertext(data)
        self._budget.remaining()

    def send_message(self, payload: dict[str, Any]) -> None:
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
        if self._serial is not None:
            self._serial.close()

    def close(self) -> None:
        """Close exact-owned tty state; never retry a possibly recycled fd."""
        self._require_owner()
        if self._busy:
            raise PipeIOError("busy")
        self._dispose()

    def __enter__(self) -> GuestTlsSerial:
        with self._operation():
            return self

    def __exit__(self, *_: object) -> None:
        self.close()
