"""OFFLINE prototype: pinned mutual TLS over bounded MemoryBIO buffers only.

No sockets, pipes, files, media, VM operations, credential provisioning, CLI or
production integration. Contexts and peer pins must come from a trusted caller;
this module does not establish their provenance or private-key secrecy.

Deadlines/cancellation are cooperative checks around OpenSSL calls, NOT native
process watchdogs. The installed watchdog remains a separate live prerequisite.
Per-session sequence checks do not replace permanent attempt claims or fresh
credentials. Nothing here enables the existing plaintext maintenance path.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import ssl
import struct
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, NoReturn
from uuid import UUID

MAX_FRAME_BYTES = 32768
MAX_CIPHER_BYTES = 131072
MAX_MESSAGES = 1024
MAX_SECONDS = 900
SERVER_NAME = 'night-shift-maintenance.invalid'
OPERATION = 'inspect_image_copy'


class PrototypeRefused(RuntimeError):
    """Fixed labels only; never expose TLS exception text or peer payloads."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class AttemptBinding:
    attempt_id: str
    vm_id: str

    def __post_init__(self) -> None:
        if (type(self.attempt_id) is not str or
                re.fullmatch('[0-9a-f]{32}', self.attempt_id) is None or
                type(self.vm_id) is not str):
            raise ValueError('invalid prototype binding')
        try:
            value = UUID(self.vm_id)
        except ValueError:
            raise ValueError('invalid prototype binding') from None
        if str(value) != self.vm_id or value.int == 0:
            raise ValueError('invalid prototype binding')


def _tree(value: Any) -> None:
    """Bound JSON depth, nodes and aggregate scalar/key work, not just values."""
    stack = [(value, 0)]
    count = 0
    budget = 0
    while stack:
        item, depth = stack.pop()
        count += 1
        budget += 1
        if depth > 8 or count > 4096:
            raise ValueError('invalid frame value')
        if type(item) is dict:
            if len(item) > 4096:
                raise ValueError('invalid frame value')
            for key in item:
                if type(key) is not str or len(key) > MAX_FRAME_BYTES:
                    raise ValueError('invalid frame value')
                budget += len(key) + 3
            stack.extend((child, depth + 1) for child in item.values())
        elif type(item) is list:
            if len(item) > 4096:
                raise ValueError('invalid frame value')
            stack.extend((child, depth + 1) for child in item)
        elif type(item) is str:
            budget += len(item) + 2
        elif type(item) is int:
            if not -(2 ** 63) <= item < 2 ** 63:
                raise ValueError('invalid frame value')
            budget += 20
        elif type(item) is float:
            if not math.isfinite(item):
                raise ValueError('invalid frame value')
            budget += 32
        elif item is None or type(item) is bool:
            budget += 5
        else:
            raise ValueError('invalid frame value')
        if budget > MAX_FRAME_BYTES:
            raise ValueError('invalid frame value')


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate frame key')
        result[key] = value
    return result


def _constant(_: str) -> NoReturn:
    raise ValueError('invalid frame constant')


