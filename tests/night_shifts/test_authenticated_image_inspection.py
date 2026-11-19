"""Fixed inspection contract with synthetic disks and TLS keys only."""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from queue import Empty, Queue
from typing import Any

import pytest

from night_shifts import authenticated_image_inspection as inspection
from night_shifts.guest import finalize_image_copy as guest
from night_shifts.guest.serial_device_io import SerialDevice
from night_shifts.inspection_bundle import FILES
from night_shifts.maintenance_tls_prototype import AttemptBinding, PrototypeRefused
from night_shifts.serial_pipe_io import BoundedPipe, IOBudget, PipeIOError
from tests.night_shifts.test_bounded_tls_pipe import material as material, setup_peer
from tests.night_shifts.test_maintenance_tls_prototype import contexts, pin

_ID = 'a' * 32
_VM = '44fcedfc-9b00-4723-b94d-bcf067f731dc'
_REQUEST = {'version': 1, 'action': 'inspect_image_copy'}
_FAILED = {'version': 1, 'status': 'inspection_not_verified'}
_PATH = 'etc/night-shift-diagnostic-027/prepared.json'
_DIAGNOSTICS = {_PATH: {'kind': 'file', 'sha256': 'f' * 64}}
_SUCCESS = {'version': 1, 'status': 'success', 'audit': 'inspection_only',
            'unmounted_read_only': True, 'diagnostics': _DIAGNOSTICS}


class Channel:
    def __init__(self, incoming: dict[str, Any], binding: AttemptBinding | None = None):
        self.incoming = incoming
        self.sent: list[dict[str, Any]] = []
        self.reads = 0
        self.binding = binding or AttemptBinding(_ID, _VM)

    def send_message(self, payload: dict[str, Any]) -> None:
        self.sent.append(payload)

    def receive_message(self) -> dict[str, Any]:
        self.reads += 1
        assert self.reads == 1
        return self.incoming


def local_request(**overrides):
    return {'version': 1, 'id': _ID, 'mode': 'inspect', 'artifacts': {},
            'payload': {'bootstrap': 'b' * 64, 'unit': 'c' * 64}, **overrides}


def unexpected(*_args):
    pytest.fail('unexpected disk operation')


@pytest.mark.parametrize('request_message', [
    {}, {'version': True, 'action': 'inspect_image_copy'},
    {'version': 1, 'action': 'finalize'}, {**_REQUEST, 'path': '/dev/sda'},
])
def test_wrong_message_never_reaches_recovery_or_disk(monkeypatch, request_message):
    monkeypatch.setattr(guest, 'recovery_request', unexpected)
    monkeypatch.setattr(guest, '_maintain_copy', unexpected)
    channel = Channel(request_message)
    with pytest.raises(inspection.InspectionRefused, match='^invalid_inspection_request$'):
        inspection.serve_inspection_once(channel)
    assert channel.sent == []


@pytest.mark.parametrize('overrides', [
    {'id': 'd' * 32}, {'mode': 'finalize'}, {'artifacts': {_PATH: 'f' * 64}},
])
def test_media_must_agree_with_tls_attempt_and_be_inspect_only(monkeypatch, overrides):
    monkeypatch.setattr(guest, 'recovery_request', lambda: local_request(**overrides))
    monkeypatch.setattr(guest, '_maintain_copy', unexpected)
    channel = Channel(_REQUEST)
    assert inspection.serve_inspection_once(channel) is False
    assert channel.sent == [_FAILED]


def test_guest_never_exports_arbitrary_link_targets(monkeypatch):
    known, unknown = guest.DEBUG_LINKS
    secret = 'PRIVATE_CANARY'
    link = {'kind': 'link', 'target': '/usr/lib/systemd/system/debug-shell.service'}
    monkeypatch.setattr(guest, 'recovery_request', local_request)
    monkeypatch.setattr(guest, '_maintain_copy', lambda _: {
        **_SUCCESS, 'diagnostics': {**_DIAGNOSTICS, known: link,
                                    unknown: {'kind': 'link', 'target': secret}},
    })
    channel = Channel(_REQUEST)
    assert inspection.serve_inspection_once(channel) is True
    assert secret not in json.dumps(channel.sent)
    assert channel.sent == [{**_SUCCESS, 'diagnostics': {
        **_DIAGNOSTICS, known: link, unknown: {'kind': 'unreviewed'},
    }}]


@pytest.mark.parametrize('receipt', [
    {}, {**_SUCCESS, 'version': True}, {**_SUCCESS, 'unmounted_read_only': 1},
    {**_SUCCESS, 'unmounted_read_only': False}, {**_SUCCESS, 'audit': 'pass'},
    {**_SUCCESS, 'vm_removed': True}, {**_SUCCESS, 'diagnostics': {'root/.ssh/private': {'kind': 'unreviewed'}}},
    {**_SUCCESS, 'diagnostics': {_PATH: {'kind': 'file', 'sha256': 'F' * 64}}},
    {**_SUCCESS, 'diagnostics': {guest.DEBUG_LINKS[0]: {'kind': 'link', 'target': 'PRIVATE_CANARY'}}},
    {**_SUCCESS, 'diagnostics': {f'root/nsdiag027_{n}': {'kind': 'unreviewed'} for n in range(65)}},
])
def test_controller_rejects_nonconforming_receipt_without_replaying(receipt):
    channel = Channel(receipt)
    with pytest.raises(inspection.InspectionRefused, match='^invalid_inspection_receipt$'):
        inspection.inspect_once(channel)
    assert channel.reads == 1 and channel.sent == [_REQUEST]


