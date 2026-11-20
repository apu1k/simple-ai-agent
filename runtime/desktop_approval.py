"""Windows desktop review for requests from the normal shared web chat.

The browser can request review, not decide it. This is a trusted application
workflow, not protection against other software running as the Windows user.
"""
from __future__ import annotations

from collections.abc import Callable
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from threading import Event, Lock, Thread
from time import monotonic

if sys.platform == 'win32':
    from ctypes import WinDLL


_MAX_DISPLAY_BYTES = 512 * 1024


def desktop_ready() -> bool:
    """Require an ordinary process in the active, unlocked console desktop."""
    if sys.platform != 'win32':
        return False
    try:
        kernel = WinDLL('kernel32', use_last_error=True)
        user = WinDLL('user32', use_last_error=True)
        if WinDLL('shell32').IsUserAnAdmin():
            return False
        session = wintypes.DWORD()
        if not kernel.ProcessIdToSessionId(os.getpid(), ctypes.byref(session)):
            return False
        if not session.value or session.value != kernel.WTSGetActiveConsoleSessionId():
            return False
        user.OpenInputDesktop.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        user.OpenInputDesktop.restype = wintypes.HANDLE
        user.CloseDesktop.argtypes = (wintypes.HANDLE,)
        user.GetUserObjectInformationW.argtypes = (
            wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
        )
        handle = user.OpenInputDesktop(0, False, 1)  # DESKTOP_READOBJECTS
        if not handle:
            return False
        try:
            name = ctypes.create_unicode_buffer(128)
            size = wintypes.DWORD()
            return bool(user.GetUserObjectInformationW(handle, 2, name, ctypes.sizeof(name), ctypes.byref(size))) \
                and name.value == 'Default'  # UOI_NAME
        finally:
            user.CloseDesktop(handle)
    except (OSError, AttributeError):
        return False


class DesktopApproval:
    """One native review at a time across all chats on this backend."""

    def __init__(self) -> None:
        self._lease = Lock()
        self._not_before = 0.0

    def ask(self, display: str, digest: str, cancelled: Callable[[], bool]) -> bool:
        if not self._lease.acquire(blocking=False):
            return False
        try:
            if (monotonic() < self._not_before or cancelled() or not desktop_ready()
                    or not re.fullmatch('[0-9a-f]{64}', digest)):
                return False
            data = json.dumps([display, digest], ensure_ascii=True).encode('ascii')
            if not data or len(data) > _MAX_DISPLAY_BYTES:
                return False
            self._not_before = monotonic() + 5
            return self._prompt(data, digest, cancelled)
        finally:
            self._lease.release()

    @staticmethod
    def _prompt(data: bytes, digest: str, cancelled: Callable[[], bool]) -> bool:
        # Never use the chat's working directory, paths, environment or shell
        # to load the reviewer. Its pipe carries text, not executable code.
        source = Path(__file__).resolve()
        env = {key: os.environ[key] for key in ('SystemRoot', 'WINDIR', 'TEMP', 'TMP') if key in os.environ}
        # Use the base interpreter: a Windows venv redirector can leave a
        # separate descendant alive if only the redirector is terminated.
        interpreter = getattr(sys, '_base_executable', sys.executable)
        if not Path(interpreter).is_absolute():
            return False
        try:
            child = subprocess.Popen(
                [interpreter, '-I', '-S', '-B', str(source), '--review'], cwd=source.parent,
                env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            )
        except (OSError, ValueError):
            return False
        done = Event()
        result: list[bool] = []

        def exchange() -> None:
            try:
                output, _ = child.communicate(input=data)
                result.append(child.returncode == 0 and output == digest.encode('ascii'))
            except (OSError, ValueError):
                pass
            finally:
                done.set()

        # A Windows pipe write can block even with communicate(timeout=...).
        # Keep pipe exchange off the deadline/cancellation observer.
        io_thread = Thread(target=exchange, name='desktop-review-pipe', daemon=True)
        try:
            io_thread.start()
            deadline = monotonic() + 120
            while not cancelled() and monotonic() < deadline:
                if done.wait(0.1):
                    return result == [True] and not cancelled() and desktop_ready()
            return False
        finally:
            try:
                if child.poll() is None:
                    child.kill()  # only the exact unelevated reviewer we created
                child.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                # A separate persisted approval is never issued on timeout;
                # even a later digest in this pipe cannot authorize anything.
                pass
            if io_thread.ident is not None:
                io_thread.join(timeout=0.5)


def _show_review() -> None:
    if sys.argv[1:] != ['--review'] or not desktop_ready():
        return
    data = sys.stdin.buffer.read(_MAX_DISPLAY_BYTES + 1)
    if len(data) > _MAX_DISPLAY_BYTES:
        return
    try:
        display, digest = json.loads(data)
    except (TypeError, ValueError):
        return
    if not isinstance(display, str) or not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest):
        return

    import tkinter as tk
    from tkinter.scrolledtext import ScrolledText

    root = tk.Tk()
    root.title('AI agent — Review Windows administrator request')
    root.geometry('870x630')
    root.attributes('-topmost', True)
    tk.Label(root, text='Approve only if you initiated the request in your browser and reviewed the full text.').pack(pady=8)
    text = ScrolledText(root, wrap='char', font='TkFixedFont')
    text.insert('1.0', display)
    text.configure(state='disabled')
    text.pack(fill='both', expand=True, padx=10)
    actions = tk.Frame(root)
    actions.pack(pady=10)
    tk.Button(actions, text='Reject', command=root.destroy).pack(side='left', padx=8)

    def accept() -> None:
        if desktop_ready():
            sys.stdout.buffer.write(digest.encode('ascii'))
            sys.stdout.buffer.flush()
        root.destroy()

    tk.Button(actions, text='Accept reviewed request and ask for UAC', command=accept).pack(side='left', padx=8)
    root.bind('<Escape>', lambda _event: root.destroy())
    root.after(120_000, root.destroy)
    text.focus_set()  # No default accept action or Enter binding.
    root.mainloop()


if __name__ == '__main__':
    _show_review()
