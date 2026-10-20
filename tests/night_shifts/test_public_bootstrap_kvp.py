"""No real WMI/KVP/service/VM access; synthetic keys stay in test memory.

PowerShell tests REMOVE the provider function before synthetic execution.
Linux native tests use disposable fds with explicit ordinary-owner substitution,
never the fixed public entrypoint. Neither establishes production provenance.
"""
from __future__ import annotations

import base64
import errno
import io
import json
import os
import stat
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from xml.sax.saxutils import escape

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from night_shifts import public_bootstrap_host as host
from night_shifts import public_bootstrap_kvp as wire
from night_shifts.guest import publish_public_bootstrap as guest
from night_shifts.maintenance_credentials_prototype import (
    PUBLIC_ITEM_NAME, PublicBootstrap, encode_public_bootstrap,
)
from night_shifts.maintenance_tls_prototype import AttemptBinding


@pytest.fixture(scope='module')
def public_value():
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'KVP synthetic CA')])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(hours=1))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .sign(key, hashes.SHA256()))
    binding = AttemptBinding('1' * 32, '00000000-0000-4000-8000-000000000001')
    return PublicBootstrap(binding, cert.public_bytes(serialization.Encoding.DER), 'a' * 64)


def item(data, *, name=PUBLIC_ITEM_NAME, source='1'):
    return ('<INSTANCE CLASSNAME="Msvm_KvpExchangeDataItem">'
            '<PROPERTY NAME="Name" TYPE="string"><VALUE>' + escape(name) + '</VALUE></PROPERTY>'
            '<PROPERTY NAME="Data" TYPE="string"><VALUE>' + escape(data) + '</VALUE></PROPERTY>'
            '<PROPERTY NAME="Source" TYPE="uint16"><VALUE>' + source + '</VALUE></PROPERTY>'
            '</INSTANCE>')


def snapshot(value, items=None, **changes):
    b = value.binding
    fields = dict(version=1, vm_id=b.vm_id, attempt_id=b.attempt_id,
                  vm_name='night-shift-bootstrap-' + b.attempt_id,
                  owner='night-shift-bootstrap-owner:' + b.attempt_id,
                  state_stamp='20261018000000.000000+000',
                  items=items if items is not None else [item(encode_public_bootstrap(value).decode())])
    fields.update(changes)
    return json.dumps(fields).encode()


def other_record():
    # Actual daemon malloc padding after NUL need not be zero.
    return b'other\0'.ljust(wire.KEY_BYTES, b'X') + b'public\0'.ljust(wire.VALUE_BYTES, b'Y')


def test_linux_pool_abi_and_public_record_only(public_value):
    raw = wire.pool_record(public_value)
    assert len(raw) == 2560 == wire.POOL_RECORD_BYTES
    assert raw[:wire.KEY_BYTES].split(b'\0')[0] == PUBLIC_ITEM_NAME.encode()
    assert raw[wire.KEY_BYTES:].split(b'\0')[0] == encode_public_bootstrap(public_value)
    assert wire.check_pool_for_append(b'') is None
    assert wire.check_pool_for_append(other_record()) is None
    with pytest.raises(wire.BootstrapKvpRefused, match='^pool_collision$'):
        wire.check_pool_for_append(raw)


@pytest.mark.parametrize('raw', [b'x', b'x' * 2560, b'\0' * 2560, other_record() * 2,
                                other_record() * wire.MAX_ITEMS, bytearray()],
                         ids=['short', 'missing-nuls', 'empty-key', 'duplicate', 'full-pool', 'not-bytes'])
def test_bad_pool_shapes_are_not_rewritten(raw):
    with pytest.raises(wire.BootstrapKvpRefused, match='^pool_shape$'):
        wire.check_pool_for_append(raw)


def test_maximum_append_count_is_bounded():
    records = [str(i).encode().ljust(wire.KEY_BYTES, b'\0') + b'\0' * wire.VALUE_BYTES
               for i in range(wire.MAX_ITEMS)]
    wire.check_pool_for_append(b''.join(records[:-1]))
    with pytest.raises(wire.BootstrapKvpRefused, match='^pool_shape$'):
        wire.check_pool_for_append(b''.join(records))


