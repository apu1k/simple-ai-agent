"""Head-only, single-use fixed Hyper-V query; never a generic admin shell."""
from __future__ import annotations

import json

from core.tool_progress import evidence_progress
from runtime.privileged_host import collect_installed_evidence, load_policy
from runtime.elevated_commands import await_approval
from tools._base import tool


@tool(
    description=(
        'Collect read-only Hyper-V evidence for the operator-pinned VHDX/ISO/workspace. '
        'Requires Elevated commands enabled for this turn, acceptance of this fixed operation in pending, '
        'a protected helper installation, and Windows UAC consent. One attempt only, '
        'including cancellation/failure. No inputs, arbitrary commands, VM launch, '
        'mounting, permission repair or lifecycle operations are accepted. '
        'Returns bounded evidence and the protected execution receipt path. '
        'run_shell_command is not elevated by this setting.'
    ),
    params={},
    requires_state=True,
)
def collect_privileged_host_evidence(state) -> str:
    gate = getattr(state, 'privileged_turn', None)
    if gate is None:
        return 'Error: Privileged evidence is unavailable in this runtime.'
    try:
        claim = gate.claim()
    except PermissionError:
        return 'Error: Enable Elevated commands for the next turn; one fixed collection attempt.'
    evidence_progress('Starting read-only host evidence collection…')
    try:
        root, powershell, policy = load_policy()
        request, decision = await_approval(gate, claim, dict(
            operation=claim.operation, request_id=claim.request_id,
            helper=str(root / 'helper.ps1'), executable=str(powershell),
            deadline_unix=int(claim.deadline_unix), policy=policy,
            scope='Fixed read-only host evidence; no VM lifecycle or arbitrary commands.',
        ))
        if decision != 'accepted':
            return json.dumps(dict(status=decision, executed=False, request_id=claim.request_id,
                                   review_sha256=request.review_sha256))
        if load_policy() != (root, powershell, policy):
            raise PermissionError('Installed evidence policy changed after review')
        gate.require_accepted(request)
        report = collect_installed_evidence(claim)
        report['approval'] = 'accepted'
        report['review_sha256'] = request.review_sha256
        evidence_progress('Collection returned; final report follows. No VM launch.')
        return json.dumps(report, sort_keys=True, indent=2)
    except Exception:
        evidence_progress('Collection blocked or outcome unknown; no automatic retry.')
        # Exceptions can include private host paths; the protected audit and
        # normal tool audit carry execution identity. Do not retry/escalate.
        return json.dumps({'status': 'blocked_or_outcome_unknown',
                           'request_id': claim.request_id, 'launch_authorized': False,
                           'reason': 'Check protected installation, inputs, ACLs and receipts. '
                                     'No retry is authorized; enable a new turn explicitly.'})
