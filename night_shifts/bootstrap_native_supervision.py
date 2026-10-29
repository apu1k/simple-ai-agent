"""Offline supervision protocol core, NOT a runnable native validator.

Pure bounded worker-report/state evaluation and paired local audit correlation.
No process creation, gate write, wait/reap, log capture, fixture/media/policy I/O,
CLI, host receipt or deployment entry. Caller-supplied observations, clocks and
records cannot establish native provenance, unreaped PID ownership or VM absence.
"""
from __future__ import annotations

import errno
import json
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import NoReturn

from night_shifts.bootstrap_native_denials import NativeDenialRefused, correlate_local_denial
from night_shifts.maintenance_tls_prototype import AttemptBinding

CASES = ('runtime_write', 'pool_sibling_write', 'outside_exec')
MAX_FRAME_BYTES = 256  # Includes the worker's newline.
MAX_REPORT_BYTES = 512
MAX_WORKER_SECONDS = 5
_MAX_PID = (1 << 22) - 1


class NativeSupervisionRefused(RuntimeError):
    """Fixed label only; no worker bytes, raw audit data or native paths."""


class NativeSupervisionUnknown(NativeSupervisionRefused):
    """Missing/uncertain observation; not failure rollback or cleanup evidence."""


@dataclass(frozen=True)
class LocalWorkerObservation:
    """Local consistency data, NOT a trusted native execution/exit receipt."""

    binding: AttemptBinding
    case_id: str
    mode: str
    worker_pid: int
    observation: str
    syscall_errno: int
    exit_code: int
    started_at: float
    finished_at: float


@dataclass(frozen=True)
class LocalPairedObservation:
    """Three coherent local workers plus a correlation, NOT a validator pass."""

    binding: AttemptBinding
    case_id: str
    worker_pids: tuple[int, int, int]  # control-before, confined, control-after
    kernel_sequence: int
    audit_serial: int


def _integer(value: object, low: int, high: int) -> bool:
    return type(value) is int and low <= value <= high


def _seconds(value: object) -> bool:
    # Range before float conversion also refuses arbitrarily large Python ints.
    return ((type(value) is int or type(value) is float)
            and 0 <= value <= 1e15 and math.isfinite(value))


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate')
        result[key] = value
    return result


def _constant(_: str) -> NoReturn:
    raise ValueError('constant')


