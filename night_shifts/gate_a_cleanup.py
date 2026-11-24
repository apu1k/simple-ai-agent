"""Preview or recover disposable Hyper-V sandboxes from one attended Gate A run."""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import stat
import sys
from contextlib import nullcontext
from pathlib import Path

from night_shifts.backends.hyperv import HyperVError, PowerShellCommandRunner, SubprocessPowerShellRunner
from night_shifts.gate_a_run import DIGEST, SANDBOX_VM, GateAError, ensure_host_environment, gate_a_run_lease

_RUN_NAME = re.compile(r'gate-a-[0-9a-f]{32}')
_SANDBOX_ID = re.compile(r'[0-9a-f]{32}')
_SCRIPT = Path(__file__).with_name('backends') / 'hyperv_scripts' / 'recover_gate_a_sandbox.ps1'


def _entry(path: Path, *, directory: bool) -> bool:
    """Check the entry itself. Only a confirmed missing entry means absent."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if (not expected(info.st_mode) or getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
            or (not directory and info.st_nlink != 1)):
        raise GateAError(f'refusing unexpected or linked entry: {path}')
    return True


def _config_tree(directory: Path, *, empty_only: bool) -> list[Path]:
    if not _entry(directory, directory=True):
        return []
    directories = [directory]
    for child in directory.iterdir():
        info = child.lstat()
        if stat.S_ISDIR(info.st_mode):
            directories.extend(_config_tree(child, empty_only=empty_only))
        elif empty_only:
            raise GateAError(f'configuration files remain: {child}')
        else:
            _entry(child, directory=False)
    return directories


def _workspace_tree(workspace: Path, *, empty_only: bool) -> list[Path]:
    if not _entry(workspace, directory=True):
        return []
    children = {child.name for child in workspace.iterdir()}
    allowed = {'vm-config'} if empty_only else {'worker.vhdx', 'vm-config'}
    if children - allowed:
        raise GateAError(f'unexpected sandbox entries: {sorted(children - allowed)}')
    if not empty_only:
        _entry(workspace / 'worker.vhdx', directory=False)
    return [workspace, *_config_tree(workspace / 'vm-config', empty_only=empty_only)]


def _vm_names(value: object) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(x, str) and SANDBOX_VM.fullmatch(x) for x in value):
        raise GateAError('Gate A report has an invalid VM inventory')
    return value


def _plan(run_dir: Path) -> tuple[set[str], set[str], Path | None]:
    report_file = run_dir / 'report.json'
    if not _entry(report_file, directory=False):
        raise GateAError('a Gate A report.json is required')
    report = json.loads(report_file.read_text(encoding='utf-8'))
    if (not isinstance(report, dict) or not isinstance(report.get('run_dir'), str)
            or Path(report['run_dir']) != run_dir or report.get('status') not in (
                'running', 'passed', 'failed', 'incomplete', 'cleanup_unknown')):
        raise GateAError('report does not describe this Gate A run')
    sandboxes = run_dir / 'sandboxes'
    found = {p.name for p in sandboxes.iterdir()} if _entry(sandboxes, directory=True) else set()
    leftovers = report.get('leftovers', {})
    if not isinstance(leftovers, dict):
        raise GateAError('invalid leftovers record')
    found.update(vm.removeprefix('night-shift-') for vm in _vm_names(leftovers.get('new_vms', [])))
    if not found:
        return found, set(), None
    preexisting = set(_vm_names(report.get('preexisting_sandbox_vms')))
    base = report.get('base_image')
    digest = report.get('base_image_sha256')
    if (not isinstance(base, str) or not Path(base).is_absolute() or '..' in Path(base).parts
            or Path(base).is_relative_to(sandboxes) or not isinstance(digest, str) or not DIGEST.fullmatch(digest)):
        raise GateAError('run has no trustworthy base-image path in its report')
    return found, preexisting, Path(base)


def cleanup_run(run_dir: Path, *, apply: bool, runner: PowerShellCommandRunner) -> dict[str, object]:
    """Apply only on a trusted local workspace after all previous writers have stopped."""
    if not run_dir.is_absolute() or '..' in run_dir.parts or not _RUN_NAME.fullmatch(run_dir.name):
        raise GateAError('give an absolute gate-a-<32 lowercase hex> run directory')
    for directory in [*reversed(run_dir.parents), run_dir]:
        if not _entry(directory, directory=True):
            raise GateAError(f'run ancestry is missing: {directory}')
    if apply:
        _entry(run_dir / '.gate-a.lock', directory=False)
    results: dict[str, dict[str, str]] = {}
    with gate_a_run_lease(run_dir) if apply else nullcontext():
        names, preexisting, base = _plan(run_dir)
        for sid in sorted(names):
            if not _SANDBOX_ID.fullmatch(sid) or f'night-shift-{sid}' in preexisting:
                results[sid] = {'status': 'retained', 'detail': 'unexpected entry or preexisting VM'}
                continue
            workspace = run_dir / 'sandboxes' / sid
            try:
                _workspace_tree(workspace, empty_only=False)
                args = ('-Workspace', str(workspace), '-BaseImage', str(base))
                outcome = runner.run(_SCRIPT, (*args, '-Apply') if apply else args)
                expected = {'verified'} if apply else {'vm_candidate', 'disk_candidate', 'folders_only', 'absent'}
                if outcome not in expected:
                    raise GateAError('unexpected Hyper-V recovery response')
                if apply:
                    for directory in reversed(_workspace_tree(workspace, empty_only=True)):
                        directory.rmdir()
                    if _entry(workspace, directory=True):
                        raise GateAError('sandbox directory absence not confirmed')
                results[sid] = {'status': 'clean' if apply else outcome}
            except (GateAError, HyperVError, OSError) as exc:
                # A failed native operation can have partial effects. Never retry it here.
                results[sid] = {'status': 'unverified', 'detail': str(exc)[:500]}
    issues = any(item['status'] in {'unverified', 'retained'} for item in results.values())
    return {'run_dir': str(run_dir), 'status': 'review_needed' if issues else ('clean' if apply else 'preview'),
            'sandboxes': results}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', required=True, type=Path)
    parser.add_argument('--apply', action='store_true',
                        help='mutate only after confirming the interrupted runner, children and host operations stopped')
    args = parser.parse_args(argv)
    if sys.platform != 'win32' or not getattr(ctypes, 'windll').shell32.IsUserAnAdmin():
        print('gate_a_cleanup must run elevated on Windows', file=sys.stderr)
        return 2
    try:
        if not re.fullmatch(r'[A-Za-z]:', args.run_dir.drive):
            raise GateAError('use a local drive-letter path, not a network or device path')
        ensure_host_environment()
        runner = SubprocessPowerShellRunner(
            str(Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'),
            timeout_seconds=45,
        )
        result = cleanup_run(args.run_dir, apply=args.apply, runner=runner)
    except (GateAError, OSError, ValueError) as exc:
        result = {'status': 'review_needed', 'error': str(exc)[:500]}
    print(json.dumps(result, indent=2))
    return 1 if result['status'] == 'review_needed' else 0


if __name__ == '__main__':
    raise SystemExit(main())
