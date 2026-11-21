"""KVP-to-COM1 handoff for a fresh owned finalization VM; not a launcher.

The protected host owner must already hold the fresh claim, confined VM/media
and key storage, and supervise the VM independently of this worker. This call
never owns lifecycle or publication. Its result is bounded guest evidence only.
"""
from __future__ import annotations

import re
import time
from collections.abc import Callable

from night_shifts.authenticated_image_finalization import (
    FinalizationRefused, GuestFinalizationEvidence, connect_and_finalize_once,
)
from night_shifts.finalization_tls_identity import LocalPemIdentity, controller_context
from night_shifts.maintenance_tls_prototype import FINALIZATION_OPERATION, AttemptBinding
from night_shifts.public_bootstrap_host import LocalFinalizationBootstrapReader
from night_shifts.serial_pipe_io import IOBudget


def finalize_bootstrapped_copy_once(
    binding: AttemptBinding, identity: LocalPemIdentity, *, request_sha256: str,
    deadline: float, cancelled: Callable[[], bool],
) -> GuestFinalizationEvidence:
    """Poll only for initial absence; never reacquire a credential after TLS starts."""
    if (type(binding) is not AttemptBinding or binding.operation != FINALIZATION_OPERATION
            or type(request_sha256) is not str or re.fullmatch('[0-9a-f]{64}', request_sha256) is None
            or deadline is None):
        raise FinalizationRefused('invalid_bootstrap_configuration')
    budget = IOBudget(900, cancelled=cancelled, deadline=deadline)
    budget.remaining()
    # Bound KVP separately after the owner observes boot/readiness; TLS and disk
    # work are not required to finish within the shorter KVP acquisition window.
    reader = LocalFinalizationBootstrapReader(binding, deadline=budget.deadline, timeout_seconds=30,
                                             cancelled=cancelled)
    try:
        while (peer := reader.poll()) is None:
            time.sleep(min(0.05, budget.remaining()))
        budget.remaining()
        context = controller_context(identity, peer.server_ca_der)
        budget.remaining()
        evidence = connect_and_finalize_once(context, binding, peer_sha256=peer.server_leaf_sha256,
                                             reviewed_request_sha256=request_sha256, deadline=budget.deadline,
                                             cancelled=cancelled)
        budget.remaining()
        if evidence != GuestFinalizationEvidence(binding, request_sha256):
            raise FinalizationRefused('invalid_finalization_receipt')
        return evidence
    finally:
        reader.close()
