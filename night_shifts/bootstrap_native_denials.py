"""Offline/local AppArmor audit correlation, NOT a validator or host receipt.

Pure bounded parsing only: no guest entry point, syscalls, log reads, execution,
policy loading, media writes or runtime evidence acceptance. The future separately
reviewed guest supervisor must establish an authentic lossless /dev/kmsg capture,
worker identity/lifetime, otherwise-valid RAM fixtures and the exact loaded policy.
Caller-provided records (including synthetic tests) establish NONE of that trust.
This module is deliberately absent from the public support seed/inspection bundle.
"""
from __future__ import annotations

import errno
import re
from dataclasses import dataclass

PROFILE = 'night-shift-kvp-public-probe'
MAX_RECORD_BYTES = 8192
MAX_RECORDS = 64
MAX_CAPTURE_BYTES = 65536
MAX_WINDOW_US = 5_000_000
MAX_COUNTER = (1 << 64) - 1
# Fixed future guest RAM objects, not caller-selected paths/commands. They must
# be prepared and positively controlled BEFORE confinement in a validation-only
# VM. They intentionally do not belong in the production probe's fresh RAM view.
_CASES = {
    'runtime_write': ('open', '/run/night-shift-bootstrap/denied-write', 'w'),
    'pool_sibling_write': ('open', '/var/lib/hyperv/.kvp_pool_denied', 'w'),
    'outside_exec': ('exec', '/run/night-shift-bootstrap/denied-exec', 'x'),
}
_HEADER = re.compile(rb'([0-9]{1,3}),([0-9]{1,20}),([0-9]{1,20}),-;([^\r\n]+)\n?')
_AUDIT = re.compile(r'audit: type=1400 audit\(([0-9]{1,12})\.([0-9]{1,9}):([0-9]{1,20})\): (.+)')
_FIELD = re.compile(r'([a-z][a-z0-9_]*)=(?:"([^"\\\r\n]*)"|([A-Za-z0-9_./:+()\-]+))(?: |$)')


class NativeDenialRefused(RuntimeError):
    """Fixed reason only; never echo raw kernel records, paths or tool output."""


@dataclass(frozen=True)
class LocalDenialCorrelation:
    """Local consistency observation only; NOT native success or VM provenance."""

    case_id: str
    worker_pid: int
    kernel_sequence: int
    audit_serial: int


def _integer(value: object, lower: int, upper: int) -> bool:
    return type(value) is int and lower <= value <= upper


def _fields(raw: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    position = 0
    while position < len(raw):
        match = _FIELD.match(raw, position)
        if match is None or match[1] in fields:
            raise NativeDenialRefused('audit_shape')
        value = match[2] if match[2] is not None else match[3]
        # No escapes, hex-encoded paths, control bytes or alternate audit syntax.
        # Unknown native formats must stop for review, not broaden attribution.
        if value is None or any(ord(char) < 32 or ord(char) > 126 for char in value):
            raise NativeDenialRefused('audit_shape')
        fields[match[1]] = value
        position = match.end()
    return fields


def correlate_local_denial(
    case_id: str, *, worker_pid: int, syscall_errno: int,
    baseline_sequence: int, start_us: int, end_us: int, records: tuple[bytes, ...],
) -> LocalDenialCorrelation:
    """Correlate ONE fixed EACCES operation with ONE exact local audit denial.

    `records` is a complete, ordered, lossless /dev/kmsg interval beginning just
    after `baseline_sequence`; timestamps are kernel monotonic microseconds.
    The future supervisor must capture the boundary before releasing one fresh
    worker, keep that exact PID unreaped through collection, and bound the whole
    attempt independently. This function cannot authenticate those assertions.

    Unsupported cases (notably network/capability), continuation/overflow/gaps,
    missing or ambiguous audit records and wrong errno refuse attribution. A
    refusal does not prove the operation was allowed, safe, rolled back or that
    any worker/VM stopped. No raw record is returned or included in exceptions.
    """
    if type(case_id) is not str or case_id not in _CASES:
        raise NativeDenialRefused('case')
    if (not _integer(worker_pid, 1, (1 << 22) - 1)
            or type(syscall_errno) is not int or syscall_errno != errno.EACCES):
        raise NativeDenialRefused('syscall_observation')
    if (not _integer(baseline_sequence, 0, MAX_COUNTER - MAX_RECORDS)
            or not _integer(start_us, 0, MAX_COUNTER)
            or not _integer(end_us, 0, MAX_COUNTER)
            or not 0 <= end_us - start_us <= MAX_WINDOW_US):
        raise NativeDenialRefused('capture_window')
    if (type(records) is not tuple or not 1 <= len(records) <= MAX_RECORDS
            or any(type(raw) is not bytes or not 0 < len(raw) <= MAX_RECORD_BYTES for raw in records)
            or sum(map(len, records)) > MAX_CAPTURE_BYTES):
        raise NativeDenialRefused('capture_bound')
    operation, path, mask = _CASES[case_id]
    matched: list[LocalDenialCorrelation] = []
    previous_us = start_us
    for index, raw in enumerate(records, 1):
        header = _HEADER.fullmatch(raw)
        if header is None:
            raise NativeDenialRefused('kernel_record')
        priority, sequence, timestamp = (int(header[n]) for n in (1, 2, 3))
        if priority > 191 or sequence > MAX_COUNTER or timestamp > MAX_COUNTER:
            raise NativeDenialRefused('kernel_record')
        if sequence != baseline_sequence + index:
            raise NativeDenialRefused('capture_gap')
        if not previous_us <= timestamp <= end_us:
            raise NativeDenialRefused('capture_time')
        previous_us = timestamp
        try:
            body = header[4].decode('ascii')
        except UnicodeError:
            raise NativeDenialRefused('kernel_record') from None
        if 'apparmor=' not in body and 'type=1400' not in body:
            continue
        # Facility zero is kernel-origin; userspace /dev/kmsg writes receive a
        # nonzero facility even if their body imitates an AppArmor audit line.
        if priority > 7:
            raise NativeDenialRefused('audit_origin')
        audit = _AUDIT.fullmatch(body)
        if audit is None or not 0 < int(audit[3]) <= MAX_COUNTER:
            raise NativeDenialRefused('audit_shape')
        fields = _fields(audit[4])
        pid = fields.get('pid', '')
        if not re.fullmatch(r'[1-9][0-9]{0,6}', pid):
            raise NativeDenialRefused('audit_shape')
        if int(pid) != worker_pid:
            continue
        required = {
            'apparmor': 'DENIED', 'operation': operation, 'profile': PROFILE,
            'name': path, 'requested_mask': mask, 'denied_mask': mask,
            'fsuid': '0', 'ouid': '0',
        }
        if (any(fields.get(key) != value for key, value in required.items())
                or ('class' in fields and fields['class'] != 'file')
                or ('error' in fields and fields['error'] != '-13')):
            raise NativeDenialRefused('denial_mismatch')
        matched.append(LocalDenialCorrelation(case_id, worker_pid, sequence, int(audit[3])))
    if len(matched) != 1:
        raise NativeDenialRefused('denial_missing' if not matched else 'denial_ambiguous')
    return matched[0]
