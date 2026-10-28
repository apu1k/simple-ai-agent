"""Native authenticated TLS round trips; synthetic keys, no Hyper-V/network.

A separate spawn-process owns the test server and every server OVERLAPPED.
The controller uses the real BoundedTlsPipe without replacing its connector.
Only the exact spawned peer may be terminated by fixture teardown. This test
harness is not the protected process/VM watchdog required for live deployment.
"""
from __future__ import annotations

import ctypes
import json
import multiprocessing
import ssl
import struct
import sys
import time
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization

from night_shifts import serial_pipe_io as io
from night_shifts.bounded_tls_pipe import BoundedTlsPipe
from night_shifts.maintenance_tls_prototype import (
    AttemptBinding,
    OfflineTlsEndpoint,
    PrototypeRefused,
)
from tests.night_shifts.test_maintenance_tls_prototype import (
    contexts,
    material as material,
    pin,
)
from tests.night_shifts.test_serial_pipe_io_windows import (
    _SecurityAttributes,
    assert_closed,
)

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows named-pipe TLS fixture")


# All helpers below are test-only. There is no guest dispatcher or production
# listener API; the peer implements only these fixed synthetic scenarios.
def _server_pipe(path, budget):
    from night_shifts.ubuntu_preparation_control import _current_user_sid

    api = io._Windows()
    owner = io.BoundedPipe(budget, api, cleanup_timeout_seconds=1)
    h, d = ctypes.c_void_p, ctypes.c_uint32
    create = api._bind("CreateNamedPipeW", [ctypes.c_wchar_p, d, d, d, d, d, d,
                                         ctypes.POINTER(_SecurityAttributes)], h)
    free = api._bind("LocalFree", [h], h)
    adv = getattr(ctypes, "WinDLL")("advapi32", use_last_error=True)
    convert = adv.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert.argtypes = [ctypes.c_wchar_p, d, ctypes.POINTER(h), ctypes.POINTER(d)]
    convert.restype = ctypes.c_int
    descriptor = h()
    with owner._operation(require_handle=False):
        sddl = f"D:P(A;;GA;;;{_current_user_sid()})"
        if not convert(sddl, 1, ctypes.byref(descriptor), None):
            raise io.PipeIOError("fixture_descriptor")
        try:
            security = _SecurityAttributes(ctypes.sizeof(_SecurityAttributes), descriptor, False)
            # Duplex, OVERLAPPED, FIRST_PIPE_INSTANCE; byte mode, remote refusal.
            handle = create(path, 0x3 | 0x40000000 | 0x80000, 0x8, 1,
                            4096, 4096, 0, ctypes.byref(security))
            if not handle or handle == ctypes.c_void_p(-1).value:
                raise io.PipeIOError("fixture_create")
            owner._handle = int(handle)  # Own before any further fallible step.
        finally:
            if free(descriptor):
                raise io.PipeIOError("fixture_descriptor_release")
    return owner


def _accept(owner):
    api = owner._api
    accept = api._bind("ConnectNamedPipe", [ctypes.c_void_p, ctypes.POINTER(io._OVERLAPPED)],
                       ctypes.c_int)
    with owner._operation():
        pending = io._Pending(ctypes.create_string_buffer(1), io._OVERLAPPED())
        pending.event = api.event()
        owner._pending = pending
        pending.overlapped.hEvent = pending.event
        pending.submitted = True
        ok = accept(owner._handle, ctypes.byref(pending.overlapped))
        error = 0 if ok else api._last_error()
        if error not in (0, 535, 997):
            pending.submitted = False
            owner._release_event()
            raise io.PipeIOError("fixture_accept")
        if error == 997:
            while True:
                owner._budget.remaining()
                completion = api.poll(owner._handle, pending)
                if completion is not None:
                    if completion.error:
                        pending.submitted = False
                        owner._release_event()
                        raise io.PipeIOError("fixture_accept_completion")
                    break
                time.sleep(min(0.005, owner._budget.remaining()))
        pending.submitted = False
        owner._release_event()
        owner._budget.remaining()


