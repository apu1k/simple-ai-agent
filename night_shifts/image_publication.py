"""Separate operator acceptance/export; never run maintenance or Gate A here."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from night_shifts.backends.hyperv import PowerShellCommandRunner, SubprocessPowerShellRunner
from night_shifts.hyperv_image_preflight import _checked_path
from night_shifts.ubuntu_preparation_control import (
    PreparationError,
    _check_control_permissions,
    checked_preparation_control,
)


def publish_finalized_image(
    manifest: Path, manifest_sha256: str, destination_directory: Path, *,
    operator_authorized: bool = False, audit_accepted: bool = False,
    runner: PowerShellCommandRunner | None = None,
) -> Path:
    """Export only a pinned, reviewed successful FINALIZE receipt to a fresh file.

    Host read-only/private policy is applied only to this newly created export,
    never repaired on retained evidence. Return provenance, not Gate A success.
    """
    if not (operator_authorized and audit_accepted):
        raise PreparationError('separate publication authorization and audit acceptance required')
    if not re.fullmatch(r'[0-9a-f]{64}', manifest_sha256):
        raise PreparationError('independently reviewed manifest SHA-256 required')
    source_manifest = _checked_path(manifest, 'finalization manifest')
    if source_manifest.name != 'manifest.json' or source_manifest.stat().st_size > 65536:
        raise PreparationError('invalid finalization manifest')
    raw = source_manifest.read_bytes()
    if hashlib.sha256(raw).hexdigest() != manifest_sha256:
        raise PreparationError('finalization manifest changed since review')
    data: dict[str, Any] = json.loads(raw)
    identity = data['id']
    if not isinstance(identity, str) or not re.fullmatch(r'[0-9a-f]{32}', identity):
        raise PreparationError('invalid finalization identity')
    workspace = Path(data['workspace'])
    control = checked_preparation_control(workspace)
    if source_manifest != control / 'manifest.json':
        raise PreparationError('manifest does not have its exact host-only control binding')
    receipt = data['receipt']
    guest = receipt['guest']
    if not (data['version'] == 1 and data['mode'] == 'finalize' and data['accepted'] is False
            and data['status'] == 'finalized_not_accepted' and receipt['id'] == identity
            and receipt['mode'] == 'finalize' and receipt['source_unchanged'] is True
            and receipt['vm_removed'] is True and guest['id'] == identity
            and guest['mode'] == 'finalize' and guest['status'] == 'success'
            and guest['audit'] == 'pass' and guest['unmounted_read_only'] is True
            and re.fullmatch(r'[0-9a-f]{64}', receipt['copy_sha256'])):
        raise PreparationError('receipt is not a successful, independently reviewable finalization')
    root = _checked_path(destination_directory, 'publication directory')
    checkout = Path(__file__).resolve().parents[1]
    if not root.is_dir() or root == Path(root.anchor) or root == workspace or workspace in root.parents or checkout in root.parents or root == checkout:
        raise PreparationError('publication must use a separate external private directory')
    _check_control_permissions(root)
    image = root / ('night-shift-protocol-' + identity + '.vhdx')
    provenance = image.with_suffix('.json')
    claim = control / 'publication.claim'  # Separate permanent acceptance/export claim.
    if image.exists() or image.is_symlink() or provenance.exists() or provenance.is_symlink():
        raise PreparationError('publication output already exists; never replace an export')
    with claim.open('xb') as stream:
        stream.write(b'image-publication-once\n')
        stream.flush()
        os.fsync(stream.fileno())
    checked_preparation_control(workspace)
    selected = runner or SubprocessPowerShellRunner(timeout_seconds=1800)
    script = Path(__file__).resolve().parent / 'backends/hyperv_scripts/publish_image_copy.ps1'
    try:
        output = selected.run(script, ('-SourceDisk', str(workspace / 'working-copy.vhdx'),
                                       '-ExpectedSha256', receipt['copy_sha256'], '-Destination', str(image)))
        if len(output) > 2048:
            raise PreparationError('oversized publication receipt')
        observation = json.loads(output)
        if not (observation == {'sha256': receipt['copy_sha256'], 'read_only': True, 'private': True}):
            raise PreparationError('publication host policy/hash read-back differs')
        with image.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != receipt['copy_sha256']:
                raise PreparationError('export digest differs during independent verification')
        record = {'version': 1, 'image': str(image), 'sha256': receipt['copy_sha256'],
                  'finalization_manifest_sha256': manifest_sha256, 'finalization_id': identity,
                  'operator_accepted': True, 'host_policy': observation, 'gate_a': 'unrun'}
        with provenance.open('xb') as stream:
            stream.write((json.dumps(record, sort_keys=True) + '\n').encode())
            stream.flush()
            os.fsync(stream.fileno())
    except Exception as exc:
        raise PreparationError('publication status UNKNOWN; preserve claim/output and inspect; never retry') from exc
    return provenance


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--destination-directory', required=True, type=Path)
    parser.add_argument('--authorize-publication', action='store_true')
    parser.add_argument('--accept-audit', action='store_true')
    args = parser.parse_args(argv)
    try:
        result = publish_finalized_image(args.manifest, args.manifest_sha256, args.destination_directory,
                                         operator_authorized=args.authorize_publication, audit_accepted=args.accept_audit)
    except Exception:
        parser.exit(2, 'Publication blocked or status unknown. Preserve exact records/output; Gate A NOT run.\n')
    print(f'Accepted image provenance: {result}; Gate A NOT run.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
