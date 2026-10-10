"""Read-only operator evidence; never authorize or execute a VM launch."""
from __future__ import annotations

import argparse
import json
import re
import shutil
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from night_shifts.backends.hyperv import PowerShellCommandRunner, SubprocessPowerShellRunner
from night_shifts.hyperv_image_preflight import _checked_path
from night_shifts.ubuntu_preparation_control import _check_control_permissions


def collect_host_evidence(
    source: Path, recovery_iso: Path, recovery_iso_sha256: str, workspace: Path, *,
    runner: PowerShellCommandRunner | None = None,
) -> dict[str, Any]:
    """Print/report facts only. Fake runners do not bypass native ACL policy.

    Missing/unsafe workspace is a blocker, but does not prevent collecting a
    safe source snapshot. No directories, files or control claims are created.
    """
    if not re.fullmatch(r'[0-9a-f]{64}', recovery_iso_sha256):
        raise ValueError('independently reviewed lowercase recovery ISO SHA-256 required')
    checkout = Path(__file__).resolve().parents[1]
    inputs = []
    for path, suffix in ((source, '.vhdx'), (recovery_iso, '.iso')):
        checked = _checked_path(path, 'evidence input')
        info = checked.stat()
        if (checked == checkout or checkout in checked.parents or checked.drive.startswith('\\\\')
                or checked.suffix.lower() != suffix or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1):
            raise ValueError('inputs must be external local regular single-link VHDX/ISO files')
        inputs.append(checked)
    source, recovery_iso = inputs
    if not workspace.is_absolute() or workspace.drive.startswith('\\\\'):
        raise ValueError('workspace must be an absolute local path')
    report: dict[str, Any] = {
        'version': 1, 'collected_at_utc': datetime.now(timezone.utc).isoformat(),
        'source': str(source), 'recovery_iso': str(recovery_iso), 'workspace': str(workspace),
        'launch_authorized': False, 'guest_audited': False, 'pipe_acl_attested': False,
        'vm_create_start_permissions_attested': False, 'blockers': [],
    }
    blockers = report['blockers']
    try:
        checked_workspace = _checked_path(workspace, 'workspace')
        if (not checked_workspace.is_dir() or checked_workspace == Path(checked_workspace.anchor)
                or checked_workspace == checkout or checkout in checked_workspace.parents
                or any(checked_workspace == p or checked_workspace in p.parents for p in inputs)):
            blockers.append('workspace_location_unsafe')
        else:
            if next(checked_workspace.iterdir(), None) is not None:
                blockers.append('workspace_not_empty')
            try:
                _check_control_permissions(checked_workspace)
                report['workspace_private_acl'] = True
            except Exception:
                report['workspace_private_acl'] = False
                blockers.append('workspace_acl_not_verified_private')
            free = shutil.disk_usage(checked_workspace).free
            required = max(20 * 1024**3, source.stat().st_size) + 512 * 1024**2
            report['workspace_free_bytes'] = free
            report['workspace_required_bytes'] = required
            if free < required:
                blockers.append('workspace_insufficient_free_space')
    except Exception:
        blockers.append('workspace_missing_or_unreadable')
    script = Path(__file__).resolve().parent / 'backends/hyperv_scripts/collect_host_evidence.ps1'
    selected = runner or SubprocessPowerShellRunner(timeout_seconds=1800)
    try:
        output = selected.run(script, ('-SourceDisk', str(source), '-RecoveryIso', str(recovery_iso)))
        if len(output) > 32768:
            raise ValueError('oversized host evidence')
        facts = json.loads(output)
        if (type(facts.get('version')) is not int or facts['version'] != 1
                or not isinstance(facts.get('source_references'), list)
                or len(facts['source_references']) > 64
                or not isinstance(facts.get('blockers'), list)
                or any(value not in {'source_vm_not_off', 'source_vhd_unsuitable', 'source_signature_invalid'}
                       for value in facts['blockers'])):
            raise ValueError('unexpected evidence schema')
        for ref in facts['source_references']:
            if not isinstance(ref, dict) or set(ref) != {'name', 'id', 'state'}:
                raise ValueError('unexpected VM reference')
            if not all(isinstance(v, str) and len(v) <= 256 for v in ref.values()):
                raise ValueError('invalid VM reference')
            if ref['state'] != 'Off' and 'source_vm_not_off' not in facts['blockers']:
                facts['blockers'].append('source_vm_not_off')
        if not facts['blockers']:
            if not all(isinstance(facts.get(k), str) and re.fullmatch(r'[0-9a-f]{64}', facts[k])
                       for k in ('source_sha256', 'recovery_iso_sha256')):
                raise ValueError('missing snapshot hashes')
        report['host'] = facts
        blockers.extend(facts['blockers'])
        if facts.get('recovery_iso_sha256') != recovery_iso_sha256:
            blockers.append('recovery_iso_digest_not_verified')
    except Exception:
        blockers.append('host_evidence_unavailable_or_invalid')
    report['status'] = 'snapshot_ready_for_review' if not blockers else 'blocked'
    report['limitations'] = 'Snapshot only; no future reservation, provenance approval, guest audit or launch permission.'
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--recovery-iso', required=True, type=Path)
    parser.add_argument('--recovery-iso-sha256', required=True)
    parser.add_argument('--workspace', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        report = collect_host_evidence(args.source, args.recovery_iso, args.recovery_iso_sha256, args.workspace)
    except Exception:
        parser.exit(2, 'Evidence collection blocked: check approved input paths/digest. No host state changed.\n')
    print(json.dumps(report, sort_keys=True, indent=2))
    return 0 if report['status'] == 'snapshot_ready_for_review' else 2


if __name__ == '__main__':
    raise SystemExit(main())
