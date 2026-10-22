"""Offline synthetic seeds and mocked supervision only. No daemon/VM execution.

Synthetic pins below are explicitly replaced for parser tests; they establish
neither Ubuntu provenance nor Linux/AppArmor/systemd behavior. No key generation.
"""
from __future__ import annotations

import hashlib
import io
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import ec

from night_shifts import bootstrap_probe_seed as seed
from night_shifts.guest import bootstrap_public_probe as guest
from night_shifts.maintenance_tls_prototype import AttemptBinding
from night_shifts.public_bootstrap_kvp import BootstrapKvpRefused


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture
def binding():
    return AttemptBinding('1' * 32, '00000000-0000-4000-8000-000000000001')


@pytest.fixture
def inputs(monkeypatch):
    daemon = b'\x7fELF\x02\x01\x01SYNTHETIC_NOT_EXECUTABLE'
    copying, gpl = b'C' * 496, b'G' * 18729
    monkeypatch.setattr(seed, 'extract_reviewed_daemon', lambda package: daemon)
    monkeypatch.setattr(seed, 'DAEMON_BYTES', len(daemon))
    monkeypatch.setattr(seed, 'DAEMON_SHA256', sha(daemon))
    monkeypatch.setattr(seed, 'COPYING_SHA256', sha(copying))
    monkeypatch.setattr(seed, 'GPL_SHA256', sha(gpl))
    return dict(package=b'SYNTHETIC', copying=copying, gpl=gpl)


@pytest.fixture
def support(binding, inputs):
    return seed.build_public_probe_seed(binding, **inputs)


def unpack(raw):
    with seed.zipfile.ZipFile(io.BytesIO(raw)) as archive:
        return {i.filename: archive.read(i) for i in archive.infolist()}


def validate(raw, binding):
    return seed.validate_public_probe_seed(raw, binding, expected_sha256=sha(raw))


def test_fixed_public_fixture_has_no_valid_signature_or_leaf_credential(binding):
    value = seed.synthetic_public_value(binding)
    assert value.server_leaf_sha256 == '0' * 64
    certificate = x509.load_der_x509_certificate(value.server_ca_der)
    with pytest.raises(InvalidSignature):
        certificate.public_key().verify(certificate.signature, certificate.tbs_certificate_bytes,
                                        ec.ECDSA(certificate.signature_hash_algorithm))
    assert b'INVALID' in seed.SOURCE_NOTICE


def test_determinism_inventory_empty_initializers_and_binding(support, binding, inputs):
    assert seed.build_public_probe_seed(binding, **inputs) == support
    entries = validate(support, binding)
    assert tuple(sorted((*entries, 'manifest.json'))) == seed.ENTRY_NAMES
    assert all(entries[n] == b'' for n in seed.EMPTY_FILES)
    assert len(support) <= seed.MAX_SEED_BYTES
    assert b'private_key' not in entries['public.json']
    other = AttemptBinding('2' * 32, binding.vm_id)
    assert seed.build_public_probe_seed(other, **inputs) != support
    with pytest.raises(seed.ProbeSeedRefused, match='^seed_manifest$'):
        validate(support, other)


@pytest.mark.parametrize('kind', ['wrong-pin', 'non-bytes', 'oversize', 'empty'])
def test_seed_preparse_digest_bound(support, binding, kind):
    raw = {'wrong-pin': support, 'non-bytes': bytearray(support),
           'oversize': b'X' * (seed.MAX_SEED_BYTES + 1), 'empty': b''}[kind]
    with pytest.raises(seed.ProbeSeedRefused, match='^seed_digest$'):
        seed.validate_public_probe_seed(raw, binding, expected_sha256='0' * 64)


@pytest.mark.parametrize('name', ['COPYING', 'GPL-2.0', 'SOURCE.txt', 'public.json',
                                  'hv_kvp_daemon', 'night_shifts/__init__.py'])
def test_rehashed_manifest_cannot_replace_pinned_public_assets(support, binding, name):
    entries = unpack(support)
    entries[name] += b'CANARY'
    del entries['manifest.json']
    entries['manifest.json'] = seed._manifest(entries, binding)
    raw = seed._zip(entries)
    with pytest.raises(seed.ProbeSeedRefused) as error:
        validate(raw, binding)
    assert 'CANARY' not in str(error.value)


@pytest.mark.parametrize('change', ['extra', 'missing', 'duplicate', 'reverse', 'compressed',
                                    'symlink', 'date', 'comment', 'extra-field', 'trailing', 'prefix'])