def test_guest_unmount_failure_is_fixed_label(monkeypatch):
    monkeypatch.setattr(guest, 'recovery_request', local_request)
    monkeypatch.setattr(guest, '_maintain_copy', lambda _: {
        **_SUCCESS, 'unmounted_read_only': False, 'error': 'PRIVATE_CANARY',
    })
    channel = Channel(_REQUEST)
    assert inspection.serve_inspection_once(channel) is False
    assert channel.sent == [_FAILED]
    with pytest.raises(inspection.InspectionRefused, match='^inspection_not_verified$'):
        inspection.inspect_once(Channel(channel.sent[0]))


def test_transport_failure_cannot_dispatch_or_retry(monkeypatch):
    class Disconnected(Channel):
        def receive_message(self):
            self.reads += 1
            raise PipeIOError('channel_closed')

    monkeypatch.setattr(guest, 'recovery_request', unexpected)
    incoming = Disconnected({})
    with pytest.raises(PipeIOError, match='^channel_closed$'):
        inspection.serve_inspection_once(incoming)
    assert incoming.reads == 1 and incoming.sent == []
    outgoing = Disconnected({})
    with pytest.raises(PipeIOError, match='^channel_closed$'):
        inspection.inspect_once(outgoing)
    assert outgoing.reads == 1 and outgoing.sent == [_REQUEST]


def test_fixed_exchange_over_real_mutual_tls(material, monkeypatch):
    fixture = setup_peer(material, monkeypatch, chunk=97)
    seen = []
    monkeypatch.setattr(guest, 'recovery_request', lambda: local_request(id=fixture.binding.attempt_id))

    def read_only(local):
        seen.append(local)
        return _SUCCESS

    monkeypatch.setattr(guest, '_maintain_copy', read_only)

    def serve():
        if fixture.pipe.messages and not seen:
            remote = Channel(fixture.pipe.messages[0], fixture.binding)
            assert inspection.serve_inspection_once(remote)
            fixture.pipe.replies.extend(remote.sent)

    fixture.pipe.on_write = serve
    with fixture.start() as channel:
        assert inspection.inspect_once(channel) == _DIAGNOSTICS
        assert len(seen) == 1 and seen[0]['mode'] == 'inspect'
        assert fixture.pipe.messages == [_REQUEST]
    assert fixture.pipe.closed and len(fixture.opens) == 1
    assert b'inspect_image_copy' not in b''.join(fixture.pipe.writes)


@pytest.mark.parametrize('fault', ['wrong_layout', 'already_mounted', 'unknown_unmount', None])
def test_inspection_disk_commands_require_layout_and_observed_unmount(tmp_path: Path, monkeypatch, fault):
    order = []
    root = tmp_path / 'mountpoint'
    monkeypatch.setattr(guest, 'ROOT', root)
    monkeypatch.setattr(guest, 'initialized', lambda _: None)
    monkeypatch.setattr(guest, 'inventory', lambda _: _DIAGNOSTICS)
    monkeypatch.setattr(guest, 'prepare', unexpected)
    monkeypatch.setattr(guest, 'finalize', unexpected)
    disk = {'type': 'disk', 'path': '/dev/sda', 'size': 20 * 1024**3,
            'children': [{'type': 'part', 'path': '/dev/sda1', 'fstype': 'vfat'},
                         {'type': 'part', 'path': '/dev/sda2', 'fstype': 'ext4'}]}
    if fault == 'wrong_layout':
        disk['path'] = '/dev/sdz'

    def command(executable, *argv):
        name = executable.rsplit('/', 1)[-1]
        order.append(name)
        if name == 'lsblk':
            return json.dumps({'blockdevices': [disk]})
        if name == 'findmnt':
            return '/dev/sda' if fault == 'already_mounted' else '{}'
        if name == 'mount':
            assert argv == ('-t', 'ext4', '-o', 'ro,noload,nodev,nosuid,noexec', '/dev/sda2', str(root))
        elif name == 'umount':
            if fault == 'unknown_unmount':
                raise RuntimeError('PRIVATE_CANARY')
        elif name == 'blockdev':
            assert argv[0] in ('--setro', '--getro')
            return '1\n'
        else:
            unexpected()
        return ''

    monkeypatch.setattr(guest, 'command', command)
    receipt = guest._maintain_copy(local_request())
    assert receipt['unmounted_read_only'] is (fault is None)
    assert receipt['status'] == ('success' if fault is None else 'failed')
    if fault == 'wrong_layout':
        assert order == ['lsblk'] and not root.exists()
    elif fault == 'already_mounted':
        assert order == ['lsblk', 'findmnt'] and not root.exists()
    else:
        assert order.index('mount') < order.index('umount')
        if fault is None:
            assert order[-1] == 'findmnt'
    assert 'PRIVATE_CANARY' not in json.dumps(receipt)