class _PeerDriver:
    def __init__(self, endpoint, channel, budget, fragment):
        self.endpoint = endpoint
        self.channel = channel
        self.budget = budget
        self.fragment = fragment
        self.incoming = bytearray()
        self.outgoing = bytearray()
        self.fragments = 0

    def _record(self, target, data):
        if len(target) + len(data) > 128 * 1024:
            raise io.PipeIOError("fixture_trace_limit")
        target.extend(data)

    def drain(self):
        wrote = False
        while self.endpoint.pending_ciphertext:
            self.budget.remaining()
            data = self.endpoint.take_ciphertext(self.fragment)
            self.channel.write_all(data)
            self.budget.remaining()
            self._record(self.outgoing, data)
            self.fragments += 1
            wrote = True
        return wrote

    def read(self):
        self.budget.remaining()
        data = self.channel.read(16384)
        self.budget.remaining()
        if not data:
            raise io.PipeIOError("channel_closed")
        self._record(self.incoming, data)
        self.endpoint.feed_ciphertext(data)

    def handshake(self):
        while not self.endpoint.authenticated:
            self.budget.remaining()
            self.endpoint.step()
            self.drain()
            if not self.endpoint.authenticated:
                self.read()
        self.budget.remaining()

    def receive(self):
        while True:
            self.budget.remaining()
            self.endpoint.step()
            message = self.endpoint.receive_message()
            wrote = self.drain()
            if message is not None:
                self.budget.remaining()
                return message
            if not wrote:
                self.read()

    def send(self, payload):
        self.endpoint.queue_message(payload)
        while True:
            self.budget.remaining()
            self.endpoint.step()
            wrote = self.drain()
            if not self.endpoint.write_pending:
                self.budget.remaining()
                return
            if not wrote:
                self.read()

    def observe_disconnect(self):
        # Native EOF is an independent peer-side observation, not a flag set by
        # controller close(). No application data is expected at this point.
        data = self.channel.read(16384)
        self.budget.remaining()
        if data:
            raise io.PipeIOError("fixture_unexpected_bytes")


