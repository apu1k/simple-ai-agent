"""Unelevated client: start the fixed installed Gate A task, or read its receipt."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from night_shifts.gate_a_installed import TASK_NAME, installed_root, windows_directory
from night_shifts.gate_a_run import GateAError


def status(root: Path) -> dict[str, Any]:
    if not root.is_dir():
        return {'status': 'not_installed'}
    try:
        with (root / 'runs' / 'latest.json').open('rb') as stream:
            raw = stream.read(16_385)
    except FileNotFoundError:
        return {'status': 'no_receipt'}
    if len(raw) > 16_384:
        raise GateAError('invalid Gate A receipt size')
    result = json.loads(raw)
    if not isinstance(result, dict) or result.get('status') not in (
            'running_or_unknown', 'passed', 'failed', 'incomplete', 'cleanup_unknown'):
        raise GateAError('invalid Gate A receipt')
    return result


def start(root: Path) -> dict[str, Any]:
    prior = status(root)
    if prior['status'] not in ('no_receipt', 'passed'):
        return {'status': 'not_submitted', 'last_receipt': prior}
    system = windows_directory() / 'System32'
    result = subprocess.run([str(system / 'schtasks.exe'), '/Run', '/TN', TASK_NAME],
                            cwd=system, capture_output=True, timeout=10, check=False,
                            text=True, errors='replace')
    if result.returncode:
        return {'status': 'submission_unconfirmed', 'detail': (result.stderr or result.stdout).strip()[:300]}
    # Task Scheduler accepted a demand-start request; this does not prove a
    # fresh execution (IgnoreNew), any VM effects, or a passing result.
    return {'status': 'submitted', 'previous_run_dir': prior.get('run_dir')}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('start', 'status'))
    args = parser.parse_args()
    if sys.platform != 'win32':
        print('the fixed Gate A task requires Windows', file=sys.stderr)
        return 2
    try:
        root = installed_root()
        result = start(root) if args.action == 'start' else status(root)
    except (GateAError, OSError, ValueError, subprocess.SubprocessError) as exc:
        result = {'status': 'request_unknown', 'detail': str(exc)[:300]}
    print(json.dumps(result, indent=2))
    return int(result['status'] in ('not_installed', 'not_submitted', 'request_unknown', 'submission_unconfirmed'))


if __name__ == '__main__':
    raise SystemExit(main())
