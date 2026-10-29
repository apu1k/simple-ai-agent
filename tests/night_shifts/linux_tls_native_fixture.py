"""Test-only native Linux PTY/TLS peer; no ttyS0, VM, network or real keys.

The parent owns a new PTY and the exact spawn-process. Only the child's private
opening seam is replaced. Actual GuestTlsSerial, SerialDevice and Linux ABI
calls handle the slave; no production identity or deployment policy is changed.
"""
from __future__ import annotations

import importlib
import json
import multiprocessing
import ssl
import struct
import sys
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

from night_shifts.guest import serial_device_io as serial
from night_shifts.guest.bounded_tls_serial import GuestTlsSerial
from night_shifts.maintenance_tls_prototype import AttemptBinding, OfflineTlsEndpoint, PrototypeRefused
from night_shifts.serial_pipe_io import IOBudget, PipeIOError
from tests.night_shifts.linux_serial_native_fixture import _PtyAPI, _closed, _require, _unique

MODES = ("small", "fragmented", "multi_record", "wrong_client_pin", "wrong_binding", "silent", "cancel")
_ERRORS = frozenset(("peer_identity", "frame_binding", "deadline", "cancelled", "channel_closed",
                     "tls_failure", "serial_read", "serial_write", "serial_poll", "serial_open",
                     "channel_failure", "cleanup_unknown", "configuration", "fixture_failure"))
_RECEIPT_LIMIT = 1024
_TRACE_LIMIT = 128 * 1024
_UNREAPED = []


def decode_receipt(raw):
    try:
        if type(raw) is not bytes or not 0 < len(raw) <= _RECEIPT_LIMIT:
            raise ValueError("size")
        value = json.loads(raw.decode("ascii"), object_pairs_hook=_unique)
        if type(value) is not dict:
            raise ValueError("schema")
        if value == {"state": "ready"} or value == {"state": "authenticated"}:
            return value
        fields = {"state", "authenticated", "received", "error", "released", "restored",
                  "post_auth_polls", "sent_bytes"}
        if (set(value) != fields or value["state"] != "finished"
                or any(type(value[name]) is not bool for name in ("authenticated", "released", "restored"))
                or type(value["received"]) is not int or not 0 <= value["received"] <= 2
                or type(value["post_auth_polls"]) is not int or not 0 <= value["post_auth_polls"] <= 10000
                or type(value["sent_bytes"]) is not int or not 0 <= value["sent_bytes"] <= _TRACE_LIMIT
                or (value["error"] is not None and
                    (type(value["error"]) is not str or value["error"] not in _ERRORS))):
            raise ValueError("schema")
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise RuntimeError("fixture_tls_receipt_invalid") from None
    return value


def encode_receipt(value):
    try:
        raw = json.dumps(value, separators=(",", ":"), sort_keys=True, allow_nan=False).encode("ascii")
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise RuntimeError("fixture_tls_receipt_invalid") from None
    decode_receipt(raw)
    return struct.pack("!I", len(raw)) + raw


def make_context(config, role):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT if role == "controller" else ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = context.maximum_version = ssl.TLSVersion.TLSv1_3
    context.verify_mode = ssl.CERT_REQUIRED
    context.verify_flags |= ssl.VERIFY_X509_STRICT
    context.options |= ssl.OP_NO_TICKET
    if role != "controller":
        context.num_tickets = 0
    context.load_verify_locations(cadata=config["ca"])
    context.load_cert_chain(config[role + "_cert"], config[role + "_key"])
    return context


class NativeStream:
    """Fixture-only nonblocking byte driver for a borrowed master or report fd.

    It never adopts/closes the fd, configures a tty, accepts a runtime command or
    stands in for the production slave. The fixture that acquired it closes it.
    """

    def __init__(self, api, fd, budget, *, fragment=16384, trace=False):
        _require(type(fragment) is int and 1 <= fragment <= 16384, "fixture_fragment")
        self.api, self.fd, self.budget = api, fd, budget
        self.fragment = fragment
        self.trace = trace
        self.incoming, self.outgoing = bytearray(), bytearray()
        self.fragments = 0

    def _record(self, target, data):
        if self.trace:
            _require(len(target) + len(data) <= _TRACE_LIMIT, "fixture_trace_limit")
            target.extend(data)

    def read(self, size):
        _require(type(size) is int and 1 <= size <= 16384, "fixture_read_size")
        while True:
            self.budget.remaining()
            try:
                data = self.api.read(self.fd, size)
            except InterruptedError:
                continue
            except BlockingIOError:
                self.api.wait(self.fd, False, min(0.05, self.budget.remaining()))
                continue
            self.budget.remaining()
            self._record(self.incoming, data)
            return data

    def read_exact(self, size):
        _require(type(size) is int and 1 <= size <= _RECEIPT_LIMIT, "fixture_frame_size")
        result = bytearray()
        while len(result) < size:
            data = self.read(size - len(result))
            _require(bool(data), "fixture_report_eof")
            result.extend(data)
        return bytes(result)

    def write_all(self, data):
        _require(type(data) is bytes and len(data) <= _TRACE_LIMIT, "fixture_write_size")
        offset = 0
        while offset < len(data):
            self.budget.remaining()
            chunk = data[offset:offset + self.fragment]
            try:
                count = self.api.write(self.fd, chunk)
            except InterruptedError:
                continue
            except BlockingIOError:
                self.api.wait(self.fd, True, min(0.05, self.budget.remaining()))
                continue
            self.budget.remaining()
            _require(type(count) is int and 0 < count <= len(chunk), "fixture_write_count")
            self._record(self.outgoing, chunk[:count])
            self.fragments += 1
            offset += count


