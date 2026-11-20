"""Fixed automatic finalization exchange; not a launcher or publication API.

A protected caller must already own the launch claim, reviewed credential/media
bindings, and supervision of the exact disposable recovery VM and copied disk.
The wire never supplies a profile, a path, an executable or host cleanup facts.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import ssl
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from night_shifts.bounded_tls_pipe import BoundedTlsPipe
from night_shifts.guest import finalize_image_copy as guest
from night_shifts.guest.bounded_tls_serial import GuestTlsSerial
from night_shifts.maintenance_tls_prototype import FINALIZATION_OPERATION, AttemptBinding
from night_shifts.serial_pipe_io import IOBudget

_DIGEST = re.compile(r'[0-9a-f]{64}', re.ASCII)
_FAILURE = {'version': 1, 'status': 'finalization_not_verified'}


class FinalizationRefused(RuntimeError):
    """Fixed failure labels; no peer data or native errors."""


@dataclass(frozen=True)
class GuestFinalizationEvidence:
    """Guest audit/unmount only; not host stop, removal, digest or acceptance."""

    binding: AttemptBinding
    request_sha256: str


class _Channel(Protocol):
    @property
    def binding(self) -> AttemptBinding: ...

    def send_message(self, payload: dict[str, Any]) -> None: ...

    def receive_message(self) -> dict[str, Any]: ...


def _require_finalization(binding: AttemptBinding) -> None:
    if type(binding) is not AttemptBinding or binding.operation != FINALIZATION_OPERATION:
        raise FinalizationRefused('invalid_finalization_binding')


def request_digest(request: dict[str, Any], binding: AttemptBinding) -> str:
    """Commit to the entire approved local media request, not an editable task."""
    _require_finalization(binding)
    try:
        local = guest.validate_request(request)
        if local['id'] != binding.attempt_id or local['mode'] != 'finalize':
            raise ValueError
        raw = json.dumps(local, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')
    except (guest.FinalizationError, ValueError, TypeError):
        raise FinalizationRefused('invalid_finalization_configuration') from None
    return hashlib.sha256(b'night-shift/finalization-request/v1\0' + raw).hexdigest()


def _require_digest(value: Any) -> None:
    if type(value) is not str or _DIGEST.fullmatch(value) is None:
        raise FinalizationRefused('invalid_finalization_digest')


def _success(digest: str) -> dict[str, Any]:
    return {'version': 1, 'status': 'success', 'audit': 'pass',
            'unmounted_read_only': True, 'request_sha256': digest}


def finalize_once(channel: _Channel, *, reviewed_request_sha256: str) -> GuestFinalizationEvidence:
    """Controller: send a fixed grant only and accept the exact bounded receipt."""
    binding = channel.binding
    _require_finalization(binding)
    _require_digest(reviewed_request_sha256)
    channel.send_message({'version': 1, 'action': FINALIZATION_OPERATION,
                          'request_sha256': reviewed_request_sha256})
    received = channel.receive_message()
    if type(received) is not dict or type(received.get('version')) is not int:
        raise FinalizationRefused('invalid_finalization_receipt')
    if received == _FAILURE:
        raise FinalizationRefused('finalization_not_verified')
    if received != _success(reviewed_request_sha256) or received['unmounted_read_only'] is not True:
        raise FinalizationRefused('invalid_finalization_receipt')
    return GuestFinalizationEvidence(binding, reviewed_request_sha256)


def serve_finalization_once(channel: _Channel, *, check_write_window: Callable[[], None]) -> bool:
    """Guest: verify the grant against trusted boot media before any disk work."""
    binding = channel.binding
    _require_finalization(binding)
    message = channel.receive_message()
    if (type(message) is not dict or set(message) != {'version', 'action', 'request_sha256'}
            or type(message['version']) is not int or message['version'] != 1
            or message['action'] != FINALIZATION_OPERATION):
        raise FinalizationRefused('invalid_finalization_request')
    digest = message['request_sha256']
    _require_digest(digest)
    try:
        local = guest.recovery_request()
        if not hmac.compare_digest(request_digest(local, binding), digest):
            raise FinalizationRefused('finalization_not_verified')
        check_write_window()
        receipt = guest._maintain_copy(local, before_write=check_write_window)
        if (type(receipt.get('version')) is not int or receipt['version'] != 1
                or receipt.get('id') != binding.attempt_id or receipt.get('mode') != 'finalize'
                or receipt.get('status') != 'success' or receipt.get('audit') != 'pass'
                or receipt.get('unmounted_read_only') is not True):
            raise FinalizationRefused('finalization_not_verified')
    except Exception:
        channel.send_message(dict(_FAILURE))
        return False
    channel.send_message(_success(digest))
    return True


def connect_and_finalize_once(
    context: ssl.SSLContext, binding: AttemptBinding, *, peer_sha256: str,
    reviewed_request_sha256: str, deadline: float, cancelled: Callable[[], bool],
) -> GuestFinalizationEvidence:
    _require_finalization(binding)
    _require_digest(reviewed_request_sha256)
    path = rf'\\.\pipe\night-shift-{binding.attempt_id}-com1'
    with BoundedTlsPipe(path, context, binding, peer_sha256=peer_sha256, timeout_seconds=900,
                        cancelled=cancelled, deadline=deadline) as channel:
        return finalize_once(channel, reviewed_request_sha256=reviewed_request_sha256)


def connect_and_serve_once(
    context: ssl.SSLContext, binding: AttemptBinding, *, peer_sha256: str,
    deadline: float, cancelled: Callable[[], bool],
) -> bool:
    _require_finalization(binding)
    budget = IOBudget(900, cancelled=cancelled, deadline=deadline)
    budget.remaining()

    def check_write_window() -> None:
        budget.remaining()

    with GuestTlsSerial(context, binding, peer_sha256=peer_sha256, timeout_seconds=900,
                        cancelled=cancelled, deadline=deadline) as channel:
        return serve_finalization_once(channel, check_write_window=check_write_window)
