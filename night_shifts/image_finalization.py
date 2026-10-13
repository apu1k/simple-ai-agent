"""Operator-only, copy-only image maintenance. No agent tool exposes this API.

Each inspection/finalization uses a fresh recovery VM and disk copy. Successful
maintenance is NOT image acceptance, export, Gate A or permission to retry.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
import re
import shutil
import stat
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from night_shifts.maintenance_runner import (
    MAX_FAILURE_RECEIPT_BYTES, PowerShellCommandRunner, SubprocessPowerShellRunner,
    validate_failure_diagnostics,
)
from night_shifts.guest.finalize_image_copy import validate_request
from night_shifts.hyperv_image_preflight import _checked_path
from night_shifts.protocol_image_bundle import _linux_text_bytes
from night_shifts.ubuntu_preparation_control import (
    PreparationError,
    check_control_parent,
    checked_preparation_control,
)

_GUEST = ('finalize_image_copy.py', 'protocol_test_bootstrap.py',
          'review_protocol_test_target.py', 'night-shift-protocol-test.service')


class ImageMaintenanceError(PreparationError):
    """Unknown attempt with an exact manifest and optional validated diagnostics."""

    def __init__(self, identity: str, manifest: Path,
                 diagnostics: dict[str, Any] | None = None):
        super().__init__(f'maintenance status UNKNOWN; inspect exact identity {identity}; never retry automatically')
        self.manifest = manifest
        self.diagnostics = diagnostics


@dataclass(frozen=True)
class FinalizationConfig:
    """Independent operator bindings, never values from a worker task."""

    source: Path
    source_sha256: str
    recovery_iso: Path
    recovery_iso_sha256: str
    workspace_root: Path
    mode: str = 'inspect'
    artifacts: dict[str, str] = field(default_factory=dict)
    guest_timeout_seconds: int = 240
    command_timeout_seconds: float = 1800

    def __post_init__(self) -> None:
        for digest in (self.source_sha256, self.recovery_iso_sha256):
            if not re.fullmatch(r'[0-9a-f]{64}', digest):
                raise ValueError('reviewed lowercase SHA-256 values required')
        if self.mode not in {'inspect', 'finalize'}:
            raise ValueError('mode must be inspect or finalize')
        if type(self.guest_timeout_seconds) is not int or not 120 <= self.guest_timeout_seconds <= 600:
            raise ValueError('guest timeout must be an integer from 120 to 600 seconds')
        if not math.isfinite(self.command_timeout_seconds) or not 900 <= self.command_timeout_seconds <= 3600:
            raise ValueError('host command timeout must be finite and from 900 to 3600 seconds')


def _digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _request(config: FinalizationConfig, identity: str) -> tuple[dict[str, Any], dict[str, bytes]]:
    guest = Path(__file__).resolve().parent / 'guest'
    payload = {name: _linux_text_bytes((guest / name).read_bytes(), name) for name in _GUEST}
    request = validate_request({
        'version': 1, 'id': identity, 'mode': config.mode, 'artifacts': dict(config.artifacts),
        'payload': {
            'bootstrap': hashlib.sha256(payload['protocol_test_bootstrap.py']).hexdigest(),
            'unit': hashlib.sha256(payload['night-shift-protocol-test.service']).hexdigest(),
        },
    })
    return request, payload


def media_files(config: FinalizationConfig, identity: str) -> dict[str, bytes]:
    """Credential-free NoCloud runcmd, deliberately NOT an autoinstall seed."""
    request, payload = _request(config, identity)
    # Nothing formats a disk, runs chroot, downloads packages or boots the target.
    script = (
        'set -eu; mkdir -m 0700 /run/night-shift-finalize-media; '
        'mount -t iso9660 -o ro,nodev,nosuid,noexec '
        '/dev/disk/by-label/CIDATA /run/night-shift-finalize-media; '
        '(cd /run/night-shift-finalize-media; sha256sum -c -- SHA256SUMS; '
        f'timeout --signal=TERM --kill-after=5 {config.guest_timeout_seconds} '
        'python3 -B finalize_image_copy.py)'
    )
    cloud = {'users': [], 'disable_root': True, 'ssh_pwauth': False,
             'package_update': False, 'package_upgrade': False,
             'runcmd': [['/bin/sh', '-c', script]]}
    files = {**payload,
             'request.json': (json.dumps(request, sort_keys=True) + '\n').encode(),
             'user-data': ('#cloud-config\n' + json.dumps(cloud, sort_keys=True) + '\n').encode(),
             # JSON is a YAML subset; avoid loading third-party YAML code on the host.
             'meta-data': (json.dumps({'instance-id': 'night-shift-finalize-' + identity,
                                      'local-hostname': 'night-shift-recovery'}) + '\n').encode()}
    files['SHA256SUMS'] = ''.join(f'{hashlib.sha256(data).hexdigest()}  {name}\n'
                                 for name, data in sorted(files.items())).encode('ascii')
    return files


def _write_media(path: Path, files: dict[str, bytes]) -> str:
    import pycdlib  # type: ignore[import-not-found]  # existing pinned development dependency

    iso = pycdlib.PyCdlib()
    iso.new(vol_ident='CIDATA', rock_ridge='1.09', joliet=3)
    try:
        for index, (name, data) in enumerate(sorted(files.items())):
            iso.add_fp(io.BytesIO(data), len(data), iso_path=f'/FILE{index:04d}.;1',
                       rr_name=name, joliet_path='/' + name)
        output = io.BytesIO()
        iso.write_fp(output)
        raw = output.getvalue()
    finally:
        iso.close()
    if not 32768 <= len(raw) <= 2 * 1024 * 1024:
        raise PreparationError('maintenance media outside fixed size bounds')
    # Read back authored contents before claiming any output path.
    reader = pycdlib.PyCdlib()
    reader.open_fp(io.BytesIO(raw))
    try:
        for name, expected in files.items():
            result = io.BytesIO()
            reader.get_file_from_iso_fp(result, rr_path='/' + name)
            if result.getvalue() != expected:
                raise PreparationError('maintenance media read-back differs')
    finally:
        reader.close()
    with path.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(raw).hexdigest()


def _manifest(workspace: Path, data: dict[str, Any], *, first: bool = False) -> None:
    control = checked_preparation_control(workspace)
    path = control / ('manifest.json' if first else 'manifest.pending')
    encoded = (json.dumps(data, sort_keys=True) + '\n').encode()
    if len(encoded) > 65536:
        raise PreparationError('maintenance manifest exceeds fixed bound')
    with path.open('xb') as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    checked_preparation_control(workspace)
    if not first:
        os.replace(path, control / 'manifest.json')


def run_image_maintenance(
    config: FinalizationConfig, *, operator_authorized: bool = False,
    iso_provenance_reviewed: bool = False, evidence_preserved: bool = False,
    runner: PowerShellCommandRunner | None = None,
    vm_receipt_path: Path | None = None,
    failure_receipt_path: Path | None = None,
) -> Path:
    """Return the host-only manifest, NEVER an accepted base-image path.

    A timed-out/crashed host command may leave its exact recovery VM running.
    Retain the permanent launch claim and unknown status; never retry or sweep.
    """
    if not (operator_authorized and iso_provenance_reviewed and evidence_preserved):
        raise PreparationError('maintenance authorization, reviewed ISO provenance and preserved evidence required')
    identity = uuid.uuid4().hex
    _request(config, identity)  # Validate artifact paths before any file/host effect.
    root = _checked_path(config.workspace_root, 'maintenance workspace root')
    checkout = Path(__file__).resolve().parents[1]
    if not root.is_dir() or root == Path(root.anchor) or root == checkout or checkout in root.parents:
        raise PreparationError('maintenance workspace must be an external, initially empty directory')
    if next(root.iterdir(), None) is not None:
        raise PreparationError('maintenance workspace not empty; preserve leftovers, do not retry')
    for path, suffix, digest in ((config.source, '.vhdx', config.source_sha256),
                                (config.recovery_iso, '.iso', config.recovery_iso_sha256)):
        checked = _checked_path(path, 'maintenance input')
        info = checked.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or checked.suffix.lower() != suffix:
            raise PreparationError('maintenance input must be a regular single-link file')
        if root == checked or root in checked.parents or checkout in checked.parents:
            raise PreparationError('maintenance inputs must be outside checkout and output workspace')
        if _digest(checked) != digest:
            raise PreparationError('maintenance input differs from independently reviewed digest')
    with config.source.open('rb') as stream:
        if stream.read(8) != b'vhdxfile':
            raise PreparationError('source lacks VHDX signature')
    # Recheck just before output creation. This is a reserve, not a disk quota.
    required = max(config.source.stat().st_size, 20 * 1024**3) + 512 * 1024**2
    if shutil.disk_usage(root).free < required:
        raise PreparationError('insufficient fresh workspace space for copy and reserve')
    workspace = root / identity
    control = check_control_parent(workspace)
    control.mkdir(exist_ok=False)
    checked_preparation_control(workspace)
    workspace.mkdir(exist_ok=False)
    state: dict[str, Any] = {'version': 1, 'id': identity, 'mode': config.mode,
                            'source': str(config.source), 'source_sha256': config.source_sha256,
                            'workspace': str(workspace), 'accepted': False,
                            'status': 'prepared_not_started'}
    _manifest(workspace, state, first=True)
    media = workspace / 'maintenance.iso'
    media_digest = _write_media(media, media_files(config, identity))
    selected = runner or SubprocessPowerShellRunner(timeout_seconds=config.command_timeout_seconds)
    script = Path(__file__).resolve().parent / 'backends/hyperv_scripts/maintain_image_copy.ps1'
    state['status'] = 'maintenance_unknown'
    _manifest(workspace, state)
    with (control / 'launch.claim').open('xb') as claim:
        claim.write((identity + '\n').encode('ascii'))
        claim.flush()
        os.fsync(claim.fileno())
    failure_path = failure_receipt_path or (control / 'host.failure.json')
    try:
        output = selected.run(script, (
            '-Identity', identity, '-Mode', config.mode,
            '-SourceDisk', str(config.source), '-SourceSha256', config.source_sha256,
            '-RecoveryIso', str(config.recovery_iso), '-RecoveryIsoSha256', config.recovery_iso_sha256,
            '-Workspace', str(workspace), '-SeedIsoSha256', media_digest,
            '-GuestTimeoutSeconds', str(config.guest_timeout_seconds),
            '-VmReceipt', str(vm_receipt_path or (control / 'host.vm.json')),
            '-FailureReceipt', str(failure_path),
        ))
        if len(output) > 65536:
            raise PreparationError('oversized host receipt')
        receipt = json.loads(output)
        guest = receipt['guest']
        if not (receipt['id'] == identity and receipt['mode'] == config.mode
                and receipt['source_sha256'] == config.source_sha256
                and receipt['source_unchanged'] is True and receipt['vm_removed'] is True
                and re.fullmatch(r'[0-9a-f]{64}', receipt['copy_sha256'])
                and guest['version'] == 1 and guest['id'] == identity and guest['mode'] == config.mode
                and guest['status'] == 'success' and guest['unmounted_read_only'] is True
                and (config.mode == 'inspect' or guest['audit'] == 'pass')):
            raise PreparationError('host/guest receipt does not prove the bounded maintenance outcome')
        if _digest(config.source) != config.source_sha256:
            raise PreparationError('source changed after maintenance')
        state['receipt'] = receipt
        state['status'] = 'inspected_not_accepted' if config.mode == 'inspect' else 'finalized_not_accepted'
        _manifest(workspace, state)
    except Exception as exc:
        phase = re.search(r'NS-MAINTENANCE-FAIL (COPY|CREATE|BOOT|CHANNEL|GUEST|STOP|VERIFY|REMOVE)', str(exc))
        state['failure_phase'] = phase.group(1) if phase else 'host_or_receipt_unknown'
        diagnostics = None
        try:
            info = failure_path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_FAILURE_RECEIPT_BYTES:
                raise ValueError('Invalid failure receipt file')
            with failure_path.open('rb') as stream:
                raw = stream.read(MAX_FAILURE_RECEIPT_BYTES + 1)
            if len(raw) > MAX_FAILURE_RECEIPT_BYTES:
                raise ValueError('Oversized failure receipt')
            candidate = validate_failure_diagnostics(json.loads(raw), identity=identity, mode=config.mode)
            if phase is not None and candidate['phase'] != phase.group(1):
                raise ValueError('Failure receipt phase differs')
            diagnostics = candidate
            state['failure_phase'] = candidate['phase']
            state['failure_diagnostics'] = candidate
        except (OSError, ValueError, TypeError):
            # Missing, partial, malformed or mismatched evidence never infers stop.
            pass
        _manifest(workspace, state)
        raise ImageMaintenanceError(identity, control / 'manifest.json', diagnostics) from exc
    return control / 'manifest.json'


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('inspect', 'finalize'))
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--source-sha256', required=True)
    parser.add_argument('--recovery-iso', type=Path, required=True)
    parser.add_argument('--recovery-iso-sha256', required=True)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--profile', type=Path, help='reviewed diagnostic path-to-code-hash JSON mapping')
    parser.add_argument('--authorize-maintenance', action='store_true')
    parser.add_argument('--iso-provenance-reviewed', action='store_true')
    parser.add_argument('--evidence-preserved', action='store_true')
    args = parser.parse_args(argv)
    try:
        artifacts = {} if args.profile is None else json.loads(args.profile.read_text(encoding='utf-8'))
        config = FinalizationConfig(args.source, args.source_sha256, args.recovery_iso,
                                    args.recovery_iso_sha256, args.workspace, args.mode, artifacts)
        manifest = run_image_maintenance(config, operator_authorized=args.authorize_maintenance,
                                         iso_provenance_reviewed=args.iso_provenance_reviewed,
                                         evidence_preserved=args.evidence_preserved)
    except Exception:
        parser.exit(2, 'Maintenance blocked or status unknown; inspect the host-only manifest. No image accepted.\n')
    print(f'Maintenance receipt: {manifest}; image NOT accepted/exported; Gate A NOT run.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
