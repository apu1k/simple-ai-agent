"""Synthetic /dev/kmsg FORMAT tests only; no Linux access or native evidence."""
from __future__ import annotations

import ast
import errno
import io
import re
import zipfile
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from night_shifts import bootstrap_native_denials as denial

CASES = {
    'runtime_write': ('open', '/run/night-shift-bootstrap/denied-write', 'w'),
    'pool_sibling_write': ('open', '/var/lib/hyperv/.kvp_pool_denied', 'w'),
    'outside_exec': ('exec', '/run/night-shift-bootstrap/denied-exec', 'x'),
}


def record(case='runtime_write', *, sequence=41, timestamp=1001, pid=123, **changes):
    operation, path, mask = CASES[case]
    fields = dict(apparmor='DENIED', operation=operation, profile=denial.PROFILE,
                  name=path, pid=str(pid), comm='SYNTHETIC_CANARY', requested_mask=mask,
                  denied_mask=mask, fsuid='0', ouid='0')
    fields.update(changes)
    body = ' '.join(key + '="' + value + '"' for key, value in fields.items() if value is not None)
    return (f'4,{sequence},{timestamp},-;audit: type=1400 audit(1760000000.001:71): '
            + body + '\n').encode('ascii')


def correlate(raw=None, **changes):
    arguments = dict(worker_pid=123, syscall_errno=errno.EACCES, baseline_sequence=40,
                     start_us=1000, end_us=2000, records=(record() if raw is None else raw,))
    arguments.update(changes)
    return denial.correlate_local_denial('runtime_write', **arguments)


def refuses(reason, call):
    with pytest.raises(denial.NativeDenialRefused, match='^' + reason + '$') as caught:
        call()
    assert 'SYNTHETIC_CANARY' not in str(caught.value)


@pytest.mark.parametrize('case', CASES)
def test_fixed_cases_correlate_without_claiming_native_or_host_success(case):
    result = denial.correlate_local_denial(
        case, worker_pid=123, syscall_errno=errno.EACCES, baseline_sequence=40,
        start_us=1000, end_us=2000, records=(record(case),))
    assert result == denial.LocalDenialCorrelation(case, 123, 41, 71)
    assert set(vars(result)) == {'case_id', 'worker_pid', 'kernel_sequence', 'audit_serial'}
    assert 'SYNTHETIC_CANARY' not in repr(result)
    with pytest.raises(FrozenInstanceError):
        result.worker_pid = 456


@pytest.mark.parametrize('fields', [{}, {'class': 'file'}, {'error': '-13'},
                                    {'class': 'file', 'error': '-13'}])
def test_optional_native_fields_do_not_weaken_exact_required_match(fields):
    assert correlate(record(**fields)).kernel_sequence == 41


def test_exact_unquoted_numeric_fields_and_no_final_newline_are_supported():
    raw = record().replace(b'pid="123"', b'pid=123').replace(b'fsuid="0"', b'fsuid=0')
    assert correlate(raw.rstrip(b'\n')).worker_pid == 123


def test_complete_capture_can_contain_unrelated_records_and_other_pids():
    records = (b'14,41,1000,-;ordinary userspace notice\n',
               record(sequence=42, pid=456), record(sequence=43, timestamp=2000))
    assert correlate(records=records).kernel_sequence == 43


@pytest.mark.parametrize('case', ['network', 'capability', '', '/arbitrary', None, True, [], {}])
def test_no_arbitrary_path_or_unsupported_denial_case(case):
    refuses('case', lambda: denial.correlate_local_denial(
        case, worker_pid=123, syscall_errno=13, baseline_sequence=40,
        start_us=1000, end_us=2000, records=(record(),)))


@pytest.mark.parametrize('changes', [
    {'worker_pid': True}, {'worker_pid': 0}, {'worker_pid': -1},
    {'worker_pid': 1 << 22}, {'worker_pid': '123'}, {'syscall_errno': True},
    {'syscall_errno': 0}, {'syscall_errno': errno.EPERM},
    {'syscall_errno': errno.ENOENT}, {'syscall_errno': errno.EROFS},
    {'syscall_errno': '13'},
])
def test_wrong_errno_or_pid_never_counts_as_attributed_denial(changes):
    refuses('syscall_observation', lambda: correlate(**changes))


@pytest.mark.parametrize('changes', [
    {'baseline_sequence': True}, {'baseline_sequence': -1},
    {'baseline_sequence': denial.MAX_COUNTER}, {'start_us': True},
    {'start_us': -1}, {'end_us': 999}, {'end_us': 5_001_001},
    {'end_us': denial.MAX_COUNTER + 1}, {'end_us': 2000.0},
])
def test_capture_window_and_counter_bounds(changes):
    refuses('capture_window', lambda: correlate(**changes))


@pytest.mark.parametrize('records', [
    (), [], [b'x'], (b'',), ('not-bytes',), (bytearray(b'x'),),
    (b'x' * (denial.MAX_RECORD_BYTES + 1),), (b'x',) * (denial.MAX_RECORDS + 1),
    (b'x' * denial.MAX_RECORD_BYTES,) * 9,
], ids=['empty', 'list-empty', 'list', 'empty-record', 'text', 'bytearray',
        'record-overflow', 'count-overflow', 'total-overflow'])
def test_capture_bounds_before_parsing(records):
    refuses('capture_bound', lambda: correlate(records=records))


