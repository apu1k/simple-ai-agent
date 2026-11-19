"""Internal operator-pinned inspection; not exposed to the model."""
from __future__ import annotations

import json

from core.tool_progress import evidence_progress
from runtime.privileged_inspection import inspect_installed_copy, load_inspection_policy
from runtime.elevated_commands import await_approval
from runtime.privileged_turn import INSPECTION_OPERATION


def inspect_privileged_image_copy(state) -> str:
    gate = getattr(state, 'privileged_turn', None)
    if gate is None:
        return 'Error: Privileged inspection is unavailable in this runtime.'
    try:
        claim = gate.claim(INSPECTION_OPERATION)
    except PermissionError:
        return 'Error: Enable Elevated commands for the next turn; pending approval is required.'
    evidence_progress('Starting inspection-only recovery on a fresh image copy; no image acceptance.')
    try:
        root, powershell, policy, policy_digest = load_inspection_policy()
        request, decision = await_approval(gate, claim, dict(
            operation=claim.operation, request_id=claim.request_id,
            helper=str(root / 'helper.ps1'), executable=str(powershell),
            deadline_unix=int(claim.deadline_unix), max_execution_seconds=policy['max_execution_seconds'],
            policy=policy, policy_sha256=policy_digest,
            scope='Inspect-only fresh copy and exact-owned recovery VM. No finalization, publication, '
                  'Gate A, ACL repair, claim reset or retry; timeout leaves outcome UNKNOWN. '
                  'Protected worker execution cap: 900 seconds; approval expiry may shorten it.',
        ))
        if decision != 'accepted':
            return json.dumps(dict(status=decision, executed=False, request_id=claim.request_id,
                                   review_sha256=request.review_sha256))
        if load_inspection_policy() != (root, powershell, policy, policy_digest):
            raise PermissionError('Installed inspection policy changed after review')
        gate.require_accepted(request)
        result = inspect_installed_copy(claim)
        result['approval'] = 'accepted'
        result['review_sha256'] = request.review_sha256
        evidence_progress('Inspection returned; final outcome requires verified protected receipts.')
        return json.dumps(result, sort_keys=True, indent=2)
    except Exception:
        evidence_progress('Inspection blocked or outcome unknown. Do not retry; inspect exact resources.')
        return json.dumps({'status': 'blocked_or_outcome_unknown', 'request_id': claim.request_id,
                           'accepted': False, 'gate_a': 'unrun', 'retry_authorized': False,
                           'reason': 'Review protected installation, approval, receipts and exact VM identity. '
                                     'Do not infer VM cleanup from process termination.'})
