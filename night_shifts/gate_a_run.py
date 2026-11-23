"""One-call attended Gate A run.

1. Copy the pinned diagnostic working disk to a fresh run directory and verify it.
2. Bare-attach the copy to WSL, clean it with the reviewed ``finalize()`` policy,
   detach it and verify WSL released it. The image is never booted in WSL.
3. Run each real-host Hyper-V case from ``test_hyperv_real_host.py`` against the
   cleaned image, one pytest process per case, inside an overall deadline.
4. Compare Night Shift sandbox VMs before and after, and check the run's sandbox
   workspace is empty.

Reruns can skip steps 1-2 with ``--base-image``/``--base-image-sha256``.
Must run elevated: WSL disk attachment and Hyper-V both require Administrator.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any

from night_shifts.backends.hyperv import _VM_PREFIX
from night_shifts.guest.finalize_image_copy import validate_request
from night_shifts.protocol_image_bundle import _linux_text_bytes

REPO = Path(__file__).resolve().parents[1]
GUEST = REPO / 'night_shifts' / 'guest'
TEST_FILE = 'tests/night_shifts/test_hyperv_real_host.py'
CASES = (
    'test_real_host_prerequisites',
    'test_real_host_serial_round_trip_and_cleanup',
    'test_real_host_unsupported_objective_fails_and_cleans_up',
    'test_real_host_guest_disconnect_cleans_up_only_its_vm',
    'test_real_host_cancellation_forces_cleanup_while_guest_is_blocked',
    'test_real_host_timeout_forces_cleanup',
    'test_real_host_reconciliation_removes_only_the_generated_orphan',
)
UNIT = 'night-shift-protocol-test.service'
STAGED = ('finalize_image_copy.py', 'protocol_test_bootstrap.py',
          'review_protocol_test_target.py', 'wsl_finalize_copy.py', UNIT)
DIGEST = re.compile(r'[0-9a-f]{64}')
# protocol_test_bootstrap.py as installed in the diagnostic source image (53e0a7b).
# Cleanup audits this exact file, then replaces it with the current guest script.
INSTALLED_BOOTSTRAP_SHA256 = '6d8fd573e51fb5f573cdf7392dbd051574021b9a2c38be72e723316794e9d58b'
# The guest needs about two minutes to boot, so the real-host defaults are too short.
CASE_ENV = {'NIGHT_SHIFT_HYPERV_JOB_TIMEOUT_SECONDS': '300',
            'NIGHT_SHIFT_HYPERV_TIMEOUT_TEST_SECONDS': '240'}
SANDBOX_VM = re.compile(re.escape(_VM_PREFIX) + r'[0-9a-f]{32}')

Runner = Callable[[Sequence[str], float, dict[str, str]], 'subprocess.CompletedProcess[str]']


CASE_TIMEOUT_SECONDS = 420  # One hung case must not consume the whole run.
CASE_STACK_DUMP_SECONDS = 300


class GateAError(RuntimeError):
    """A step failed; the report records where."""


def _run(argv: Sequence[str], timeout: float, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(argv), capture_output=True, text=True, encoding='utf-8',
                          errors='replace', timeout=timeout, env=env, cwd=REPO, check=False)


def ensure_host_environment(environ: Any = os.environ) -> None:
    """Fill variables a stripped elevated launcher omits.

    CreateProcess resolves bare names such as ``powershell.exe`` against this
    process's PATH, and Hyper-V cmdlets need COMPUTERNAME to find the local host.
    """
    buffer = ctypes.create_unicode_buffer(260)
    if not getattr(ctypes, 'windll').kernel32.GetSystemWindowsDirectoryW(buffer, 260):
        raise GateAError('cannot resolve the Windows directory')
    windows = Path(buffer.value)
    system = windows / 'System32'
    for key in ('SystemRoot', 'WINDIR'):
        if not environ.get(key):
            environ[key] = str(windows)
    if not environ.get('COMPUTERNAME'):
        environ['COMPUTERNAME'] = platform.node()
    current = [p for p in environ.get('PATH', '').split(os.pathsep) if p]
    known = {p.rstrip('\\').lower() for p in current}
    required = [str(system), str(system / 'Wbem'), str(system / 'WindowsPowerShell' / 'v1.0')]
    environ['PATH'] = os.pathsep.join([p for p in required if p.lower() not in known] + current)


def sha256(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def wsl_path(path: Path) -> str:
    windows = PureWindowsPath(path)
    if not re.fullmatch(r'[A-Za-z]:', windows.drive) or not windows.is_absolute():
        raise GateAError(f'not an absolute drive path: {path}')
    parts = windows.parts[1:]
    if not all(re.fullmatch(r'[A-Za-z0-9._-]+', part) for part in parts):
        raise GateAError(f'path has characters not allowed for WSL handoff: {path}')
    return '/mnt/' + windows.drive[0].lower() + ''.join('/' + part for part in parts)


def build_request(artifacts: dict[str, str]) -> dict[str, bytes]:
    files = {name: _linux_text_bytes((GUEST / name).read_bytes(), name) for name in STAGED}
    request = validate_request({
        'version': 1, 'id': uuid.uuid4().hex, 'mode': 'finalize', 'artifacts': dict(artifacts),
        'payload': {'bootstrap': INSTALLED_BOOTSTRAP_SHA256,
                    'unit': hashlib.sha256(files[UNIT]).hexdigest()},
    })
    files['request.json'] = (json.dumps(request, sort_keys=True) + '\n').encode()
    upgrade = {'from': INSTALLED_BOOTSTRAP_SHA256,
               'to': hashlib.sha256(files['protocol_test_bootstrap.py']).hexdigest()}
    files['bootstrap-upgrade.json'] = (json.dumps(upgrade, sort_keys=True) + '\n').encode()
    return files


def new_disk(before: set[str], after: set[str]) -> str:
    added = after - before
    if len(added) != 1 or not before <= after:
        raise GateAError(f'expected exactly one new WSL disk, saw added={sorted(added)}')
    return added.pop()


@dataclass(frozen=True)
class GateAConfig:
    workspace_root: Path
    source: Path | None = None
    source_sha256: str | None = None
    profile: Path | None = None
    base_image: Path | None = None
    base_image_sha256: str | None = None
    distro: str = 'Ubuntu'
    cases: tuple[str, ...] = CASES
    deadline_seconds: float = 840.0
    case_budget_seconds: float = 300.0
    keep_going: bool = False

    def __post_init__(self) -> None:
        prepare = self.source is not None
        if prepare == (self.base_image is not None):
            raise ValueError('give either --source/--source-sha256/--profile or --base-image/--base-image-sha256')
        digest = self.source_sha256 if prepare else self.base_image_sha256
        if digest is None or not DIGEST.fullmatch(digest):
            raise ValueError('a lowercase SHA-256 is required for the source or base image')
        if prepare and self.profile is None:
            raise ValueError('--profile is required when preparing from --source')
        paths = [self.workspace_root, self.source, self.profile, self.base_image]
        if not all(p.is_absolute() for p in paths if p is not None):
            raise ValueError('paths must be absolute')
        if not self.cases or set(self.cases) - set(CASES) or len(set(self.cases)) != len(self.cases):
            raise ValueError('unknown or repeated Gate A case')
        if not re.fullmatch(r'[A-Za-z0-9._-]+', self.distro):
            raise ValueError('invalid WSL distribution name')
        if self.deadline_seconds <= 0 or self.case_budget_seconds <= 0:
            raise ValueError('deadlines must be positive')


class GateARun:
    def __init__(self, config: GateAConfig, *, runner: Runner = _run,
                 clock: Callable[[], float] = time.monotonic):
        self.config = config
        self.runner = runner
        self.clock = clock
        self.started = clock()
        self.run_dir = config.workspace_root / f'gate-a-{uuid.uuid4().hex}'
        self.env = {**os.environ, 'WSL_UTF8': '1'}
        # Hyper-V cmdlets resolve the local host from COMPUTERNAME and raise
        # ArgumentNullException when a launcher strips it from the environment.
        if not self.env.get('COMPUTERNAME'):
            self.env['COMPUTERNAME'] = platform.node()
        self.report: dict[str, Any] = {'run_dir': str(self.run_dir), 'status': 'running',
                                       'steps': [], 'cases': {}}

    # -- bookkeeping -------------------------------------------------------
    def _save(self) -> None:
        (self.run_dir / 'report.json').write_text(json.dumps(self.report, indent=2, sort_keys=True))

    def _step(self, name: str, **data: Any) -> None:
        self.report['steps'].append({'step': name, 'seconds': round(self.clock() - self.started, 1), **data})
        self._save()

    def _remaining(self) -> float:
        return self.config.deadline_seconds - (self.clock() - self.started)

    # -- WSL ---------------------------------------------------------------
    def _wsl_root(self, *argv: str, timeout: float = 120) -> subprocess.CompletedProcess[str]:
        return self.runner(['wsl.exe', '-d', self.config.distro, '-u', 'root', '--exec', *argv],
                           timeout, self.env)

    def _wsl_disks(self) -> set[str]:
        result = self._wsl_root('/usr/bin/lsblk', '--json', '-d', '-b', '-e', '7', '-o', 'PATH,TYPE')
        if result.returncode != 0:
            raise GateAError(f'WSL lsblk failed: {result.stderr.strip()[:300]}')
        return {d['path'] for d in json.loads(result.stdout)['blockdevices'] if d['type'] == 'disk'}

    def prepare(self) -> tuple[Path, str]:
        cfg = self.config
        assert cfg.source is not None and cfg.source_sha256 is not None and cfg.profile is not None
        artifacts = json.loads(cfg.profile.read_text(encoding='utf-8'))
        if not isinstance(artifacts, dict):
            raise GateAError('cleanup profile must be a JSON object')
        files = build_request(artifacts)
        if sha256(cfg.source) != cfg.source_sha256:
            raise GateAError('source disk SHA-256 differs from the pinned value')
        base = self.run_dir / 'base.vhdx'
        with cfg.source.open('rb') as reader, base.open('xb') as writer:
            shutil.copyfileobj(reader, writer, 16 * 1024 * 1024)
            writer.flush()
            os.fsync(writer.fileno())
        if sha256(base) != cfg.source_sha256:
            raise GateAError('fresh copy SHA-256 differs from the source')
        self._step('copied', path=str(base))
        stage = self.run_dir / 'wsl'
        stage.mkdir()
        for name, data in files.items():
            (stage / name).write_bytes(data)

        before = self._wsl_disks()
        device: str | None = None
        self.report['wsl_detach'] = 'unknown'  # Until release is observed.
        try:
            mount = self.runner(['wsl.exe', '--mount', '--vhd', str(base), '--bare'], 180, self.env)
            if mount.returncode != 0:
                raise GateAError(f'wsl --mount failed: {(mount.stdout + mount.stderr).strip()[:300]}')
            device = new_disk(before, self._wsl_disks())
            self._step('attached_to_wsl', device=device)
            helper = self._wsl_root('/usr/bin/python3', '-B', wsl_path(stage / 'wsl_finalize_copy.py'),
                                    '--device', device, '--workdir', wsl_path(stage), timeout=600)
            lines = [line for line in helper.stdout.splitlines() if line.strip()]
            try:
                receipt = json.loads(lines[-1])
            except (IndexError, ValueError):
                receipt = {'status': 'failed', 'error': 'no receipt',
                           'stderr': helper.stderr.strip()[-500:]}
            self.report['cleanup_receipt'] = receipt
            if helper.returncode != 0 or receipt.get('status') != 'success' or receipt.get('unmounted') is not True:
                raise GateAError('WSL cleanup refused or failed; see cleanup_receipt')
            self._step('cleaned')
        finally:
            try:
                self.runner(['wsl.exe', '--unmount', str(base)], 180, self.env)
                released = self._wsl_disks() == before
            except (GateAError, OSError, ValueError, subprocess.SubprocessError):
                released = False
            self.report['wsl_detach'] = 'verified' if released else 'unknown'
            self._step('detached_from_wsl', verified=released)
            if not released:
                raise GateAError('could not verify WSL released the disk; not using it for Hyper-V')

        digest = sha256(base)
        if digest == cfg.source_sha256:
            raise GateAError('cleaned image is byte-identical to the source; cleanup did not write')
        return base, digest

    # -- Hyper-V -----------------------------------------------------------
    def sandbox_vms(self) -> set[str] | None:
        script = "Get-VM -ErrorAction Stop | ForEach-Object { $_.Name }"
        result = self.runner(['powershell.exe', '-NoLogo', '-NoProfile', '-NonInteractive',
                              '-Command', script], 120, self.env)
        if result.returncode != 0:
            return None
        return {n.strip() for n in result.stdout.splitlines() if SANDBOX_VM.fullmatch(n.strip())}

    def run_cases(self, base: Path, digest: str) -> None:
        sandboxes = self.run_dir / 'sandboxes'
        sandboxes.mkdir()
        env = {**self.env, 'NIGHT_SHIFT_HYPERV_INTEGRATION': '1',
               'NIGHT_SHIFT_HYPERV_BASE_IMAGE': str(base),
               'NIGHT_SHIFT_HYPERV_BASE_IMAGE_SHA256': digest,
               'NIGHT_SHIFT_HYPERV_WORKSPACE': str(sandboxes), **CASE_ENV}
        cases: dict[str, Any] = self.report['cases']
        stop: str | None = None
        for case in self.config.cases:
            if stop is None and self._remaining() < self.config.case_budget_seconds:
                stop = 'deadline'
            if stop is not None:
                cases[case] = {'result': 'not_started', 'reason': stop}
                continue
            log = self.run_dir / f'test-{case}.log'
            started = self.clock()
            # -s -v so partial progress survives a kill; faulthandler dumps every
            # thread's stack if a case blocks, so a hang shows where it is stuck.
            argv = [sys.executable, '-X', 'faulthandler', '-m', 'pytest', f'{TEST_FILE}::{case}',
                    '-v', '-s', '-rA', '-p', 'no:cacheprovider',
                    '-o', f'faulthandler_timeout={CASE_STACK_DUMP_SECONDS}']
            try:
                result = self.runner(argv, max(min(self._remaining() - 15, CASE_TIMEOUT_SECONDS), 1), env)
            except subprocess.TimeoutExpired as exc:
                parts = [p if isinstance(p, str) else (p or b'').decode('utf-8', 'replace')
                         for p in (exc.stdout, exc.stderr)]
                log.write_text('\n--- stderr ---\n'.join(parts), encoding='utf-8')
                cases[case] = {'result': 'interrupted', 'log': str(log)}
                stop = f'{case} was interrupted mid-run'
                self._save()
                continue
            output = result.stdout + result.stderr
            log.write_text(output, encoding='utf-8')
            passed = (result.returncode == 0 and re.search(r'\b1 passed\b', result.stdout) is not None
                      and 'skipped' not in result.stdout)
            summary = next((line for line in reversed(result.stdout.splitlines()) if line.strip()), '')
            cases[case] = {'result': 'passed' if passed else 'failed', 'log': str(log),
                           'seconds': round(self.clock() - started, 1), 'summary': summary[:300]}
            if not passed and not self.config.keep_going:
                stop = f'{case} failed'
            self._save()

    # -- driver ------------------------------------------------------------
    def execute(self) -> dict[str, Any]:
        self.run_dir.mkdir(parents=True, exist_ok=False)
        self._save()
        vms_before: set[str] | None = None
        try:
            if self.config.source is not None:
                base, digest = self.prepare()
            else:
                assert self.config.base_image is not None and self.config.base_image_sha256 is not None
                base, digest = self.config.base_image, self.config.base_image_sha256
                if sha256(base) != digest:
                    raise GateAError('base image SHA-256 differs from the pinned value')
            self.report.update(base_image=str(base), base_image_sha256=digest)
            self._step('image_ready')
            vms_before = self.sandbox_vms()
            if vms_before is None:
                raise GateAError('could not list Hyper-V VMs before the tests')
            self.report['preexisting_sandbox_vms'] = sorted(vms_before)
            self.run_cases(base, digest)
        except Exception as exc:
            self.report['error'] = f'{type(exc).__name__}: {exc}'[:500]
        finally:
            if vms_before is not None:
                after = self.sandbox_vms()
                sandboxes = self.run_dir / 'sandboxes'
                self.report['leftovers'] = {
                    'inventory': 'ok' if after is not None else 'unknown',
                    'new_vms': sorted(after - vms_before) if after is not None else [],
                    'sandbox_dirs': sorted(p.name for p in sandboxes.iterdir()) if sandboxes.exists() else [],
                }
            self.report['status'] = self._status()
            self.report['seconds'] = round(self.clock() - self.started, 1)
            self._save()
        return self.report

    def _status(self) -> str:
        results = [c['result'] for c in self.report['cases'].values()]
        left = self.report.get('leftovers')
        if (self.report.get('wsl_detach') == 'unknown' or 'interrupted' in results
                or (left is not None and (left['inventory'] != 'ok' or left['new_vms'] or left['sandbox_dirs']))):
            return 'cleanup_unknown'
        if 'error' in self.report or 'failed' in results:
            return 'failed'
        if len(results) == len(self.config.cases) and all(r == 'passed' for r in results):
            return 'passed'
        return 'incomplete'


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--source-sha256')
    parser.add_argument('--profile', type=Path)
    parser.add_argument('--base-image', type=Path)
    parser.add_argument('--base-image-sha256')
    parser.add_argument('--distro', default='Ubuntu')
    parser.add_argument('--cases', nargs='+', choices=CASES, default=list(CASES))
    parser.add_argument('--deadline-seconds', type=float, default=840.0)
    parser.add_argument('--keep-going', action='store_true')
    args = parser.parse_args(argv)
    if sys.platform != 'win32' or not getattr(ctypes, 'windll').shell32.IsUserAnAdmin():
        print('gate_a_run must run elevated on Windows', file=sys.stderr)
        return 2
    ensure_host_environment()
    config = GateAConfig(workspace_root=args.workspace, source=args.source,
                         source_sha256=args.source_sha256, profile=args.profile,
                         base_image=args.base_image, base_image_sha256=args.base_image_sha256,
                         distro=args.distro, cases=tuple(args.cases),
                         deadline_seconds=args.deadline_seconds, keep_going=args.keep_going)
    report = GateARun(config).execute()
    print(json.dumps({key: report.get(key) for key in (
        'status', 'run_dir', 'base_image', 'base_image_sha256', 'error', 'wsl_detach',
        'cleanup_receipt', 'cases', 'leftovers', 'seconds')}, indent=2))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
