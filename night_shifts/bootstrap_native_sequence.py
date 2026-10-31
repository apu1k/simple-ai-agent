"""Fixed paired guest sequence candidate; UNWIRED, no CLI or native receipt.

run() WOULD execute eleven fixed owned workers through the reviewed single-worker
candidate: two confined pool controls surrounding three control/negative/control
triples. Caller must own isolation, immutable media and independent host watchdog.
No policy/media/VM action, retry, arbitrary catalog or host evidence acceptance.
"""
from __future__ import annotations

import json
import math
import time
from collections.abc import Callable
from dataclasses import dataclass

from night_shifts.bootstrap_native_capture import (
    LocalCapturedWorker, LocalKernelInterval, NativeCaptureUnknown, observe_fixed_worker,
)
from night_shifts.bootstrap_native_denials import (
    MAX_CAPTURE_BYTES, MAX_COUNTER, MAX_RECORD_BYTES, MAX_RECORDS, MAX_WINDOW_US, LocalDenialCorrelation,
)
from night_shifts.bootstrap_native_ram import NativeRamFixtures
from night_shifts.bootstrap_native_supervision import (
    CASES, POOL_CASE, LocalPairedObservation, LocalWorkerObservation, correlate_paired_case,
)
from night_shifts.maintenance_tls_prototype import AttemptBinding

MAX_SEQUENCE_SECONDS = 60
MAX_SUMMARY_BYTES = 512
WORKER_COUNT = 11


class NativeSequenceRefused(RuntimeError):
    """Fixed label only; never raw worker/log/native output."""


class NativeSequenceUnknown(NativeSequenceRefused):
    """No validator pass, rollback, retry or child/tree/VM absence implied."""


@dataclass(frozen=True)
class LocalSequenceObservation:
    """Forgeable local consistency data, NOT authenticated native validation."""

    binding: AttemptBinding
    pool_worker_pids: tuple[int, int]
    paired: tuple[LocalPairedObservation, LocalPairedObservation, LocalPairedObservation]
    started_at: float
    finished_at: float

    def summary_bytes(self) -> bytes:
        """Fixed bounded local summary only; NEVER serialize captures/asdict."""
        if type(self.binding) is not AttemptBinding:
            raise NativeSequenceRefused('summary_context')
        raw = (json.dumps({
            'kind': 'local_native_sequence_observation', 'scope': 'local_consistency_only',
            'attempt_id': self.binding.attempt_id, 'vm_id': self.binding.vm_id,
            'workers_observed': WORKER_COUNT, 'paired_cases': list(CASES),
            'confined_pool_controls': 2, 'allowed_pool_files': 5,
        }, sort_keys=True, separators=(',', ':')) + '\n').encode('ascii')
        if len(raw) > MAX_SUMMARY_BYTES:
            raise NativeSequenceRefused('summary_bound')
        return raw


def _seconds(value: object) -> bool:
    return ((type(value) is int or type(value) is float)
            and 0 <= value <= 1e15 and math.isfinite(value))