class WorkerReportSession:
    """One expected exact child's report stream under its original deadline.

    Future native code must own the PID, pipes and authenticated context, establish
    a fresh audit cursor after ready, write exactly G once/close the gate, observe
    report EOF and normal child exit with WNOWAIT/pidfd ownership still held, and
    retain that unreaped PID through audit capture. This class does NONE of that.
    mark_gate_released() records the caller's observation; it never writes a gate.
    """

    def __init__(
        self, binding: AttemptBinding, case_id: str, mode: str, worker_pid: int, *,
        deadline: float, clock: Callable[[], float] = time.monotonic,
        cancelled: Callable[[], bool] = lambda: False,
    ) -> None:
        if (type(binding) is not AttemptBinding or type(case_id) is not str or case_id not in CASES
                or mode not in ('control', 'confined') or type(mode) is not str
                or not _integer(worker_pid, 1, _MAX_PID)
                or not _seconds(deadline) or not callable(clock) or not callable(cancelled)):
            raise NativeSupervisionRefused('context')
        try:
            now = clock()
            if not _seconds(now) or not 0 < deadline - now <= MAX_WORKER_SECONDS:
                raise ValueError
        except Exception:
            raise NativeSupervisionRefused('context') from None
        self._binding, self._case, self._mode, self._pid = binding, case_id, mode, worker_pid
        self._deadline, self._clock, self._cancelled = deadline, clock, cancelled
        self._started = self._last = float(now)
        self._buffer = bytearray()
        self._total = self._frames = 0
        self._ready = self._released = self._eof = self._finished = False
        self._result: tuple[str, int] | None = None
        self._failure: tuple[str, bool] | None = None
        self._guard()

    def _stop(self, label: str, *, unknown: bool = False) -> NoReturn:
        if self._failure is None:
            self._failure = (label, unknown)
        self._buffer.clear()
        reason, uncertain = self._failure
        error = NativeSupervisionUnknown if uncertain else NativeSupervisionRefused
        raise error(reason) from None

    def _guard(self) -> None:
        if self._failure is not None:
            self._stop(self._failure[0])
        if self._finished:
            raise NativeSupervisionRefused('terminal')
        try:
            stopped = self._cancelled()
            now = self._clock()
        except Exception:
            self._stop('budget_check_unknown', unknown=True)
        if type(stopped) is not bool or not _seconds(now) or now < self._last:
            self._stop('budget_check_unknown', unknown=True)
        if stopped:
            self._stop('cancelled_unknown', unknown=True)
        self._last = float(now)
        if now >= self._deadline:
            self._stop('deadline_unknown', unknown=True)

    @property
    def ready_for_release(self) -> bool:
        self._guard()
        return self._ready and not self._released and not self._buffer and not self._eof

    def feed(self, data: bytes) -> None:
        self._guard()
        if self._eof:
            self._stop('after_eof')
        if (type(data) is not bytes or not 0 < len(data) <= MAX_REPORT_BYTES
                or self._total + len(data) > MAX_REPORT_BYTES):
            self._stop('report_bound')
        self._total += len(data)
        self._buffer.extend(data)
        while b'\n' in self._buffer:
            size = self._buffer.index(b'\n') + 1
            if size > MAX_FRAME_BYTES or self._frames >= 2:
                self._stop('report_bound')
            raw = bytes(self._buffer[:size - 1])
            del self._buffer[:size]
            self._frames += 1
            self._frame(raw)
            self._guard()
        if len(self._buffer) >= MAX_FRAME_BYTES:
            self._stop('report_bound')
        self._guard()

    def _frame(self, raw: bytes) -> None:
        try:
            value = json.loads(raw.decode('ascii'), object_pairs_hook=_unique, parse_constant=_constant)
        except (ValueError, TypeError, UnicodeError, RecursionError):
            self._stop('report_shape')
        if type(value) is not dict:
            self._stop('report_shape')
        common = {'phase', 'case_id', 'mode', 'pid'}
        if (not common <= value.keys() or value['case_id'] != self._case
                or value['mode'] != self._mode or type(value['pid']) is not int
                or value['pid'] != self._pid):
            self._stop('report_identity')
        if value['phase'] == 'ready':
            if set(value) != common or self._ready or self._released:
                self._stop('report_order')
            self._ready = True
            return
        if value['phase'] != 'result' or set(value) != common | {'observation', 'errno'}:
            self._stop('report_shape')
        if not self._ready or not self._released or self._result is not None:
            self._stop('report_order')
        kind, number = value['observation'], value['errno']
        if kind == 'syscall_error' and _integer(number, 1, 4095):
            self._result = (kind, number)
        elif (self._case != 'outside_exec' and _integer(number, 0, 0)
              and kind == ('control_written' if self._mode == 'control' else 'unexpected_open')):
            self._result = (kind, number)
        else:
            self._stop('result_semantics')

    def mark_gate_released(self) -> None:
        self._guard()
        if not self._ready or self._released or self._eof or self._buffer:
            self._stop('gate_order')
        self._released = True
        self._guard()

    def end_of_reports(self) -> None:
        self._guard()
        if self._eof or not self._ready or not self._released:
            self._stop('eof_order', unknown=True)
        if self._buffer:
            self._stop('report_truncated_unknown', unknown=True)
        self._eof = True
        self._guard()

    def finish_exit(self, *, worker_pid: int, exit_code: int) -> LocalWorkerObservation:
        """Evaluate an externally observed NORMAL exit, without waiting/reaping.

        A signal/provider error/missing exact exit must never be converted to an
        exit code or supplied as authority from a worker frame. No retry/cleanup
        is authorized by this method, including after any terminal refusal.
        """
        self._guard()
        if (not _integer(worker_pid, 1, _MAX_PID) or worker_pid != self._pid
                or not _integer(exit_code, 0, 255)):
            self._stop('exit_identity_unknown', unknown=True)
        if not self._eof or not self._released:
            self._stop('exit_incomplete_unknown', unknown=True)
        if self._result is None:
            if self._case == 'outside_exec' and self._mode == 'confined' and exit_code == 37:
                self._stop('negative_allowed')
            if self._case != 'outside_exec' or self._mode != 'control' or exit_code != 37:
                self._stop('result_missing_unknown', unknown=True)
            kind, number = 'control_exec', 0
        else:
            kind, number = self._result
            if exit_code != 0:
                self._stop('exit_status_unknown', unknown=True)
            if self._mode == 'control' and kind != 'control_written':
                self._stop('control_failed')
            if self._mode == 'confined':
                if kind == 'unexpected_open':
                    self._stop('negative_allowed')
                if kind != 'syscall_error' or number != errno.EACCES:
                    self._stop('syscall_not_eacces_unknown', unknown=True)
        self._guard()
        self._finished = True
        return LocalWorkerObservation(self._binding, self._case, self._mode, self._pid,
                                      kind, number, exit_code, self._started, self._last)