@pytest.mark.parametrize('raw', [
    b'not kmsg', b'4,41,1001,c;continued', b'4,41,1001,-;a\nb',
    b'4,41,1001,-;\xff', b'192,41,1001,-;message',
    b'4,18446744073709551616,1001,-;message',
    b'4,41,18446744073709551616,-;message',
], ids=['header', 'continuation', 'multiple-lines', 'encoding', 'priority',
        'sequence-overflow', 'timestamp-overflow'])
def test_invalid_kernel_record_is_not_reinterpreted(raw):
    refuses('kernel_record', lambda: correlate(raw))


@pytest.mark.parametrize('records', [
    (record(sequence=42),), (record(sequence=40),),
    (record(), record()), (record(), record(sequence=43)),
], ids=['missing-first', 'stale', 'duplicate', 'gap'])
def test_sequence_gaps_duplicates_or_stale_records_stop(records):
    refuses('capture_gap', lambda: correlate(records=records))


@pytest.mark.parametrize('records', [
    (record(timestamp=999),), (record(timestamp=2001),),
    (record(timestamp=1500), record(sequence=42, timestamp=1499)),
], ids=['before-window', 'after-window', 'time-regression'])
def test_monotonic_capture_interval(records):
    refuses('capture_time', lambda: correlate(records=records))


@pytest.mark.parametrize('priority', [8, 12, 14, 191])
def test_userspace_facility_cannot_spoof_kernel_audit_origin(priority):
    refuses('audit_origin', lambda: correlate(record().replace(b'4,41,', f'{priority},41,'.encode())))


@pytest.mark.parametrize('fields', [
    {'apparmor': 'ALLOWED'}, {'apparmor': 'AUDIT'}, {'operation': 'mknod'},
    {'profile': 'unconfined'}, {'profile': denial.PROFILE + '//stack'},
    {'name': '/tmp/SYNTHETIC_CANARY'}, {'name': None}, {'requested_mask': 'rw'},
    {'denied_mask': 'r'}, {'fsuid': '1000'}, {'ouid': '1000'},
    {'class': 'net'}, {'error': '-1'},
])
def test_same_worker_must_match_exact_label_operation_object_and_access(fields):
    refuses('denial_mismatch', lambda: correlate(record(**fields)))


@pytest.mark.parametrize('mutate', [
    lambda raw: raw.replace(b' pid="123"', b' pid="123" pid="123"'),
    lambda raw: raw.replace(b'pid="123"', b'pid="0123"'),
    lambda raw: raw.replace(b'pid="123"', b'pid="0"'),
    lambda raw: raw.replace(b' pid="123"', b''),
    lambda raw: raw.replace(b'SYNTHETIC_CANARY', b'bad\\escape'),
    lambda raw: raw.replace(b'SYNTHETIC_CANARY', b'bad\tcontrol'),
    lambda raw: raw.replace(b'SYNTHETIC_CANARY', b'unclosed"quote'),
    lambda raw: raw.replace(b' ouid=', b'  ouid='),
    lambda raw: raw.replace(b'audit: type=1400', b'type=1400'),
    lambda raw: raw.replace(b'.001:71', b'.001:0'),
    lambda raw: raw.replace(b'.001:71', b'.001:18446744073709551616'),
], ids=['duplicate-key', 'noncanonical-pid', 'zero-pid', 'missing-pid', 'escape',
        'control', 'quote', 'spacing', 'audit-prefix', 'zero-serial', 'serial-overflow'])
def test_malformed_audit_is_not_leniently_salvaged(mutate):
    refuses('audit_shape', lambda: correlate(mutate(record())))


def test_no_audit_no_matching_pid_and_duplicate_denials_are_not_success():
    refuses('denial_missing', lambda: correlate(b'4,41,1001,-;ordinary notice\n'))
    refuses('denial_missing', lambda: correlate(record(pid=456)))
    refuses('denial_ambiguous', lambda: correlate(records=(record(), record(sequence=42))))


def test_unexpected_same_worker_event_cannot_hide_beside_a_matching_one():
    refuses('denial_mismatch', lambda: correlate(
        records=(record(), record(sequence=42, operation='unlink'))))


def test_input_record_order_field_order_and_boundary_window():
    raw = record()
    prefix, fields = raw.decode().rstrip('\n').split(': apparmor=', 1)
    fields = 'apparmor=' + fields
    tokens = re.findall(r'[a-z_]+="[^"]*"', fields)
    reordered = (prefix + ': ' + ' '.join(reversed(tokens))).encode()
    assert correlate(reordered, start_us=1001, end_us=1001).kernel_sequence == 41
    assert correlate(end_us=5_001_000).kernel_sequence == 41


def test_component_has_no_native_io_entrypoint_or_transitive_runtime_import():
    source = Path(denial.__file__).read_text(encoding='utf-8')
    tree = ast.parse(source)
    imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    imports |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import)
                for alias in node.names}
    assert imports == {'__future__', 'errno', 're', 'dataclasses'}
    assert not any(isinstance(node, ast.Name) and node.id in
                   {'open', 'exec', 'eval', 'compile', '__import__'} for node in ast.walk(tree))
    assert not any(isinstance(node, ast.FunctionDef) and node.name in {'main', 'boot', 'run'}
                   for node in ast.walk(tree))


def test_component_is_excluded_from_actual_in_memory_support_and_inspection_inventory():
    from night_shifts.bootstrap_probe_seed import ENTRY_NAMES
    from night_shifts.inspection_bundle import bundle_bytes

    entry = 'night_shifts/bootstrap_native_denials.py'
    assert entry not in ENTRY_NAMES
    with zipfile.ZipFile(io.BytesIO(bundle_bytes())) as archive:
        assert entry not in archive.namelist()
