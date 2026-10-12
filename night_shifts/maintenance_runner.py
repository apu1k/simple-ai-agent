"""Small fixed-script runner shared by the app and protected inspection bundle."""
from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol


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
