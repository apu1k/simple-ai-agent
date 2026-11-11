"""Explicit fixed setup handoff via the EXISTING protected command channel.

Not registered as a model tool, installer or production approval. Never invoke
checkout scripts elevated. Only a complete independently pinned, frozen review
snapshot is submitted; pending acceptance, separate installation and UAC remain.
"""
from __future__ import annotations

from typing import Any

from night_shifts.bootstrap_native_setup_launch import (
    SetupLaunchRefused, _review, prepare_setup_handoff, reconcile_setup_handoff,
)
from runtime.elevated_commands import run_approved_script
from runtime.privileged_turn import ELEVATED_OPERATION, PrivilegedClaim, PrivilegedTurn

REASON = ('Run only the independently reviewed fixed setup prepare/publication operation under its original protected '
    'execution deadline. Permanently consume the fixed outer claim before loading the held pinned watchdog. '
    'No provisioning, VM operation, overwrite, permission repair, claim reset, retry, installation acceptance or Gate A. '
    'Failure/cancellation or incomplete receipts leave outcome UNKNOWN; preserve exact evidence.')


def run_reviewed_setup_handoff(
    gate: PrivilegedTurn, claim: PrivilegedClaim, review: object, *, template: bytes,
) -> dict[str, Any]:
    """ONE handoff using an already-registered general command claim; no retry.

    All review inputs must be independently approved, INCLUDING template/helper
    pins and the helper/PowerShell/OS/CLR runtime closure and inherited native job
    behavior. There is no observed-pin promotion, default deployment or fallback.
    A general helper process receipt is NOT installation/VM cleanup evidence.
    """
    if claim.operation != ELEVATED_OPERATION:
        raise SetupLaunchRefused('handoff_operation')
    p = _review(review)
    frozen = prepare_setup_handoff(p, template=template, request_id=claim.request_id,
        deadline_unix=int(claim.deadline_unix))
    result = run_approved_script(gate, claim, frozen.script, frozen.seconds, REASON, frozen.working_directory,
        required_helper_sha256=str(p['outer_helper_sha256']))
    base = dict(request_id=claim.request_id, accepted=False, provisioning_authorized=False,
        retry_authorized=False, gate_a='unrun', effects_verified=False)
    if result.get('status') in ('rejected', 'expired', 'uac_cancelled') and result.get('executed') is False:
        return dict(base, status=result['status'], executed=False)
    try:
        observed = reconcile_setup_handoff(p, request_id=claim.request_id, outer=result)
    except SetupLaunchRefused:
        return dict(base, status='setup_outcome_unknown', receipt=result.get('receipt'),
            reason='Preserve the fixed outer/setup claims and protected command/setup receipts. No retry or cleanup inference.')
    return dict(observed, effects_verified=False, receipt=result.get('receipt'), review_sha256=result.get('review_sha256'))