def test_inventory_zip_metadata_and_canonical_encoding(support, binding, change):
    entries = unpack(support)
    if change == 'extra':
        raw = seed._zip({**entries, '../CANARY': b'x'})
    elif change == 'missing':
        del entries['SOURCE.txt']
        raw = seed._zip(entries)
    elif change in ('trailing', 'prefix'):
        raw = support + b'CANARY' if change == 'trailing' else b'CANARY' + support
    else:
        stream = io.BytesIO()
        with seed.zipfile.ZipFile(stream, 'w') as archive:
            names = list(sorted(entries))
            if change == 'reverse':
                names.reverse()
            if change == 'duplicate':
                names.append(names[-1])
            for name in names:
                item = seed.zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                item.create_system = 3
                item.external_attr = 0o100444 << 16
                if name == 'SOURCE.txt':
                    if change == 'compressed':
                        item.compress_type = seed.zipfile.ZIP_DEFLATED
                    elif change == 'symlink':
                        item.external_attr = 0o120777 << 16
                    elif change == 'date':
                        item.date_time = (2020, 1, 1, 0, 0, 0)
                    elif change == 'comment':
                        item.comment = b'CANARY'
                    elif change == 'extra-field':
                        item.extra = b'\x01\x00\x00\x00'
                if change == 'duplicate' and name in archive.namelist():
                    with pytest.warns(UserWarning, match='Duplicate name:'):
                        archive.writestr(item, entries[name])
                else:
                    archive.writestr(item, entries[name])
        raw = stream.getvalue()
    with pytest.raises(seed.ProbeSeedRefused) as error:
        validate(raw, binding)
    assert 'CANARY' not in str(error.value)


@pytest.mark.parametrize('name', ['copying', 'gpl'])
def test_license_digest_precedes_extraction(binding, inputs, monkeypatch, name):
    inputs[name] = b'CANARY'
    monkeypatch.setattr(seed, 'extract_reviewed_daemon', lambda _: pytest.fail('must not parse package'))
    with pytest.raises(seed.ProbeSeedRefused, match='^asset_digest$'):
        seed.build_public_probe_seed(binding, **inputs)


def mount_view():
    return ('1 0 0:1 / / ro - overlay overlay ro\n'
            '2 1 0:2 / /run/night-shift-bootstrap rw,nosuid,nodev - tmpfs tmpfs rw\n'
            '3 1 0:3 / /var/lib/hyperv rw,nosuid,nodev,noexec - tmpfs tmpfs rw\n'
            '4 1 0:4 / /proc ro - proc proc ro\n'
            '5 1 0:5 / /dev rw,nosuid - devtmpfs devtmpfs rw\n')


def test_fixed_readonly_and_ram_mount_view():
    guest.check_mounts(mount_view())


@pytest.mark.parametrize('change', ['root-rw', 'pool-disk', 'pool-exec', 'runtime-noexec',
                                    'extra-rw', 'nested', 'duplicate', 'escape', 'malformed'])
def test_unsafe_mount_views_refuse_without_repairs(change):
    raw = mount_view()
    if change == 'root-rw':
        raw = raw.replace('/ / ro ', '/ / rw ')
    elif change == 'pool-disk':
        raw = raw.replace('noexec - tmpfs', 'noexec - ext4')
    elif change == 'pool-exec':
        raw = raw.replace(',noexec', '')
    elif change == 'runtime-noexec':
        raw = raw.replace('bootstrap rw,nosuid,nodev', 'bootstrap rw,nosuid,nodev,noexec')
    elif change == 'extra-rw':
        raw += '6 1 8:1 / /target rw - ext4 /dev/sda1 rw\n'
    elif change == 'nested':
        raw += '6 1 8:1 / /var/lib/hyperv/redirect ro - ext4 /dev/sda1 ro\n'
    elif change == 'duplicate':
        raw += raw.splitlines()[1] + '\n'
    elif change == 'escape':
        raw = raw.replace('/ /proc ', '/ /proc\\040x ')
    else:
        raw = 'malformed'
    with pytest.raises(guest.GuestProbeRefused):
        guest.check_mounts(raw)


def status():
    return 'NoNewPrivs:\t1\n' + ''.join(k + ':\t0000000000000000\n'
                                         for k in ('CapInh', 'CapPrm', 'CapEff', 'CapBnd', 'CapAmb'))


def test_nnp_and_all_capability_sets_required():
    guest.check_status(status())
    for raw in (status().replace('0000000000000000', '0000000000000001', 1),
                status().replace('NoNewPrivs:\t1', 'NoNewPrivs:\t0'), status() + status(), ''):
        with pytest.raises(guest.GuestProbeRefused, match='^confinement$'):
            guest.check_status(raw)


