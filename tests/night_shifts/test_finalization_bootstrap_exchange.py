"""Real TLS, synthetic per-attempt keys and mocked WMI, boot and device I/O only."""
from __future__ import annotations

import json
import ssl
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from queue import Queue
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.serialization import Encoding

from night_shifts import finalization_bootstrap_controller as host
from night_shifts import public_bootstrap_host as kvp
from night_shifts.authenticated_image_finalization import FinalizationRefused, GuestFinalizationEvidence, request_digest
from night_shifts.finalization_tls_identity import (
    ControllerPublicTrust, FinalizationIdentityRefused, LocalPemIdentity, controller_context, guest_context,
)
from night_shifts.guest import finalization_bootstrap as boot
from night_shifts.guest.serial_device_io import SerialDevice
from night_shifts.maintenance_credentials_prototype import FinalizationPublicBootstrap
from night_shifts.maintenance_tls_prototype import FINALIZATION_OPERATION, AttemptBinding, PrototypeRefused
from night_shifts.serial_pipe_io import BoundedPipe, IOBudget, PipeIOError
from tests.night_shifts.test_authenticated_image_finalization import _BINDING, local_receipt, local_request
from tests.night_shifts.test_authenticated_image_inspection import ByteLink
from tests.night_shifts.test_maintenance_tls_prototype import material as material
from tests.night_shifts.test_maintenance_tls_prototype import pin
from tests.night_shifts.test_public_bootstrap_kvp import finalization_snapshot


def never_cancelled():
    return False


def unexpected(*args, **kwargs):
    pytest.fail('unexpected boot, TLS, KVP or disk access')


def identities(material, fault=None):
    # Independent issuer per role. No Windows trust store or default trust path.
    server = FinalizationPublicBootstrap(_BINDING, material['ca'].public_bytes(Encoding.DER),
                                        '0' * 64 if fault == 'server_pin' else pin(material, 'server'))
    controller = ControllerPublicTrust(_BINDING, material['foreign_ca'].public_bytes(Encoding.DER),
                                       '0' * 64 if fault == 'controller_pin' else pin(material, 'foreign_client'))
    return (server, controller, LocalPemIdentity(*material['server'][:2]),
            LocalPemIdentity(*material['foreign_client'][:2]))


def live_fixture(monkeypatch, fault=None):
    def read(path):
        if path.endswith('/product_uuid'):
            text = 'fed811b8-1e28-4ca5-917b-cd1197cf4d92' if fault == 'vm_uuid' else _BINDING.vm_id
        else:
            assert path == '/proc/swaps'
            text = 'Filename Type Size Used Priority\n'
            if fault == 'swap':
                text += '/dev/sda2 partition 1024 0 -2\n'
        return SimpleNamespace(read_text=lambda: text)

    def command(*argv):
        assert argv == ('/usr/bin/findmnt', '--json', '--mountpoint', str(boot.guest.MEDIA),
                        '-o', 'TARGET,FSTYPE,OPTIONS')
        row = {'target': str(boot.guest.MEDIA), 'fstype': 'iso9660', 'options': 'ro,nodev,nosuid,noexec'}
        if fault == 'mount_options':
            row['options'] = 'rw,nodev,nosuid,noexec'
        if fault == 'mount_type':
            row['fstype'] = 'ext4'
        return json.dumps({'filesystems': [row, row] if fault == 'mount_ambiguous' else [row]})

    monkeypatch.setattr(boot, 'Path', read)
    monkeypatch.setattr(boot.guest, 'command', command)
    monkeypatch.setattr(boot.guest, 'recovery_request', lambda: (
        local_request(id='e' * 32) if fault == 'request' else local_request()))


