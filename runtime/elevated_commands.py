"""Approved PowerShell execution via a separately installed protected launcher.

The app is trusted to present/collect approval; this is not a sandbox against a
compromised app. Arbitrary scripts may load mutable dependencies or affect host
services. The fixed helpers keep their independent installed constraints.
"""
from __future__ import annotations

import hashlib
import os
import re
import time
from pathlib import Path
from contextlib import nullcontext
from typing import Any

from core.tool_progress import approval_progress
from runtime.privileged_host import (
    PrivilegedHostError, _assert_protected, _bounded_json, _elevate, _windows_paths,
)
from runtime.privileged_turn import PendingPrivilege, PrivilegedClaim, PrivilegedTurn
from runtime.command_lifetime import CommandLifetime
from night_shifts.ubuntu_preparation_control import _current_user_sid
# Independent Administrator execution ceiling, not derived from the shell tool.
MAX_TIMEOUT = 15 * 60
LEGACY_MAX_TIMEOUT = 60
MAX_SCRIPT_BYTES = 32768
MAX_OUTPUT_BYTES = 50000
HELPER_DIRECTORY = 'AiAgentElevatedCommands'


def await_approval(gate: PrivilegedTurn, claim: PrivilegedClaim,
                   details: dict[str, Any]) -> tuple[PendingPrivilege, str]:
    request = gate.submit(claim, details)
    approval_progress(request.id)
    return request, gate.wait(request)


def local_path(value: str, *, directory: bool = False) -> Path:
    if (not isinstance(value, str) or not re.match(r'^[A-Za-z]:\\', value)
            or len(value) > 240 or any(c in value for c in '\x00\r\n"')
            or ':' in value[2:] or any(part in ('.', '..') for part in value.split('\\')[1:])):
        raise ValueError('Use an absolute canonical local Windows path')
    path = Path(value)
    if str(path) != value or (not path.is_dir() if directory else not path.exists()):
        raise ValueError('Path is missing or noncanonical')
    for entry in (path, *path.parents):
        if entry.is_symlink() or getattr(entry.lstat(), 'st_file_attributes', 0) & 0x400:
            raise ValueError('Reparse paths are refused')
    return path


def load_launcher() -> tuple[Path, Path, dict[str, Any]]:
    old_root, powershell = _windows_paths()
    root = old_root.parent / HELPER_DIRECTORY
    for path in (root, root / 'receipts', root / 'helper.ps1', root / 'policy.json'):
        _assert_protected(path)
    _assert_protected(powershell, system_binary=True)
    policy = _bounded_json(root / 'policy.json')
    if (set(policy) not in ({'version', 'operator_sid', 'helper_sha256', 'max_timeout'},
                           {'version', 'operator_sid', 'helper_sha256', 'max_timeout', 'lifetime_protocol'},
                           {'version', 'operator_sid', 'helper_sha256', 'max_timeout', 'lifetime_protocol', 'preparation_protocol'})
            or ('lifetime_protocol' in policy and (type(policy['lifetime_protocol']) is not int or policy['lifetime_protocol'] != 1))
            or ('preparation_protocol' in policy and (type(policy['preparation_protocol']) is not int or policy['preparation_protocol'] != 1))
            or type(policy['version']) is not int or policy['version'] != 1
            or policy['operator_sid'] != _current_user_sid()
            or type(policy['max_timeout']) is not int
            or policy['max_timeout'] not in (LEGACY_MAX_TIMEOUT, MAX_TIMEOUT)
            or not isinstance(policy['helper_sha256'], str)
            or not re.fullmatch('[0-9a-f]{64}', policy['helper_sha256'])):
        raise PrivilegedHostError('Unexpected elevated launcher policy')
    helper = (root / 'helper.ps1').read_bytes()
    if len(helper) > 65536 or hashlib.sha256(helper).hexdigest() != policy['helper_sha256']:
        raise PrivilegedHostError('Elevated launcher differs from installed policy')
    # Requests are intentionally operator-writable; NEVER load code from here.
    local_path(str(root / 'requests'), directory=True)
    return root, powershell, policy


