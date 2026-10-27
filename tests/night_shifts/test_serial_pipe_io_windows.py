"""NON-SECRET current-user Windows pipe fixtures; no Hyper-V or elevation.

Each fixture creates one random first-instance, local-only byte pipe with an
explicit current-user-only DACL. The server and client both use overlapped I/O.
These are I/O/lifetime observations, NOT production pipe identity/ACL evidence.
"""
from __future__ import annotations

import ctypes
import sys
import time
import uuid
from types import SimpleNamespace

import pytest

from night_shifts import serial_pipe_io as m

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows named-pipe fixture")


class _SecurityAttributes(ctypes.Structure):
    _fields_ = [
        ("length", ctypes.c_uint32),
        ("descriptor", ctypes.c_void_p),
        ("inherit", ctypes.c_int),
    ]


@pytest.fixture
def local_pipe():
    from night_shifts.ubuntu_preparation_control import _current_user_sid

    api = m._Windows()
    h, d, b = ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int
    create = api._bind("CreateNamedPipeW", [ctypes.c_wchar_p, d, d, d, d, d, d,
                                         ctypes.POINTER(_SecurityAttributes)], h)
    accept = api._bind("ConnectNamedPipe", [h, ctypes.POINTER(m._OVERLAPPED)], b)
    free = api._bind("LocalFree", [h], h)
    adv = getattr(ctypes, "WinDLL")("advapi32", use_last_error=True)
    convert = adv.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert.argtypes = [ctypes.c_wchar_p, d, ctypes.POINTER(h), ctypes.POINTER(d)]
    convert.restype = b
    descriptor = h()
    sddl = f"D:P(A;;GA;;;{_current_user_sid()})"
    assert convert(sddl, 1, ctypes.byref(descriptor), None)
    path = rf"\\.\pipe\night-shift-{uuid.uuid4().hex}-com1"
    try:
        security = _SecurityAttributes(ctypes.sizeof(_SecurityAttributes), descriptor, False)
        # DUPLEX | OVERLAPPED | FIRST_PIPE_INSTANCE; byte mode | REJECT_REMOTE_CLIENTS.
        handle = create(path, 0x3 | 0x40000000 | 0x80000, 0x8, 1,
                        1024, 1024, 0, ctypes.byref(security))
    finally:
        assert not free(descriptor)
    assert handle and handle != ctypes.c_void_p(-1).value, api._last_error()
    owner = m.BoundedPipe(m.IOBudget(10), api)
    owner._handle = int(handle)

    def connected():
        # Called AFTER client open: ERROR_PIPE_CONNECTED is expected, not failure.
        with owner._operation():
            pending = m._Pending(ctypes.create_string_buffer(1), m._OVERLAPPED())
            pending.event = api.event()
            owner._pending = pending
            pending.overlapped.hEvent = pending.event
            pending.submitted = True
            ok = accept(owner._handle, ctypes.byref(pending.overlapped))
            error = 0 if ok else api._last_error()
            if error not in (0, 535, 997):
                pending.submitted = False
                owner._release_event()
                pytest.fail(f"fixture connect error {error}")
            if error == 997:
                while api.poll(owner._handle, pending) is None:
                    owner._budget.remaining()
                    time.sleep(0.01)
            pending.submitted = False
            owner._release_event()
            owner._budget.remaining()

    try:
        yield SimpleNamespace(path=path, server=owner, accept=connected)
    finally:
        owner.close()
        assert not owner.cleanup_unknown
        assert owner._handle is None and owner._pending is None


def assert_closed(channel):
    assert channel.closed and not channel.cleanup_unknown
    assert channel._handle is None and channel._pending is None
    assert id(channel) not in m._QUARANTINE


def test_native_fragmented_round_trip_and_exact_close(local_pipe):
    with m.BoundedPipe.connect(local_pipe.path, m.IOBudget(3)) as client:
        local_pipe.accept()
        local_pipe.server.write_all(b"a")
        assert client.read(8) == b"a"
        local_pipe.server.write_all(b"bc")
        assert client.read(8) == b"bc"
        client.write_all(b"synthetic")
        assert local_pipe.server.read(32) == b"synthetic"
    assert_closed(client)
    assert local_pipe.server.read(1) == b""  # Native peer sees the client disconnect.


def test_native_eof_after_server_disconnect(local_pipe):
    with m.BoundedPipe.connect(local_pipe.path, m.IOBudget(3)) as client:
        local_pipe.accept()
        local_pipe.server.close()
        assert client.read(8) == b""
    assert_closed(client)


@pytest.mark.parametrize("write", [False, True])
def test_native_silent_peer_or_write_backpressure_times_out_and_drains(local_pipe, write):
    client = m.BoundedPipe.connect(local_pipe.path, m.IOBudget(0.3))
    try:
        local_pipe.accept()
        started = time.monotonic()
        with pytest.raises(m.PipeIOError, match="^deadline$"):
            if write:
                client.write_all(b"x" * m.MAX_WRITE_BYTES)
            else:
                client.read(32)
        # Observed fixture bound, not proof a Win32/provider call is preemptible.
        assert time.monotonic() - started < 4
        assert_closed(client)
        if not write:
            assert local_pipe.server.read(1) == b""
    finally:
        client.close()


@pytest.mark.parametrize("write", [False, True])
def test_native_cancellation_after_actual_submission_drains(local_pipe, write, monkeypatch):
    submitted = []
    budget = m.IOBudget(3, cancelled=lambda: bool(submitted))
    client = m.BoundedPipe.connect(local_pipe.path, budget)
    try:
        local_pipe.accept()
        original = client._api.begin
        def begin(handle, pending, size, writing):
            original(handle, pending, size, writing)
            submitted.append(pending)
        monkeypatch.setattr(client._api, "begin", begin)
        started = time.monotonic()
        with pytest.raises(m.PipeIOError, match="^cancelled$"):
            if write:
                client.write_all(b"x" * m.MAX_WRITE_BYTES)
            else:
                client.read(32)
        assert submitted
        assert time.monotonic() - started < 4
        assert_closed(client)
        if not write:
            assert local_pipe.server.read(1) == b""
    finally:
        client.close()


def test_native_absent_pipe_connection_deadline():
    path = rf"\\.\pipe\night-shift-{uuid.uuid4().hex}-com1"
    started = time.monotonic()
    with pytest.raises(m.PipeIOError, match="^deadline$"):
        m.BoundedPipe.connect(path, m.IOBudget(0.1))
    assert time.monotonic() - started < 2
