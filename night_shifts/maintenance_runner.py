"""Small fixed-script runner shared by the app and protected inspection bundle."""
from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol
import re
import uuid


FAILURE_PHASES = frozenset(('COPY', 'CREATE', 'BOOT', 'CHANNEL', 'GUEST', 'STOP', 'VERIFY', 'REMOVE'))
CHANNEL_STAGES = frozenset(('not_applicable', 'pipe_create', 'pipe_connect', 'security_compile',
                           'security_query', 'security_parse', 'sid_resolve', 'acl_check',
                           'handshake_prepare', 'handshake_write', 'handshake_wait'))
FAILURE_CODES = frozenset(('operation_failed', 'win32_error', 'timeout', 'sid_unresolved',
                          'owner_rejected', 'dacl_absent', 'ace_unsupported', 'principal_rejected'))
FAILURE_FIELDS = frozenset(('version', 'id', 'mode', 'phase', 'channel_stage', 'code',
                           'win32_error', 'vm_id', 'stop_observation'))
MAX_FAILURE_RECEIPT_BYTES = 4096


def validate_failure_diagnostics(value: Any, *, identity: str | None = None,
                                 mode: str | None = None) -> dict[str, Any]:
    """Accept only fixed labels/numeric evidence, never raw exceptions or guest data.

    This is a failed-attempt snapshot, NOT image acceptance, verified unmount,
    current VM state, removal, or authorization to retry/clean up.
    """
    if not isinstance(value, dict) or set(value) != FAILURE_FIELDS:
        raise ValueError('Unexpected maintenance failure schema')
    if type(value['version']) is not int or value['version'] != 1:
        raise ValueError('Unexpected maintenance failure version')
    if not isinstance(value['id'], str) or not re.fullmatch('[0-9a-f]{32}', value['id']):
        raise ValueError('Invalid maintenance failure identity')
    for key, allowed in (('mode', ('inspect', 'finalize')), ('phase', FAILURE_PHASES),
                         ('channel_stage', CHANNEL_STAGES), ('code', FAILURE_CODES),
                         ('stop_observation', ('unknown', 'off_observed'))):
        if not isinstance(value[key], str) or value[key] not in allowed:
            raise ValueError('Invalid maintenance failure label')
    if identity is not None and value['id'] != identity:
        raise ValueError('Maintenance failure identity differs')
    if mode is not None and value['mode'] != mode:
        raise ValueError('Maintenance failure operation differs')
    if (value['phase'] == 'CHANNEL') == (value['channel_stage'] == 'not_applicable'):
        raise ValueError('Maintenance failure stage differs from phase')
    native = value['win32_error']
    if native is not None and (type(native) is not int or not 0 <= native <= 0xffffffff):
        raise ValueError('Invalid numeric Windows error')
    vm_id = value['vm_id']
    if vm_id is not None:
        if not isinstance(vm_id, str):
            raise ValueError('Invalid failure VM identity')
        try:
            valid = str(uuid.UUID(vm_id)) == vm_id
        except ValueError:
            valid = False
        if not valid:
            raise ValueError('Invalid failure VM identity')
    if value['stop_observation'] == 'off_observed' and vm_id is None:
        raise ValueError('Stop observation requires an exact VM identity')
    return dict(value)


class PowerShellCommandRunner(Protocol):
    def run(self, script: Path, arguments: Sequence[str]) -> str: ...


class SubprocessPowerShellRunner:
    def __init__(self, executable: str = 'powershell.exe', *, timeout_seconds: float = 1800):
        self.executable = executable
        self.timeout_seconds = timeout_seconds

    def run(self, script: Path, arguments: Sequence[str]) -> str:
        try:
            result = subprocess.run(
                [self.executable, '-NoLogo', '-NoProfile', '-NonInteractive',
                 '-ExecutionPolicy', 'RemoteSigned', '-File', str(script), *arguments],
                check=True, capture_output=True, text=True, shell=False,
                timeout=self.timeout_seconds,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            # Preserve only the fixed maintenance failure phase, never raw output.
            import re
            phase = re.search(r'NS-MAINTENANCE-FAIL (COPY|CREATE|BOOT|CHANNEL|GUEST|STOP|VERIFY|REMOVE)',
                              str(getattr(exc, 'stderr', '')))
            raise RuntimeError(phase.group(0) if phase else 'maintenance host outcome unknown') from exc
        return result.stdout.strip()
