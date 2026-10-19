"""Offline policy/fault tests and disposable NON-SECRET Windows fixtures.

No elevation, protected anchor provisioning, production credentials, VM tokens,
Hyper-V, services, registry, deployment or inspection. Native positive tests
explicitly substitute current-user ownership and bypass production acquisition.
"""
from __future__ import annotations

import ast
import ctypes
import inspect
import os
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from night_shifts import maintenance_store_native_prototype as m
from night_shifts.maintenance_credentials_prototype import ADMINS_SID, FULL_CONTROL, SYSTEM_SID
from night_shifts.ubuntu_preparation_control import AclRule, AclSnapshot, _current_user_sid

ATTEMPT = 'a' * 32
USER = 'S-1-5-21-1-2-3-1001'


def observation(index=1, *, directory=True, **changes):
    flags = 3 if directory else 0
    value = m.Observation(
        m.FileIdentity(42, index), 0x10 if directory else 0x80, 1, 0,
        AclSnapshot(ADMINS_SID, (AclRule(SYSTEM_SID, FULL_CONTROL, flags),
                                AclRule(ADMINS_SID, FULL_CONTROL, flags))), True,
    )
    return replace(value, **changes)


@pytest.mark.parametrize('path', [
    '', '.', 'relative', r'C:relative', 'C:\\', r'\\server\share\anchor',
    r'\\?\C:\anchor', r'\\.\C:\anchor', 'C:/anchor', 'C:\\anchor\\',
    r'C:\anchor\\child', r'C:\anchor\..\child', r'C:\anchor\.\child',
    r'C:\anchor:stream', r'C:\anchor\CON', r'C:\anchor\nul.txt',
    r'C:\anchor\LPT1', r'C:\anchor\com9.ext', 'C:\\anchor ', 'C:\\anchor.',
    'C:\\an\x00chor', r'C:\anchor\*', r'C:\anchor\?', r'C:\anchor\a|b',
    'C:\\' + 'x' * 121, 'C:\\' + ('abcde\\' * 50) + 'z',
    None, 12,
])
def test_paths_refuse_before_native_calls(path, monkeypatch):
    monkeypatch.setattr(m, '_Windows', lambda: pytest.fail('native call before input refusal'))
    with pytest.raises(m.NativeStoreRefused):
        m.probe_new_store(path, ATTEMPT)


def test_path_parts_preserve_exact_components():
    assert m._path_parts(r'C:\Program Files\Host Store') == ('C:\\', ('Program Files', 'Host Store'))


@pytest.mark.parametrize('attempt', ['', 'A' * 32, 'a' * 31, 'a' * 33, '../x', None, 1])
def test_attempt_refused_before_native_calls(attempt, monkeypatch):
    monkeypatch.setattr(m, '_Windows', lambda: pytest.fail('native call before input refusal'))
    with pytest.raises(m.NativeStoreRefused, match='attempt_id'):
        m.probe_new_store(r'C:\anchor', attempt)


def test_admin_gate_precedes_path_opens(monkeypatch):
    def refuse():
        raise m.NativeStoreRefused('enabled_administrator_required')
    monkeypatch.setattr(m, '_Windows', lambda: SimpleNamespace(require_admin=refuse))
    with pytest.raises(m.NativeStoreRefused, match='enabled_administrator_required'):
        m.probe_new_store(r'C:\anchor', ATTEMPT)


@pytest.mark.parametrize('directory', [True, False])
def test_exact_production_profile_passes_model_only(directory):
    m._check_private(observation(directory=directory), directory=directory)
    sddl = m._sddl(directory=directory)
    assert sddl == ('O:BAG:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)' if directory else
                    'O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)')


