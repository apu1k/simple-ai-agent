"""Head-only, operator-pinned inspection. Not a generic administrator shell."""
from __future__ import annotations

import json

from core.tool_progress import evidence_progress
from runtime.privileged_inspection import inspect_installed_copy
from runtime.privileged_turn import INSPECTION_OPERATION
from tools._base import tool


@tool(
    description=(
        'Inspect a fresh copy of the operator-pinned diagnostic VHDX using one isolated recovery VM. '
        'Requires the distinct Privileged image inspection next-turn setting, separately reviewed '
        'protected installation/approval, and UAC. No model-selected inputs or commands. '
        'May create/start/stop/remove only the new exact-owned recovery VM and retain copy/media/evidence. '
        'No source modification, finalization, publication, Gate A, ACL repair, retry or broad cleanup. '
        'A process timeout is UNKNOWN and does not prove the VM stopped. Shell commands remain unelevated.'
    ),
    params={}, requires_state=True,
)
def inspect_privileged_image_copy(state) -> str:
    gate = getattr(state, 'privileged_turn', None)
    if gate is None:
        return 'Error: Privileged inspection is unavailable in this runtime.'
    try:
        claim = gate.claim(INSPECTION_OPERATION)
    except PermissionError:
        return 'Error: Enable the distinct privileged image inspection setting for the next turn.'
    evidence_progress('Starting inspection-only recovery on a fresh image copy; no image acceptance.')
    try:
        result = inspect_installed_copy(claim)
        evidence_progress('Inspection returned; final outcome requires verified protected receipts.')
        return json.dumps(result, sort_keys=True, indent=2)
    except Exception:
        evidence_progress('Inspection blocked or outcome unknown. Do not retry; inspect exact resources.')
        return json.dumps({'status': 'blocked_or_outcome_unknown', 'request_id': claim.request_id,
                           'accepted': False, 'gate_a': 'unrun', 'retry_authorized': False,
                           'reason': 'Review protected installation, approval, receipts and exact VM identity. '
                                     'Do not infer VM cleanup from process termination.'})
