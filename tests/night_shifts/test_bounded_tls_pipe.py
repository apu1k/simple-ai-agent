"""Real TLS over a deterministic byte peer, plus native failure-path fixtures.

Synthetic temporary keys only. No VM, production credentials, network socket,
protected installation, CLI or policy mutation. Native cases require Windows.
"""
from __future__ import annotations

import sys
from collections import deque
from types import SimpleNamespace
from uuid import uuid4

import pytest

from night_shifts import bounded_tls_pipe as m
from night_shifts.maintenance_tls_prototype import (
    AttemptBinding,
    OfflineTlsEndpoint,
    PrototypeRefused,
)
from night_shifts.serial_pipe_io import BoundedPipe, IOBudget, PipeCleanupUnknown, PipeIOError
from tests.night_shifts.test_maintenance_tls_prototype import (
    Clock,
    contexts,
    handshake,
    material as material,
    pair,
    pin,
)
from tests.night_shifts.test_serial_pipe_io_windows import (
    assert_closed,
    local_pipe as local_pipe,
)

PATH = r"\\.\pipe\night-shift-0123456789abcdef0123456789abcdef-com1"


class PeerPipe:
    """Trusted test driver; production has no peer pump or fake-I/O fallback."""

    def __init__(self, guest, *, chunk=16384):
        self.guest = guest
        self.chunk = chunk
        self.budget = None
        self.closed = False
        self.cleanup_unknown = False
        self.close_calls = 0
        self.read_calls = 0
        self.writes = []
        self.messages = []
        self.replies = deque()
        self.read_error = None
        self.write_error = None
        self.unknown_close = False
        self.on_read = lambda: None
        self.on_write = lambda: None
        self.eof = False
        self.raw_reply = None

    def pump(self):
        self.guest.step()
        if self.guest.authenticated:
            while True:
                value = self.guest.receive_message()
                if value is None:
                    break
                self.messages.append(value)
            if self.replies and not self.guest.write_pending:
                self.guest.queue_message(self.replies.popleft())
                self.guest.step()

    def write_all(self, data):
        assert not self.closed
        self.budget.remaining()
        self.writes.append(data)
        if self.write_error is not None:
            # Model a failed write after an unknown/partial peer delivery.
            self.guest.feed_ciphertext(data[:1])
            raise self.write_error
        self.guest.feed_ciphertext(data)
        self.pump()
        self.on_write()

    def read(self, size):
        assert not self.closed
        self.budget.remaining()
        self.read_calls += 1
        if self.read_error is not None:
            if isinstance(self.read_error, PipeCleanupUnknown):
                self.closed = self.cleanup_unknown = True
            raise self.read_error
        if self.eof:
            return b""
        if self.raw_reply is not None:
            data, self.raw_reply = self.raw_reply, None
        else:
            self.pump()
            data = self.guest.take_ciphertext(min(size, self.chunk))
            if not data:
                raise PipeIOError("fixture_stalled")
        self.on_read()
        return data

    def close(self):
        self.close_calls += 1
        self.closed = True
        if self.unknown_close:
            self.cleanup_unknown = True
            raise PipeCleanupUnknown(self)
        self.cleanup_unknown = False
        self.guest.close()


def setup_peer(material, monkeypatch, *, chunk=16384, connect_cost=0):
    clock = Clock(0.0)
    binding = AttemptBinding(uuid4().hex, str(uuid4()))
    controller_context, guest_context = contexts(material)
    guest = OfflineTlsEndpoint(
        guest_context, binding, role="guest", peer_sha256=pin(material, "client"),
        timeout_seconds=900, clock=clock,
    )
    pipe = PeerPipe(guest, chunk=chunk)
    opens = []

    def connect(path, budget):
        assert path == PATH and isinstance(budget, IOBudget)
        opens.append(path)
        pipe.budget = budget
        clock.now += connect_cost
        return pipe

    monkeypatch.setattr(BoundedPipe, "connect", connect)

    def start(**overrides):
        options = dict(peer_sha256=pin(material, "server"), timeout_seconds=5, clock=clock)
        options.update(overrides)
        return m.BoundedTlsPipe(PATH, controller_context, binding, **options)

    return SimpleNamespace(start=start, pipe=pipe, clock=clock, opens=opens,
                           context=controller_context, binding=binding)