@pytest.mark.parametrize('fault', [None, 'server_pin', 'controller_pin'])
def test_finalization_bootstrap_transitions_from_kvp_to_tls(material, monkeypatch, fault):
    server, controller, server_identity, host_identity = identities(material, fault)
    live_fixture(monkeypatch)
    advertised: list[FinalizationPublicBootstrap] = []
    captures: list[bool] = []
    disk_work = []
    c2g: Queue[bytes] = Queue(maxsize=32)
    g2c: Queue[bytes] = Queue(maxsize=32)
    client, peer = ByteLink(g2c, c2g), ByteLink(c2g, g2c)
    deadline = time.monotonic() + 5

    def publish(value, *, deadline, cancelled):
        assert deadline == expiry and not cancelled()
        advertised.append(value)

    def capture(script, budget):
        budget.check()
        assert _BINDING.vm_id in script and 'night-shift-auth-finalize-' + _BINDING.attempt_id in script
        # Exercise initial absence even if the guest thread advertises immediately.
        present = bool(captures and advertised)
        captures.append(present)
        return finalization_snapshot(server, None if present else [])

    def open_pipe(path, budget):
        assert path == rf'\\.\pipe\night-shift-{_BINDING.attempt_id}-com1'
        assert captures[-1] and budget.deadline == expiry
        client.budget = budget
        return client

    def open_serial(budget):
        assert advertised == [server] and budget.deadline == expiry
        peer.budget = budget
        return peer

    def maintain(local, *, before_write):
        before_write()
        disk_work.append(local)
        return local_receipt()

    expiry = deadline
    monkeypatch.setattr(boot, 'publish_finalization_bootstrap', publish)
    monkeypatch.setattr(kvp, '_capture', capture)
    monkeypatch.setattr(BoundedPipe, 'connect', staticmethod(open_pipe))
    monkeypatch.setattr(SerialDevice, 'open', staticmethod(open_serial))
    monkeypatch.setattr(boot.guest, '_maintain_copy', maintain)
    digest = request_digest(local_request(), _BINDING)
    with ThreadPoolExecutor(max_workers=1) as executor:
        guest = executor.submit(boot.serve_bootstrapped_copy_once, server, controller, server_identity,
                                deadline=deadline, cancelled=never_cancelled)
        if fault:
            with pytest.raises((PipeIOError, PrototypeRefused)):
                host.finalize_bootstrapped_copy_once(_BINDING, host_identity, request_sha256=digest,
                                                     deadline=deadline, cancelled=never_cancelled)
            with pytest.raises((PipeIOError, PrototypeRefused)):
                guest.result(timeout=6)
        else:
            result = host.finalize_bootstrapped_copy_once(_BINDING, host_identity, request_sha256=digest,
                                                         deadline=deadline, cancelled=never_cancelled)
            assert result == GuestFinalizationEvidence(_BINDING, digest)
            assert guest.result(timeout=6) is True
    assert disk_work == ([] if fault else [local_request()])
    assert captures.count(True) == 1 and captures[0] is False
    assert client.closes == peer.closes == 1


@pytest.mark.parametrize('fault', ['vm_uuid', 'swap', 'mount_options', 'mount_type', 'mount_ambiguous', 'request'])
def test_guest_refuses_before_opening_credentials_or_publishing(material, monkeypatch, fault):
    server, controller, identity, _ = identities(material)
    live_fixture(monkeypatch, fault)
    monkeypatch.setattr(boot, 'guest_context', unexpected)
    monkeypatch.setattr(boot, 'publish_finalization_bootstrap', unexpected)
    with pytest.raises(FinalizationRefused, match='^unverified_recovery_boot$'):
        boot.serve_bootstrapped_copy_once(server, controller, identity, deadline=time.monotonic() + 3,
                                          cancelled=never_cancelled)


def test_guest_rejects_cross_attempt_controller_trust(material, monkeypatch):
    server, controller, identity, _ = identities(material)
    other = AttemptBinding('e' * 32, _BINDING.vm_id, FINALIZATION_OPERATION)
    wrong = ControllerPublicTrust(other, controller.ca_der, controller.leaf_sha256)
    monkeypatch.setattr(boot, '_check_live_boot', unexpected)
    with pytest.raises(FinalizationRefused, match='^invalid_bootstrap_configuration$'):
        boot.serve_bootstrapped_copy_once(server, wrong, identity, deadline=time.monotonic() + 3,
                                          cancelled=never_cancelled)


def test_contexts_load_only_the_exact_peer_ca(material, tmp_path):
    server, controller, server_identity, host_identity = identities(material)
    client = controller_context(host_identity, server.server_ca_der)
    guest = guest_context(server_identity, controller)
    for ctx, expected in ((client, server.server_ca_der), (guest, controller.ca_der)):
        assert ctx.get_ca_certs(binary_form=True) == [expected]
        assert ctx.minimum_version == ctx.maximum_version == ssl.TLSVersion.TLSv1_3
        assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.options & ssl.OP_NO_TICKET
        assert ctx.keylog_filename is None
    assert client.check_hostname and not client.hostname_checks_common_name
    assert guest.num_tickets == 0
    for broken, reason in ((LocalPemIdentity(Path('relative.pem'), host_identity.key), 'local_identity'),
                           (LocalPemIdentity(tmp_path / 'PRIVATE_CANARY', host_identity.key), 'tls_identity_load')):
        with pytest.raises(FinalizationIdentityRefused, match='^' + reason + '$') as error:
            controller_context(broken, server.server_ca_der)
        assert 'CANARY' not in str(error.value)


def test_controller_refuses_to_open_any_resource_after_expiry(material, monkeypatch):
    *_, identity = identities(material)
    monkeypatch.setattr(host, 'LocalFinalizationBootstrapReader', unexpected)
    with pytest.raises(PipeIOError, match='^deadline$'):
        host.finalize_bootstrapped_copy_once(_BINDING, identity, request_sha256='a' * 64,
                                             deadline=time.monotonic() - 1, cancelled=never_cancelled)


def test_constrained_budget_is_not_extended_when_handed_to_next_stage():
    budget = IOBudget(3, deadline=100, clock=lambda: 10)
    follow = IOBudget(3, deadline=budget.deadline, clock=lambda: 12)
    assert budget.deadline == follow.deadline == 13
    assert follow.remaining() == 1