def validate_script(script: str, timeout: int, reason: str) -> None:
    if (not isinstance(script, str) or not script.strip() or '\x00' in script
            or len(script.encode('utf-8')) > MAX_SCRIPT_BYTES):
        raise ValueError('Provide a nonempty PowerShell script of at most 32768 UTF-8 bytes')
    if type(timeout) is not int or not 1 <= timeout <= MAX_TIMEOUT:
        raise ValueError(f'Timeout must be an integer from 1 to {MAX_TIMEOUT} seconds')
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 2000 or '\x00' in reason:
        raise ValueError('Provide a purpose/change explanation of at most 2000 characters')


def validate_receipt(receipt: dict[str, Any], claim: PrivilegedClaim, digest: str,
                     helper_digest: str) -> None:
    if (receipt.get('version') != 1 or type(receipt.get('version')) is not int
            or receipt.get('request_id') != claim.request_id
            or receipt.get('request_sha256') != digest
            or receipt.get('helper_sha256') != helper_digest
            or receipt.get('operation') != 'elevated_commands'
            or receipt.get('status') not in ('completed', 'failed', 'timeout_outcome_unknown', 'cancelled_outcome_unknown', 'outcome_unknown')
            or (receipt.get('executed') is not None and type(receipt['executed']) is not bool)
            or receipt.get('effects_verified') is not False
            or ('process_tree_observed' in receipt and type(receipt['process_tree_observed']) is not bool)
            or ('lifetime_observed' in receipt and type(receipt['lifetime_observed']) is not bool)
            or ('preparation_observed' in receipt and type(receipt['preparation_observed']) is not bool)
            or not isinstance(receipt.get('stdout'), str) or not isinstance(receipt.get('stderr'), str)
            or len(receipt['stdout'].encode('utf-8')) + len(receipt['stderr'].encode('utf-8')) > 150000
            or receipt.get('retry_authorized') is not False
            or type(receipt.get('output_truncated')) is not bool
            or (receipt.get('exit_code') is not None and type(receipt['exit_code']) is not int)):
        raise PrivilegedHostError('Invalid elevated execution receipt; outcome unknown')
    # Legacy general receipts remain readable, but never acquire the new tree
    # observation implicitly. Fixed setup reconciliation REQUIRES positive data.
    if ('process_tree_observed' in receipt
            and ((receipt['status'] != 'outcome_unknown' and receipt['process_tree_observed'] is not True)
                 or (receipt['status'] == 'outcome_unknown' and receipt['process_tree_observed'] is not False))):
        raise PrivilegedHostError('Inconsistent process-tree observation')
    if receipt['status'] != 'outcome_unknown' and receipt.get('executed') is not True:
        raise PrivilegedHostError('Missing positive execution observation')
    if receipt['status'] == 'failed' and (receipt['exit_code'] is None or receipt['exit_code'] == 0):
        raise PrivilegedHostError('Inconsistent failure receipt')
    if receipt['status'] == 'timeout_outcome_unknown' and receipt['exit_code'] != 124:
        raise PrivilegedHostError('Inconsistent timeout receipt')
    if receipt['status'] == 'cancelled_outcome_unknown' and (receipt['exit_code'] != 125
            or receipt.get('process_tree_observed') is not True or receipt.get('lifetime_observed') is not True):
        raise PrivilegedHostError('Inconsistent cancellation receipt')
    if ('lifetime_observed' in receipt and receipt['status'] != 'outcome_unknown'
            and receipt['lifetime_observed'] is not True):
        raise PrivilegedHostError('Missing lifetime observation')
    if ('preparation_observed' in receipt and
            (receipt['preparation_observed'] is not (receipt['status'] != 'outcome_unknown')
             or (receipt['preparation_observed'] and
                 (receipt.get('lifetime_observed') is not True or receipt.get('process_tree_observed') is not True)))):
        raise PrivilegedHostError('Inconsistent preparation observation')
    if receipt['status'] == 'completed' and (not receipt['executed'] or receipt['exit_code'] != 0):
        raise PrivilegedHostError('Inconsistent completion receipt')


