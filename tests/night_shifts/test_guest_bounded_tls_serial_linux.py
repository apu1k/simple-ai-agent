"""Real guest adapter over native Linux PTYs; portable checks are NOT native.

Synthetic temporary certificate fixture only. No Hyper-V, network listener,
existing serial device, production key discovery or deployment activation.
"""
from __future__ import annotations

import json
import ssl
import struct
import sys
from collections import deque
from types import SimpleNamespace
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization

from night_shifts.maintenance_tls_prototype import AttemptBinding
from night_shifts.serial_pipe_io import IOBudget, PipeIOError
from tests.night_shifts import linux_tls_native_fixture as fixture
from tests.night_shifts.test_maintenance_tls_prototype import material as material, pin


def config_for(material, mode):
    binding = AttemptBinding(uuid4().hex, str(uuid4()))
    return binding, dict(
        mode=mode, attempt=binding.attempt_id,
        guest_vm=str(uuid4()) if mode == "wrong_binding" else binding.vm_id,
        client_pin=pin(material, "other_client" if mode == "wrong_client_pin" else "client"),
        ca=material["ca"].public_bytes(serialization.Encoding.PEM).decode("ascii"),
        guest_cert=str(material["server"][0]), guest_key=str(material["server"][1]),
        controller_cert=str(material["client"][0]), controller_key=str(material["client"][1]),
        payload={"marker": "SYNTHETIC_LINUX_TLS_" + uuid4().hex,
                 "body": "x" * (30000 if mode == "multi_record" else 32)},
    )


@pytest.mark.skipif(sys.platform != "linux", reason="native Linux disposable PTY/TLS required")
@pytest.mark.parametrize("mode", fixture.MODES)
def test_native_guest_tls_over_exact_owned_linux_pty(material, mode):
    binding, config = config_for(material, mode)
    with fixture.native_peer(config) as peer:
        controller = fixture.Controller(fixture.make_context(config, "controller"), binding,
                                        peer.stream, pin(material, "server"))
        try:
            controller.handshake()
            assert controller.endpoint.authenticated
            if mode == "wrong_client_pin":
                report = peer.receive_report("finished")
                assert report["authenticated"] is False
                assert report["received"] == 0 and report["error"] == "peer_identity"
            else:
                peer.receive_report("authenticated")
                if mode in ("silent", "cancel"):
                    report = peer.receive_report("finished")
                    assert report["error"] == ("deadline" if mode == "silent" else "cancelled")
                    assert report["received"] == 0 and report["post_auth_polls"] > 0
                else:
                    controller.send(config["payload"])
                    if mode == "wrong_binding":
                        report = peer.receive_report("finished")
                        assert report["received"] == 0 and report["error"] == "frame_binding"
                    else:
                        assert controller.receive() == config["payload"]
                        controller.send({"ordinal": 2})
                        assert controller.receive() == {"ordinal": 2}
                        report = peer.receive_report("finished")
                        assert report["received"] == 2 and report["error"] is None
                        assert report["sent_bytes"] > 0
                assert report["authenticated"] is True
            assert report["released"] is True and report["restored"] is True
            assert peer.attributes_restored()  # Independent parent-side readback.
            marker = config["payload"]["marker"].encode("ascii")
            assert marker not in peer.stream.incoming and marker not in peer.stream.outgoing
            if mode == "fragmented":
                assert peer.stream.fragments > 10
        finally:
            controller.endpoint.close()
    assert peer.reaped and not peer.forced and peer.exitcode == 0


def finished(**changes):
    report = dict(state="finished", authenticated=True, received=2, error=None, released=True,
                  restored=True, post_auth_polls=1, sent_bytes=100)
    report.update(changes)
    return report


@pytest.mark.parametrize("report", [{"state": "ready"}, {"state": "authenticated"}, finished(),
                                   finished(error="deadline", received=0),
                                   finished(error="cleanup_unknown", released=False, restored=False)],
                         ids=["ready", "authenticated", "finished", "deadline", "unknown-cleanup"])