@pytest.mark.parametrize("chunk", [1, 7, 1024, 16384])
def test_mutual_tls_round_trip_fragmentation_and_no_plaintext(material, monkeypatch, chunk):
    fixture = setup_peer(material, monkeypatch, chunk=chunk)
    marker = "SYNTHETIC_PRIVATE_FRAME_" + uuid4().hex
    with fixture.start() as channel:
        assert channel._endpoint.authenticated and fixture.pipe.guest.authenticated
        channel.send_message({"request": marker})
        assert fixture.pipe.messages == [{"request": marker}]
        fixture.pipe.replies.append({"reply": marker})
        assert channel.receive_message() == {"reply": marker}
        channel.send_message({})
        assert fixture.pipe.messages[-1] == {}
        assert marker.encode() not in b"".join(fixture.pipe.writes)
        assert fixture.pipe.budget is channel._budget
        assert len(fixture.opens) == 1
    assert channel.closed and fixture.pipe.closed
    channel.close()


def test_large_frame_drains_buffered_records_before_waiting_for_more_input(material, monkeypatch):
    fixture = setup_peer(material, monkeypatch)
    with fixture.start() as channel:
        payload = {"large": "x" * 30000}
        fixture.pipe.replies.append(payload)
        assert channel.receive_message() == payload
        channel.send_message(payload)
        assert fixture.pipe.messages == [payload]


def test_endpoint_receive_itself_drains_all_available_tls_records(material):
    controller, guest = pair(material)
    handshake(controller, guest)
    payload = {"large": "x" * 30000}
    controller.queue_message(payload)
    controller.step()
    while controller.pending_ciphertext:
        guest.feed_ciphertext(controller.take_ciphertext())
    assert guest.receive_message() == payload  # One call, not a cooperative retry loop.
    assert guest.receive_message() is None


def test_two_buffered_messages_do_not_require_an_extra_pipe_read(material, monkeypatch):
    fixture = setup_peer(material, monkeypatch)
    with fixture.start() as channel:
        for value in (1, 2):
            fixture.pipe.guest.queue_message({"value": value})
            fixture.pipe.guest.step()
        assert channel.receive_message() == {"value": 1}
        reads = fixture.pipe.read_calls
        assert channel.receive_message() == {"value": 2}
        assert fixture.pipe.read_calls == reads


def test_connect_and_all_messages_share_original_deadline(material, monkeypatch):
    fixture = setup_peer(material, monkeypatch, connect_cost=2)
    channel = fixture.start()
    assert channel._budget.remaining() == 3
    fixture.clock.now = 4
    channel.send_message({"one": True})
    assert channel._budget.remaining() == 1
    fixture.clock.now = 5
    with pytest.raises(PipeIOError, match="^deadline$"):
        channel.send_message({"two": True})
    assert channel.closed and fixture.pipe.closed
    assert fixture.pipe.messages == [{"one": True}]
    assert len(fixture.opens) == 1


def test_late_connect_return_is_rejected_and_closed(material, monkeypatch):
    fixture = setup_peer(material, monkeypatch, connect_cost=5)
    with pytest.raises(PipeIOError, match="^deadline$"):
        fixture.start()
    assert fixture.pipe.closed and not fixture.pipe.writes


@pytest.mark.parametrize("phase", ["handshake", "send", "receive"])
def test_late_io_result_is_not_delivered(material, monkeypatch, phase):
    fixture = setup_peer(material, monkeypatch)

    def expire():
        fixture.clock.now = 5

    if phase == "handshake":
        fixture.pipe.on_read = expire
        action = fixture.start
    else:
        channel = fixture.start()
        if phase == "send":
            fixture.pipe.on_write = expire
            def action():
                channel.send_message({"fixture": True})
        else:
            fixture.pipe.replies.append({"fixture": True})
            fixture.pipe.on_read = expire
            action = channel.receive_message
    with pytest.raises(PipeIOError, match="^deadline$"):
        action()
    assert fixture.pipe.closed


