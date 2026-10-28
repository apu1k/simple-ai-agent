"""Real memory TLS with a deterministic guest-serial model; no Linux/VM I/O."""
from __future__ import annotations

import io
import zipfile
from types import SimpleNamespace
from uuid import uuid4

import pytest

from night_shifts.guest import bounded_tls_serial as m
from night_shifts.guest.serial_device_io import SerialCleanupUnknown, SerialDevice
from night_shifts.maintenance_tls_prototype import AttemptBinding, OfflineTlsEndpoint, PrototypeRefused
from night_shifts.serial_pipe_io import IOBudget, PipeIOError
from tests.night_shifts.test_bounded_tls_pipe import PeerPipe
from tests.night_shifts.test_maintenance_tls_prototype import (
    Clock,
    contexts,
    material as material,
    pin,
)


class PeerSerial(PeerPipe):
    """Reverse-role byte-peer driver; no production fake or fd adoption API."""

    def read(self, size):
        if isinstance(self.read_error, SerialCleanupUnknown):
            self.closed = self.cleanup_unknown = True
            raise self.read_error
        return super().read(size)

    def close(self):
        if self.cleanup_unknown:
            raise SerialCleanupUnknown(self)
        if self.unknown_close:
            self.close_calls += 1
            self.closed = self.cleanup_unknown = True
            raise SerialCleanupUnknown(self)
        super().close()


def setup_peer(material, monkeypatch, *, chunk=16384, open_cost=0):
    clock = Clock(0.0)
    binding = AttemptBinding(uuid4().hex, str(uuid4()))
    controller_context, guest_context = contexts(material)
    controller = OfflineTlsEndpoint(
        controller_context, binding, role="controller", peer_sha256=pin(material, "server"),
        timeout_seconds=900, clock=clock,
    )
    peer = PeerSerial(controller, chunk=chunk)
    opens = []

    def open_serial(budget):
        assert isinstance(budget, IOBudget)
        opens.append(budget)
        peer.budget = budget
        clock.now += open_cost
        return peer

    monkeypatch.setattr(SerialDevice, "open", open_serial)

    def start(**overrides):
        options = dict(peer_sha256=pin(material, "client"), timeout_seconds=5, clock=clock)
        options.update(overrides)
        return m.GuestTlsSerial(guest_context, binding, **options)

    return SimpleNamespace(start=start, peer=peer, clock=clock, opens=opens,
                           context=guest_context, binding=binding)


@pytest.mark.parametrize("chunk", [7, 16384])
def test_guest_role_authenticated_bidirectional_exchange_and_hidden_payload(material, monkeypatch, chunk):
    fixture = setup_peer(material, monkeypatch, chunk=chunk)
    payload = {"marker": "SYNTHETIC_GUEST_TLS_" + uuid4().hex}
    with fixture.start() as guest:
        assert guest._endpoint.authenticated and fixture.peer.guest.authenticated
        fixture.peer.replies.append(payload)
        assert guest.receive_message() == payload
        guest.send_message(payload)
        assert fixture.peer.messages == [payload]
        guest.send_message({})
        assert fixture.peer.messages[-1] == {}
        assert payload["marker"].encode() not in b"".join(fixture.peer.writes)
        assert fixture.peer.budget is guest._budget and len(fixture.opens) == 1
    assert guest.closed and fixture.peer.closed


def test_guest_large_frame_and_two_buffered_messages(material, monkeypatch):
    fixture = setup_peer(material, monkeypatch)
    with fixture.start() as guest:
        payload = {"body": "x" * 30000}
        fixture.peer.replies.append(payload)
        assert guest.receive_message() == payload
        guest.send_message(payload)
        assert fixture.peer.messages == [payload]
        for ordinal in (1, 2):
            fixture.peer.guest.queue_message({"ordinal": ordinal})
            fixture.peer.guest.step()
        assert guest.receive_message() == {"ordinal": 1}
        reads = fixture.peer.read_calls
        assert guest.receive_message() == {"ordinal": 2}
        assert fixture.peer.read_calls == reads


def test_guest_open_and_all_messages_share_original_budget(material, monkeypatch):
    fixture = setup_peer(material, monkeypatch, open_cost=2)
    guest = fixture.start()
    assert guest._budget.remaining() == 3
    fixture.clock.now = 4
    guest.send_message({"first": True})
    fixture.clock.now = 5
    with pytest.raises(PipeIOError, match="^deadline$"):
        guest.send_message({"second": True})
    assert guest.closed and fixture.peer.closed
    assert fixture.peer.messages == [{"first": True}]
    assert len(fixture.opens) == 1


def test_guest_late_open_return_is_closed_before_authentication(material, monkeypatch):
    fixture = setup_peer(material, monkeypatch, open_cost=5)
    with pytest.raises(PipeIOError, match="^deadline$"):
        fixture.start()
    assert fixture.peer.closed and fixture.peer.messages == []


