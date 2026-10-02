"""Host-only preparation state, separate from Hyper-V worker-writable storage.

Only read permissions here; never repair ACLs, migrate legacy state, or invoke
Hyper-V. Production checks require Windows. Fake-host tests replace the ACL
reader/policy explicitly, never by choosing a fake PowerShell runner.
"""

from __future__ import annotations

import ctypes
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from night_shifts.hyperv_image_preflight import _checked_path

_CONTROL_NAMES = frozenset({
    "manifest.json", "manifest.pending", "launch.claim", "retirement.claim", "vm-operation.lock",
})
_SYSTEM = "S-1-5-18"
_ADMINS = "S-1-5-32-544"
_FULL = 0x1F01FF
_GENERIC_ALL = 0x10000000
_INHERIT_ONLY = 0x08


class PreparationError(RuntimeError):
    """A preparation operation cannot safely proceed or needs investigation."""


@dataclass(frozen=True)
class AclRule:
    """One native DACL entry; unsupported ACE types are deliberately refused."""

    sid: str
    mask: int
    flags: int = 0
    kind: int = 0


@dataclass(frozen=True)
class AclSnapshot:
    """Owner and DACL only; this is not a guest-isolation certificate."""

    owner: str
    rules: tuple[AclRule, ...]


def preparation_control_path(workspace: Path) -> Path:
    """Derive an exact sibling, never a directory beneath VM-worker storage."""
    if not workspace.is_absolute() or not re.fullmatch(r"[0-9a-f]{32}", workspace.name):
        raise PreparationError("control path requires an identity-scoped absolute preparation workspace")
    if workspace.drive.startswith("\\\\"):
        raise PreparationError("preparation control must use local storage, not a UNC share")
    return workspace.with_name(workspace.name + ".control")


def _api() -> tuple[Any, Any]:
    if os.name != "nt":
        raise PreparationError("host-only control permission checks require Windows")
    from ctypes import wintypes as w

    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    adv.GetNamedSecurityInfoW.argtypes = [
        w.LPWSTR, ctypes.c_int, w.DWORD, ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    adv.GetNamedSecurityInfoW.restype = w.DWORD
    adv.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(w.LPWSTR)]
    adv.ConvertSidToStringSidW.restype = w.BOOL
    adv.GetAclInformation.argtypes = [ctypes.c_void_p, ctypes.c_void_p, w.DWORD, ctypes.c_int]
    adv.GetAclInformation.restype = w.BOOL
    adv.GetAce.argtypes = [ctypes.c_void_p, w.DWORD, ctypes.POINTER(ctypes.c_void_p)]
    adv.GetAce.restype = w.BOOL
    adv.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)]
    adv.OpenProcessToken.restype = w.BOOL
    adv.GetTokenInformation.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD)]
    adv.GetTokenInformation.restype = w.BOOL
    kernel.GetCurrentProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.CloseHandle.restype = w.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    return adv, kernel


def _sid_text(pointer: Any, adv: Any, kernel: Any) -> str:
    from ctypes import wintypes as w

    text = w.LPWSTR()
    if not pointer or not adv.ConvertSidToStringSidW(pointer, ctypes.byref(text)):
        raise PreparationError("cannot read control security identifier")
    try:
        if text.value is None:
            raise PreparationError("empty control security identifier")
        return str(text.value)
    finally:
        kernel.LocalFree(ctypes.cast(text, ctypes.c_void_p))


def _current_user_sid() -> str:
    from ctypes import wintypes as w

    adv, kernel = _api()
    token = w.HANDLE()
    if not adv.OpenProcessToken(kernel.GetCurrentProcess(), 8, ctypes.byref(token)):
        raise PreparationError("cannot inspect operator token for control permissions")
    try:
        size = w.DWORD()
        adv.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
        if not 0 < size.value <= 65536:
            raise PreparationError("operator token information is outside fixed bounds")
        buffer = ctypes.create_string_buffer(size.value)
        if not adv.GetTokenInformation(token, 1, buffer, size.value, ctypes.byref(size)):
            raise PreparationError("cannot read operator token")
        pointer = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]
        return _sid_text(pointer, adv, kernel)
    finally:
        kernel.CloseHandle(token)