@pytest.mark.parametrize('change', [
    {'protected': False}, {'links': 2}, {'identity': m.FileIdentity(42, 0)},
    {'attributes': 0}, {'attributes': 0x410}, {'attributes': 0x210},
    {'attributes': 0x810}, {'attributes': 0x1010}, {'attributes': 0x4010},
    {'acl': AclSnapshot(USER, (AclRule(USER, FULL_CONTROL, 3),))},
    {'acl': AclSnapshot(ADMINS_SID, ())},
    {'acl': AclSnapshot(ADMINS_SID, (AclRule(SYSTEM_SID, FULL_CONTROL, 3),
                                   AclRule(ADMINS_SID, FULL_CONTROL, 3),
                                   AclRule('S-1-1-0', 0x120089, 3)))},
    {'acl': AclSnapshot(ADMINS_SID, (AclRule(SYSTEM_SID, FULL_CONTROL, 3),
                                   AclRule(ADMINS_SID, FULL_CONTROL, 0x13)))},
])
def test_private_security_shape_refusals(change):
    with pytest.raises(m.NativeStoreRefused):
        m._check_private(observation(**change), directory=True)


@pytest.mark.parametrize('mask', [0x40, 0x10000, 0x40000, 0x80000, 0x40000000,
                                   0x10000000, 0x100, 0x10])
def test_untrusted_ancestor_mutation_rights_refused(mask):
    before = observation()
    acl = replace(before.acl, rules=before.acl.rules + (AclRule(USER, mask),))
    with pytest.raises(m.NativeStoreRefused, match='ancestor_security'):
        m._check_ancestor(replace(before, acl=acl))


@pytest.mark.parametrize('rule', [AclRule(USER, 0x1200A9), AclRule(USER, 6),
                                  AclRule(USER, FULL_CONTROL, 0x0B)])
def test_ancestor_read_sibling_creation_or_inherit_only(rule):
    before = observation()
    m._check_ancestor(replace(before, acl=replace(before.acl, rules=before.acl.rules + (rule,))))


@pytest.mark.parametrize('change', [
    {'identity': m.FileIdentity(43, 1)}, {'identity': m.FileIdentity(42, 2)},
    {'links': 2}, {'size': 1}, {'protected': False}, {'attributes': 0x410},
    {'acl': AclSnapshot(USER, ())},
])
def test_identity_security_size_drift_refuses(change):
    before = observation()
    with pytest.raises(m.NativeStoreRefused, match='object_drift'):
        m._same(before, replace(before, **change))


def test_only_archive_and_expected_marker_size_change_are_accepted():
    before = observation(directory=False)
    after = replace(before, attributes=before.attributes | 0x20, size=len(m.MARKER))
    m._same(before, after, marker_written=True)
    with pytest.raises(m.NativeStoreRefused):
        m._same(before, after)


class FakeHandle:
    def __init__(self, name):
        self.name = name
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.closed = True


class FakeApi:
    def __init__(self, fault=''):
        self.fault = fault
        self.anchor = FakeHandle('anchor')
        self.values = {'anchor': observation(1), 'store': observation(2),
                       'leaf': observation(3, directory=False)}
        self.counts = dict.fromkeys(self.values, 0)
        self.created = []
        self.writes = 0

    def observe(self, handle):
        name = handle.name
        self.counts[name] += 1
        value = self.values[name]
        if self.fault == name + '_drift' and self.counts[name] == 2:
            return replace(value, protected=False)
        if name == 'leaf' and self.fault == 'nonempty':
            return replace(value, size=1)
        if name == 'leaf' and self.fault == 'broad_acl':
            return replace(value, acl=replace(value.acl, rules=value.acl.rules +
                                              (AclRule('S-1-1-0', 0x120089),)))
        return value

    def relative(self, parent, name, **options):
        assert options['create'] is True and options['writable'] is True
        if self.fault == 'collision':
            raise m.NativeStoreRefused('relative_create', 183)
        kind = 'store' if options['directory'] else 'leaf'
        assert name == ('native-probe-' + ATTEMPT if kind == 'store' else 'probe.bin')
        assert options['sddl'] == m._sddl(directory=options['directory'])
        handle = FakeHandle(kind)
        self.created.append(handle)
        return handle

    def write_marker(self, handle):
        assert handle.name == 'leaf'
        self.writes += 1
        if self.fault == 'write_failure':
            raise m.NativeStoreRefused('marker_write', 5)
        self.values['leaf'] = replace(self.values['leaf'], size=len(m.MARKER))


