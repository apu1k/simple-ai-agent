"""Client for the separately installed, pinned, inspect-only UAC supervisor."""
from __future__ import annotations

import hashlib
import re
import time
import uuid
from pathlib import Path
from typing import Any

from runtime.privileged_host import (
    PrivilegedHostError, _assert_protected, _bounded_json, _elevate, _windows_paths,
)
from runtime.privileged_turn import INSPECTION_OPERATION, PrivilegedClaim
from night_shifts.ubuntu_preparation_control import _current_user_sid

DIRECTORY = 'AiAgentHyperVInspection'
FIELDS = frozenset(('version', 'operation', 'operator_sid', 'source', 'source_sha256',
                    'recovery_iso', 'recovery_iso_sha256', 'workspace', 'approved_until_unix',
                    'iso_provenance_reviewed', 'evidence_preserved', 'files',
                    'bundle_sha256', 'python_archive_sha256'))
DIGEST = re.compile('[0-9a-f]{64}')


def validate_policy(policy: dict[str, Any]) -> None:
    if set(policy) != FIELDS or type(policy['version']) is not int or policy['version'] != 1:
        raise PrivilegedHostError('Unexpected inspection policy schema')
    if (policy['operation'] != INSPECTION_OPERATION or policy['iso_provenance_reviewed'] is not True
            or policy['evidence_preserved'] is not True):
        raise PrivilegedHostError('Separate inspection approvals missing')
    if not isinstance(policy['operator_sid'], str) or not re.fullmatch(r'S-1-5-21-\d+-\d+-\d+-\d+', policy['operator_sid']):
        raise PrivilegedHostError('Invalid inspection operator')
    for field in ('source_sha256', 'recovery_iso_sha256', 'bundle_sha256', 'python_archive_sha256'):
        if not isinstance(policy[field], str) or not DIGEST.fullmatch(policy[field]):
            raise PrivilegedHostError('Invalid pinned inspection digest')
    for field in ('source', 'recovery_iso', 'workspace'):
        value = policy[field]
        if (not isinstance(value, str) or len(value) > 240 or not re.fullmatch(r'[A-Za-z]:\\[^:"\r\n\x00]+', value)
                or any(part in ('.', '..') for part in value.replace('\\', '/').split('/'))):
            raise PrivilegedHostError('Canonical local inspection paths required')
    if not policy['source'].lower().endswith('.vhdx') or not policy['recovery_iso'].lower().endswith('.iso'):
        raise PrivilegedHostError('Invalid pinned input types')
    if type(policy['approved_until_unix']) is not int or policy['approved_until_unix'] <= time.time():
        raise PrivilegedHostError('Inspection approval window expired')
    files = policy['files']
    if not isinstance(files, dict) or not 20 <= len(files) <= 256:
        raise PrivilegedHostError('Invalid deployment inventory')
    if len({name.casefold() for name in files}) != len(files):
        raise PrivilegedHostError('Case-colliding deployment paths')
    for name, digest in files.items():
        if (not re.fullmatch(r'(helper\.ps1|(?:payload|runtime)/[A-Za-z0-9_./-]+)', name)
                or '..' in name or '//' in name or name.endswith('/')
                or not isinstance(digest, str) or not DIGEST.fullmatch(digest)):
            raise PrivilegedHostError('Invalid deployment path/hash')
    required = {'helper.ps1', 'runtime/python.exe', 'payload/night_shifts/inspection_worker.py',
                'payload/night_shifts/backends/hyperv_scripts/maintain_image_copy.ps1'}
    if not required <= files.keys():
        raise PrivilegedHostError('Incomplete inspection deployment')


def load_inspection_policy() -> tuple[Path, Path, dict[str, Any], str]:
    evidence_root, powershell = _windows_paths()
    root = evidence_root.parent / DIRECTORY
    for path in (root, root / 'receipts', root / 'payload', root / 'runtime'):
        _assert_protected(path)
    _assert_protected(powershell, system_binary=True)
    policy = _bounded_json(root / 'policy.json')
    validate_policy(policy)
    if policy['operator_sid'] != _current_user_sid():
        raise PrivilegedHostError('Inspection installed for a different operator')
    if (root / 'inspection.claim.json').exists():
        raise PrivilegedHostError('Inspection already attempted; preserve evidence, no retry')
    for name, digest in policy['files'].items():
        path = root / name
        _assert_protected(path)
        with path.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != digest:
                raise PrivilegedHostError('Protected inspection code/runtime drift')
    for tree in ('payload', 'runtime'):
        for path in (root / tree).rglob('*'):
            _assert_protected(path)
            if path.is_file() and path.relative_to(root).as_posix() not in policy['files']:
                raise PrivilegedHostError('Unexpected deployed code/runtime file')
    digest = hashlib.sha256((root / 'policy.json').read_bytes()).hexdigest()
    return root, powershell, policy, digest