def _read_acl(path: Path) -> AclSnapshot:
    from ctypes import wintypes as w

    class AclSize(ctypes.Structure):
        _fields_ = [("count", w.DWORD), ("used", w.DWORD), ("free", w.DWORD)]

    class AceHeader(ctypes.Structure):
        _fields_ = [("kind", w.BYTE), ("flags", w.BYTE), ("size", w.WORD)]

    adv, kernel = _api()
    owner, dacl, descriptor = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
    result = adv.GetNamedSecurityInfoW(
        str(path), 1, 5, ctypes.byref(owner), None, ctypes.byref(dacl), None,
        ctypes.byref(descriptor),
    )
    if result != 0:
        raise PreparationError(f"cannot inspect control ACL: {path} (Windows error {result})")
    try:
        if not dacl:
            raise PreparationError("null control DACL permits unrestricted access")
        size = AclSize()
        if not adv.GetAclInformation(dacl, ctypes.byref(size), ctypes.sizeof(size), 2) or size.count > 1024:
            raise PreparationError("control ACL is unreadable or exceeds fixed bounds")
        rules: list[AclRule] = []
        for index in range(size.count):
            ace = ctypes.c_void_p()
            if not adv.GetAce(dacl, index, ctypes.byref(ace)) or not ace.value:
                raise PreparationError("control ACL contains an unreadable ACE")
            header = AceHeader.from_address(ace.value)
            if header.kind not in (0, 1) or header.size < 12:
                rules.append(AclRule("", 0, header.flags, header.kind))
                continue
            mask = w.DWORD.from_address(ace.value + 4).value
            sid = _sid_text(ctypes.c_void_p(ace.value + 8), adv, kernel)
            rules.append(AclRule(sid, mask, header.flags, header.kind))
        return AclSnapshot(_sid_text(owner, adv, kernel), tuple(rules))
    finally:
        kernel.LocalFree(descriptor)


def _validate_acl(snapshot: AclSnapshot, allowed: frozenset[str], *, private: bool, volume_root: bool = False) -> None:
    if snapshot.owner not in allowed:
        raise PreparationError("control path or ancestor has an untrusted owner")
    if private:
        if not snapshot.rules or {rule.sid for rule in snapshot.rules} != allowed:
            raise PreparationError("host-only control ACL must contain only operator, SYSTEM and Administrators")
        for rule in snapshot.rules:
            if rule.kind != 0 or rule.mask not in (_FULL, _GENERIC_ALL) or rule.flags & _INHERIT_ONLY:
                raise PreparationError("host-only control requires simple FullControl allow entries")
        return
    # A private child is not enough if an ancestor can be renamed/replaced or
    # its ACL changed. The volume root itself cannot be renamed as a directory.
    dangerous = 0x40 | 0x40000 | 0x80000 | _GENERIC_ALL
    if not volume_root:
        dangerous |= 0x10000
    for rule in snapshot.rules:
        if rule.flags & _INHERIT_ONLY:
            continue
        if rule.kind not in (0, 1):
            raise PreparationError("unsupported ancestor ACE; inspect permissions before proceeding")
        if rule.kind == 0 and rule.sid not in allowed and rule.mask & dangerous:
            raise PreparationError("control ancestor permits untrusted replacement or ACL changes")


def _check_control_permissions(path: Path) -> None:
    """Read native owner/DACL at every step; no cache and no permission repair."""
    allowed = frozenset({_SYSTEM, _ADMINS, _current_user_sid()})
    _validate_acl(_read_acl(path), allowed, private=True)
    parent = path.parent
    _validate_acl(_read_acl(parent), allowed, private=True)
    for ancestor in parent.parents:
        _validate_acl(_read_acl(ancestor), allowed, private=False, volume_root=ancestor == Path(ancestor.anchor))


def check_control_parent(workspace: Path) -> Path:
    """Validate the private parent before creating a new identity-only sibling."""
    control = preparation_control_path(workspace)
    parent = _checked_path(control.parent, "host-only control parent")
    if not parent.is_dir():
        raise PreparationError("host-only control parent is not a directory")
    _check_control_permissions(parent)
    return control


def checked_preparation_control(workspace: Path) -> Path:
    """Refuse missing/unsafe state; legacy worker files are never authority."""
    control = preparation_control_path(workspace)
    checkout = Path(__file__).resolve().parents[1]
    if checkout == control or checkout in control.parents:
        raise PreparationError("host-only control must be outside the checkout")
    try:
        control = _checked_path(control, "host-only preparation control")
    except (OSError, ValueError) as exc:
        raise PreparationError("host-only control missing or irregular; separately review legacy migration") from exc
    if not control.is_dir():
        raise PreparationError("host-only control is not a directory")
    _check_control_permissions(control)
    for entry in control.iterdir():
        if entry.name not in _CONTROL_NAMES:
            raise PreparationError("unexpected host-only control entry; inspect before operating")
        checked = _checked_path(entry, "host-only control file")
        info = checked.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise PreparationError("control files must be regular, single-link files")
        _check_control_permissions(checked)
    return control