class Mailbox:
    """Own framing on a nonblocking test-only pipe, not Connection.recv/pickle.

    Incremental prefix/body reads and writes have actual I/O deadlines too. The
    multiprocessing connection supplies fd ownership only, not a wire codec.
    """

    def __init__(self, stream):
        self.stream = stream
        self.count = 0

    def send(self, value):
        self.count += 1
        _require(self.count <= 3, "fixture_report_count")
        self.stream.write_all(encode_receipt(value))

    def receive(self, state):
        self.count += 1
        _require(self.count <= 3, "fixture_report_count")
        size, = struct.unpack("!I", self.stream.read_exact(4))
        _require(0 < size <= _RECEIPT_LIMIT, "fixture_report_size")
        value = decode_receipt(self.stream.read_exact(size))
        _require(value["state"] == state, "fixture_report_order")
        return value


class Controller:
    def __init__(self, context, binding, stream, pin):
        self.stream, self.budget = stream, stream.budget
        self.endpoint = OfflineTlsEndpoint(context, binding, role="controller", peer_sha256=pin,
                                           timeout_seconds=self.budget.remaining())

    def drain(self):
        wrote = False
        while self.endpoint.pending_ciphertext:
            self.budget.remaining()
            self.stream.write_all(self.endpoint.take_ciphertext())
            wrote = True
        self.budget.remaining()
        return wrote

    def read(self):
        data = self.stream.read(16384)
        if not data:
            raise PipeIOError("channel_closed")
        self.endpoint.feed_ciphertext(data)
        self.budget.remaining()

    def handshake(self):
        while not self.endpoint.authenticated:
            self.budget.remaining()
            self.endpoint.step()
            self.drain()
            if not self.endpoint.authenticated:
                self.read()
        self.budget.remaining()

    def send(self, payload):
        self.endpoint.queue_message(payload)
        while True:
            self.budget.remaining()
            self.endpoint.step()
            wrote = self.drain()
            if not self.endpoint.write_pending:
                return
            if not wrote:
                self.read()

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