def test_report_codec_preserves_fixed_status_without_promoting_failures(report):
    frame = fixture.encode_receipt(report)
    size, = struct.unpack("!I", frame[:4])
    assert 0 < size <= 1024 and size == len(frame) - 4
    assert fixture.decode_receipt(frame[4:]) == report


@pytest.mark.parametrize("fault", [
    "extra", "duplicate", "phase", "missing", "bool_type", "received_bool", "received_limit",
    "polls_bool", "polls_limit", "bytes_bool", "bytes_limit", "error_payload", "encoding",
    "oversize", "array", "nonbytes",
])
def test_report_codec_refuses_unbounded_ambiguous_or_raw_data(fault):
    value = finished()
    if fault == "extra":
        value["path"] = "not_an_allowed_field"
    elif fault == "phase":
        value["state"] = "unexpected"
    elif fault == "missing":
        del value["released"]
    elif fault == "bool_type":
        value["authenticated"] = 1
    elif fault == "received_bool":
        value["received"] = True
    elif fault == "received_limit":
        value["received"] = 3
    elif fault == "polls_bool":
        value["post_auth_polls"] = False
    elif fault == "polls_limit":
        value["post_auth_polls"] = 10001
    elif fault == "bytes_bool":
        value["sent_bytes"] = True
    elif fault == "bytes_limit":
        value["sent_bytes"] = 128 * 1024 + 1
    elif fault == "error_payload":
        value["error"] = "PRIVATE_ERROR_CANARY"
    raw = json.dumps(value).encode("ascii")
    if fault == "duplicate":
        raw = b'{"state":"finished",' + raw[1:]
    elif fault == "encoding":
        raw = b"\xff"
    elif fault == "oversize":
        raw = b" " * 1025
    elif fault == "array":
        raw = b"[]"
    elif fault == "nonbytes":
        raw = "not_bytes"
    with pytest.raises(RuntimeError, match="^fixture_tls_receipt_invalid$") as failure:
        fixture.decode_receipt(raw)
    assert "PRIVATE_ERROR_CANARY" not in str(failure.value)


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class ByteAPI:
    """Portable syscall model for fixture framing only, not a Linux pass."""

    def __init__(self, clock, data=b""):
        self.clock, self.data = clock, bytearray(data)
        self.written = bytearray()
        self.counts = deque()
        self.waits = 0

    def read(self, fd, size):
        assert fd == 7
        if not self.data:
            raise BlockingIOError()
        size = min(size, 3)  # Fragment even the four-byte prefix.
        result = bytes(self.data[:size])
        del self.data[:size]
        return result

    def write(self, fd, data):
        assert fd == 7
        count = self.counts.popleft() if self.counts else len(data)
        if isinstance(count, BaseException):
            raise count
        if type(count) is int and 0 < count <= len(data):
            self.written.extend(data[:count])
        return count

    def wait(self, fd, writing, seconds):
        assert fd == 7 and type(writing) is bool and 0 < seconds <= 0.05
        self.waits += 1
        self.clock.now += seconds


def stream_for(data=b"", *, timeout=0.12):
    clock = Clock()
    api = ByteAPI(clock, data)
    return fixture.NativeStream(api, 7, IOBudget(timeout, clock=clock), trace=True), api


def test_mailbox_handles_fragmented_prefix_body_and_fixed_sequence():
    stream, api = stream_for(fixture.encode_receipt({"state": "ready"})
                             + fixture.encode_receipt({"state": "authenticated"})
                             + fixture.encode_receipt(finished()))
    mailbox = fixture.Mailbox(stream)
    assert mailbox.receive("ready") == {"state": "ready"}
    assert mailbox.receive("authenticated") == {"state": "authenticated"}
    assert mailbox.receive("finished") == finished()
    assert not api.data and api.waits == 0
    with pytest.raises(AssertionError, match="^fixture_report_count$"):
        mailbox.receive("finished")


@pytest.mark.parametrize("partial", [b"", b"\x00\x00", struct.pack("!I", 20) + b"{"],
                         ids=["silent", "partial-prefix", "partial-body"])
