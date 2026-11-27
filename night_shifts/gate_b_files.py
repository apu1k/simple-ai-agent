"""Read regular, local workspace files without traversing filesystem links."""

from __future__ import annotations

import ctypes
import os
import re
import stat
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from night_shifts.gate_b_profile import PreviewError


class _FileBasicInfo(ctypes.Structure):
    _fields_ = [("creation_time", ctypes.c_int64), ("last_access_time", ctypes.c_int64),
                ("last_write_time", ctypes.c_int64), ("change_time", ctypes.c_int64),
                ("attributes", wintypes.DWORD)]


class _WindowsFiles:
    def __init__(self) -> None:
        dll = ctypes.WinDLL("kernel32.dll", use_last_error=True)
        self.create = dll.CreateFileW
        self.create.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
        self.create.restype = wintypes.HANDLE
        self.info = dll.GetFileInformationByHandleEx
        self.info.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
        self.info.restype = wintypes.BOOL
        self.close = dll.CloseHandle
        self.close.argtypes = (wintypes.HANDLE,)
        self.close.restype = wintypes.BOOL
        self.drive_type = dll.GetDriveTypeW
        self.drive_type.argtypes = (wintypes.LPCWSTR,)
        self.drive_type.restype = wintypes.UINT

    @contextmanager
    def open(self, path: Path, *, directory: bool) -> Iterator[int]:
        # OPEN_REPARSE_POINT | BACKUP_SEMANTICS | OPEN_NO_RECALL; share read only.
        # Pin ancestors with FILE_LIST_DIRECTORY | FILE_READ_ATTRIBUTES.
        # Attributes-only handles do not enforce the deny-delete share mode on Windows.
        access = 0x81 if directory else 0x80000000  # GENERIC_READ for regular files
        handle = self.create(_extended(path), access, 1, None, 3, 0x02300000, None)
        if handle == ctypes.c_void_p(-1).value:
            raise PreviewError(f"cannot open {str(path)!r}: {ctypes.WinError(ctypes.get_last_error())}")
        try:
            # Query attributes on the same no-follow handle. exFAT on Windows
            # rejects FileAttributeTagInfo (9), but supports FileBasicInfo (0).
            info = _FileBasicInfo()
            if not self.info(handle, 0, ctypes.byref(info), ctypes.sizeof(info)):
                raise ctypes.WinError(ctypes.get_last_error())
            attributes = info.attributes
            if attributes & (0x400 | 0x1000 | 0x40000 | 0x400000):
                raise PreviewError(f"link, reparse point or offline file is not allowed: {str(path)!r}")
            if bool(attributes & 0x10) != directory:
                raise PreviewError(f"entry changed its type: {str(path)!r}")
            assert isinstance(handle, int)
            yield handle
        finally:
            self.close(handle)


def _extended(path: Path) -> str:
    return "\\\\?\\" + str(path)


def _child_name(name: str) -> None:
    if not name or name in (".", "..") or "/" in name or "\\" in name or ":" in name:
        raise PreviewError(f"not a single path component: {name!r}")


def _posix_flags(*names: str) -> int:
    flags = os.O_RDONLY
    for name in names:
        value = getattr(os, name, None)
        if not isinstance(value, int):
            raise PreviewError(f"required safe file-open flag is unavailable: {name}")
        flags |= value
    return flags


@dataclass(frozen=True)
class Directory:
    path: Path
    posix_fd: int | None
    win: _WindowsFiles | None

    @contextmanager
    def child(self, name: str) -> Iterator[Directory]:
        _child_name(name)
        path = self.path / name
        if self.win is not None:
            with self.win.open(path, directory=True):
                yield Directory(path, None, self.win)
        else:
            fd = os.open(name, _posix_flags("O_DIRECTORY", "O_NOFOLLOW"), dir_fd=self.posix_fd)
            try:
                yield Directory(path, fd, None)
            finally:
                os.close(fd)

    @contextmanager
    def file(self, name: str) -> Iterator[BinaryIO]:
        _child_name(name)
        if self.win is not None:
            import msvcrt

            with self.win.open(self.path / name, directory=False) as handle:
                # The CRT owns the duplicated handle, not the handle managed by win.open.
                # Reopen through a duplicate rather than opening the name twice.
                duplicate = _duplicate(handle)
                try:
                    fd = msvcrt.open_osfhandle(duplicate, os.O_RDONLY | os.O_BINARY)
                except OSError:
                    self.win.close(duplicate)
                    raise
        else:
            before = os.stat(name, dir_fd=self.posix_fd, follow_symlinks=False)
            if not stat.S_ISREG(before.st_mode):
                raise PreviewError(f"link or non-regular file is not allowed: {name!r}")
            fd = os.open(name, _posix_flags("O_NOFOLLOW", "O_NONBLOCK"), dir_fd=self.posix_fd)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise PreviewError(f"non-regular or multiply linked file is not allowed: {name!r}")
            yield stream

    def entries(self) -> Iterator[tuple[str, bool]]:
        with os.scandir(_extended(self.path) if self.posix_fd is None else self.posix_fd) as it:
            for entry in it:
                yield entry.name, entry.is_dir(follow_symlinks=False)


def _duplicate(handle: int) -> int:
    dll = ctypes.WinDLL("kernel32.dll", use_last_error=True)
    dll.GetCurrentProcess.argtypes = ()
    dll.GetCurrentProcess.restype = wintypes.HANDLE
    process = dll.GetCurrentProcess()
    duplicate = wintypes.HANDLE()
    call = dll.DuplicateHandle
    call.argtypes = (wintypes.HANDLE, wintypes.HANDLE, wintypes.HANDLE,
                     ctypes.POINTER(wintypes.HANDLE), wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    call.restype = wintypes.BOOL
    if not call(process, handle, process, ctypes.byref(duplicate), 0, False, 2):
        raise ctypes.WinError(ctypes.get_last_error())
    assert duplicate.value is not None
    return duplicate.value


@contextmanager
def open_directory(path: Path) -> Iterator[Directory]:
    if not path.is_absolute() or len(path.parts) < 2 or ".." in path.parts:
        raise PreviewError("expected a local absolute directory below a drive root")
    with ExitStack() as stack:
        if os.name == "nt":
            win = _WindowsFiles()
            if not re.fullmatch(r"[A-Za-z]:", path.drive) or win.drive_type(path.anchor) not in (2, 3):
                raise PreviewError("Windows sources must be on local fixed or removable drives")
            current = Directory(Path(path.anchor), None, win)
        else:
            fd = os.open(path.anchor, _posix_flags("O_DIRECTORY"))
            stack.callback(os.close, fd)
            current = Directory(Path(path.anchor), fd, None)
        for part in path.parts[1:]:
            current = stack.enter_context(current.child(part))
        yield current


def signature(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_nlink,
            info.st_mtime_ns, info.st_ctime_ns)