@pytest.mark.parametrize("phase", ["handshake", "send", "receive"])
def test_cancellation_is_terminal_and_never_reconnects(material, monkeypatch, phase):
    fixture = setup_peer(material, monkeypatch)
    stopped = []
    if phase == "handshake":
        fixture.pipe.on_read = lambda: stopped.append(True)
        def action():
            return fixture.start(cancelled=lambda: bool(stopped))
    else:
        channel = fixture.start(cancelled=lambda: bool(stopped))
        stopped.append(True)
        action = (lambda: channel.send_message({})) if phase == "send" else channel.receive_message
    with pytest.raises(PipeIOError, match="^cancelled$"):
        action()
    assert fixture.pipe.closed and len(fixture.opens) == 1


def test_wrong_pin_refuses_before_application_traffic(material, monkeypatch):
    fixture = setup_peer(material, monkeypatch)
    with pytest.raises(PrototypeRefused, match="^peer_identity$"):
        fixture.start(peer_sha256="0" * 64)
    assert fixture.pipe.closed and fixture.pipe.messages == []


def test_insecure_context_refuses_before_open(material, monkeypatch):
    fixture = setup_peer(material, monkeypatch)
    fixture.context.check_hostname = False
    with pytest.raises(PrototypeRefused, match="^configuration$"):
        fixture.start()
    assert not fixture.opens and fixture.pipe.budget is None


@pytest.mark.parametrize("during_handshake", [False, True])
def test_plaintext_or_eof_is_terminal_without_fallback(material, monkeypatch, during_handshake):
    fixture = setup_peer(material, monkeypatch)
    if during_handshake:
        fixture.pipe.raw_reply = b'{"not":"TLS"}\n'
        action = fixture.start
        error, label = PrototypeRefused, "tls_failure"
    else:
        channel = fixture.start()
        fixture.pipe.eof = True
        action = channel.receive_message
        error, label = PipeIOError, "channel_closed"
    with pytest.raises(error, match=f"^{label}$"):
        action()
    assert fixture.pipe.closed and len(fixture.opens) == 1


def test_partial_failed_write_is_not_replayed(material, monkeypatch):
    fixture = setup_peer(material, monkeypatch)
    channel = fixture.start()
    fixture.pipe.write_error = PipeIOError("native_io")
    writes = len(fixture.pipe.writes)
    with pytest.raises(PipeIOError, match="^native_io$"):
        channel.send_message({"must_not_replay": True})
    assert len(fixture.pipe.writes) == writes + 1
    assert fixture.pipe.messages == []
    with pytest.raises(PipeIOError, match="^closed$"):
        channel.send_message({"must_not_replay": True})
    assert len(fixture.pipe.writes) == writes + 1 and len(fixture.opens) == 1


def test_unknown_cleanup_overrides_original_failure(material, monkeypatch):
    fixture = setup_peer(material, monkeypatch)
    channel = fixture.start()
    fixture.pipe.eof = True
    fixture.pipe.unknown_close = True
    with pytest.raises(PipeCleanupUnknown, match="^cleanup_unknown$") as error:
        channel.receive_message()
    assert error.value.channel is fixture.pipe
    assert channel.closed and fixture.pipe.close_calls == 1
    fixture.pipe.unknown_close = False
    channel.close()
    assert not fixture.pipe.cleanup_unknown


def test_unknown_io_cleanup_is_not_implicitly_retried(material, monkeypatch):
    fixture = setup_peer(material, monkeypatch)
    channel = fixture.start()
    fixture.pipe.read_error = PipeCleanupUnknown(fixture.pipe)
    with pytest.raises(PipeCleanupUnknown) as error:
        channel.receive_message()
    assert error.value.channel is fixture.pipe
    assert channel.closed and fixture.pipe.cleanup_unknown
    assert fixture.pipe.close_calls == 0
    channel.close()
    assert fixture.pipe.close_calls == 1