class NativeValidationSequence:
    """One-shot fixed sequence; original outer budget plus <=5s per NEW worker.

    A failed object cannot be resumed/retried. Constructing another object is not
    permission to repeat a live attempt; protected execution must enforce that.
    The fixture owner remains caller-owned, including after any failure.
    """

    def __init__(
        self, fixtures: NativeRamFixtures, *, deadline: float,
        cancelled: Callable[[], bool] = lambda: False,
    ) -> None:
        self._state = 'new'
        self._last = 0.0
        self._seen: set[int] = set()
        if type(fixtures) is not NativeRamFixtures or not _seconds(deadline) or not callable(cancelled):
            raise NativeSequenceRefused('context')
        self._fixtures, self._deadline, self._cancelled = fixtures, float(deadline), cancelled
        try:
            self._binding, self._seed = fixtures.launch_context()
            self._guard()
            if self._deadline - self._last > MAX_SEQUENCE_SECONDS:
                raise NativeSequenceRefused('context')
        except BaseException as error:
            if isinstance(error, NativeSequenceRefused):
                raise error from None
            raise NativeSequenceUnknown('context_unknown') from None
        self._started = self._previous_finish = self._last

    def _guard(self) -> float:
        stopped, now = self._cancelled(), time.monotonic()
        if (type(stopped) is not bool or not _seconds(now) or now < self._last):
            raise NativeSequenceUnknown('budget_unknown')
        self._last = float(now)
        if stopped or now >= self._deadline:
            raise NativeSequenceUnknown('budget_unknown')
        return self._last

    def _step(self, case_id: str, mode: str) -> LocalCapturedWorker:
        began = self._guard()
        if self._fixtures.launch_context() != (self._binding, self._seed):
            raise NativeSequenceUnknown('fixture_context_unknown')
        # New worker, not a renewed budget on an existing child. Its own entire
        # acquisition/report/capture/reap sequence must stay inside this bound.
        child_deadline = min(self._deadline, began + 5)
        captured = observe_fixed_worker(self._fixtures, case_id, mode, deadline=child_deadline,
                                        cancelled=self._cancelled)
        ended = self._guard()
        if type(captured) is not LocalCapturedWorker or type(captured.worker) is not LocalWorkerObservation:
            raise NativeSequenceUnknown('worker_observation_unknown')
        worker = captured.worker
        negative = case_id in CASES and mode == 'confined'
        kind = ('pools_checked' if case_id == POOL_CASE else 'syscall_error' if negative
                else 'control_exec' if case_id == 'outside_exec' else 'control_written')
        status = 37 if case_id == 'outside_exec' and mode == 'control' else 0
        if (type(worker.binding) is not AttemptBinding or worker.binding != self._binding
                or worker.case_id != case_id or worker.mode != mode
                or type(worker.worker_pid) is not int or not 1 <= worker.worker_pid < 1 << 22
                or worker.worker_pid in self._seen or worker.observation != kind
                or type(worker.syscall_errno) is not int or worker.syscall_errno != (13 if negative else 0)
                or type(worker.exit_code) is not int or worker.exit_code != status
                or not _seconds(worker.started_at) or not _seconds(worker.finished_at)
                or not max(began, self._previous_finish) <= worker.started_at <= worker.finished_at <= ended
                or worker.finished_at - worker.started_at > 5 or ended >= child_deadline):
            raise NativeSequenceUnknown('worker_observation_unknown')
        interval = captured.interval
        if (type(interval) is not LocalKernelInterval
                or type(interval.baseline_sequence) is not int
                or not 0 <= interval.baseline_sequence <= MAX_COUNTER - MAX_RECORDS
                or type(interval.start_us) is not int or type(interval.end_us) is not int
                or not 0 <= interval.start_us <= interval.end_us <= MAX_COUNTER
                or not int(worker.started_at * 1e6) <= interval.start_us <= interval.end_us <= int(ended * 1e6)
                or interval.end_us < int(worker.finished_at * 1e6)
                or interval.end_us - interval.start_us > MAX_WINDOW_US
                or type(interval.records) is not tuple or len(interval.records) > MAX_RECORDS
                or any(type(raw) is not bytes or not 0 < len(raw) <= MAX_RECORD_BYTES for raw in interval.records)
                or sum(map(len, interval.records)) > MAX_CAPTURE_BYTES):
            raise NativeSequenceUnknown('capture_observation_unknown')
        if negative:
            denial = captured.denial
            if (type(denial) is not LocalDenialCorrelation or denial.case_id != case_id
                    or denial.worker_pid != worker.worker_pid
                    or type(denial.kernel_sequence) is not int or not 0 < denial.kernel_sequence <= MAX_COUNTER
                    or type(denial.audit_serial) is not int or not 0 < denial.audit_serial <= MAX_COUNTER):
                raise NativeSequenceUnknown('denial_observation_unknown')
        elif captured.denial is not None:
            raise NativeSequenceUnknown('denial_observation_unknown')
        if self._fixtures.launch_context() != (self._binding, self._seed):
            raise NativeSequenceUnknown('fixture_context_unknown')
        self._seen.add(worker.worker_pid)
        self._previous_finish = ended
        return captured

    def run(self) -> LocalSequenceObservation:
        if self._state != 'new':
            raise NativeSequenceRefused('terminal')
        self._state = 'running'  # Consume before any fallible/cancellable action.
        try:
            first_pool = self._step(POOL_CASE, 'confined')
            pairs: list[LocalPairedObservation] = []
            previous_sequence, previous_serial = -1, 0
            for case_id in CASES:
                before = self._step(case_id, 'control')
                negative = self._step(case_id, 'confined')
                after = self._step(case_id, 'control')
                interval = negative.interval
                # Native collection AND initial denial correlation already ran
                # while that exact child was WNOWAIT-held in observe_fixed_worker.
                # This second, pure evaluation joins its before/after controls;
                # it does not claim the now-reaped PID remains held.
                pair = correlate_paired_case(
                    before.worker, negative.worker, after.worker,
                    baseline_sequence=interval.baseline_sequence, start_us=interval.start_us,
                    end_us=interval.end_us, records=interval.records,
                )
                denial = negative.denial
                if (denial is None or pair.kernel_sequence != denial.kernel_sequence
                        or pair.audit_serial != denial.audit_serial
                        or pair.kernel_sequence <= previous_sequence or pair.audit_serial <= previous_serial):
                    raise NativeSequenceUnknown('paired_observation_unknown')
                previous_sequence, previous_serial = pair.kernel_sequence, pair.audit_serial
                pairs.append(pair)
                self._guard()
            last_pool = self._step(POOL_CASE, 'confined')
            self._guard()
            if len(self._seen) != WORKER_COUNT:
                raise NativeSequenceUnknown('worker_count_unknown')
            result = LocalSequenceObservation(
                self._binding, (first_pool.worker.worker_pid, last_pool.worker.worker_pid),
                (pairs[0], pairs[1], pairs[2]), self._started, self._last,
            )
            result.summary_bytes()  # Bound locally; do not print or write it.
            self._guard()
            self._state = 'done'
            return result
        except BaseException as error:
            self._state = 'failed'
            if isinstance(error, NativeSequenceRefused):
                raise error from None
            # Single-worker helper already attempted both exact cleanups. Never
            # start the next worker or retry/repair its uncertain native lifetime.
            label = ('cleanup_unknown' if type(error) is NativeCaptureUnknown
                     and error.args == ('cleanup_unknown',) else 'sequence_unknown')
            raise NativeSequenceUnknown(label) from None