def test_mocked_flow_writes_once_and_closes_handles():
    api = FakeApi()
    with ExitStack() as stack:
        result = m._probe_on_anchor(api, stack, [(api.anchor, api.values['anchor'])], ATTEMPT)
    assert result == m.MarkerResult(m.FileIdentity(42, 2), m.FileIdentity(42, 3), len(m.MARKER))
    assert api.writes == 1 and all(item.closed for item in api.created)


@pytest.mark.parametrize('fault', ['anchor_drift', 'store_drift', 'leaf_drift',
                                   'nonempty', 'broad_acl', 'collision', 'write_failure'])
def test_mocked_faults_never_retry_or_write_after_prewrite_refusal(fault):
    api = FakeApi(fault)
    with pytest.raises(m.NativeStoreRefused), ExitStack() as stack:
        m._probe_on_anchor(api, stack, [(api.anchor, api.values['anchor'])], ATTEMPT)
    assert api.writes == (1 if fault == 'write_failure' else 0)
    assert len(api.created) <= 2 and all(item.closed for item in api.created)


@pytest.fixture
def native(tmp_path, monkeypatch):
    if os.name != 'nt':
        pytest.skip('disposable Windows NTFS fixture only')
    if ctypes.windll.shell32.IsUserAnAdmin():
        pytest.skip('fixture must run unelevated')
    api = m._Windows()
    sid = _current_user_sid()

    def fixture_sddl(*, directory):
        flags = 'OICI' if directory else ''
        return f'O:{sid}G:{sid}D:P(A;{flags};FA;;;{sid})'

    def fixture_private(value, *, directory):
        m._check_shape(value, directory=directory)
        expected = AclSnapshot(sid, (AclRule(sid, FULL_CONTROL, 3 if directory else 0),))
        if value.acl != expected or not value.protected:
            raise m.NativeStoreRefused('fixture_security')

    monkeypatch.setattr(m, '_sddl', fixture_sddl)
    monkeypatch.setattr(m, '_check_private', fixture_private)
    # Test-owned temporary parent acquired directly. This deliberately does NOT
    # exercise production anchor acquisition or claim its ancestor/token proof.
    access = m._READ_CONTROL | m._READ_ATTRIBUTES | m._SYNCHRONIZE | 0x26
    raw = api.k.CreateFileW(str(tmp_path), access, 3, None, 3, 0x02200000, None)
    assert raw not in (None, ctypes.c_void_p(-1).value)
    with ExitStack() as outer:
        parent = outer.enter_context(m._Handle(api, raw))
        anchor = outer.enter_context(api.relative(parent, 'fixture-anchor', directory=True,
                                                  create=True, sddl=fixture_sddl(directory=True),
                                                  writable=True))
        baseline = api.observe(anchor)
        fixture_private(baseline, directory=True)
        yield api, anchor, baseline, tmp_path / 'fixture-anchor'


def test_native_marker_create_readback_and_collision_retains_bytes(native):
    api, anchor, baseline, path = native
    with ExitStack() as stack:
        result = m._probe_on_anchor(api, stack, [(anchor, baseline)], ATTEMPT)
    leaf = path / ('native-probe-' + ATTEMPT) / 'probe.bin'
    assert leaf.read_bytes() == m.MARKER
    assert result.marker_bytes == len(m.MARKER) and result.store != result.marker
    with pytest.raises(m.NativeStoreRefused) as failure, ExitStack() as stack:
        m._probe_on_anchor(api, stack, [(anchor, api.observe(anchor))], ATTEMPT)
    assert failure.value.winerror in (80, 183)
    assert leaf.read_bytes() == m.MARKER


@pytest.mark.parametrize('access', [0x80000000, 0x40000000, 0xC0000000],
                         ids=['read', 'write', 'read-write'])
