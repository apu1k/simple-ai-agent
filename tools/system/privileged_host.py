"""Head-only, single-use fixed Hyper-V query; never a generic admin shell."""
from __future__ import annotations

import json

from runtime.privileged_host import collect_installed_evidence
from tools._base import tool


@tool(
    description=(
        'Collect read-only Hyper-V evidence for the operator-pinned VHDX/ISO/workspace. '
        'Requires the user to enable Privileged Hyper-V evidence in settings for this turn, '
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
        return 'Error: Enable privileged Hyper-V evidence in settings for the next turn; one attempt only.'
    try:
        report = collect_installed_evidence(claim)
        return json.dumps(report, sort_keys=True, indent=2)
    except Exception:
        # Exceptions can include private host paths; the protected audit and
        # normal tool audit carry execution identity. Do not retry/escalate.
        return json.dumps({'status': 'blocked_or_outcome_unknown',
                           'request_id': claim.request_id, 'launch_authorized': False,
                           'reason': 'Check protected installation, inputs, ACLs and receipts. '
                                     'No retry is authorized; enable a new turn explicitly.'})