@pytest.mark.parametrize('blocks,interfaces,swaps', [
    (('sda', 'sr0'), ('lo',), 'Filename Type Size Used Priority\n'),
    (('nvme0n1',), ('lo',), 'Filename Type Size Used Priority\n'),
    (('loop0', 'sr0'), ('eth0', 'lo'), 'Filename Type Size Used Priority\n'),
    (('loop0', 'sr0'), ('lo',), 'Filename Type Size Used Priority\n/swap file 1 0 -2\n'),
])
def test_target_disk_network_and_swap_refuse(blocks, interfaces, swaps):
    with pytest.raises(guest.GuestProbeRefused):
        guest.check_devices(blocks, interfaces, swaps)


def test_loop_optical_only_no_swap_no_network():
    guest.check_devices(('loop0', 'sr0', 'sr1'), ('lo',), 'Filename Type Size Used Priority\n')


@pytest.fixture
def mock_native(monkeypatch, support):
    calls = []
    clock = [100.0]
    monkeypatch.setattr(guest, 'time', SimpleNamespace(
        monotonic=lambda: clock[0], sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds)))
    monkeypatch.setattr(guest, 'preflight', lambda b: calls.append('preflight'))
    monkeypatch.setattr(guest, '_read', lambda path, limit: support)
    monkeypatch.setattr(guest, '_write_daemon', lambda raw: calls.append('create-new'))
    child = SimpleNamespace(pid=12345, poll=lambda: None)

    def popen(command, **options):
        calls.append((command, options))
        return child

    monkeypatch.setattr(guest.subprocess, 'Popen', popen)
    monkeypatch.setattr(guest, '_ready', lambda: True)
    monkeypatch.setattr(guest, 'publish_public_bootstrap', lambda *a, **k: calls.append('publish'))
    monkeypatch.setattr(guest, '_stop', lambda c: calls.append('stop') or True)
    return calls, child


def run(support, binding):
    return json.loads(guest.run_guest_probe(support, binding, expected_sha256=sha(support)))


def test_exact_foreground_supervision_once_no_raw_output(support, binding, mock_native):
    calls, child = mock_native
    report = run(support, binding)
    assert report['outcome'] == 'local_published'
    assert report['publication'] == 'local_readback'
    assert report['direct_child_stopped'] is True
    assert report['spawn_attempted'] is report['direct_child_started'] is True
    assert report['host_observed'] is report['vm_cleanup_confirmed'] is False
    assert calls.count('publish') == calls.count('create-new') == calls.count('stop') == 1
    command, options = calls[2]
    assert command == ['/run/night-shift-bootstrap/hv_kvp_daemon', '-n']
    assert options['start_new_session'] is options['close_fds'] is True
    assert options['env'] == {'PATH': '', 'LANG': 'C', 'LC_ALL': 'C'}
    assert options['stdout'] == options['stderr'] == options['stdin'] == subprocess.DEVNULL
    assert len(json.dumps(report).encode()) < 3000
    assert 'server_ca_der_b64' not in json.dumps(report)


def test_preflight_refusal_has_no_write_or_spawn(support, binding, mock_native, monkeypatch):
    calls, child = mock_native

    def refuse(_):
        raise guest.GuestProbeRefused('apparmor')

    monkeypatch.setattr(guest, 'preflight', refuse)
    report = run(support, binding)
    assert calls == []
    assert report['outcome'] == 'refused'
    assert report['publication'] == 'not_attempted'
    assert report['reason'] == 'apparmor'
    assert report['spawn_attempted'] is report['direct_child_started'] is False
    assert report['direct_child_stopped'] is None


def test_uncertain_publication_never_retried(support, binding, mock_native, monkeypatch):
    calls, child = mock_native

    def refuse(*a, **k):
        calls.append('publish')
        raise BootstrapKvpRefused('publication_unknown')

    monkeypatch.setattr(guest, 'publish_public_bootstrap', refuse)
    report = run(support, binding)
    assert report['publication'] == 'unknown'
    assert report['reason'] == 'publication_unknown'
    assert calls.count('publish') == calls.count('stop') == 1


def test_unknown_child_stop_dominates_local_success(support, binding, mock_native, monkeypatch):
    monkeypatch.setattr(guest, '_stop', lambda _: False)
    report = run(support, binding)
    assert report['outcome'] == 'unknown'
    assert report['reason'] == 'daemon_stop_unknown'
    assert report['direct_child_stopped'] is False


def test_early_daemon_exit_prevents_publication(support, binding, mock_native):
    calls, child = mock_native
    child.poll = lambda: 1
    report = run(support, binding)
    assert report['reason'] == 'daemon_exited'
    assert 'publish' not in calls
    assert calls.count('stop') == 1


