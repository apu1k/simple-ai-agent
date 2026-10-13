"""Installed inspect-only worker. Never run checkout code elevated."""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import sys
import time
from pathlib import Path


def write_protected_json(path: Path, value: dict, operator_sid: str) -> None:
    """Atomic create-new Administrators ownership, including credential/UAC races."""
    from ctypes import wintypes as w
    if not re.fullmatch(r'S-1-5-21-\d+-\d+-\d+-\d+', operator_sid):
        raise ValueError('invalid operator SID')
    raw = (json.dumps(value, sort_keys=True) + '\n').encode()
    if len(raw) > 65536:
        raise ValueError('oversized inspection receipt')
    adv = ctypes.WinDLL('advapi32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)

    class Attributes(ctypes.Structure):
        _fields_ = [('length', w.DWORD), ('descriptor', ctypes.c_void_p), ('inherit', w.BOOL)]

    adv.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [w.LPCWSTR, w.DWORD,
                                                                        ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    adv.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = w.BOOL
    kernel.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.POINTER(Attributes),
                                  w.DWORD, w.DWORD, w.HANDLE]
    kernel.CreateFileW.restype = w.HANDLE
    kernel.WriteFile.argtypes = [w.HANDLE, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD), ctypes.c_void_p]
    kernel.WriteFile.restype = w.BOOL
    kernel.FlushFileBuffers.argtypes = [w.HANDLE]
    kernel.FlushFileBuffers.restype = w.BOOL
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    descriptor = ctypes.c_void_p()
    sddl = f'O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;FR;;;{operator_sid})'
    if not adv.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(descriptor), None):
        raise OSError('cannot construct protected receipt security')
    handle = None
    try:
        attrs = Attributes(ctypes.sizeof(Attributes), descriptor, False)
        handle = kernel.CreateFileW(str(path), 0x40000000, 1, ctypes.byref(attrs), 1, 0x80000000, None)
        if handle == ctypes.c_void_p(-1).value:
            handle = None
            raise OSError('receipt collision or creation refused')
        buffer = ctypes.create_string_buffer(raw)
        written = w.DWORD()
        if not kernel.WriteFile(handle, buffer, len(raw), ctypes.byref(written), None) or written.value != len(raw):
            raise OSError('receipt write incomplete')
        if not kernel.FlushFileBuffers(handle):
            raise OSError('receipt flush failed')
    finally:
        if handle is not None:
            kernel.CloseHandle(handle)
        kernel.LocalFree(descriptor)


def installed_root() -> Path:
    from ctypes import wintypes as w
    if os.name != 'nt' or ctypes.sizeof(ctypes.c_void_p) != 8:
        raise ValueError('native Windows x64 required')
    shell = ctypes.WinDLL('shell32', use_last_error=True)
    shell.SHGetFolderPathW.argtypes = [w.HWND, ctypes.c_int, w.HANDLE, w.DWORD, w.LPWSTR]
    buffer = ctypes.create_unicode_buffer(32768)
    if shell.SHGetFolderPathW(None, 0x26, None, 0, buffer) != 0:
        raise OSError('cannot locate Program Files')
    root = Path(buffer.value) / 'AiAgentHyperVInspection'
    if Path(__file__).resolve() != root / 'payload/night_shifts/inspection_worker.py':
        raise ValueError('protected installation required')
    return root


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request-id', required=True)
    parser.add_argument('--deadline', required=True, type=int)
    args = parser.parse_args(argv)
    root = installed_root()
    if not re.fullmatch('[0-9a-f]{32}', args.request_id):
        raise ValueError('invalid request identity')
    policy = json.loads((root / 'policy.json').read_bytes())
    remaining = min(args.deadline, policy['approved_until_unix']) - time.time()
    # Never start a VM with an already exhausted host execution budget.
    if not 900 <= remaining <= 1800 or policy['operation'] != 'inspect_image_copy':
        raise ValueError('inspection deadline or operation refused')
    sys.path.insert(0, str(root / 'payload'))  # Protected fixed assets only; -I -S -B at launch.
    from night_shifts.image_finalization import FinalizationConfig, ImageMaintenanceError, run_image_maintenance
    from night_shifts.maintenance_runner import SubprocessPowerShellRunner
    from night_shifts.ubuntu_preparation_control import _current_user_sid
    if _current_user_sid() != policy['operator_sid']:
        raise ValueError('different-account elevation is not supported')
    from ctypes import wintypes as w
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetSystemDirectoryW.argtypes = [w.LPWSTR, w.UINT]
    buffer = ctypes.create_unicode_buffer(32768)
    if not kernel.GetSystemDirectoryW(buffer, len(buffer)):
        raise OSError('cannot locate native PowerShell')
    powershell = Path(buffer.value) / 'WindowsPowerShell/v1.0/powershell.exe'
    config = FinalizationConfig(Path(policy['source']), policy['source_sha256'],
                                Path(policy['recovery_iso']), policy['recovery_iso_sha256'],
                                Path(policy['workspace']), mode='inspect',
                                command_timeout_seconds=max(900, remaining - 10))
    facts: dict = {'version': 1, 'request_id': args.request_id, 'operation': 'inspect_image_copy',
                   'status': 'blocked_or_outcome_unknown', 'accepted': False, 'gate_a': 'unrun'}
    code = 2
    try:
        manifest = run_image_maintenance(
            config, operator_authorized=True,
            iso_provenance_reviewed=policy['iso_provenance_reviewed'] is True,
            evidence_preserved=policy['evidence_preserved'] is True,
            runner=SubprocessPowerShellRunner(str(powershell), timeout_seconds=config.command_timeout_seconds),
            vm_receipt_path=root / 'receipts' / (args.request_id + '.vm.json'),
            failure_receipt_path=root / 'receipts' / (args.request_id + '.failure.json'),
        )
        state = json.loads(manifest.read_bytes())
        receipt = state['receipt']
        if receipt.get('pipe_acl_checked') is not True or receipt.get('copy_unattached') is not True:
            raise ValueError('missing native inspection evidence')
        facts.update(status='inspected_not_accepted', manifest=str(manifest), receipt=receipt)
        code = 0
    except ImageMaintenanceError as exc:
        # Only the protected producer's schema-validated fixed labels/numbers cross.
        # An Off snapshot is not inspection success, unmount, removal or retry consent.
        facts['manifest'] = str(exc.manifest)
        if exc.diagnostics is not None:
            facts['failure_diagnostics'] = exc.diagnostics
    except Exception:
        # No arbitrary exception, key/log contents or inferred cleanup crosses.
        pass
    write_protected_json(root / 'receipts' / (args.request_id + '.facts.json'), facts, policy['operator_sid'])
    return code


if __name__ == '__main__':
    raise SystemExit(main())
