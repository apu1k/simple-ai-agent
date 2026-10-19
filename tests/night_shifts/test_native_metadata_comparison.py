"""Metadata policy/report tests and ordinary disposable native observations.

No protected fixture Run(), elevation, credentials or VM use. Models are not
attestation. Native reproduction uses only the current user's temp directory.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from night_shifts import maintenance_store_native_prototype as m
from night_shifts.maintenance_credentials_prototype import ADMINS_SID, FULL_CONTROL, SYSTEM_SID
from night_shifts.ubuntu_preparation_control import AclRule, AclSnapshot

ROOT = Path(__file__).resolve().parents[2]
USER = 'S-1-5-21-1-2-3-1001'


def observation(*, directory=True, **changes):
    flags = 3 if directory else 0
    value = m.Observation(
        m.FileIdentity(7, 42), 0x10 if directory else 0x20, 1, 0,
        AclSnapshot(ADMINS_SID, (AclRule(SYSTEM_SID, FULL_CONTROL, flags),
                                AclRule(ADMINS_SID, FULL_CONTROL, flags))), True,
    )
    return replace(value, **changes)


@pytest.mark.parametrize('before_size,after_size', [(0, 4096), (4096, 8192), (8192, 4096),
                                                   (4096, 0), (0, 2**64 - 1)])
def test_directory_storage_is_recorded_not_treated_as_content(before_size, after_size):
    before = observation(size=before_size)
    after = replace(before, size=after_size)
    report = m.compare_metadata(before, after, object_label='store')
    assert report.matches and report.differences == () and report.refusals == ()
    assert report.directory_storage_bytes == (before_size, after_size)
    value = json.loads(report.to_json())
    assert value['object'] == 'store' and value['scope'] == 'supplied_metadata_only'
    assert value['directory_storage_bytes'] == [before_size, after_size]
    assert value['acceptance'] is False
    m._same(before, after, object_label='store')


@pytest.mark.parametrize('directory', [False, True])
def test_unchanged_metadata_report_not_an_authorization(directory):
    before = observation(directory=directory)
    report = m.compare_metadata(before, before)
    assert report.matches and report.directory_storage_bytes is None
    assert json.loads(report.to_json())['acceptance'] is False


@pytest.mark.parametrize('after_size', [0, 1, 4096, 2**64 - 1])
def test_regular_file_size_remains_exact(after_size):
    before = observation(directory=False, size=49)
    after = replace(before, size=after_size)
    report = m.compare_metadata(before, after, object_label='marker')
    assert not report.matches and ('file_size', 49, after_size) in report.differences
    assert report.directory_storage_bytes is None


@pytest.mark.parametrize('field,changes', [
    ('identity', {'identity': m.FileIdentity(8, 42)}),
    ('identity', {'identity': m.FileIdentity(7, 43)}),
    ('attributes', {'attributes': 0x11}),
    ('links', {'links': 2}),
    ('owner', {'acl': AclSnapshot(USER, (AclRule(SYSTEM_SID, FULL_CONTROL, 3),
                                        AclRule(ADMINS_SID, FULL_CONTROL, 3)))}),
    ('acl', {'acl': AclSnapshot(ADMINS_SID, (AclRule(SYSTEM_SID, FULL_CONTROL, 3),))}),
    ('protected', {'protected': False}),
])
def test_directory_growth_does_not_hide_real_metadata_drift(field, changes):
    before = observation()
    after = replace(before, size=4096, **changes)
    with pytest.raises(m.NativeStoreRefused, match='object_drift') as failure:
        m._same(before, after, object_label='ancestor_2')
    report = failure.value.comparison
    assert not report.matches and report.object_label == 'ancestor_2'
    assert field in [row[0] for row in report.differences]
    assert report.directory_storage_bytes == (0, 4096)
    assert str(failure.value) == 'object_drift'  # No arbitrary raw metadata text.


@pytest.mark.parametrize('before_dir,after_dir', [(False, True), (True, False)])
def test_object_kind_transition_cannot_use_directory_size_exception(before_dir, after_dir):
    before = observation(directory=before_dir)
    after = replace(before, attributes=0x10 if after_dir else 0x20, size=4096)
    report = m.compare_metadata(before, after)
    assert not report.matches and report.directory_storage_bytes is None
    assert {'kind', 'attributes', 'file_size'} <= {row[0] for row in report.differences}


@pytest.mark.parametrize('changes,reason', [
    ({'identity': m.FileIdentity(7, 0)}, 'zero_identity'),
    ({'links': 2}, 'multiple_links'),
    ({'attributes': 0x410}, 'reparse'),
    ({'attributes': 0x210}, 'unsupported_attributes'),
    ({'attributes': 0x810}, 'unsupported_attributes'),
    ({'attributes': 0x1010}, 'unsupported_attributes'),
    ({'attributes': 0x4010}, 'unsupported_attributes'),
])
def test_invalid_shape_is_not_accepted_merely_because_it_is_stable(changes, reason):
    value = observation(**changes)
    report = m.compare_metadata(value, value)
    assert not report.matches and report.differences == ()
    assert 'before_' + reason in report.refusals and 'after_' + reason in report.refusals


@pytest.mark.parametrize('directory', [False, True])
def test_archive_bit_is_not_ignored_outside_controlled_file_write(directory):
    before = observation(directory=directory)
    after = replace(before, attributes=before.attributes ^ 0x20)
    report = m.compare_metadata(before, after)
    assert not report.matches and report.archive_change is None
    assert report.differences[0][0] == 'attributes'


def test_controlled_marker_write_is_specific_and_keeps_other_checks():
    before = observation(directory=False, attributes=0x80)
    after = replace(before, attributes=0xA0, size=len(m.MARKER))
    report = m.compare_metadata(before, after, expected_file_size=len(m.MARKER),
                                allow_archive_change=True, object_label='marker')
    assert report.matches and report.archive_change == (0x80, 0xA0)
    assert report.expected_file_size == len(m.MARKER)
    m._same(before, after, marker_written=True, object_label='marker')
    changed_acl = replace(after, protected=False)
    assert not m.compare_metadata(before, changed_acl, expected_file_size=len(m.MARKER),
                                  allow_archive_change=True).matches
    wrong_attribute = replace(after, attributes=after.attributes | 1)
    assert not m.compare_metadata(before, wrong_attribute, expected_file_size=len(m.MARKER),
                                  allow_archive_change=True).matches
    wrong_length = replace(after, size=len(m.MARKER) + 1)
    report = m.compare_metadata(before, wrong_length, expected_file_size=len(m.MARKER),
                                allow_archive_change=True)
    assert ('file_size', 0, len(m.MARKER) + 1) in report.differences and not report.matches


def test_controlled_write_cannot_apply_to_directory_or_preexisting_content():
    directory = observation()
    report = m.compare_metadata(directory, replace(directory, size=4096), expected_file_size=49)
    assert not report.matches and 'controlled_write_not_regular' in report.refusals
    before = observation(directory=False, size=1)
    report = m.compare_metadata(before, replace(before, size=49), expected_file_size=49)
    assert not report.matches and 'controlled_write_not_empty' in report.refusals


@pytest.mark.parametrize('label', ['', 'A', '../store', r'C:\secret', 'a' * 33, 'secret\nvalue', None, 1])
def test_labels_are_fixed_bounded_object_names_not_arbitrary_paths(label):
    value = observation()
    with pytest.raises(m.NativeStoreRefused, match='metadata_policy'):
        m.compare_metadata(value, value, object_label=label)


@pytest.mark.parametrize('options', [
    {'expected_file_size': True}, {'expected_file_size': -1}, {'expected_file_size': 2**64},
    {'allow_archive_change': True}, {'allow_archive_change': 1},
])
def test_invalid_comparison_policy_refuses(options):
    value = observation()
    with pytest.raises(m.NativeStoreRefused, match='metadata_policy'):
        m.compare_metadata(value, value, **options)


@pytest.mark.parametrize('changes', [
    {'attributes': True}, {'attributes': -1}, {'attributes': 2**32},
    {'links': True}, {'links': -1}, {'links': 2**32},
    {'size': True}, {'size': -1}, {'size': 2**64}, {'protected': 1},
    {'identity': m.FileIdentity(True, 42)}, {'identity': m.FileIdentity(7, 2**64)},
    {'acl': AclSnapshot('not-a-sid', ())},
    {'acl': AclSnapshot(ADMINS_SID, cast(tuple[AclRule, ...], []))},
    {'acl': AclSnapshot(ADMINS_SID, tuple(AclRule(SYSTEM_SID, FULL_CONTROL) for _ in range(129)))},
    {'acl': AclSnapshot(ADMINS_SID, (AclRule(SYSTEM_SID, True),))},
    {'acl': AclSnapshot(ADMINS_SID, (AclRule(SYSTEM_SID, FULL_CONTROL, 256),))},
    {'acl': AclSnapshot(ADMINS_SID, (AclRule(SYSTEM_SID, FULL_CONTROL, 0, -1),))},
])
def test_metadata_schema_refuses_without_logging_unbounded_values(changes):
    before = observation()
    with pytest.raises(m.NativeStoreRefused, match='metadata_schema'):
        m.compare_metadata(before, replace(before, **changes))


def test_acl_changes_have_bounded_exact_ordered_fingerprints_not_raw_sddl():
    before = observation()
    after = replace(before, acl=replace(before.acl, rules=tuple(reversed(before.acl.rules))))
    report = m.compare_metadata(before, after)
    assert not report.matches and len(report.differences) == 1
    field, old, new = report.differences[0]
    assert field == 'acl' and old.startswith('2:') and new.startswith('2:') and old != new
    assert len(old) == len(new) == 66
    assert 'O:BA' not in report.to_json() and 'A;OICI' not in report.to_json()


def test_maximum_metadata_diff_report_fits_complete_capture_bound():
    sid = 'S-' + '1-' * 89 + '1111'
    assert len(sid) == 184
    rules = tuple(AclRule(sid, 2**32 - 1, 255, 255) for _ in range(128))
    before = observation(acl=AclSnapshot(sid, rules))
    after = replace(before, identity=m.FileIdentity(2**32 - 1, 2**64 - 1),
                    attributes=0x410, links=2**32 - 1, size=2**64 - 1, protected=False,
                    acl=AclSnapshot(sid[:-1] + '2', rules[:-1]))
    report = m.compare_metadata(before, after, object_label='a' * 32)
    raw = report.to_json()
    assert not report.matches and len(raw) <= 3000 and len(raw.encode('utf-8')) <= 3000
    decoded = json.loads(raw)
    assert decoded['acceptance'] is False and len(decoded['differences']) >= 5
    assert decoded['directory_storage_bytes'] == [0, 2**64 - 1]


def test_manually_constructed_oversize_report_is_refused_not_truncated():
    report = m.MetadataComparison('object', (('owner', 'x' * 4000, 'y'),), (), None, None, None)
    with pytest.raises(m.NativeStoreRefused, match='metadata_report_size'):
        report.to_json()


def test_ordinary_native_directory_growth_report(tmp_path):
    if os.name != 'nt':
        pytest.skip('Windows native GetFileInformationByHandle reproduction')
    if ctypes.windll.shell32.IsUserAnAdmin():
        pytest.skip('NEVER elevate the disposable metadata reproduction')
    api = m._Windows()
    path = tmp_path / 'nonsecret-directory'
    path.mkdir()
    raw = api.k.CreateFileW(str(path), 0x1200A0, 3, None, 3, 0x02200000, None)
    assert raw not in (None, ctypes.c_void_p(-1).value)
    with m._Handle(api, raw) as handle:
        before = api.observe(handle)
        for index in range(12):
            (path / f'fixed-public-entry-{index:02d}.bin').write_bytes(b'NON-SECRET directory metadata test\n')
        after = api.observe(handle)
        assert before.identity == after.identity and before.acl == after.acl
        assert before.attributes == after.attributes and before.links == after.links
        assert before.protected == after.protected
        if after.size == before.size:
            pytest.skip('this disposable directory did not grow; native size exception not exercised')
        report = m.compare_metadata(before, after, object_label='temp_directory')
        assert report.matches and report.directory_storage_bytes == (before.size, after.size)
        assert len(report.to_json().encode('utf-8')) <= 3000
        m._same(before, after, object_label='temp_directory')


def test_executed_powershell_sources_remain_frozen():
    cases = [
        ('validate_native_store_privileged_fixture.ps1', 'AuthorizeNonSecretNativeStoreFixtureV1',
         '41aaea7abbd0f08720e224b67e1fbdb42f25e4f115db07f0a426a1f0761df02d'),
        ('validate_native_store_guard_checks.ps1', 'AuthorizeNewNativeStoreGuardFixtureV1',
         '9f25e268d29fabc5103a053e9fc1904f5825b66c0347ed895aac545bca8c9bfb'),
    ]
    for name, flag, expected in cases:
        raw = '& {\n' + (ROOT / 'scripts' / name).read_text(encoding='utf-8-sig') + '\n} -' + flag + '\n'
        assert hashlib.sha256(raw.encode('utf-8')).hexdigest() == expected