def test_stop_escalation_is_only_new_exact_session(monkeypatch):
    sent = []
    polls = [None]
    waits = []

    def wait(*, timeout):
        waits.append(timeout)
        if len(waits) == 1:
            raise subprocess.TimeoutExpired('synthetic', timeout)
        polls[0] = -9
        return -9

    child = SimpleNamespace(pid=12345, poll=lambda: polls[0], wait=wait)
    monkeypatch.setattr(guest, 'signal', SimpleNamespace(SIGTERM=15, SIGKILL=9))
    monkeypatch.setattr(guest, '_linux', lambda: SimpleNamespace(
        killpg=lambda pid, sig: sent.append((pid, sig))))
    assert guest._stop(child) is True
    assert sent == [(12345, 15), (12345, 9)]
    assert waits == [1, 1]


def test_linux_paths_are_lexical_and_native_helpers_refuse_windows(monkeypatch):
    assert str(guest.RUNTIME) == '/run/night-shift-bootstrap'
    assert str(guest.POOL) == '/var/lib/hyperv'
    assert str(guest.DAEMON) == '/run/night-shift-bootstrap/hv_kvp_daemon'
    monkeypatch.setattr(guest, 'sys', SimpleNamespace(platform='win32'))
    monkeypatch.setattr(guest.os, 'open', lambda *a, **k: pytest.fail('native open on Windows'))
    for call in (lambda: guest._read(guest.DAEMON), lambda: guest._directory(guest.RUNTIME),
                 lambda: guest._write_daemon(b'CANARY'), guest._ready,
                 lambda: guest._stop(SimpleNamespace(poll=lambda: None))):
        with pytest.raises(guest.GuestProbeRefused, match='^linux_required$'):
            call()


def test_process_creation_without_a_returned_handle_is_unknown(
    support, binding, mock_native, monkeypatch,
):
    calls, child = mock_native

    def refuse(*a, **k):
        calls.append('spawn')
        raise OSError('CANARY')

    monkeypatch.setattr(guest.subprocess, 'Popen', refuse)
    report = run(support, binding)
    assert report['outcome'] == 'unknown'
    assert report['reason'] == 'spawn_unknown'
    assert report['spawn_attempted'] is True
    assert report['direct_child_started'] is False
    assert report['direct_child_stopped'] is None
    assert calls.count('spawn') == 1
    assert 'stop' not in calls and 'publish' not in calls
    assert 'CANARY' not in json.dumps(report)


def test_unready_daemon_timeout_does_not_publish_or_retry(support, binding, mock_native, monkeypatch):
    calls, child = mock_native
    monkeypatch.setattr(guest, '_ready', lambda: False)
    report = run(support, binding)
    assert report['reason'] == 'daemon_not_ready'
    assert report['publication'] == 'not_attempted'
    assert calls.count('stop') == 1 and 'publish' not in calls


def test_local_readback_is_preserved_if_daemon_then_exits(support, binding, mock_native):
    calls, child = mock_native
    states = iter((None, 1))
    child.poll = lambda: next(states)
    report = run(support, binding)
    assert report['outcome'] == 'refused'
    assert report['reason'] == 'daemon_exited'
    assert report['publication'] == 'local_readback'
    assert calls.count('publish') == calls.count('stop') == 1


def test_stop_wait_exhaustion_remains_unknown_without_more_kills(monkeypatch):
    sent, waits = [], []

    def wait(*, timeout):
        waits.append(timeout)
        raise subprocess.TimeoutExpired('synthetic', timeout)

    child = SimpleNamespace(pid=12345, poll=lambda: None, wait=wait)
    monkeypatch.setattr(guest, 'signal', SimpleNamespace(SIGTERM=15, SIGKILL=9))
    monkeypatch.setattr(guest, '_linux', lambda: SimpleNamespace(
        killpg=lambda pid, sig: sent.append((pid, sig))))
    assert guest._stop(child) is False
    assert sent == [(12345, 15), (12345, 9)] and waits == [1, 1]


def test_candidate_policy_has_no_shell_helpers_or_network_allow():
    policy = (Path(guest.__file__).with_name('bootstrap-public-probe.apparmor')).read_text()
    rules = '\n'.join(line for line in policy.splitlines() if not line.lstrip().startswith('#'))
    assert 'deny network,' in rules and 'deny capability,' in rules
    assert '/bin/sh' not in rules and '/usr/libexec/hypervkvpd' not in rules
    assert '/run/night-shift-bootstrap/hv_kvp_daemon mrwix,' in rules


def test_existing_inspection_bundle_excludes_all_probe_assets():
    from night_shifts.inspection_bundle import bundle_bytes

    with seed.zipfile.ZipFile(io.BytesIO(bundle_bytes())) as archive:
        names = archive.namelist()
    assert all('bootstrap_probe_seed' not in n and 'bootstrap_public_probe' not in n
               and 'bootstrap-public-probe.apparmor' not in n and 'hv_kvp_daemon' not in n
               for n in names)