def test_native_exclusive_leaf_blocks_other_data_open(native, access):
    api, anchor, _, path = native
    with ExitStack() as stack:
        leaf = stack.enter_context(api.relative(anchor, 'probe.bin', directory=False, create=True,
                                                sddl=m._sddl(directory=False), writable=True))
        api.write_marker(leaf)
        # relative(..., writable=False) requests METADATA, not file data.
        # Use independent native data-access opens and retain the numeric error;
        # Python's CRT-backed open can discard the underlying Win32 error code.
        raw = api.k.CreateFileW(str(path / 'probe.bin'), access, 7, None, 3, 0x00200000, None)
        error = ctypes.get_last_error()
        if raw not in (None, ctypes.c_void_p(-1).value):
            with m._Handle(api, raw):  # always close an unexpected success
                pytest.fail('exclusive leaf allowed another data-access handle')
        assert error == 32


def test_native_share_zero_still_allows_metadata_only_handle(native):
    api, anchor, _, _ = native
    with ExitStack() as stack:
        leaf = stack.enter_context(api.relative(anchor, 'probe.bin', directory=False, create=True,
                                                sddl=m._sddl(directory=False), writable=True))
        api.write_marker(leaf)
        with api.relative(anchor, 'probe.bin', directory=False, create=False) as metadata:
            assert api.observe(metadata).identity == api.observe(leaf).identity


def test_native_hardlinked_file_is_refused(native):
    api, anchor, _, path = native
    with api.relative(anchor, 'probe.bin', directory=False, create=True,
                      sddl=m._sddl(directory=False), writable=True) as leaf:
        api.write_marker(leaf)
    os.link(path / 'probe.bin', path / 'alias.bin')
    with api.relative(anchor, 'probe.bin', directory=False, create=False) as leaf:
        value = api.observe(leaf)
        assert value.links == 2
        with pytest.raises(m.NativeStoreRefused, match='object_shape'):
            m._check_shape(value, directory=False)


def test_native_reparse_target_is_not_followed(native):
    api, anchor, _, path = native
    target = path / 'target.bin'
    target.write_bytes(m.MARKER)
    try:
        (path / 'linked.bin').symlink_to(target)
    except OSError:
        pytest.skip('unelevated symlink creation unavailable')
    with pytest.raises(m.NativeStoreRefused):
        with api.relative(anchor, 'linked.bin', directory=False, create=False) as leaf:
            m._check_shape(api.observe(leaf), directory=False)
    assert target.read_bytes() == m.MARKER


def test_native_public_entry_refuses_unelevated_before_any_creation():
    if os.name != 'nt' or ctypes.windll.shell32.IsUserAnAdmin():
        pytest.skip('requires ordinary Windows token')
    with pytest.raises(m.NativeStoreRefused, match='enabled_administrator_required'):
        m.probe_new_store(r'C:\NOT-CREATED-host-store-probe', ATTEMPT)


def test_native_error_does_not_expose_path_or_payload():
    error = m.NativeStoreRefused('relative_open', 32)
    assert str(error) == 'relative_open: win32=32' and error.winerror == 32


def test_no_secret_payload_parameter_or_production_caller():
    assert list(inspect.signature(m.probe_new_store).parameters) == ['anchor_path', 'attempt_id']
    assert list(inspect.signature(m._Windows.write_marker).parameters) == ['self', 'handle']
    assert m.MARKER.startswith(b'NON-SECRET')
    root = Path(__file__).resolve().parents[2]
    for path in (root / 'night_shifts').rglob('*.py'):
        if path.name == 'maintenance_store_native_prototype.py':
            continue
        tree = ast.parse(path.read_text(encoding='utf-8-sig'))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert 'maintenance_store_native_prototype' not in (node.module or '')
                assert all(alias.name != 'maintenance_store_native_prototype' for alias in node.names)
            elif isinstance(node, ast.Import):
                assert all('maintenance_store_native_prototype' not in alias.name for alias in node.names)
