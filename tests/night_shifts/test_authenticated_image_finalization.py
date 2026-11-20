"""Simulated disk/byte link with real pinned TLS; no Hyper-V or Linux mounts."""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from queue import Queue

import pytest

from night_shifts import authenticated_image_finalization as finalization
from night_shifts import authenticated_image_inspection as inspection
from night_shifts.guest import finalize_image_copy as guest
from night_shifts.guest.serial_device_io import SerialDevice
from night_shifts.maintenance_credentials_prototype import CredentialPrototypeRefused, PublicBootstrapLatch
from night_shifts.maintenance_tls_prototype import FINALIZATION_OPERATION, AttemptBinding, PrototypeRefused
from night_shifts.serial_pipe_io import BoundedPipe, PipeIOError
from tests.night_shifts.test_authenticated_image_inspection import ByteLink, Channel
from tests.night_shifts.test_bounded_tls_pipe import material as material
from tests.night_shifts.test_maintenance_tls_prototype import contexts, pin

_ID = 'a' * 32
_VM = '44fcedfc-9b00-4723-b94d-bcf067f731dc'
_BINDING = AttemptBinding(_ID, _VM, FINALIZATION_OPERATION)
_INSPECTION = AttemptBinding(_ID, _VM)
_PATH = 'etc/night-shift-diagnostic-027/prepared.json'
_FAILED = {'version': 1, 'status': 'finalization_not_verified'}


def local_request(**overrides):
    return {'version': 1, 'id': _ID, 'mode': 'finalize', 'artifacts': {_PATH: 'f' * 64},
            'payload': {'bootstrap': 'b' * 64, 'unit': 'c' * 64}, **overrides}


def local_receipt(**overrides):
    return {'version': 1, 'id': _ID, 'mode': 'finalize', 'status': 'success', 'audit': 'pass',
            'unmounted_read_only': True, **overrides}


def grant():
    return {'version': 1, 'action': FINALIZATION_OPERATION,
            'request_sha256': finalization.request_digest(local_request(), _BINDING)}


def unexpected(*args, **kwargs):
    pytest.fail('unexpected device or transport operation')


def test_operation_boundary_has_no_inspection_downgrade(monkeypatch):
    monkeypatch.setattr(guest, '_maintain_copy', unexpected)
    channel = Channel(grant(), _INSPECTION)
    with pytest.raises(finalization.FinalizationRefused, match='invalid_finalization_binding'):
        finalization.serve_finalization_once(channel, check_write_window=unexpected)
    assert channel.reads == 0
    channel = Channel({'version': 1, 'action': 'inspect_image_copy'}, _BINDING)
    with pytest.raises(inspection.InspectionRefused, match='invalid_inspection_request'):
        inspection.serve_inspection_once(channel)
    assert channel.reads == 0
    with pytest.raises(CredentialPrototypeRefused):
        PublicBootstrapLatch(_BINDING)


@pytest.mark.parametrize('overrides', [
    {'version': True}, {'action': 'inspect_image_copy'}, {'path': '/dev/sda'},
    {'request_sha256': 'A' * 64}, {'profile': {}},
])
def test_fixed_grant_only(monkeypatch, overrides):
    monkeypatch.setattr(guest, 'recovery_request', unexpected)
    monkeypatch.setattr(guest, '_maintain_copy', unexpected)
    channel = Channel({**grant(), **overrides}, _BINDING)
    with pytest.raises(finalization.FinalizationRefused):
        finalization.serve_finalization_once(channel, check_write_window=unexpected)
    assert channel.reads == 1 and channel.sent == []


@pytest.mark.parametrize('overrides', [
    {'id': 'd' * 32}, {'mode': 'inspect'}, {'artifacts': {_PATH: '0' * 64}},
    {'payload': {'bootstrap': 'b' * 64, 'unit': 'd' * 64}},
])
def test_local_media_drift_never_opens_disk(monkeypatch, overrides):
    monkeypatch.setattr(guest, 'recovery_request', lambda: local_request(**overrides))
    monkeypatch.setattr(guest, '_maintain_copy', unexpected)
    channel = Channel(grant(), _BINDING)
    assert finalization.serve_finalization_once(channel, check_write_window=unexpected) is False
    assert channel.sent == [_FAILED]


@pytest.mark.parametrize('overrides', [
    {'version': True}, {'request_sha256': '1' * 64}, {'unmounted_read_only': 1},
    {'unmounted_read_only': False}, {'audit': 'inspection_only'}, {'vm_removed': True},
])
def test_reject_wrong_completion_without_replay(overrides):
    expected = grant()['request_sha256']
    receipt = {'version': 1, 'status': 'success', 'audit': 'pass', 'unmounted_read_only': True,
               'request_sha256': expected, **overrides}
    channel = Channel(receipt, _BINDING)
    with pytest.raises(finalization.FinalizationRefused, match='invalid_finalization_receipt'):
        finalization.finalize_once(channel, reviewed_request_sha256=expected)
    assert channel.reads == 1 and channel.sent == [grant()]


