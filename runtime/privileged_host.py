"""UAC client for an operator-installed, protected read-only evidence helper.

Never elevate checkout code. Model tools choose neither inputs nor code paths.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from core.tool_progress import evidence_progress
from night_shifts.host_evidence import collect_host_evidence
from night_shifts.hyperv_image_preflight import _checked_path
from night_shifts.ubuntu_preparation_control import _current_user_sid, _read_acl
from runtime.privileged_turn import PrivilegedClaim

HELPER_DIRECTORY = 'AiAgentHyperVEvidence'
SYSTEM = 'S-1-5-18'
ADMINS = 'S-1-5-32-544'
TRUSTED_INSTALLER = 'S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464'
TRUSTED = frozenset((SYSTEM, ADMINS, TRUSTED_INSTALLER))
FIELDS = frozenset(('version', 'operator_sid', 'source', 'recovery_iso',
                    'recovery_iso_sha256', 'workspace', 'helper_sha256', 'collector_sha256',
                    'max_execution_seconds'))
MAX_RECEIPT_BYTES = 65536


class PrivilegedHostError(RuntimeError):
    """Fail closed; no arbitrary elevated fallback."""


def _windows_paths() -> tuple[Path, Path]:
    from ctypes import wintypes as w

    if os.name != 'nt' or ctypes.sizeof(ctypes.c_void_p) != 8:
        raise PrivilegedHostError('A native 64-bit Windows runtime is required')
    shell = ctypes.WinDLL('shell32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    shell.SHGetFolderPathW.argtypes = [w.HWND, ctypes.c_int, w.HANDLE, w.DWORD, w.LPWSTR]
    shell.SHGetFolderPathW.restype = ctypes.c_long
    kernel.GetSystemDirectoryW.argtypes = [w.LPWSTR, w.UINT]
    kernel.GetSystemDirectoryW.restype = w.UINT
    buffer = ctypes.create_unicode_buffer(32768)
    if shell.SHGetFolderPathW(None, 0x26, None, 0, buffer) != 0:
        raise PrivilegedHostError('Cannot locate protected Program Files')
    root = Path(buffer.value) / HELPER_DIRECTORY
    if not kernel.GetSystemDirectoryW(buffer, len(buffer)):
        raise PrivilegedHostError('Cannot locate system PowerShell')
    return root, Path(buffer.value) / 'WindowsPowerShell/v1.0/powershell.exe'


def _assert_protected(path: Path, *, system_binary: bool = False) -> None:
    checked = _checked_path(path, 'protected privileged helper')
    # OS servicing legitimately hard-links PowerShell into WinSxS. This
    # exception is used only for the fixed OS-known-folder executable.
    if not system_binary and not checked.is_dir() and checked.stat().st_nlink != 1:
        raise PrivilegedHostError('Protected helper must be single-link')
    for index, candidate in enumerate((checked, *checked.parents)):
        acl = _read_acl(candidate)
        if acl.owner not in TRUSTED or not acl.rules:
            raise PrivilegedHostError('Untrusted protected-path owner or empty ACL')
        dangerous = 0x40 | 0x40000 | 0x80000 | 0x10000000
        if candidate != Path(candidate.anchor):
            dangerous |= 0x10000
        if index == 0:
            dangerous |= 0x2 | 0x4 | 0x10 | 0x100 | 0x40000000
        for rule in acl.rules:
            if rule.flags & 0x08:
                continue
            if rule.kind not in (0, 1):
                raise PrivilegedHostError('Unsupported protected-path ACL')
            if rule.kind == 0 and rule.sid not in TRUSTED and rule.mask & dangerous:
                raise PrivilegedHostError('Protected path permits untrusted writes/replacement')


def _bounded_json(path: Path) -> dict[str, Any]:
    _assert_protected(path)
    with path.open('rb') as stream:
        raw = stream.read(MAX_RECEIPT_BYTES + 1)
    if len(raw) > MAX_RECEIPT_BYTES:
        raise PrivilegedHostError('Oversized privileged evidence')
    value = json.loads(raw.decode('utf-8-sig'))
    if not isinstance(value, dict):
        raise PrivilegedHostError('Invalid privileged evidence object')
    return value


def load_policy() -> tuple[Path, Path, dict[str, Any]]:
    root, powershell = _windows_paths()
    _assert_protected(root)
    _assert_protected(root / 'receipts')
    _assert_protected(powershell, system_binary=True)
    policy = _bounded_json(root / 'policy.json')
    if set(policy) != FIELDS or type(policy['version']) is not int or policy['version'] != 1:
        raise PrivilegedHostError('Unexpected installed policy schema')
    if type(policy['max_execution_seconds']) is not int or policy['max_execution_seconds'] != 900:
        raise PrivilegedHostError('Reviewed 900-second evidence deployment required')
    if policy['operator_sid'] != _current_user_sid():
        raise PrivilegedHostError('Helper installed for a different operator')
    for field in ('source', 'recovery_iso', 'workspace'):
        value = policy[field]
        if not isinstance(value, str) or len(value) > 240 or any(c in value for c in '\x00\r\n\"'):
            raise PrivilegedHostError('Invalid installed input')
        path = Path(value)
        if not path.is_absolute() or path.drive.startswith('\\\\'):
            raise PrivilegedHostError('Installed inputs must be absolute local paths')
    for field in ('helper_sha256', 'collector_sha256', 'recovery_iso_sha256'):
        if not isinstance(policy[field], str) or not re.fullmatch('[0-9a-f]{64}', policy[field]):
            raise PrivilegedHostError('Invalid installed digest')
    for name, field in (('helper.ps1', 'helper_sha256'), ('collector.ps1', 'collector_sha256')):
        path = root / name
        _assert_protected(path)
        if path.stat().st_size > 65536 or hashlib.sha256(path.read_bytes()).hexdigest() != policy[field]:
            raise PrivilegedHostError('Installed code differs from reviewed snapshot')
    for field, suffix in (('source', '.vhdx'), ('recovery_iso', '.iso')):
        path = _checked_path(Path(policy[field]), 'installed evidence input')
        if path.suffix.lower() != suffix or not path.is_file() or path.stat().st_nlink != 1:
            raise PrivilegedHostError('Installed input is unsuitable')
        with path.open('rb'):
            pass
    return root, powershell, policy


PHASES = (
    ('inventory', 'Querying Hyper-V inventory'),
    ('source_hash', 'Hashing source VHDX'),
    ('iso_hash', 'Hashing recovery ISO'),
    ('recheck', 'Rechecking source VM state'),
)


def _observed_phase(root: Path, request_id: str) -> str:
    """Optional, protected display hints only; never infer completion here."""
    if root.name == 'AiAgentElevatedCommands':
        return 'Running an explicitly approved Administrator command (effects are not verified)'
    if root.name in ('AiAgentHyperVInspection', 'AiAgentHyperVInspectionV2'):
        return 'Inspecting a fresh image copy (VM outcome requires a verified receipt)'
    for phase, label in reversed(PHASES):
        path = root / 'receipts' / f'{request_id}.phase-{phase}.json'
        try:
            record = _bounded_json(path)
            if (type(record.get('version')) is int and record['version'] == 1
                    and record.get('request_id') == request_id and record.get('phase') == phase):
                return label
        except Exception:
            # Old installations have no phase receipts. Missing, partial or
            # unsafe hints must neither grant success nor abort contained work.
            continue
    return 'Collecting host evidence (fresh hashing may take several minutes)'


def _wait_for_helper(kernel: Any, handle: Any, root: Path, claim: PrivilegedClaim) -> int:
    """Short native waits keep display updates flowing; the deadline is fixed."""
    started = time.monotonic()
    next_update = started
    while True:
        remaining = claim.deadline_unix + 5 - time.time()
        if remaining <= 0:
            return 0x102
        now = time.monotonic()
        if now >= next_update:
            evidence_progress(f'{_observed_phase(root, claim.request_id)} — {int(now - started)}s elapsed')
            next_update = now + 5
        wait = kernel.WaitForSingleObject(handle, min(1000, max(1, int(remaining * 1000))))
        if wait != 0x102:
            return int(wait)


def _elevate(powershell: Path, helper: Path, claim: PrivilegedClaim, *,
             request_sha256: str | None = None) -> str:
    """RunAs with Windows consent, never shell/PATH lookup or arbitrary text."""
    from ctypes import wintypes as w

    class ShellExecuteInfo(ctypes.Structure):
        _fields_ = [('cbSize', w.DWORD), ('fMask', w.ULONG), ('hwnd', w.HWND),
                    ('lpVerb', w.LPCWSTR), ('lpFile', w.LPCWSTR), ('lpParameters', w.LPCWSTR),
                    ('lpDirectory', w.LPCWSTR), ('nShow', ctypes.c_int), ('hInstApp', w.HINSTANCE),
                    ('lpIDList', ctypes.c_void_p), ('lpClass', w.LPCWSTR), ('hkeyClass', w.HKEY),
                    ('dwHotKey', w.DWORD), ('hIcon', w.HANDLE), ('hProcess', w.HANDLE)]

    if not re.fullmatch('[0-9a-f]{32}', claim.request_id) or not 0 < claim.deadline_unix - time.time() <= 1801:
        raise PrivilegedHostError('Privileged turn deadline expired or invalid')
    shell = ctypes.WinDLL('shell32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    shell.ShellExecuteExW.argtypes = [ctypes.POINTER(ShellExecuteInfo)]
    shell.ShellExecuteExW.restype = w.BOOL
    kernel.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
    kernel.WaitForSingleObject.restype = w.DWORD
    kernel.GetExitCodeProcess.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]
    kernel.GetExitCodeProcess.restype = w.BOOL
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.CloseHandle.restype = w.BOOL
    params = (f'-NoProfile -NonInteractive -ExecutionPolicy RemoteSigned -File "{helper}" '
              f'-RequestId {claim.request_id} -DeadlineUnix {int(claim.deadline_unix)}')
    if request_sha256 is not None:
        if not re.fullmatch('[0-9a-f]{64}', request_sha256):
            raise PrivilegedHostError('Invalid approved request digest')
        params += f' -RequestSha256 {request_sha256}'
    info = ShellExecuteInfo()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x40 | 0x100  # NOCLOSEPROCESS, NOASYNC
    info.lpVerb = 'runas'
    info.lpFile = str(powershell)
    info.lpParameters = params
    info.lpDirectory = str(helper.parent)
    info.nShow = 1
    evidence_progress('Waiting for Windows UAC consent…')
    if not shell.ShellExecuteExW(ctypes.byref(info)):
        if ctypes.get_last_error() == 1223:
            return 'uac_cancelled'
        raise PrivilegedHostError('Windows refused elevation')
    if not info.hProcess:
        raise PrivilegedHostError('No elevated process handle; outcome unknown')
    try:
        # Windows consent cannot be forcibly dismissed here. Late acceptance
        # is rejected by the helper's independent deadline.
        wait = _wait_for_helper(kernel, info.hProcess, helper.parent, claim)
        if wait == 0x102:
            return 'deadline_outcome_unknown'
        if wait != 0:
            raise PrivilegedHostError('Cannot observe completion; outcome unknown')
        code = w.DWORD()
        if not kernel.GetExitCodeProcess(info.hProcess, ctypes.byref(code)):
            raise PrivilegedHostError('Cannot read elevated exit status')
        return 'completed' if code.value == 0 else 'helper_failed'
    finally:
        kernel.CloseHandle(info.hProcess)


class _ReceiptRunner:
    def __init__(self, policy: dict[str, Any], facts: dict[str, Any]) -> None:
        self.policy = policy
        self.facts = facts

    def run(self, script: Path, arguments: Sequence[str]) -> str:
        if (script.name != 'collect_host_evidence.ps1' or len(arguments) != 4
                or arguments[0] != '-SourceDisk' or arguments[2] != '-RecoveryIso'
                or Path(arguments[1]) != Path(self.policy['source'])
                or Path(arguments[3]) != Path(self.policy['recovery_iso'])):
            raise PrivilegedHostError('Collector requested unpinned inputs')
        return json.dumps(self.facts)


def collect_installed_evidence(claim: PrivilegedClaim) -> dict[str, Any]:
    if claim.operation != 'collect_host_evidence':
        raise PrivilegedHostError('Evidence requires its own operation grant')
    root, powershell, policy = load_policy()
    state = _elevate(powershell, root / 'helper.ps1', claim)
    if state not in ('completed', 'helper_failed'):
        return {'status': state, 'request_id': claim.request_id, 'launch_authorized': False}
    evidence_progress('Helper exited; validating protected receipt and workspace…')
    receipt_path = root / 'receipts' / f'{claim.request_id}.result.json'
    receipt = _bounded_json(receipt_path)
    if (receipt.get('request_id') != claim.request_id or type(receipt.get('version')) is not int
            or receipt['version'] != 1 or receipt.get('helper_sha256') != policy['helper_sha256']
            or receipt.get('collector_sha256') != policy['collector_sha256']):
        raise PrivilegedHostError('Privileged receipt identity/code mismatch; outcome unknown')
    if state != 'completed' or receipt.get('status') != 'completed':
        return {'status': 'helper_failed', 'request_id': claim.request_id,
                'receipt': str(receipt_path), 'launch_authorized': False}
    facts = receipt.get('host')
    if not isinstance(facts, dict):
        raise PrivilegedHostError('Missing privileged host evidence')
    report = collect_host_evidence(
        Path(policy['source']), Path(policy['recovery_iso']), policy['recovery_iso_sha256'],
        Path(policy['workspace']), runner=_ReceiptRunner(policy, facts),
    )
    report['privileged_request_id'] = claim.request_id
    report['privileged_receipt'] = str(receipt_path)
    return report