class OfflineTlsEndpoint:
    """One terminal-on-failure TLS session; caller moves ciphertext explicitly.

    A guest is the TLS server and a controller is the TLS client. Both validate
    certificates and exact peer-leaf SHA-256 pins before application messages.
    Contexts are trusted inputs, not a sandbox boundary. They must not be shared
    or mutated while a session runs; known insecure settings are rechecked.
    """

    def __init__(
        self, context: ssl.SSLContext, binding: AttemptBinding, *, role: str,
        peer_sha256: str, timeout_seconds: float = 5.0,
        clock: Callable[[], float] = time.monotonic,
        cancelled: Callable[[], bool] = lambda: False,
    ) -> None:
        if (not isinstance(context, ssl.SSLContext) or type(binding) is not AttemptBinding or
                role not in ('controller', 'guest') or type(peer_sha256) is not str or
                re.fullmatch('[0-9a-f]{64}', peer_sha256) is None or
                type(timeout_seconds) not in (int, float) or
                not 0 < timeout_seconds <= MAX_SECONDS or not math.isfinite(timeout_seconds)):
            raise PrototypeRefused('configuration')
        self._context = context
        self._binding = binding
        self._role = role
        self._pin = peer_sha256
        self._clock = clock
        self._cancelled = cancelled
        try:
            started = float(clock())
        except Exception:
            raise PrototypeRefused('configuration') from None
        if not math.isfinite(started):
            raise PrototypeRefused('configuration')
        self._deadline = started + timeout_seconds
        self._failure: str | None = None
        self._ready = False
        self._eof = False
        self._handshake_input = 0
        self._tx_sequence = 0
        self._rx_sequence = 0
        self._plain = bytearray()
        self._write_pending = b''
        self._write_offset = 0
        self._incoming = ssl.MemoryBIO()
        self._outgoing = ssl.MemoryBIO()
        self._guard()
        self._configuration()
        try:
            self._tls = context.wrap_bio(
                self._incoming, self._outgoing, server_side=role == 'guest',
                server_hostname=SERVER_NAME if role == 'controller' else None,
            )
        except (ssl.SSLError, ValueError):
            self._fail('configuration')
        self._guard()

    @property
    def authenticated(self) -> bool:
        """Cached pin/handshake status; every operation still checks its budget."""
        return self._ready and self._failure is None

    @property
    def pending_ciphertext(self) -> int:
        self._guard()
        return self._outgoing.pending

    @property
    def write_pending(self) -> bool:
        return bool(self._write_pending) and self._failure is None

    def _fail(self, code: str) -> NoReturn:
        if self._failure is None:
            self._failure = code
        self._ready = False
        self._plain.clear()
        self._write_pending = b''
        raise PrototypeRefused(self._failure) from None

    def _guard(self) -> None:
        if self._failure is not None:
            self._fail(self._failure)
        try:
            stopped = self._cancelled()
            now = float(self._clock())
        except Exception:
            self._fail('budget_check')
        if stopped:
            self._fail('cancelled')
        if not math.isfinite(now) or now >= self._deadline:
            self._fail('deadline')

    def _configuration(self) -> None:
        context = self._context
        expected = ssl.PROTOCOL_TLS_SERVER if self._role == 'guest' else ssl.PROTOCOL_TLS_CLIENT
        if (context.protocol != expected or context.verify_mode != ssl.CERT_REQUIRED or
                context.minimum_version < ssl.TLSVersion.TLSv1_3 or
                context.maximum_version not in (ssl.TLSVersion.TLSv1_3, ssl.TLSVersion.MAXIMUM_SUPPORTED) or
                not context.verify_flags & ssl.VERIFY_X509_STRICT or
                not context.options & ssl.OP_NO_TICKET or context.post_handshake_auth or
                context.keylog_filename is not None or context.sni_callback is not None or
                (self._role == 'controller' and not context.check_hostname) or
                (self._role == 'guest' and context.num_tickets != 0)):
            self._fail('configuration')

    def _buffers(self) -> None:
        if (self._incoming.pending > MAX_CIPHER_BYTES or
                self._outgoing.pending > MAX_CIPHER_BYTES):
            self._fail('cipher_buffer')

    def feed_ciphertext(self, data: bytes) -> None:
        self._guard()
        self._configuration()
        if type(data) is not bytes or self._eof:
            self._fail('input_closed' if self._eof else 'cipher_buffer')
        if len(data) > MAX_CIPHER_BYTES - self._incoming.pending:
            self._fail('cipher_buffer')
        if not self._ready:
            self._handshake_input += len(data)
            if self._handshake_input > MAX_CIPHER_BYTES:
                self._fail('handshake_buffer')
        self._incoming.write(data)
        self._guard()

    def take_ciphertext(self, limit: int = 16384) -> bytes:
        self._guard()
        self._configuration()
        self._buffers()
        if type(limit) is not int or not 1 <= limit <= 16384:
            self._fail('cipher_buffer')
        data = self._outgoing.read(limit)
        self._guard()
        return data

    def feed_eof(self) -> None:
        self._guard()
        if self._eof:
            self._fail('input_closed')
        self._eof = True
        self._incoming.write_eof()

    def close(self) -> None:
        """Abandon only this memory session; no I/O or secure-erasure claim."""
        if self._failure is None:
            self._failure = 'closed'
        self._ready = False
        self._plain.clear()
        self._write_pending = b''

    def step(self) -> bool:
        self._guard()
        self._configuration()
        try:
            if not self._ready:
                self._tls.do_handshake()
                self._guard()
                self._configuration()
                certificate = self._tls.getpeercert(binary_form=True)
                if (self._tls.version() != 'TLSv1.3' or self._tls.session_reused or
                        not certificate or not hmac.compare_digest(
                            hashlib.sha256(certificate).hexdigest(), self._pin,
                        )):
                    self._fail('peer_identity')
                self._guard()
                self._ready = True
            if self._write_pending:
                count = self._tls.write(self._write_pending[self._write_offset:])
                self._guard()
                if count <= 0:
                    self._fail('tls_failure')
                self._write_offset += count
                if self._write_offset == len(self._write_pending):
                    self._write_pending = b''
                    self._write_offset = 0
        except (ssl.SSLWantReadError, ssl.SSLWantWriteError):
            pass
        except ssl.SSLError:
            self._fail('tls_failure')
        self._buffers()
        self._guard()
        return self.authenticated

    def queue_message(self, payload: dict[str, Any]) -> None:
        self._guard()
        self._configuration()
        if not self.authenticated:
            self._fail('not_authenticated')
        if self._write_pending:
            self._fail('write_busy')
        if self._tx_sequence >= MAX_MESSAGES:
            self._fail('message_limit')
        if type(payload) is not dict:
            self._fail('frame_value')
        envelope = dict(
            version=1, attempt_id=self._binding.attempt_id, vm_id=self._binding.vm_id,
            operation=OPERATION, sender=self._role, sequence=self._tx_sequence, payload=payload,
        )
        try:
            _tree(envelope)
            body = json.dumps(
                envelope, ensure_ascii=True, allow_nan=False, separators=(',', ':'), sort_keys=True,
            ).encode('utf-8')
        except (ValueError, TypeError, RecursionError):
            self._fail('frame_value')
        if not 0 < len(body) <= MAX_FRAME_BYTES:
            self._fail('frame_size')
        self._guard()
        self._write_pending = struct.pack('!I', len(body)) + body
        self._write_offset = 0
        self._tx_sequence += 1

    def _pop(self) -> dict[str, Any] | None:
        if len(self._plain) < 4:
            return None
        size = struct.unpack('!I', self._plain[:4])[0]
        if not 0 < size <= MAX_FRAME_BYTES:
            self._fail('frame_size')
        if len(self._plain) < size + 4:
            return None
        body = bytes(self._plain[4:size + 4])
        del self._plain[:size + 4]
        try:
            value = json.loads(body.decode('utf-8'), object_pairs_hook=_unique, parse_constant=_constant)
            _tree(value)
        except (ValueError, TypeError, RecursionError):
            self._fail('frame_value')
        fields = {'version', 'attempt_id', 'vm_id', 'operation', 'sender', 'sequence', 'payload'}
        peer = 'guest' if self._role == 'controller' else 'controller'
        if (type(value) is not dict or set(value) != fields or
                type(value['version']) is not int or value['version'] != 1 or
                value['attempt_id'] != self._binding.attempt_id or
                value['vm_id'] != self._binding.vm_id or value['operation'] != OPERATION or
                value['sender'] != peer or type(value['payload']) is not dict):
            self._fail('frame_binding')
        if (type(value['sequence']) is not int or value['sequence'] != self._rx_sequence or
                self._rx_sequence >= MAX_MESSAGES):
            self._fail('frame_sequence')
        self._guard()
        self._rx_sequence += 1
        return value['payload']

    def receive_message(self) -> dict[str, Any] | None:
        self._guard()
        self._configuration()
        if not self.authenticated:
            self._fail('not_authenticated')
        value = self._pop()
        if value is not None:
            return value
        try:
            data = self._tls.read(min(16384, MAX_FRAME_BYTES + 4 - len(self._plain)))
        except (ssl.SSLWantReadError, ssl.SSLWantWriteError):
            self._guard()
            return None
        except ssl.SSLError:
            self._fail('tls_failure')
        self._guard()
        if not data:
            self._fail('truncated_frame' if self._plain else 'channel_closed')
        self._plain.extend(data)
        self._buffers()
        return self._pop()