@pytest.mark.parametrize('fault', [None, 'expired', 'unmount'])
def test_guest_checks_write_window_and_only_returns_audited_evidence(monkeypatch, fault):
    windows = []
    writes = []
    monkeypatch.setattr(guest, 'recovery_request', local_request)

    def guard():
        windows.append(True)
        if fault == 'expired' and len(windows) == 2:
            raise PipeIOError('deadline')

    def maintain(local, *, before_write):
        assert local == local_request()
        before_write()
        writes.append(True)
        return local_receipt(unmounted_read_only=fault != 'unmount', error='PRIVATE_CANARY')

    monkeypatch.setattr(guest, '_maintain_copy', maintain)
    peer = Channel(grant(), _BINDING)
    assert finalization.serve_finalization_once(peer, check_write_window=guard) is (fault is None)
    assert len(windows) == 2 and len(writes) == (0 if fault == 'expired' else 1)
    control = Channel(peer.sent[0], _BINDING)
    if fault:
        assert peer.sent == [_FAILED]
        with pytest.raises(finalization.FinalizationRefused, match='finalization_not_verified'):
            finalization.finalize_once(control, reviewed_request_sha256=grant()['request_sha256'])
    else:
        assert finalization.finalize_once(control, reviewed_request_sha256=grant()['request_sha256']) == (
            finalization.GuestFinalizationEvidence(_BINDING, grant()['request_sha256']))
    assert 'PRIVATE_CANARY' not in json.dumps(peer.sent)


def test_real_disk_phase_model_does_not_switch_writable_after_guard_failure(tmp_path, monkeypatch):
    root = tmp_path / 'mountpoint'
    actions = []
    disk = {'type': 'disk', 'path': '/dev/sda', 'size': 20 * 1024**3,
            'children': [{'type': 'part', 'path': '/dev/sda1', 'fstype': 'vfat'},
                         {'type': 'part', 'path': '/dev/sda2', 'fstype': 'ext4'}]}
    monkeypatch.setattr(guest, 'ROOT', root)
    monkeypatch.setattr(guest, 'prepare', lambda *_: actions.append(('prepared',)))
    monkeypatch.setattr(guest, 'finalize', unexpected)

    def command(executable, *args):
        name = executable.rsplit('/', 1)[-1]
        actions.append((name, *args))
        if name == 'lsblk':
            return json.dumps({'blockdevices': [disk]})
        if name == 'blockdev':
            assert args[0] in ('--setro', '--getro')
            return '1\n'
        if name == 'mount':
            assert args[3] == 'ro,noload,nodev,nosuid,noexec'
        return '{}'

    def expired():
        actions.append(('guard',))
        raise PipeIOError('deadline')

    monkeypatch.setattr(guest, 'command', command)
    result = guest._maintain_copy(local_request(), before_write=expired)
    assert result['status'] == 'failed' and result['unmounted_read_only'] is True
    assert actions.index(('prepared',)) < actions.index(('umount', str(root))) < actions.index(('guard',))


@pytest.mark.parametrize('fault', [None, 'wrong_request', 'inspection_session'])
def test_real_tls_adapters_end_to_end(material, monkeypatch, fault):
    c2g: Queue[bytes] = Queue(maxsize=32)
    g2c: Queue[bytes] = Queue(maxsize=32)
    client, server = ByteLink(g2c, c2g), ByteLink(c2g, g2c)
    cctx, sctx = contexts(material)
    disk_work = []
    deadline = time.monotonic() + 4

    def open_pipe(path, budget):
        assert path == rf'\\.\pipe\night-shift-{_ID}-com1'
        client.budget = budget
        return client

    def open_serial(budget):
        server.budget = budget
        return server

    def maintain(local, *, before_write):
        before_write()
        disk_work.append(local)
        return local_receipt()

    def cancelled():
        return False

    monkeypatch.setattr(BoundedPipe, 'connect', staticmethod(open_pipe))
    monkeypatch.setattr(SerialDevice, 'open', staticmethod(open_serial))
    monkeypatch.setattr(guest, 'recovery_request', lambda: local_request(
        artifacts={_PATH: '0' * 64} if fault == 'wrong_request' else {_PATH: 'f' * 64},
    ))
    monkeypatch.setattr(guest, '_maintain_copy', maintain)
    with ThreadPoolExecutor(max_workers=1) as executor:
        if fault == 'inspection_session':
            run_guest, binding = inspection.connect_and_serve_once, _INSPECTION
        else:
            run_guest, binding = finalization.connect_and_serve_once, _BINDING
        worker = executor.submit(run_guest, sctx, binding, peer_sha256=pin(material, 'client'),
                                 deadline=deadline, cancelled=cancelled)

        def run_controller():
            return finalization.connect_and_finalize_once(
                cctx, _BINDING, peer_sha256=pin(material, 'server'),
                reviewed_request_sha256=grant()['request_sha256'], deadline=deadline, cancelled=cancelled,
            )

        if fault == 'inspection_session':
            with pytest.raises((PipeIOError, PrototypeRefused)):
                run_controller()
            with pytest.raises(PrototypeRefused, match='frame_binding'):
                worker.result(timeout=5)
        elif fault == 'wrong_request':
            with pytest.raises(finalization.FinalizationRefused, match='finalization_not_verified'):
                run_controller()
            assert worker.result(timeout=5) is False
        else:
            assert run_controller() == finalization.GuestFinalizationEvidence(_BINDING, grant()['request_sha256'])
            assert worker.result(timeout=5) is True
    assert len(disk_work) == (1 if fault is None else 0)
    assert client.closes == server.closes == 1
    assert FINALIZATION_OPERATION.encode() not in b''.join(client.writes)