class ByteLink:
    """Fragmented full-duplex test link; real TLS adapters own opposite ends."""

    def __init__(self, incoming: Queue[bytes], outgoing: Queue[bytes]):
        self.incoming, self.outgoing = incoming, outgoing
        self.budget: IOBudget
        self.tail = b''
        self.closes = 0
        self.writes: list[bytes] = []

    def read(self, size):
        if not self.tail:
            try:
                self.tail = self.incoming.get(timeout=self.budget.remaining())
            except Empty:
                raise PipeIOError('deadline') from None
        chunk = min(size, 97)
        result, self.tail = self.tail[:chunk], self.tail[chunk:]
        return result

    def write_all(self, data):
        self.budget.remaining()
        self.writes.append(data)
        self.outgoing.put_nowait(data)

    def close(self):
        self.closes += 1
        self.outgoing.put_nowait(b'')


@pytest.mark.parametrize('fault', [None, 'wrong_guest_copy', 'wrong_client_pin'])
def test_both_real_adapters_under_one_owning_thread_each(material, monkeypatch, fault):
    c2g: Queue[bytes] = Queue(maxsize=32)
    g2c: Queue[bytes] = Queue(maxsize=32)
    client, server = ByteLink(g2c, c2g), ByteLink(c2g, g2c)
    client_context, server_context = contexts(material)
    binding = AttemptBinding(_ID, _VM)
    opens: list[str] = []
    disk_operations = []
    deadline = time.monotonic() + 4

    def pipe_open(path, budget):
        assert path == rf'\\.\pipe\night-shift-{_ID}-com1'
        assert 0 < budget.remaining() <= 4
        opens.append('client')
        client.budget = budget
        return client

    def serial_open(budget):
        assert 0 < budget.remaining() <= 4
        opens.append('guest')
        server.budget = budget
        return server

    def inspect_disk(local):
        disk_operations.append(local)
        return _SUCCESS

    def cancelled():
        return False

    monkeypatch.setattr(BoundedPipe, 'connect', staticmethod(pipe_open))
    monkeypatch.setattr(SerialDevice, 'open', staticmethod(serial_open))
    monkeypatch.setattr(guest, '_maintain_copy', inspect_disk)
    monkeypatch.setattr(guest, 'recovery_request', lambda: local_request(
        id='b' * 32 if fault == 'wrong_guest_copy' else _ID,
    ))
    with ThreadPoolExecutor(max_workers=1) as executor:
        worker = executor.submit(
            inspection.connect_and_serve_once, server_context, binding,
            peer_sha256='0' * 64 if fault == 'wrong_client_pin' else pin(material, 'client'),
            deadline=deadline, cancelled=cancelled,
        )

        def controller():
            return inspection.connect_and_inspect_once(
                client_context, binding, peer_sha256=pin(material, 'server'),
                deadline=deadline, cancelled=cancelled,
            )

        if fault == 'wrong_client_pin':
            with pytest.raises((PipeIOError, PrototypeRefused)):
                controller()
            with pytest.raises(PrototypeRefused, match='^peer_identity$'):
                worker.result(timeout=5)
        elif fault == 'wrong_guest_copy':
            with pytest.raises(inspection.InspectionRefused, match='^inspection_not_verified$'):
                controller()
            assert worker.result(timeout=5) is False
        else:
            assert controller() == _DIAGNOSTICS
            assert worker.result(timeout=5) is True
    assert sorted(opens) == ['client', 'guest']
    assert client.closes == server.closes == 1
    assert len(disk_operations) == (1 if fault is None else 0)
    assert b'inspect_image_copy' not in b''.join(client.writes + server.writes)


@pytest.mark.parametrize('deadline, expected_error', [
    (-1, PipeIOError), (float('nan'), ValueError), (True, ValueError),
])
def test_bad_or_expired_original_deadline_never_opens_transport(material, monkeypatch, deadline, expected_error):
    client, server = contexts(material)
    binding = AttemptBinding(_ID, _VM)
    monkeypatch.setattr(BoundedPipe, 'connect', unexpected)
    monkeypatch.setattr(SerialDevice, 'open', unexpected)
    for connect, context, role in (
        (inspection.connect_and_inspect_once, client, 'server'),
        (inspection.connect_and_serve_once, server, 'client'),
    ):
        with pytest.raises(expected_error, match=r'^(invalid_)?deadline$'):
            connect(context, binding, peer_sha256=pin(material, role), deadline=deadline, cancelled=lambda: False)


def test_authenticated_exchange_is_not_deployed_by_plaintext_bundle():
    assert 'authenticated_image_inspection.py' not in FILES
    assert 'guest/bounded_tls_serial.py' not in FILES
    assert 'bounded_tls_pipe.py' not in FILES