def test_public_selection_and_absence(public_value):
    raw = encode_public_bootstrap(public_value)
    assert wire.select_public_item((), public_value.binding) is None
    assert wire.select_public_item((item('unrelated', name='other'), item(raw.decode())),
                                   public_value.binding) == raw


@pytest.mark.parametrize('source', ['0', '2', '4', '01', 'true', '-1', ''])
def test_xml_requires_canonical_guest_source(public_value, source):
    with pytest.raises(wire.BootstrapKvpRefused, match='^item_schema$'):
        wire.select_public_item((item('data', name='other', source=source),), public_value.binding)


@pytest.mark.parametrize('transform', [
    lambda s: '<!DOCTYPE INSTANCE [<!ENTITY x "canary">]>' + s,
    lambda s: s.replace('<VALUE>', '<VALUE>&x;', 1),
    lambda s: s.replace('Msvm_KvpExchangeDataItem', 'WrongClass'),
    lambda s: s.replace('TYPE="uint16"', 'TYPE="string"'),
    lambda s: s.replace('</INSTANCE>', '<PROPERTY NAME="Source" TYPE="uint16"><VALUE>1</VALUE></PROPERTY></INSTANCE>'),
    lambda s: s.replace('<VALUE>1</VALUE>', '<VALUE><nested>1</nested></VALUE>'),
    lambda s: s.replace('<VALUE>1</VALUE>', '<VALUE.NULL/>'),
    lambda s: s.replace('<INSTANCE ', '<INSTANCE EXTRA="1" '),
    lambda s: s.replace('<PROPERTY NAME="Source"', '<PROPERTY EXTRA="1" NAME="Source"'),
    lambda s: '<wrapper>' + s + '</wrapper>', lambda s: s + '\0',
    lambda s: '<!--comment-->' + s,
    lambda s: s.replace('<VALUE>1</VALUE>', '<VALUE>1</VALUE><VALUE>1</VALUE>'),
])
def test_xml_declarations_duplicates_nesting_types_refused(public_value, transform):
    with pytest.raises(wire.BootstrapKvpRefused):
        wire.select_public_item((transform(item(encode_public_bootstrap(public_value).decode())),),
                                public_value.binding)


def test_duplicate_names_are_fatal(public_value):
    for duplicate in (item(encode_public_bootstrap(public_value).decode()), item('data', name='other')):
        with pytest.raises(wire.BootstrapKvpRefused, match='^item_duplicate$'):
            wire.select_public_item((duplicate, duplicate), public_value.binding)


@pytest.mark.parametrize('items', [[], ('x' * (wire.MAX_XML_CHARS + 1),),
                                    ('x',) * (wire.MAX_ITEMS + 1),
                                    ('x' * wire.MAX_XML_CHARS,) * 9, (None,)])
def test_xml_collection_bounds(public_value, items):
    with pytest.raises(wire.BootstrapKvpRefused):
        wire.select_public_item(items, public_value.binding)


def test_wrong_attempt_and_secret_field_never_skipped(public_value):
    fields = json.loads(encode_public_bootstrap(public_value))
    for changes in ({'attempt_id': '2' * 32}, {'private_key': 'PRIVATE_CANARY'}):
        with pytest.raises(wire.BootstrapKvpRefused, match='^public_record$') as error:
            wire.select_public_item((item(json.dumps({**fields, **changes})),), public_value.binding)
        assert 'CANARY' not in str(error.value)


@pytest.mark.parametrize('seconds', [True, 0, -1, 31, float('nan'), float('inf'), '3'])
def test_invalid_budget(seconds):
    with pytest.raises(wire.BootstrapKvpRefused, match='^configuration$'):
        wire.Budget(seconds, lambda: False)


