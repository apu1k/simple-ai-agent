"""Fixed Windows Task Scheduler action for the reviewed Gate A image and suite."""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from night_shifts.gate_a_run import (
    GateAConfig, GateAError, GateARun, Runner, _run, ensure_host_environment, gate_a_run_lease,
)

IMAGE_SHA256 = '13bc986452a63d145b6cdd2d5b79e629d9244745269b0996b3bf24daf39894d6'
INSTALL_NAME = 'AiAgentGateA'
TASK_NAME = r'\AiAgentGateA'
_ROOT = Path(__file__).resolve().parents[2]


def windows_directory() -> Path:
    buf = ctypes.create_unicode_buffer(260)
    count = getattr(ctypes, 'windll').kernel32.GetSystemWindowsDirectoryW(buf, len(buf))
    if not 0 < count < len(buf):
        raise GateAError('Windows directory unavailable')
    return Path(buf.value)


def installed_root() -> Path:
    # Program Files via the native shell API; no path from caller env.
    buf = ctypes.create_unicode_buffer(260)
    if getattr(ctypes, 'windll').shell32.SHGetFolderPathW(None, 0x26, None, 0, buf) != 0:
        raise GateAError('Program Files unavailable')
    return Path(buf.value) / INSTALL_NAME


def _prepare_environment(root: Path) -> None:
    windows = windows_directory()
    system = windows / 'System32'
    powershell = system / 'WindowsPowerShell/v1.0'
    os.environ.clear()
    os.environ.update({
        'SystemRoot': str(windows), 'WINDIR': str(windows),
        'ComSpec': str(system / 'cmd.exe'),
        'PSModulePath': str(powershell / 'Modules'),
        'TEMP': str(root / 'scratch'), 'TMP': str(root / 'scratch'),
        'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1',
    })
    ensure_host_environment()


def _fixed_child_runner(root: Path) -> Runner:
    def run(argv: Sequence[str], timeout: float, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        if argv[0] == sys.executable:
            # Never discover pytest settings or conftest files in ancestor
            # folders, even for a package in an Administrator-owned directory.
            argv = [argv[0], '-I', '-B', *argv[1:], '-c', str(root / 'app/gate-a-pytest.ini'), '--noconftest']
        elif argv[0] == 'powershell.exe':
            # Resolve natively: {**os.environ} upper-cases keys on Windows
            # ('SYSTEMROOT'), so a dict lookup of 'SystemRoot' fails.
            exe = windows_directory() / 'System32/WindowsPowerShell/v1.0/powershell.exe'
            argv = [str(exe), *argv[1:]]
        else:
            raise GateAError('unexpected protected Gate A child process')
        return _run(argv, timeout, env)

    return run


def _publish(path: Path, result: dict[str, Any]) -> None:
    pending = path.with_name('.latest.json.tmp')
    pending.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    pending.replace(path)


def _installed_runner(root: Path) -> int:
    runs = root / 'runs'
    latest = runs / 'latest.json'
    with gate_a_run_lease(runs):
        try:
            previous = json.loads(latest.read_text(encoding='utf-8'))
        except FileNotFoundError:
            pass
        else:
            if not isinstance(previous, dict) or previous.get('status') != 'passed':
                raise GateAError('earlier protected run requires operator review; no automatic retry')
        job = GateARun(GateAConfig(workspace_root=runs, base_image=root / 'base.vhdx',
                                   base_image_sha256=IMAGE_SHA256, deadline_seconds=810),
                       runner=_fixed_child_runner(root))
        receipt: dict[str, Any] = {
            'status': 'running_or_unknown', 'started_utc': datetime.now(UTC).isoformat(),
            'run_dir': str(job.run_dir), 'image_sha256': IMAGE_SHA256,
        }
        _publish(latest, receipt)  # Fail before any host work if the start receipt cannot be written.
        try:
            report = job.execute()
        except Exception:
            # Do not retry unknown Hyper-V outcomes, even with the scheduler idle.
            return 1
        status = report.get('status')
        if status not in ('passed', 'failed', 'incomplete', 'cleanup_unknown'):
            return 1
        receipt.update(status=status, seconds=report.get('seconds'),
                       finished_utc=datetime.now(UTC).isoformat(),
                       report=str(job.run_dir / 'report.json'),
                       cases={name: item['result'] for name, item in report['cases'].items()},
                       leftovers=report.get('leftovers'))
        _publish(latest, receipt)
        return 0 if status == 'passed' else 1


def main() -> int:
    # Only the pinned package, in the fixed location, under a trusted token.
    if (sys.platform != 'win32' or sys.argv[1:] or not sys.flags.isolated
            or not getattr(ctypes, 'windll').shell32.IsUserAnAdmin() or _ROOT != installed_root()
            or Path(sys.executable) != _ROOT / 'python' / 'python.exe'):
        return 2
    try:
        _prepare_environment(_ROOT)
        return _installed_runner(_ROOT)
    except (GateAError, OSError, ValueError, subprocess.SubprocessError):
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