def validate_result(result: dict[str, Any], claim: PrivilegedClaim, policy: dict[str, Any]) -> None:
    receipt = result.get('receipt')
    if not isinstance(receipt, dict):
        raise PrivilegedHostError('Missing native inspection receipt')
    identity = receipt.get('id')
    guest = receipt.get('guest')
    if (not isinstance(identity, str) or not re.fullmatch('[0-9a-f]{32}', identity)
            or not isinstance(guest, dict) or receipt.get('mode') != 'inspect'
            or receipt.get('source_sha256') != policy['source_sha256']
            or any(receipt.get(key) is not True for key in ('source_unchanged', 'vm_removed', 'copy_unattached', 'pipe_acl_checked'))
            or not isinstance(receipt.get('copy_sha256'), str) or not DIGEST.fullmatch(receipt['copy_sha256'])
            or type(guest.get('version')) is not int or guest['version'] != 1
            or guest.get('id') != identity or guest.get('mode') != 'inspect'
            or guest.get('status') != 'success' or guest.get('unmounted_read_only') is not True
            or guest.get('audit') != 'inspection_only'
            or result.get('request_id') != claim.request_id or result.get('operation') != INSPECTION_OPERATION
            or result.get('accepted') is not False or result.get('gate_a') != 'unrun'):
        raise PrivilegedHostError('Inspection outcome is not proven')
    try:
        uuid.UUID(receipt['vm_id'])
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise PrivilegedHostError('Invalid observed VM identity') from exc
    expected = Path(policy['workspace']) / (identity + '.control') / 'manifest.json'
    if Path(result.get('manifest', '')) != expected:
        raise PrivilegedHostError('Inspection manifest binding differs')
    diagnostics = guest.get('diagnostics')
    if not isinstance(diagnostics, dict) or len(diagnostics) > 128:
        raise PrivilegedHostError('Unbounded inspection inventory')
    from night_shifts.guest.finalize_image_copy import DEBUG_LINKS, artifact_name
    for name, item in diagnostics.items():
        if not isinstance(name, str) or len(name) > 240 or not isinstance(item, dict):
            raise PrivilegedHostError('Invalid diagnostic entry')
        if not artifact_name(name) and name not in DEBUG_LINKS:
            raise PrivilegedHostError('Unexpected diagnostic path')
        if item == {'kind': 'unreviewed'}:
            continue
        if set(item) == {'kind', 'sha256'} and item['kind'] == 'file' and isinstance(item['sha256'], str) and DIGEST.fullmatch(item['sha256']):
            continue
        if item.get('kind') == 'link' and set(item) == {'kind', 'target'} and item['target'] in (
                '/dev/null', '/usr/lib/systemd/system/debug-shell.service', '/lib/systemd/system/debug-shell.service'):
            continue
        raise PrivilegedHostError('Unexpected diagnostic content')


def inspect_installed_copy(claim: PrivilegedClaim) -> dict[str, Any]:
    if claim.operation != INSPECTION_OPERATION:
        raise PrivilegedHostError('Inspection requires its distinct operation grant')
    root, powershell, policy, policy_digest = load_inspection_policy()
    state = _elevate(powershell, root / 'helper.ps1', claim)
    path = root / 'receipts' / (claim.request_id + '.result.json')
    unknown = {'status': 'blocked_or_outcome_unknown', 'request_id': claim.request_id,
               'accepted': False, 'gate_a': 'unrun', 'retry_authorized': False,
               'receipt': str(path), 'vm_evidence': str(path.with_name(claim.request_id + '.vm.json'))}
    if state not in ('completed', 'helper_failed'):
        return {**unknown, 'status': state}
    envelope = _bounded_json(path)
    if (type(envelope.get('version')) is not int or envelope['version'] != 1
            or envelope.get('request_id') != claim.request_id or envelope.get('operation') != INSPECTION_OPERATION
            or envelope.get('policy_sha256') != policy_digest):
        raise PrivilegedHostError('Protected inspection receipt binding differs')
    if state != 'completed' or envelope.get('status') != 'completed':
        return unknown
    result = envelope.get('result')
    if not isinstance(result, dict) or result.get('status') != 'inspected_not_accepted':
        raise PrivilegedHostError('Missing successful inspection result')
    validate_result(result, claim, policy)
    return {**result, 'privileged_receipt': str(path), 'retry_authorized': False}