def test_deadline_and_callback_context(monkeypatch):
    clock = [10.0]
    monkeypatch.setattr(wire.time, 'monotonic', lambda: clock[0])
    budget = wire.Budget(1, lambda: False)
    clock[0] = 11.0
    with pytest.raises(wire.BootstrapKvpRefused, match='^timeout$'):
        budget.check()
    for callback, reason in ((lambda: True, 'cancelled'), (lambda: 1, 'cancellation_context')):
        with pytest.raises(wire.BootstrapKvpRefused, match='^' + reason + '$'):
            wire.Budget(1, callback)


def test_host_absence_freeze_change_terminal_and_close(public_value, monkeypatch):
    outputs = [snapshot(public_value, []), snapshot(public_value), snapshot(public_value)]
    monkeypatch.setattr(host, '_capture', lambda script, budget: outputs.pop(0))
    reader = host.LocalPublicBootstrapReader(public_value.binding)
    assert reader.poll() is None
    assert reader.poll() == public_value
    assert reader.poll() == public_value
    changed = PublicBootstrap(public_value.binding, public_value.server_ca_der, 'b' * 64)
    outputs.append(snapshot(changed))
    with pytest.raises(wire.BootstrapKvpRefused, match='^bootstrap_changed$'):
        reader.poll()
    outputs.append(snapshot(public_value))
    with pytest.raises(wire.BootstrapKvpRefused, match='^bootstrap_changed$'):
        reader.poll()
    assert len(outputs) == 1
    closed = host.LocalPublicBootstrapReader(public_value.binding)
    closed.close()
    with pytest.raises(wire.BootstrapKvpRefused, match='^closed$'):
        closed.poll()


@pytest.mark.parametrize('changes', [
    {'version': True}, {'vm_id': 'different'}, {'attempt_id': '2' * 32},
    {'owner': 'different'}, {'vm_name': 'different'}, {'state_stamp': ''},
    {'state_stamp': 2}, {'items': 'not an array'}, {'items': [None]},
    {'items': ['x'] * 33}, {'extra': 'PRIVATE_CANARY'},
])
def test_host_snapshot_substitution(public_value, changes, monkeypatch):
    monkeypatch.setattr(host, '_capture', lambda script, budget: snapshot(public_value, **changes))
    with pytest.raises(wire.BootstrapKvpRefused, match='^provider_schema$') as error:
        host.LocalPublicBootstrapReader(public_value.binding).poll()
    assert 'CANARY' not in str(error.value)


@pytest.mark.parametrize('second,reason', [('missing', 'public_record_disappeared'),
                                         ('state', 'vm_state_changed')])
def test_disappearance_or_state_change_terminal(public_value, monkeypatch, second, reason):
    outputs = [snapshot(public_value), snapshot(public_value, [] if second == 'missing' else None,
                                              state_stamp='changed' if second == 'state' else '20261018000000.000000+000')]
    monkeypatch.setattr(host, '_capture', lambda script, budget: outputs.pop(0))
    reader = host.LocalPublicBootstrapReader(public_value.binding)
    reader.poll()
    with pytest.raises(wire.BootstrapKvpRefused, match='^' + reason + '$'):
        reader.poll()


@pytest.mark.parametrize('raw', [b'', b'[]', b'{"version":1,"version":1}', b'\xff',
                                b'x' * (host.MAX_CAPTURE_BYTES + 1)],
                         ids=['empty', 'array', 'duplicate-json', 'non-utf8', 'too-large'])
def test_malformed_oversized_provider_output(public_value, monkeypatch, raw):
    monkeypatch.setattr(host, '_capture', lambda script, budget: raw)
    with pytest.raises(wire.BootstrapKvpRefused):
        host.LocalPublicBootstrapReader(public_value.binding).poll()