def test_wrong_owner_and_reentry_do_not_close_active_channel(material, monkeypatch):
    fixture = setup_peer(material, monkeypatch)
    with fixture.start() as channel:
        with monkeypatch.context() as patch:
            patch.setattr(m.threading, "get_ident", lambda: -1)
            for action in (channel.close, channel.receive_message):
                with pytest.raises(PipeIOError, match="^wrong_thread$"):
                    action()
        channel._busy = True
        try:
            for action in (channel.close, channel.receive_message):
                with pytest.raises(PipeIOError, match="^busy$"):
                    action()
        finally:
            channel._busy = False
        assert not channel.closed and not fixture.pipe.closed
        channel.send_message({"still_usable": True})


@pytest.mark.parametrize("error", [RuntimeError("PRIVATE_CANARY"), KeyboardInterrupt()])
def test_unexpected_failure_and_interrupt_release_channel(material, monkeypatch, error):
    fixture = setup_peer(material, monkeypatch)
    channel = fixture.start()
    fixture.pipe.read_error = error
    expected = KeyboardInterrupt if isinstance(error, KeyboardInterrupt) else PipeIOError
    with pytest.raises(expected) as failure:
        channel.receive_message()
    assert "PRIVATE_CANARY" not in str(failure.value)
    assert channel.closed and fixture.pipe.closed


def test_expired_context_entry_disposes_session(material, monkeypatch):
    fixture = setup_peer(material, monkeypatch)
    channel = fixture.start()
    fixture.clock.now = 5
    with pytest.raises(PipeIOError, match="^deadline$"):
        with channel:
            pytest.fail("expired context must not enter")
    assert channel.closed and fixture.pipe.closed


def test_bad_application_payload_closes_both_layers(material, monkeypatch):
    fixture = setup_peer(material, monkeypatch)
    channel = fixture.start()
    with pytest.raises(PrototypeRefused, match="^frame_value$"):
        channel.send_message({"bad": float("nan")})
    assert channel.closed and fixture.pipe.closed


@pytest.mark.skipif(sys.platform != "win32", reason="Windows named-pipe fixture")
@pytest.mark.parametrize("mode", ["silent", "cancel", "plaintext", "disconnect"])
def test_native_handshake_failure_closes_exact_client_handles(material, local_pipe, monkeypatch, mode):
    controller_context, _ = contexts(material)
    original_connect = BoundedPipe.connect
    clients = []
    stopped = []

    def connect(path, budget):
        client = original_connect(path, budget)
        clients.append(client)
        local_pipe.accept()
        if mode == "cancel":
            original_begin = client._api.begin

            def begin(handle, pending, size, writing):
                original_begin(handle, pending, size, writing)
                if not writing:
                    stopped.append(True)

            monkeypatch.setattr(client._api, "begin", begin)
        elif mode == "plaintext":
            local_pipe.server.write_all(b'{"not":"TLS"}\n')
        elif mode == "disconnect":
            local_pipe.server.close()
        return client

    monkeypatch.setattr(BoundedPipe, "connect", connect)
    expected = PrototypeRefused if mode == "plaintext" else PipeIOError
    label = {"silent": "deadline", "cancel": "cancelled", "plaintext": "tls_failure"}.get(mode)
    with pytest.raises(expected) as error:
        m.BoundedTlsPipe(
            local_pipe.path, controller_context, AttemptBinding(uuid4().hex, str(uuid4())),
            peer_sha256=pin(material, "server"), timeout_seconds=0.5,
            cancelled=lambda: bool(stopped),
        )
    if label is not None:
        assert str(error.value) == label
    assert len(clients) == 1
    assert_closed(clients[0])
    if mode in ("silent", "cancel"):
        while local_pipe.server.read(16384):  # Drain ClientHello, observe native EOF.
            pass


def test_adapter_still_excluded_from_actual_inspection_bundle():
    import io
    import zipfile

    from night_shifts.inspection_bundle import bundle_bytes

    with zipfile.ZipFile(io.BytesIO(bundle_bytes())) as archive:
        names = set(archive.namelist())
    for name in ("bounded_tls_pipe.py", "serial_pipe_io.py", "maintenance_tls_prototype.py"):
        assert "night_shifts/" + name not in names