def _valid_local(value: object) -> bool:
    if type(value) is not LocalWorkerObservation:
        return False
    if (type(value.binding) is not AttemptBinding or type(value.case_id) is not str
            or value.case_id not in CASES or type(value.mode) is not str
            or value.mode not in ('control', 'confined') or not _integer(value.worker_pid, 1, _MAX_PID)
            or type(value.observation) is not str
            or not _integer(value.syscall_errno, 0, 4095) or not _integer(value.exit_code, 0, 255)
            or not _seconds(value.started_at) or not _seconds(value.finished_at)
            or not 0 <= value.finished_at - value.started_at <= MAX_WORKER_SECONDS):
        return False
    if value.mode == 'confined':
        return value.observation == 'syscall_error' and value.syscall_errno == errno.EACCES and value.exit_code == 0
    if value.case_id == 'outside_exec':
        return value.observation == 'control_exec' and value.syscall_errno == 0 and value.exit_code == 37
    return value.observation == 'control_written' and value.syscall_errno == 0 and value.exit_code == 0


def correlate_paired_case(
    before: LocalWorkerObservation, confined: LocalWorkerObservation, after: LocalWorkerObservation, *,
    baseline_sequence: int, start_us: int, end_us: int, records: tuple[bytes, ...],
) -> LocalPairedObservation:
    """Check three ordered local observations, then use the existing correlator.

    Matching IDs/times/errno and supplied logs are consistency, NOT provenance.
    The future supervisor must independently hold identical pinned RAM fixtures,
    actual isolation/labels, fresh authentic lossless capture and exact unreaped
    child ownership. A new object/call does not authorize another live attempt.
    """
    if (not all(_valid_local(item) for item in (before, confined, after))
            or (before.mode, confined.mode, after.mode) != ('control', 'confined', 'control')
            or not before.binding == confined.binding == after.binding
            or not before.case_id == confined.case_id == after.case_id
            or len({before.worker_pid, confined.worker_pid, after.worker_pid}) != 3
            or before.finished_at > confined.started_at or confined.finished_at > after.started_at):
        raise NativeSupervisionRefused('paired_observations')
    try:
        correlation = correlate_local_denial(
            confined.case_id, worker_pid=confined.worker_pid, syscall_errno=confined.syscall_errno,
            baseline_sequence=baseline_sequence, start_us=start_us, end_us=end_us, records=records,
        )
    except NativeDenialRefused:
        raise NativeSupervisionUnknown('audit_unknown') from None
    return LocalPairedObservation(before.binding, before.case_id,
                                  (before.worker_pid, confined.worker_pid, after.worker_pid),
                                  correlation.kernel_sequence, correlation.audit_serial)
