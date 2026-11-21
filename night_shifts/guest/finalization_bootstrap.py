"""Fixed guest handoff: publish the public key, then serve authenticated COM1.

No CLI, daemon setup, secret creation, mount or VM action. The future reviewed
boot owner supplies stable private RAM keys, reviewed CD media and the confined
KVP daemon. No target filesystem is opened before mutual TLS and its grant.
"""
from __future__ import annotations

import json
import ssl
from collections.abc import Callable
from pathlib import Path
from uuid import UUID

from night_shifts.authenticated_image_finalization import (
    FinalizationRefused, connect_and_serve_once, request_digest,
)
from night_shifts.finalization_tls_identity import ControllerPublicTrust, LocalPemIdentity, guest_context
from night_shifts.guest import finalize_image_copy as guest
from night_shifts.guest.finalization_guest_identity import new_guest_identity
from night_shifts.guest.publish_public_bootstrap import publish_finalization_bootstrap
from night_shifts.maintenance_credentials_prototype import FinalizationPublicBootstrap
from night_shifts.maintenance_tls_prototype import AttemptBinding
from night_shifts.serial_pipe_io import IOBudget


def _check_live_boot(binding: AttemptBinding) -> None:
    # Request bytes cannot establish media provenance; the protected host pins
    # the entire media separately. Check the actual mount before reading them.
    try:
        raw = guest.command('/usr/bin/findmnt', '--json', '--mountpoint', str(guest.MEDIA),
                            '-o', 'TARGET,FSTYPE,OPTIONS')
        rows = json.loads(raw)['filesystems']
        if type(rows) is not list or len(rows) != 1 or type(rows[0]) is not dict:
            raise ValueError
        row = rows[0]
        options = set(row['options'].split(','))
        if (row['target'] != str(guest.MEDIA) or row['fstype'] != 'iso9660' or 'rw' in options
                or not {'ro', 'nodev', 'nosuid', 'noexec'} <= options):
            raise ValueError
        if str(UUID(Path('/sys/class/dmi/id/product_uuid').read_text().strip())) != binding.vm_id:
            raise ValueError
        if Path('/proc/swaps').read_text().split() != ['Filename', 'Type', 'Size', 'Used', 'Priority']:
            raise ValueError
        request_digest(guest.recovery_request(), binding)
    except Exception:
        raise FinalizationRefused('unverified_recovery_boot') from None


def serve_bootstrapped_copy_once(
    server: FinalizationPublicBootstrap, controller: ControllerPublicTrust, identity: LocalPemIdentity,
    *, deadline: float, cancelled: Callable[[], bool],
) -> bool:
    """No public advertisement on a stale, wrong or unverified recovery boot."""
    if (type(server) is not FinalizationPublicBootstrap or type(controller) is not ControllerPublicTrust
            or server.binding != controller.binding or deadline is None):
        raise FinalizationRefused('invalid_bootstrap_configuration')
    budget = IOBudget(900, cancelled=cancelled, deadline=deadline)
    budget.remaining()
    _check_live_boot(server.binding)
    budget.remaining()
    return _publish_and_serve(server, controller, guest_context(identity, controller), budget, cancelled)


def serve_fresh_guest_once(controller: ControllerPublicTrust, *, deadline: float,
                           cancelled: Callable[[], bool]) -> bool:
    """Future recovery boot entry after reviewed KVP daemon startup/ownership."""
    if type(controller) is not ControllerPublicTrust or deadline is None:
        raise FinalizationRefused('invalid_bootstrap_configuration')
    budget = IOBudget(900, cancelled=cancelled, deadline=deadline)
    budget.remaining()
    _check_live_boot(controller.binding)
    with new_guest_identity(controller.binding, budget) as (server, identity):
        budget.remaining()
        context = guest_context(identity, controller)
    # OpenSSL owns the TLS key now; no private descriptors need to remain open.
    return _publish_and_serve(server, controller, context, budget, cancelled)


def _publish_and_serve(server: FinalizationPublicBootstrap, controller: ControllerPublicTrust,
                       context: ssl.SSLContext, budget: IOBudget, cancelled: Callable[[], bool]) -> bool:
    budget.remaining()
    publish_finalization_bootstrap(server, deadline=budget.deadline, cancelled=cancelled)
    budget.remaining()
    return connect_and_serve_once(context, server.binding, peer_sha256=controller.leaf_sha256,
                                  deadline=budget.deadline, cancelled=cancelled)