def test_cancel_before_native_acquisition(public_value, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('native acquisition forbidden')
    monkeypatch.setattr(host, '_capture', forbidden)
    with pytest.raises(wire.BootstrapKvpRefused, match='^cancelled$'):
        host.LocalPublicBootstrapReader(public_value.binding, cancelled=lambda: True)
    monkeypatch.setattr(guest, 'sys', SimpleNamespace(platform='unsupported-test-host'))
    monkeypatch.setattr(guest, 'os', SimpleNamespace(open=forbidden))
    with pytest.raises(wire.BootstrapKvpRefused, match='^linux_required$'):
        guest.publish_public_bootstrap(public_value)


def info(*, size=0, uid=0, gid=0, links=1, mode=stat.S_IFREG | 0o644, atime=1, mtime=2):
    return os.stat_result((mode, 100, 200, links, uid, gid, size, atime, mtime, 3))


@pytest.mark.parametrize('changes', [{'uid': 1000}, {'gid': 1000}, {'links': 2},
                                     {'mode': stat.S_IFREG | 0o666},
                                     {'mode': stat.S_IFLNK | 0o777},
                                     {'mode': stat.S_IFIFO | 0o600}])
def test_pool_security_refusals(changes):
    with pytest.raises(wire.BootstrapKvpRefused, match='^pool_security$'):
        guest._profile(info(**changes), directory=False)


def test_version_ignores_atime_not_length_or_mtime():
    assert guest._version(info(atime=1)) == guest._version(info(atime=9))
    assert guest._version(info(size=1)) != guest._version(info())
    # os.stat_result constructed from a tuple has no ns values; native fixtures
    # cover real ns metadata; model security/length comparisons stay meaningful.
    assert guest._profile(info(mode=stat.S_IFREG | 0o600), directory=False) != guest._profile(info(), directory=False)


def model_pool(monkeypatch, raw=b'', *, short=False, lock_error=None, after_write=None):
    storage = bytearray(raw)
    locks, writes = [], []
    def lockf(fd, operation, *args):
        locks.append((operation, args))
        if operation != 8 and lock_error:
            raise OSError(lock_error, 'PRIVATE_CANARY')
    monkeypatch.setitem(sys.modules, 'fcntl', SimpleNamespace(LOCK_EX=2, LOCK_NB=4, LOCK_UN=8, lockf=lockf))
    def write(fd, data, offset):
        writes.append((bytes(data), offset))
        storage[offset:offset + len(data)] = data
        if after_write:
            after_write()
        return len(data) - int(short)
    # Replace ONLY the guest module's reference, not global os.stat/fstat.
    monkeypatch.setattr(guest, 'os', SimpleNamespace(
        SEEK_SET=os.SEEK_SET, fstat=lambda fd: info(size=len(storage)),
        stat=lambda *a, **k: info(size=len(storage)),
        pread=lambda fd, size, offset: bytes(storage[offset:offset + size]), pwrite=write))
    return storage, locks, writes


def test_modeled_whole_file_record_lock_and_exact_append(public_value, monkeypatch):
    raw = other_record()
    storage, locks, writes = model_pool(monkeypatch, raw)
    record = wire.pool_record(public_value)
    guest._append_locked(10, 11, record, wire.Budget(1, lambda: False))
    assert bytes(storage) == raw + record and writes == [(record, len(raw))]
    assert locks == [(6, (0, 0, os.SEEK_SET)), (8, (0, 0, os.SEEK_SET))]


def test_modeled_collision_has_no_write(public_value, monkeypatch):
    record = wire.pool_record(public_value)
    storage, locks, writes = model_pool(monkeypatch, record)
    with pytest.raises(wire.BootstrapKvpRefused, match='^pool_collision$'):
        guest._append_locked(10, 11, record, wire.Budget(1, lambda: False))
    assert not writes and bytes(storage) == record and locks[-1][0] == 8


@pytest.mark.parametrize('failure', ['short', 'cancel'])
def test_possible_publication_unknown_not_rolled_back(public_value, monkeypatch, failure):
    cancelled = [False]
    storage, locks, writes = model_pool(monkeypatch, short=failure == 'short',
        after_write=lambda: cancelled.__setitem__(0, failure == 'cancel'))
    with pytest.raises(wire.BootstrapKvpRefused, match='^publication_unknown$'):
        guest._append_locked(10, 11, wire.pool_record(public_value), wire.Budget(1, lambda: cancelled[0]))
    assert len(writes) == 1 and storage and locks[-1][0] == 8


def test_busy_lock_has_bounded_wait_no_writes(public_value, monkeypatch):
    storage, locks, writes = model_pool(monkeypatch, lock_error=errno.EAGAIN)
    clock = [0.0]
    monkeypatch.setattr(wire.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(guest.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    with pytest.raises(wire.BootstrapKvpRefused, match='^timeout$'):
        guest._append_locked(10, 11, wire.pool_record(public_value), wire.Budget(0.05, lambda: False))
    assert not writes and not storage and 1 <= len(locks) <= 4


@pytest.mark.parametrize('case', ['ok', 'overflow', 'exit', 'cancel'])
def test_capture_bound_and_process_termination_without_starting_process(monkeypatch, case):
    payload = b'{}' if case != 'overflow' else b'x' * (host.MAX_CAPTURE_BYTES + 1)
    class FakeProcess:
        def __init__(self):
            self.stdout = io.BytesIO(payload)
            self.returncode = None if case == 'cancel' else (2 if case == 'exit' else 0)
            self.killed = False
        def poll(self):
            return self.returncode
        def kill(self):
            self.killed = True
            self.returncode = -1
        def wait(self, timeout):
            return self.returncode
    process = FakeProcess()
    arguments = []
    def start(args, **kwargs):
        arguments.append((args, kwargs))
        return process
    fake_subprocess = SimpleNamespace(Popen=start, DEVNULL=-3, PIPE=-1, STDOUT=-2,
                                     CREATE_NO_WINDOW=0, SubprocessError=subprocess.SubprocessError)
    monkeypatch.setattr(host, 'subprocess', fake_subprocess)
    monkeypatch.setattr(host, '_powershell', lambda: 'synthetic-not-executed.exe')
    budget = wire.Budget(1, lambda: bool(arguments) and case == 'cancel')
    if case == 'ok':
        assert host._capture('synthetic', budget) == b'{}'
    else:
        with pytest.raises(wire.BootstrapKvpRefused):
            host._capture('synthetic', budget)
    assert arguments[0][1]['shell'] is False
    if case == 'cancel':
        assert process.killed
    assert process.stdout.closed


@pytest.mark.skipif(sys.platform != 'linux', reason='Linux fds only; no WSL/VM fallback')
def test_native_disposable_pool_with_explicit_owner_substitution(public_value, tmp_path, monkeypatch):
    original = guest._profile
    def ordinary_profile(metadata, *, directory):
        assert metadata.st_uid == os.getuid() and metadata.st_gid == os.getgid()
        fields = list(metadata)
        fields[4:6] = [0, 0]
        return original(os.stat_result(fields), directory=directory)
    monkeypatch.setattr(guest, '_profile', ordinary_profile)
    path = tmp_path / '.kvp_pool_1'
    path.write_bytes(other_record())
    path.chmod(0o600)
    parent = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
    try:
        guest._append_locked(fd, parent, wire.pool_record(public_value), wire.Budget(1, lambda: False))
        assert os.pread(fd, wire.POOL_RECORD_BYTES * 2, 0) == other_record() + wire.pool_record(public_value)
        with pytest.raises(wire.BootstrapKvpRefused, match='^pool_collision$'):
            guest._append_locked(fd, parent, wire.pool_record(public_value), wire.Budget(1, lambda: False))
    finally:
        os.close(fd)
        os.close(parent)


@pytest.mark.skipif(os.name != 'nt', reason='PowerShell parsing, no provider execution')
def test_host_script_parses_without_executing_it(public_value):
    driver = ("$s=[Console]::In.ReadToEnd(); $t=$null; $e=$null; "
              "[void][System.Management.Automation.Language.Parser]::ParseInput($s,[ref]$t,[ref]$e); "
              "if ($e.Count) { exit 2 }; [Console]::Write('parsed')")
    result = subprocess.run([host._powershell(), '-NoLogo', '-NoProfile', '-NonInteractive',
                             '-Command', driver], input=host.query_script(public_value.binding).encode('ascii'),
                            capture_output=True, timeout=10, check=False)
    assert result.returncode == 0, result.stderr.decode(errors='replace')
    assert result.stdout == b'parsed'


@pytest.mark.skipif(os.name != 'nt', reason='synthetic PowerShell selection; native WMI removed')
@pytest.mark.parametrize('case', ['ok', 'wrong_vm', 'wrong_owner', 'off', 'ambiguous', 'wrong_component'])
def test_host_query_selection_without_native_provider(public_value, case):
    script = host.query_script(public_value.binding)
    start = script.index('function Read-LocalRows(')
    end = script.index('function Read-OwnedVm', start)
    mock = r'''
$fixture = [Console]::In.ReadToEnd() | ConvertFrom-Json
function Read-LocalRows([string]$Query, [string[]]$Properties) {
    if ($Query -like '*FROM Msvm_ComputerSystem WHERE*') { $fixture.vm }
    elseif ($Query -like '*FROM Msvm_VirtualSystemSettingData WHERE*') { $fixture.settings }
    elseif ($Query -like '*FROM Msvm_KvpExchangeComponent WHERE*') { $fixture.component }
    else { throw 'unexpected synthetic query' }
}
'''
    script = script[:start] + mock + script[end:]
    assert 'ManagementObjectSearcher' not in script and 'ManagementScope' not in script
    b = public_value.binding
    fixture = dict(
        vm=dict(Name=b.vm_id, ElementName='night-shift-bootstrap-' + b.attempt_id,
                CreationClassName='Msvm_ComputerSystem', EnabledState=2,
                TimeOfLastStateChange='20261018000000.000000+000'),
        settings=dict(VirtualSystemIdentifier=b.vm_id, VirtualSystemType='Microsoft:Hyper-V:System:Realized',
                      Notes=['night-shift-bootstrap-owner:' + b.attempt_id]),
        component=dict(SystemName=b.vm_id, SystemCreationClassName='Msvm_ComputerSystem',
                       CreationClassName='Msvm_KvpExchangeComponent', EnabledState=2,
                       OperationalStatus=[2], GuestExchangeItems=[item(encode_public_bootstrap(public_value).decode())]))
    if case == 'wrong_vm':
        fixture['vm']['Name'] = 'different'
    elif case == 'wrong_owner':
        fixture['settings']['Notes'] = ['different']
    elif case == 'off':
        fixture['vm']['EnabledState'] = 3
    elif case == 'ambiguous':
        fixture['vm'] = [fixture['vm'], fixture['vm']]
    elif case == 'wrong_component':
        fixture['component']['SystemName'] = 'different'
    encoded = base64.b64encode(script.encode('utf-16-le')).decode()
    result = subprocess.run([host._powershell(), '-NoLogo', '-NoProfile', '-NonInteractive',
                             '-EncodedCommand', encoded], input=json.dumps(fixture).encode('ascii'),
                            capture_output=True, timeout=10, check=False)
    if case == 'ok':
        assert result.returncode == 0, result.stderr.decode(errors='replace')
        stamp, items = host._snapshot(result.stdout, b)
        assert stamp and wire.select_public_item(items, b) == encode_public_bootstrap(public_value)
    else:
        assert result.returncode == 2
        assert json.loads(result.stdout) == {'error': 'provider_refused'}


def test_sources_stay_out_of_existing_inspection_bundle_and_runtime():
    from night_shifts.inspection_bundle import FILES
    assert not {'public_bootstrap_host.py', 'public_bootstrap_kvp.py',
                'guest/publish_public_bootstrap.py'}.intersection(FILES)
    root = Path(host.__file__).parent
    for name in ('inspection_worker.py', 'maintenance_runner.py', 'image_finalization.py'):
        text = (root / name).read_text(encoding='utf-8')
        assert 'public_bootstrap_host' not in text and 'publish_public_bootstrap' not in text
    script = host.query_script(AttemptBinding('1' * 32, '00000000-0000-4000-8000-000000000001'))
    assert r'\\.\root\virtualization\v2' in script
    for forbidden in ('Get-VM', 'Start-VM', 'Stop-VM', 'Set-VM', 'InvokeMethod', 'AddKvpItems',
                      'GuestIntrinsicExchangeItems', 'SetSecurityInfo', 'Invoke-Expression'):
        assert forbidden not in script