def _guest_main(config, sender):
    observer = api = guest = None
    channels = []
    report = dict(state="finished", authenticated=False, received=0, error=None,
                  released=False, restored=False, post_auth_polls=0, sent_bytes=0)
    polls_at_auth = None
    mailbox = None
    try:
        native = serial._Linux()
        native.os.set_blocking(sender.fileno(), False)
        mailbox = Mailbox(NativeStream(native, sender.fileno(), IOBudget(8)))
        context = make_context(config, "guest")
        observer = native.os.open(config["path"], native.os.O_RDWR | native.os.O_NOCTTY
                                  | native.os.O_NONBLOCK | native.os.O_CLOEXEC | native.os.O_NOFOLLOW)
        info = native.os.fstat(observer)
        _require((info.st_dev, info.st_ino, info.st_rdev) == config["identity"], "guest_pty_identity")
        api = _PtyAPI(config["path"], observer)
        original = api.attributes(observer)

        def open_serial(budget):
            _require(not channels, "unexpected_reopen")
            channel = serial.SerialDevice._open(budget, api)
            channels.append(channel)  # Retain ownership if the ready send fails.
            mailbox.send({"state": "ready"})
            return channel

        with patch.object(serial.SerialDevice, "open", side_effect=open_serial):
            guest = GuestTlsSerial(
                context, AttemptBinding(config["attempt"], config["guest_vm"]),
                peer_sha256=config["client_pin"], timeout_seconds=1.5 if config["mode"] == "silent" else 5,
                cancelled=lambda: api.cancelled,
            )
            report["authenticated"] = guest._endpoint.authenticated
            polls_at_auth = api.polls
            mailbox.send({"state": "authenticated"})
            if config["mode"] in ("silent", "cancel"):
                api.cancel_after_poll = config["mode"] == "cancel"
                guest.receive_message()
                raise AssertionError("unexpected_application_delivery")
            first = guest.receive_message()
            report["received"] += 1
            _require(first == config["payload"], "first_payload")
            guest.send_message(first)
            second = guest.receive_message()
            report["received"] += 1
            _require(second == {"ordinal": 2}, "second_payload")
            guest.send_message(second)
    except (PipeIOError, PrototypeRefused) as error:
        report["error"] = str(error) if str(error) in _ERRORS else "fixture_failure"
    except BaseException:
        report["error"] = "fixture_failure"
    finally:
        try:
            if guest is not None:
                guest.close()
            for channel in channels:
                if channel.cleanup_unknown:
                    raise RuntimeError("cleanup_unknown")
                channel.close()
                _require(channel.closed and channel._fd is None, "guest_fd_detached")
            if api is not None:
                if api.fd is not None:
                    _closed(api.os, api.fd)
                report["sent_bytes"] = len(api.accepted)
                report["post_auth_polls"] = 0 if polls_at_auth is None else api.polls - polls_at_auth
                report["restored"] = api.attributes(observer) == original
            if observer is not None:
                native.os.close(observer)
                old_observer, observer = observer, None
                _closed(native.os, old_observer)
            report["released"] = bool(channels) and report["restored"]
        except BaseException:
            report["error"] = "cleanup_unknown"
            report["released"] = False
        try:
            if mailbox is not None:
                # Final local reporting is allowed after session expiry; it has
                # its own original finite report budget, never a serial retry.
                mailbox.send(report)
        finally:
            sender.close()
        # An unclosed observer, if any, is reclaimed on exact process exit.
        # It must never be reported as a successful explicit release.


def _reap(peer):
    process = peer.process
    process.join(2)
    peer.forced = process.is_alive()
    if peer.forced:
        process.terminate()
        process.join(2)
    if process.is_alive():
        process.kill()
        process.join(2)
    if process.is_alive():
        _UNREAPED.append(process)
        raise RuntimeError("fixture_tls_process_cleanup_unknown")
    peer.exitcode = process.exitcode
    peer.reaped = True
    process.close()
    if peer.forced:
        raise RuntimeError("fixture_tls_required_termination")
    _require(peer.exitcode == 0, "fixture_tls_process_failed")


@contextmanager
def native_peer(config):
    if sys.platform != "linux":
        raise RuntimeError("linux_required")
    if config.get("mode") not in MODES:
        raise ValueError("unknown_tls_fixture_case")
    api = serial._Linux()
    pty = importlib.import_module("pty")
    master, observer = pty.openpty()
    receiver = sender = process = None
    started = False
    try:
        for fd in (master, observer):
            api.os.set_blocking(fd, False)
            api.os.set_inheritable(fd, False)
        path = api.os.ttyname(observer)
        _require(path.startswith("/dev/pts/") and path.rsplit("/", 1)[1].isdigit(), "parent_pty_path")
        original = api.attributes(observer)
        info = api.os.fstat(observer)
        config = dict(config, path=path, identity=(info.st_dev, info.st_ino, info.st_rdev))
        context = multiprocessing.get_context("spawn")
        receiver, sender = context.Pipe(duplex=False)
        api.os.set_blocking(receiver.fileno(), False)
        process = context.Process(target=_guest_main, args=(config, sender))
        budget = IOBudget(10)
        peer = SimpleNamespace(process=process, reaped=False, forced=False, exitcode=None,
                               stream=NativeStream(api, master, budget, trace=True,
                                                   fragment=97 if config["mode"] == "fragmented" else 16384))
        mailbox = Mailbox(NativeStream(api, receiver.fileno(), budget))
        peer.receive_report = mailbox.receive
        peer.attributes_restored = lambda: api.attributes(observer) == original
        process.start()
        started = True
        sender.close()
        mailbox.receive("ready")  # Slave raw configuration precedes ClientHello.
        yield peer
    finally:
        try:
            if started:
                _reap(peer)
            elif process is not None:
                process.close()
        finally:
            try:
                if receiver is not None:
                    receiver.close()
                if sender is not None:
                    sender.close()
            finally:
                try:
                    api.os.close(observer)
                    _closed(api.os, observer)
                finally:
                    api.os.close(master)
                    _closed(api.os, master)