def test_report_io_has_deadline_even_when_a_prefix_or_body_is_incomplete(partial):
    stream, api = stream_for(partial)
    with pytest.raises(PipeIOError, match="^deadline$"):
        fixture.Mailbox(stream).receive("ready")
    assert api.waits > 0 and stream.budget._deadline == pytest.approx(0.12)


@pytest.mark.parametrize("size", [0, 1025, 0xFFFFFFFF])
def test_mailbox_refuses_length_before_reading_body(size):
    stream, api = stream_for(struct.pack("!I", size))
    with pytest.raises(AssertionError, match="^fixture_report_size$"):
        fixture.Mailbox(stream).receive("ready")
    assert api.waits == 0


def test_mailbox_refuses_out_of_order_phase():
    stream, _ = stream_for(fixture.encode_receipt({"state": "authenticated"}))
    with pytest.raises(AssertionError, match="^fixture_report_order$"):
        fixture.Mailbox(stream).receive("ready")


def test_report_writes_retry_only_remaining_prefix_under_original_budget():
    stream, api = stream_for()
    api.counts.extend([2, InterruptedError(), BlockingIOError(), 1])
    mailbox = fixture.Mailbox(stream)
    mailbox.send({"state": "ready"})
    assert bytes(api.written) == fixture.encode_receipt({"state": "ready"})
    assert api.waits == 1 and stream.budget._deadline == pytest.approx(0.12)
    assert stream.outgoing == api.written


class OwnedProcess:
    def __init__(self, outcome):
        self.outcome = outcome
        self.alive = outcome != "normal"
        self.calls = []
        self.exitcode = 0 if outcome == "normal" else -15

    def join(self, seconds):
        self.calls.append(("join", seconds))

    def is_alive(self):
        return self.alive

    def terminate(self):
        self.calls.append(("terminate",))
        if self.outcome == "terminate":
            self.alive = False

    def kill(self):
        self.calls.append(("kill",))
        if self.outcome == "kill":
            self.alive = False

    def close(self):
        assert not self.alive
        self.calls.append(("close",))


@pytest.mark.parametrize("outcome", ["normal", "terminate", "kill", "unknown"])
def test_exact_process_reaping_never_converts_forced_or_unknown_exit_into_success(outcome):
    process = OwnedProcess(outcome)
    peer = SimpleNamespace(process=process, forced=False, reaped=False, exitcode=None)
    if outcome == "normal":
        fixture._reap(peer)
        assert peer.reaped and not peer.forced and peer.exitcode == 0
    else:
        label = "fixture_tls_process_cleanup_unknown" if outcome == "unknown" else "fixture_tls_required_termination"
        try:
            with pytest.raises(RuntimeError, match=f"^{label}$"):
                fixture._reap(peer)
            assert peer.forced
            if outcome == "unknown":
                assert fixture._UNREAPED[-1] is process
                assert not peer.reaped and ("close",) not in process.calls
            else:
                assert peer.reaped and process.calls[-1] == ("close",)
        finally:
            if outcome == "unknown" and process in fixture._UNREAPED:
                fixture._UNREAPED.remove(process)  # Model object, not a live process.


@pytest.mark.parametrize("role", ["controller", "guest"])
def test_synthetic_contexts_keep_strict_tls_settings(material, role):
    binding, config = config_for(material, "small")
    context = fixture.make_context(config, role)
    assert context.minimum_version == context.maximum_version == ssl.TLSVersion.TLSv1_3
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.verify_flags & ssl.VERIFY_X509_STRICT and context.options & ssl.OP_NO_TICKET
    assert context.keylog_filename is None
    if role == "guest":
        assert context.num_tickets == 0
    else:
        assert context.check_hostname
    assert binding.vm_id == config["guest_vm"]


def test_native_fixture_refuses_non_linux_before_any_device_or_process(monkeypatch):
    monkeypatch.setattr(fixture.sys, "platform", "win32")
    with pytest.raises(RuntimeError, match="^linux_required$"):
        with fixture.native_peer({"mode": "small"}):
            pytest.fail("unreachable")