@pytest.mark.parametrize("phase", ["handshake", "read", "write"])
def test_guest_late_native_result_is_terminal(material, monkeypatch, phase):
    fixture = setup_peer(material, monkeypatch)

    def expire():
        fixture.clock.now = 5

    if phase == "handshake":
        fixture.peer.on_read = expire
        action = fixture.start
    else:
        guest = fixture.start()
        if phase == "read":
            fixture.peer.replies.append({"fixture": True})
            fixture.peer.on_read = expire
            action = guest.receive_message
        else:
            fixture.peer.on_write = expire

            def action():
                guest.send_message({"fixture": True})

    with pytest.raises(PipeIOError, match="^deadline$"):
        action()
    assert fixture.peer.closed


def test_guest_cancellation_before_next_message_is_terminal(material, monkeypatch):
    fixture = setup_peer(material, monkeypatch)
    stopped = []
    guest = fixture.start(cancelled=lambda: bool(stopped))
    stopped.append(True)
    with pytest.raises(PipeIOError, match="^cancelled$"):
        guest.receive_message()
    assert guest.closed and fixture.peer.closed and len(fixture.opens) == 1


def test_guest_wrong_client_pin_refuses_without_application_delivery(material, monkeypatch):
    fixture = setup_peer(material, monkeypatch)
    with pytest.raises(PrototypeRefused, match="^peer_identity$"):
        fixture.start(peer_sha256="0" * 64)
    assert fixture.peer.closed and fixture.peer.messages == []


def test_guest_insecure_server_context_refuses_before_open(material, monkeypatch):
    fixture = setup_peer(material, monkeypatch)
    fixture.context.num_tickets = 1
    with pytest.raises(PrototypeRefused, match="^configuration$"):
        fixture.start()
    assert fixture.opens == []


@pytest.mark.parametrize("phase", ["handshake", "eof"])
def test_guest_plaintext_or_eof_has_no_fallback(material, monkeypatch, phase):
    fixture = setup_peer(material, monkeypatch)
    if phase == "handshake":
        fixture.peer.raw_reply = b'{"not":"TLS"}\n'
        action = fixture.start
        expected, label = PrototypeRefused, "tls_failure"
    else:
        guest = fixture.start()
        fixture.peer.eof = True
        action = guest.receive_message
        expected, label = PipeIOError, "channel_closed"
    with pytest.raises(expected, match=f"^{label}$"):
        action()
    assert fixture.peer.closed and len(fixture.opens) == 1


def test_guest_failed_write_is_not_replayed(material, monkeypatch):
    fixture = setup_peer(material, monkeypatch)
    guest = fixture.start()
    fixture.peer.write_error = PipeIOError("serial_write")
    before = len(fixture.peer.writes)
    with pytest.raises(PipeIOError, match="^serial_write$"):
        guest.send_message({"no_replay": True})
    assert guest.closed and len(fixture.peer.writes) == before + 1
    with pytest.raises(PipeIOError, match="^closed$"):
        guest.send_message({"no_replay": True})
    assert len(fixture.peer.writes) == before + 1 and len(fixture.opens) == 1


def test_guest_unknown_cleanup_overrides_error_and_cannot_retry_fd_close(material, monkeypatch):
    fixture = setup_peer(material, monkeypatch)
    guest = fixture.start()
    fixture.peer.eof = True
    fixture.peer.unknown_close = True
    with pytest.raises(SerialCleanupUnknown) as failure:
        guest.receive_message()
    assert failure.value.channel is fixture.peer
    assert guest.closed and fixture.peer.close_calls == 1
    with pytest.raises(SerialCleanupUnknown):
        guest.close()
    assert fixture.peer.close_calls == 1


def test_guest_unknown_io_cleanup_does_not_implicitly_close_again(material, monkeypatch):
    fixture = setup_peer(material, monkeypatch)
    guest = fixture.start()
    fixture.peer.read_error = SerialCleanupUnknown(fixture.peer)
    with pytest.raises(SerialCleanupUnknown):
        guest.receive_message()
    assert guest.closed and fixture.peer.close_calls == 0
    with pytest.raises(SerialCleanupUnknown):
        guest.close()
    assert fixture.peer.close_calls == 0


def test_guest_owner_and_reentry_checks_preserve_active_session(material, monkeypatch):
    fixture = setup_peer(material, monkeypatch)
    with fixture.start() as guest:
        with monkeypatch.context() as patch:
            patch.setattr(m.threading, "get_ident", lambda: -1)
            with pytest.raises(PipeIOError, match="^wrong_thread$"):
                guest.close()
        guest._busy = True
        try:
            with pytest.raises(PipeIOError, match="^busy$"):
                guest.close()
        finally:
            guest._busy = False
        assert not guest.closed
        guest.send_message({"still_usable": True})


def test_guest_candidates_excluded_from_actual_inspection_bundle():
    from night_shifts.inspection_bundle import bundle_bytes

    with zipfile.ZipFile(io.BytesIO(bundle_bytes())) as archive:
        names = set(archive.namelist())
    assert "night_shifts/guest/serial_device_io.py" not in names
    assert "night_shifts/guest/bounded_tls_serial.py" not in names