def _send_receipt(sender, value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(raw) > 8192:
        raise io.PipeIOError("fixture_receipt_limit")
    sender.send_bytes(raw)


def _peer_main(config, sender):
    channel = endpoint = driver = None
    report = dict(state="finished", authenticated=False, received=0, error=None,
                  released=False, peer_eof=False, plaintext_visible=False, fragments=0)
    try:
        budget = io.IOBudget(10)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = context.maximum_version = ssl.TLSVersion.TLSv1_3
        context.verify_mode = ssl.CERT_REQUIRED
        context.verify_flags |= ssl.VERIFY_X509_STRICT
        context.options |= ssl.OP_NO_TICKET
        context.num_tickets = 0
        context.load_verify_locations(cadata=config["ca"])
        context.load_cert_chain(config["cert"], config["key"])
        endpoint = OfflineTlsEndpoint(
            context, AttemptBinding(config["attempt"], config["guest_vm"]), role="guest",
            peer_sha256=config["client_pin"], timeout_seconds=budget.remaining(),
        )
        channel = _server_pipe(config["path"], budget)
        _send_receipt(sender, {"state": "ready"})
        _accept(channel)
        driver = _PeerDriver(endpoint, channel, budget, config["fragment"])
        driver.handshake()
        report["authenticated"] = True
        _send_receipt(sender, {"state": "authenticated"})
        if config["mode"] in ("silent", "cancel"):
            driver.observe_disconnect()
            report["peer_eof"] = True
        else:
            message = driver.receive()
            if message != config["payload"]:
                raise io.PipeIOError("fixture_payload_mismatch")
            report["received"] += 1
            if config["mode"] == "truncated":
                # Authenticated hostile-peer fixture ONLY: emit an incomplete
                # application frame in a valid TLS record, then close the pipe.
                raw = struct.pack("!I", 100) + b"{"
                if endpoint._tls.write(raw) != len(raw):
                    raise io.PipeIOError("fixture_partial_tls_write")
                driver.drain()
            else:
                driver.send(message)
                second = driver.receive()
                if second != {"ordinal": 2}:
                    raise io.PipeIOError("fixture_second_message")
                report["received"] += 1
                driver.send(second)
                driver.observe_disconnect()
                report["peer_eof"] = True
    except (PrototypeRefused, io.PipeIOError) as error:
        report["error"] = str(error)  # Both APIs provide fixed labels only.
    except BaseException:
        report["error"] = "fixture_failure"
    finally:
        if endpoint is not None:
            endpoint.close()
        if channel is not None:
            try:
                if not channel.cleanup_unknown:
                    channel.close()  # Never implicitly retry cleanup_unknown.
            except BaseException:
                report["error"] = "fixture_cleanup_unknown"
            report["released"] = (
                channel.closed and not channel.cleanup_unknown and channel._handle is None
                and channel._pending is None and id(channel) not in io._QUARANTINE
            )
        if driver is not None:
            marker = config["payload"]["marker"].encode("ascii")
            report["plaintext_visible"] = (
                marker in driver.incoming or marker in driver.outgoing
            )
            report["fragments"] = driver.fragments
        try:
            _send_receipt(sender, report)
        except (OSError, EOFError):
            pass  # Parent teardown may already have closed its fixture channel.
        finally:
            sender.close()


def _reap(peer):
    process = peer.process
    process.join(2)
    peer.forced = process.is_alive()
    if peer.forced:
        process.terminate()  # Exact owned process only, never a name/group search.
        process.join(3)
    if process.is_alive():
        raise RuntimeError("fixture_peer_cleanup_unknown")
    peer.exitcode = process.exitcode
    peer.reaped = True
    process.close()
    if peer.forced:
        pytest.fail("fixture_peer_required_termination")
    assert peer.exitcode == 0, "fixture_peer_failed"


@pytest.fixture
def peer_factory(material):
    @contextmanager
    def start(mode, *, fragment=16384, size=32):
        context = multiprocessing.get_context("spawn")
        receiver, sender = context.Pipe(duplex=False)
        binding = AttemptBinding(uuid4().hex, str(uuid4()))
        payload = {"marker": "SYNTHETIC_NATIVE_TLS_" + uuid4().hex, "body": "x" * size}
        config = dict(
            mode=mode, fragment=fragment, payload=payload,
            path=rf"\\.\pipe\night-shift-{uuid4().hex}-com1",
            attempt=binding.attempt_id,
            guest_vm=str(uuid4()) if mode == "wrong_binding" else binding.vm_id,
            client_pin=pin(material, "other_client" if mode == "wrong_client_pin" else "client"),
            ca=material["ca"].public_bytes(serialization.Encoding.PEM).decode("ascii"),
            cert=str(material["server"][0]), key=str(material["server"][1]),
        )
        process = context.Process(target=_peer_main, args=(config, sender), daemon=True)
        peer = SimpleNamespace(process=process, path=config["path"], binding=binding,
                               payload=payload, reaped=False, forced=False, exitcode=None,
                               messages=0)

        def wait_for(state, timeout=5):
            deadline = time.monotonic() + timeout
            for _ in range(3):
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not receiver.poll(remaining):
                    pytest.fail("fixture_receipt_deadline")
                raw = receiver.recv_bytes(8192)  # Bounded JSON, no received pickle.
                value = json.loads(raw.decode("utf-8"))
                assert type(value) is dict and value.get("state") in (
                    "ready", "authenticated", "finished",
                ), "fixture_receipt_schema"
                peer.messages += 1
                assert peer.messages <= 3, "fixture_receipt_count"
                if value["state"] == state:
                    return value
                assert state == "finished" and value["state"] == "authenticated", (
                    "fixture_unexpected_state"
                )
            pytest.fail("fixture_receipt_count")

        peer.wait_for = wait_for
        started = False
        try:
            process.start()
            started = True
            sender.close()
            wait_for("ready", 8)
            yield peer
        finally:
            sender.close()
            receiver.close()
            if started:
                _reap(peer)
            else:
                process.close()

    return start


def _finished(peer, *, error=None, received=0, authenticated=True, eof=False):
    report = peer.wait_for("finished")
    assert report["error"] == error
    assert report["authenticated"] is authenticated
    assert report["received"] == received
    assert report["released"] is True
    assert report["peer_eof"] is eof
    assert report["plaintext_visible"] is False
    return report


@pytest.mark.parametrize("fragment,size", [(16384, 32), (97, 32), (1024, 30000)],
                         ids=["small", "fragmented", "multi-record"])
def test_native_authenticated_two_message_round_trip(material, peer_factory, fragment, size):
    controller_context, _ = contexts(material)
    with peer_factory("exchange", fragment=fragment, size=size) as peer:
        with BoundedTlsPipe(peer.path, controller_context, peer.binding,
                            peer_sha256=pin(material, "server"), timeout_seconds=5) as client:
            native = client._pipe
            client.send_message(peer.payload)
            assert client.receive_message() == peer.payload
            client.send_message({"ordinal": 2})
            assert client.receive_message() == {"ordinal": 2}
        assert_closed(native)
        report = _finished(peer, received=2, eof=True)
        assert report["fragments"] > 1
    assert peer.reaped and not peer.forced and peer.exitcode == 0


@pytest.mark.parametrize("mode", ["wrong_client_pin", "wrong_server_pin"])
def test_native_mutual_peer_pins_refuse_before_application_delivery(material, peer_factory, mode):
    controller_context, _ = contexts(material)
    with peer_factory(mode) as peer:
        expected = PrototypeRefused if mode == "wrong_server_pin" else (io.PipeIOError, PrototypeRefused)
        with pytest.raises(expected) as failure:
            with BoundedTlsPipe(
                peer.path, controller_context, peer.binding, timeout_seconds=5,
                peer_sha256=pin(material, "other_server" if mode == "wrong_server_pin" else "server"),
            ) as client:
                client.receive_message()
        if mode == "wrong_server_pin":
            assert str(failure.value) == "peer_identity"
            report = peer.wait_for("finished")
            assert report["authenticated"] is False and report["received"] == 0
            assert report["released"] is True
            assert report["error"] in ("channel_closed", "tls_failure", "native_io")
        else:
            _finished(peer, error="peer_identity", authenticated=False)
    assert peer.reaped and not peer.forced


def test_native_authenticated_wrong_vm_binding_is_not_delivered(material, peer_factory):
    controller_context, _ = contexts(material)
    with peer_factory("wrong_binding") as peer:
        with pytest.raises((io.PipeIOError, PrototypeRefused)):
            with BoundedTlsPipe(peer.path, controller_context, peer.binding,
                                peer_sha256=pin(material, "server"), timeout_seconds=5) as client:
                native = client._pipe
                client.send_message(peer.payload)
                client.receive_message()
        assert_closed(native)
        _finished(peer, error="frame_binding")
    assert peer.reaped and not peer.forced


def test_native_authenticated_truncated_frame_never_returns_partial_payload(material, peer_factory):
    controller_context, _ = contexts(material)
    with peer_factory("truncated") as peer:
        with pytest.raises((io.PipeIOError, PrototypeRefused)):
            with BoundedTlsPipe(peer.path, controller_context, peer.binding,
                                peer_sha256=pin(material, "server"), timeout_seconds=5) as client:
                native = client._pipe
                client.send_message(peer.payload)
                client.receive_message()
        assert_closed(native)
        _finished(peer, received=1)
    assert peer.reaped and not peer.forced


@pytest.mark.parametrize("mode", ["silent", "cancel"])
def test_native_post_authentication_stall_or_submitted_read_cancellation(
    material, peer_factory, monkeypatch, mode,
):
    controller_context, _ = contexts(material)
    stopped = []
    with peer_factory(mode) as peer:
        client = BoundedTlsPipe(
            peer.path, controller_context, peer.binding, peer_sha256=pin(material, "server"),
            timeout_seconds=1.5 if mode == "silent" else 5,
            cancelled=lambda: bool(stopped),
        )
        native = client._pipe
        try:
            peer.wait_for("authenticated")
            if mode == "cancel":
                original = native._api.begin

                def begin(handle, pending, size, writing):
                    original(handle, pending, size, writing)
                    if not writing:
                        stopped.append(True)

                monkeypatch.setattr(native._api, "begin", begin)
            label = "deadline" if mode == "silent" else "cancelled"
            with pytest.raises(io.PipeIOError, match=f"^{label}$"):
                client.receive_message()
            if mode == "cancel":
                assert stopped  # The native read was actually submitted.
            assert client.closed
            assert_closed(native)
        finally:
            client.close()
        _finished(peer, eof=True)
    assert peer.reaped and not peer.forced and peer.exitcode == 0
