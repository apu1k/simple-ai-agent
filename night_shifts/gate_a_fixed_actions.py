"""Bind one prepared Gate A attempt to two installed Windows action snapshots.

The protected owner, not the runtime, supplies the independently pinned source
bytes/digests and holds the workspace and media leases. This adapter accepts
neither script paths nor shell strings from an attempt request.
"""
from __future__ import annotations

import base64
import hashlib
import re
import time
from dataclasses import dataclass
from pathlib import PureWindowsPath
from threading import Lock

from night_shifts.gate_a_action_process_windows import _WindowsGateAProcess
from night_shifts.gate_a_host_lifecycle import _RECONCILE, _START, _action_args, _local_path
from night_shifts.gate_a_watchdog import (
    CLEANUP_RESERVE_NS, MAX_RECEIPT_BYTES, MAX_WINDOW_NS, TeardownTarget, WatchdogRefused,
)

_MAX_SCRIPT_BYTES = 8192
_MODULES = (
    r'Microsoft.PowerShell.Management\Microsoft.PowerShell.Management.psd1',
    r'Microsoft.PowerShell.Utility\Microsoft.PowerShell.Utility.psd1',
    r'Hyper-V\2.0.0.0\Hyper-V.psd1',
)


@dataclass(frozen=True)
class GateAActionSnapshot:
    source: bytes
    approved_sha256: str

    def text(self) -> str:
        if (type(self.source) is not bytes or not 0 < len(self.source) <= _MAX_SCRIPT_BYTES
                or type(self.approved_sha256) is not str
                or re.fullmatch('[0-9a-f]{64}', self.approved_sha256) is None
                or hashlib.sha256(self.source).hexdigest() != self.approved_sha256):
            raise WatchdogRefused('action_pin')
        try:
            text = self.source.decode('utf-8-sig')
        except UnicodeError:
            raise WatchdogRefused('action_encoding') from None
        if not text or '\0' in text:
            raise WatchdogRefused('action_encoding')
        return text


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _command(source: str, *, modules: PureWindowsPath, args: tuple[str, ...]) -> str:
    # The flag positions come from _action_args, not split/parsed caller text.
    arguments = ' '.join(value if i % 2 == 0 else _literal(value) for i, value in enumerate(args))
    imports = '\n'.join('Import-Module -Name ' + _literal(str(modules / path)) for path in _MODULES)
    script = (
        "$ErrorActionPreference = 'Stop'\n$ProgressPreference = 'SilentlyContinue'\n"
        "$WarningPreference = 'SilentlyContinue'\n$InformationPreference = 'SilentlyContinue'\n"
        "$PSModuleAutoLoadingPreference = 'None'\ntry {\n" + imports + '\n'
        '$result = & {\n' + source + '\n} ' + arguments + '\n'
        "if ($result -isnot [string]) { exit 2 }\n[Console]::Write($result)\nexit 0\n} catch { exit 2 }\n"
    )
    return base64.b64encode(script.encode('utf-16-le')).decode('ascii')


class WindowsPinnedGateAActions:
    """Fixed-script runner confined to one exact target and the original cap."""

    def __init__(self, target: TeardownTarget, *, held_workspace_root: str, held_boot_asset: str,
                 deadline_ns: int, start: GateAActionSnapshot, reconcile: GateAActionSnapshot) -> None:
        now = time.monotonic_ns()
        if (type(target) is not TeardownTarget or type(deadline_ns) is not int
                or not 0 < deadline_ns < 2**63 or not 0 < deadline_ns - now <= MAX_WINDOW_NS
                or type(start) is not GateAActionSnapshot or type(reconcile) is not GateAActionSnapshot):
            raise WatchdogRefused('action_binding')
        workspace, asset = _local_path(held_workspace_root), _local_path(held_boot_asset)
        if (asset.suffix.lower() != ('.iso' if target.operation == 'finalization' else '.vhdx')
                or asset == workspace or workspace / target.attempt_id in asset.parents):
            raise WatchdogRefused('action_binding')
        start_args, reconcile_args = _action_args(target, held_workspace_root, held_boot_asset, deadline_ns)
        self._bindings = {
            _START: (start_args, deadline_ns - CLEANUP_RESERVE_NS, start.text()),
            _RECONCILE: (reconcile_args, deadline_ns, reconcile.text()),
        }
        self._scratch = str(workspace / target.attempt_id)
        self._lock = Lock()
        self._admitted: set[str] = set()

    def run(self, fixed_script: str, args: tuple[str, ...], *, deadline_ns: int, stdout_limit: int) -> bytes:
        with self._lock:
            binding = self._bindings.get(fixed_script) if type(fixed_script) is str else None
            if (binding is None or type(args) is not tuple or any(type(a) is not str for a in args)
                    or type(deadline_ns) is not int or type(stdout_limit) is not int
                    or (args, deadline_ns) != binding[:2] or stdout_limit != MAX_RECEIPT_BYTES
                    or fixed_script in self._admitted or _RECONCILE in self._admitted
                    or time.monotonic_ns() >= deadline_ns):
                raise WatchdogRefused('action_refused')
            self._admitted.add(fixed_script)
        native = _WindowsGateAProcess(require_protected_owner=True)
        system_path, computer = native.system_identity()
        system = _local_path(system_path)
        powershell = system / r'WindowsPowerShell\v1.0'
        modules = powershell / 'Modules'
        exe = str(powershell / 'powershell.exe')
        environment = {
            'SystemRoot': str(system.parent), 'WINDIR': str(system.parent),
            'COMPUTERNAME': computer, 'PATH': str(system), 'PSModulePath': str(modules),
            'ComSpec': str(system / 'cmd.exe'), 'TEMP': self._scratch, 'TMP': self._scratch,
        }
        argv = (exe, '-NoLogo', '-NoProfile', '-NonInteractive', '-OutputFormat', 'Text', '-EncodedCommand',
                _command(binding[2], modules=modules, args=args))
        return native.capture(argv, cwd=str(system), environment=environment,
                              deadline_ns=deadline_ns, limit=stdout_limit)
