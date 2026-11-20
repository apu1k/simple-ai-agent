"""Head-only general Administrator execution, with live approval and UAC."""
from __future__ import annotations

import json

from runtime.elevated_commands import MAX_TIMEOUT, read_script_file, run_approved_script, validate_script
from runtime.privileged_turn import ELEVATED_OPERATION
from tools._base import tool


@tool(
    description=(
        'Request execution of an inline PowerShell script or a local .ps1 file as '
        'Administrator on Windows. Set exactly one of script and script_path. '
        'For a file, approval review shows the source path and full contents; only the frozen '
        'snapshot is executed, not a later read of the original file. '
        'Requires Elevated commands: Enable next turn, per-request acceptance in the '
        'configured approval UI (local Textual or host desktop), a separately installed protected launcher, and UAC. '
        'The app and ordinary shell tool remain unelevated. Head agent only. '
        f'Execution timeout is 1-{MAX_TIMEOUT} seconds (15-minute maximum, installed policy may be lower); '
        'approval waiting is separate and expires with the turn. Script is shown verbatim, '
        'then hash-bound to protected execution. Arbitrary scripts/dependencies are NOT '
        'sandboxed. Timeout does not undo changes or prove external resources stopped. '
        'No automatic retry. Output is bounded and execution is audited.'
    ),
    params={
        'script': {'type': 'string', 'default': '', 'description':
                   'Complete inline script (max 32768 UTF-8 bytes); omit when using script_path.'},
        'script_path': {'type': 'string', 'default': '', 'description':
                        'Local UTF-8 .ps1 file, absolute or relative to the working directory; omit for inline scripts.'},
        'reason': 'Explain the purpose and expected host changes; not a safety guarantee.',
        'timeout': {'type': 'integer', 'minimum': 1, 'maximum': MAX_TIMEOUT,
                    'default': 30, 'description': f'Execution limit, 1-{MAX_TIMEOUT} seconds.'},
    },
    requires_state=True,
)
def run_elevated_shell_command(state, script: str = '', reason: str = '', timeout: int = 30,
                               script_path: str = '') -> str:
    gate = getattr(state, 'privileged_turn', None)
    if gate is None:
        return 'Error: Elevated commands are unavailable in this runtime.'
    try:
        if not isinstance(script, str) or not isinstance(script_path, str) or bool(script) == bool(script_path):
            raise ValueError('Specify exactly one of script and script_path')
        source_path = None
        if script_path:
            source_path, script = read_script_file(state.cwd, script_path)
        validate_script(script, timeout, reason)
    except (OSError, ValueError) as exc:
        return f'Error: {exc}'
    try:
        claim = gate.claim(ELEVATED_OPERATION)
    except PermissionError:
        return 'Error: Enable Elevated commands for the next turn; each request needs approval and UAC.'
    try:
        result = run_approved_script(gate, claim, script, timeout, reason, str(state.cwd),
                                     script_path=source_path)
    except Exception:
        result = dict(status='blocked_or_outcome_unknown', request_id=claim.request_id,
                      effects_verified=False, retry_authorized=False,
                      reason='Review installation and protected receipts; do not infer rollback or retry.')
    return json.dumps(result, sort_keys=True, indent=2)