def run_approved_script(gate: PrivilegedTurn, claim: PrivilegedClaim, script: str,
                        timeout: int, reason: str, cwd: str, *,
                        required_helper_sha256: str | None = None,
                        require_lifetime: bool = False,
                        require_preparation: bool = False) -> dict[str, Any]:
    if os.name != 'nt' or claim.operation != 'elevated_commands':
        raise PrivilegedHostError('Windows elevated-command grant required')
    validate_script(script, timeout, reason)
    local_path(cwd, directory=True)
    root, powershell, policy = load_launcher()
    # Optional independent caller pin only NARROWS the installed authority.
    # Fixed handoffs must refuse an older/different helper BEFORE pending/UAC.
    if required_helper_sha256 is not None and policy['helper_sha256'] != required_helper_sha256:
        raise PrivilegedHostError('Independently reviewed command helper required')
    # Retained 60-second installations stay usable but never inherit wider authority.
    if timeout > policy['max_timeout']:
        raise PrivilegedHostError('Requested timeout exceeds installed launcher policy; reviewed deployment required')
    capable = type(policy.get('lifetime_protocol')) is int and policy['lifetime_protocol'] == 1
    prepared = type(policy.get('preparation_protocol')) is int and policy['preparation_protocol'] == 1
    if require_preparation and (not capable or not prepared):
        raise PrivilegedHostError('Reviewed preparation-lifetime deployment required before approval')
    if require_lifetime and not capable:
        raise PrivilegedHostError('Reviewed caller-lifetime deployment required before approval')
    # Explicit old installations retain their old general-command behavior. Fixed
    # setup refuses them; neither receipt defaults nor source edits upgrade them.
    context = CommandLifetime(gate, claim, policy['operator_sid']) if capable else nullcontext(None)
    with context as lifetime:
        payload = dict(version=1, request_id=claim.request_id, operation=claim.operation,
                       deadline_unix=int(claim.deadline_unix), timeout=timeout, script=script,
                       cwd=cwd, reason=reason, operator_sid=policy['operator_sid'],
                       helper_sha256=policy['helper_sha256'])
        if lifetime is not None:
            payload['lifetime'] = lifetime.binding
        request, decision = await_approval(gate, claim, payload)
        base = dict(request_id=claim.request_id, approval=decision, review_sha256=request.review_sha256)
        if decision != 'accepted':
            return dict(base, status=decision, executed=False)
        if load_launcher() != (root, powershell, policy):
            raise PrivilegedHostError('Installed launcher changed after review')
        if time.time() >= claim.deadline_unix:
            return dict(base, status='expired', executed=False)
        local_path(cwd, directory=True)
        gate.require_accepted(request)
        inbox = root / 'requests' / (claim.request_id + '.json')
        with inbox.open('xb') as stream:
            stream.write(request.review_json.encode('utf-8'))
            stream.flush()
            os.fsync(stream.fileno())
        state = _elevate(powershell, root / 'helper.ps1', claim,
                         request_sha256=request.review_sha256)
        if state == 'uac_cancelled':
            return dict(base, status=state, executed=False)
        if state not in ('completed', 'helper_failed'):
            return dict(base, status='outcome_unknown', execution_state=state, effects_verified=False)
        receipt_path = root / 'receipts' / (claim.request_id + '.result.json')
        receipt = _bounded_json(receipt_path)
        validate_receipt(receipt, claim, request.review_sha256, policy['helper_sha256'])
        if capable and receipt.get('status') != 'outcome_unknown' and receipt.get('lifetime_observed') is not True:
            raise PrivilegedHostError('Missing protected lifetime observation; outcome unknown')
        if prepared and receipt.get('status') != 'outcome_unknown' and receipt.get('preparation_observed') is not True:
            raise PrivilegedHostError('Missing protected preparation observation; outcome unknown')
        if capable and gate.execution_cancelled(claim):
            return dict(base, status='cancelled_outcome_unknown', effects_verified=False,
                        retry_authorized=False, receipt=str(receipt_path))
        return dict(receipt, approval='accepted', review_sha256=request.review_sha256,
                    receipt=str(receipt_path))
