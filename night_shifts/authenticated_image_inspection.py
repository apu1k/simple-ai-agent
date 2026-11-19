"""One fixed read-only inspection over an already authenticated TLS session.

This is not a launch or deployment entry point. The trusted caller supplies
reviewed per-attempt credentials and an original monotonic deadline; it owns
the one-shot claim and independent VM cleanup. A guest receipt is not host
unmount, VM absence, or image acceptance evidence.
"""
from __future__ import annotations

import re
import ssl
from collections.abc import Callable
from typing import Any, Protocol

from night_shifts.bounded_tls_pipe import BoundedTlsPipe
from night_shifts.guest import finalize_image_copy as guest
from night_shifts.guest.bounded_tls_serial import GuestTlsSerial
from night_shifts.maintenance_tls_prototype import AttemptBinding

_REQUEST = {'version': 1, 'action': 'inspect_image_copy'}
_FAILURE = {'version': 1, 'status': 'inspection_not_verified'}
_SUCCESS_KEYS = {'version', 'status', 'audit', 'unmounted_read_only', 'diagnostics'}
_COMPONENT = re.compile(r'[A-Za-z0-9_.@-]+', re.ASCII)
_DIGEST = re.compile(r'[0-9a-f]{64}', re.ASCII)
_DEBUG_TARGET = '/usr/lib/systemd/system/debug-shell.service'


class InspectionRefused(RuntimeError):
    """Fixed failure labels, with no guest or TLS provider data."""


class _TLSChannel(Protocol):
    def send_message(self, payload: dict[str, Any]) -> None: ...

    def receive_message(self) -> dict[str, Any]: ...


class _GuestTLSChannel(_TLSChannel, Protocol):
    @property
    def binding(self) -> AttemptBinding: ...


def _diagnostic_name(name: Any) -> bool:
    if type(name) is not str or not 1 <= len(name) <= 192:
        return False
    if any(part in ('.', '..') or not _COMPONENT.fullmatch(part) for part in name.split('/')):
        return False
    return (guest.artifact_name(name) or name in guest.DEBUG_LINKS
            or name.startswith('etc/night-shift-diagnostic-027/')
            or (name.startswith('etc/systemd/system/')
                and ('debug-shell.service' in name or 'night-shift-protocol-test.service' in name)))


def _diagnostics(value: Any, *, sanitize_links: bool = False) -> dict[str, dict[str, str]]:
    if type(value) is not dict or len(value) > 64:
        raise InspectionRefused('invalid_inspection_receipt')
    result: dict[str, dict[str, str]] = {}
    for name, item in value.items():
        if not _diagnostic_name(name) or type(item) is not dict:
            raise InspectionRefused('invalid_inspection_receipt')
        kind = item.get('kind')
        if (kind == 'file' and set(item) == {'kind', 'sha256'}
                and type(item['sha256']) is str and _DIGEST.fullmatch(item['sha256'])):
            result[name] = {'kind': 'file', 'sha256': item['sha256']}
        elif kind == 'unreviewed' and set(item) == {'kind'}:
            result[name] = {'kind': 'unreviewed'}
        elif kind == 'link' and set(item) == {'kind', 'target'} and type(item['target']) is str:
            if name in guest.DEBUG_LINKS and item['target'] == _DEBUG_TARGET:
                result[name] = {'kind': 'link', 'target': _DEBUG_TARGET}
            elif sanitize_links:
                # An unknown target may be text from the disk, not a reviewed path.
                result[name] = {'kind': 'unreviewed'}
            else:
                raise InspectionRefused('invalid_inspection_receipt')
        else:
            raise InspectionRefused('invalid_inspection_receipt')
    return result


def inspect_once(channel: _TLSChannel) -> dict[str, dict[str, str]]:
    """Controller: send only the fixed request and return bounded guest evidence."""
    channel.send_message(dict(_REQUEST))
    receipt = channel.receive_message()
    if type(receipt) is dict and receipt == _FAILURE and type(receipt['version']) is int:
        raise InspectionRefused('inspection_not_verified')
    if not (type(receipt) is dict and set(receipt) == _SUCCESS_KEYS
            and type(receipt['version']) is int and receipt['version'] == 1
            and receipt['status'] == 'success' and receipt['audit'] == 'inspection_only'
            and receipt['unmounted_read_only'] is True):
        raise InspectionRefused('invalid_inspection_receipt')
    return _diagnostics(receipt['diagnostics'])


def serve_inspection_once(channel: _GuestTLSChannel) -> bool:
    """Guest: authenticate one request before touching the copy; never finalize."""
    message = channel.receive_message()
    if not (type(message) is dict and message == _REQUEST and type(message['version']) is int):
        raise InspectionRefused('invalid_inspection_request')
    try:
        local = guest.recovery_request()
        if local['id'] != channel.binding.attempt_id or local['mode'] != 'inspect' or local['artifacts']:
            raise InspectionRefused('inspection_not_verified')
        receipt = guest._maintain_copy(local)
        if not (receipt['status'] == 'success' and receipt.get('audit') == 'inspection_only'
                and receipt['unmounted_read_only'] is True):
            raise InspectionRefused('inspection_not_verified')
        diagnostics = _diagnostics(receipt['diagnostics'], sanitize_links=True)
    except Exception:
        # Keep local exceptions, diagnostic contents and partial results off the wire.
        channel.send_message(dict(_FAILURE))
        return False
    channel.send_message({'version': 1, 'status': 'success', 'audit': 'inspection_only',
                          'unmounted_read_only': True, 'diagnostics': diagnostics})
    return True


def connect_and_inspect_once(
    context: ssl.SSLContext, binding: AttemptBinding, *, peer_sha256: str,
    deadline: float, cancelled: Callable[[], bool],
) -> dict[str, dict[str, str]]:
    """Connect only to the pipe derived from an independently observed new VM.

    A pipe name proves neither provenance nor access rights. No legacy
    maintenance prefix, arbitrary endpoint or plaintext fallback is supported.
    The deadline is on this host process's monotonic clock.
    """
    path = rf'\\.\pipe\night-shift-{binding.attempt_id}-com1'
    with BoundedTlsPipe(path, context, binding, peer_sha256=peer_sha256, timeout_seconds=900,
                        cancelled=cancelled, deadline=deadline) as channel:
        return inspect_once(channel)


def connect_and_serve_once(
    context: ssl.SSLContext, binding: AttemptBinding, *, peer_sha256: str,
    deadline: float, cancelled: Callable[[], bool],
) -> bool:
    """Serve on fixed ttyS0 under the guest's own local monotonic deadline."""
    with GuestTlsSerial(context, binding, peer_sha256=peer_sha256, timeout_seconds=900,
                        cancelled=cancelled, deadline=deadline) as channel:
        return serve_inspection_once(channel)
