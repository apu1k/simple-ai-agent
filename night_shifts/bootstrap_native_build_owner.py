"""Unwired HOST build-lifetime core; NOT a trusted builder or authorization.

This core has no default kernel/clock, CLI, file access or process implementation.
The explicit bootstrap_native_builder candidate supplies UNELEVATED Windows
adapters; it is not a protected install/starter or an independently trusted build.
Never run checkout code elevated. Windows/CLR and builder-runtime/load policy
must be trusted BEFORE loading compiler or builder code; pins cannot prove that.
"""
from __future__ import annotations

import hashlib
import math
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import ClassVar, Protocol, TypeVar

from night_shifts import bootstrap_native_build as build
from night_shifts import bootstrap_native_install_request as request

_MAX_SECONDS = 300
_STOP_SECONDS = 5
_WAIT_MS = 100
_POLL_MS = 20
_T = TypeVar('_T')
# Strong process-local retention, not a receipt or survival across owner death.
# No automatic reaper, reset or release API; future protected reconciliation is
# a separate reviewed operation. Tests substitute this list with model storage.
_RETAINED: list[_ValidatorBuildOwner] = []


class ValidatorBuildOwnerRefused(RuntimeError):
    """Fixed-label local refusal, never permission to retry or install."""


class ValidatorBuildOwnerUnknown(ValidatorBuildOwnerRefused):
    """No known build outcome; retained state is NOT child-absence evidence."""


@dataclass(frozen=True)
class LocalBuildArtifact:
    name: str
    raw: bytes
    sha256: str


@dataclass(frozen=True)
class LocalBuildObservation:
    scope: ClassVar[str] = 'local_build_process_and_bytes_not_review_or_installation'
    artifacts: tuple[LocalBuildArtifact, ...]
    # Observed byte hashes are NOT independently reviewed finished-binary pins.


@dataclass(frozen=True)
class _CompilerChild:
    process: object
    thread: object
    pid: int


class _BuildInputs(Protocol):
    # Adapter: hold actual identities/ancestry and exact reviewed application
    # inputs/private fresh staging. Selected compiler pins are NOT the complete
    # OS/CLR or builder-runtime load closure; that trust base is a prerequisite.
    # No process operation may be hidden behind these methods. Reverification
    # failure MUST retain handles. outputs() must read bounded immutable bytes
    # through held handles and reject extra/case-alias/changed output entries.
    def reverify(self) -> None: ...
    def outputs(self) -> object: ...
    def close(self) -> None: ...  # once, disarmed before the attempt; no finalizer


class _BuildKernel(Protocol):
    def cancelled(self) -> bool: ...
    def require_unelevated_host(self, recipe: build.ValidatorBuildRecipe) -> None: ...
    # prepare must establish fresh private non-reparse stage, exact files,
    # identities, permissions and held inputs. On failure it owns its partial
    # resources. No repair, overwrite, process creation or staging deletion.
    def prepare(self, recipe: build.ValidatorBuildRecipe) -> _BuildInputs: ...
    # New exact-owned kill-on-close, no-breakaway BUILD job each time: fixed
    # compiler/resource-helper concurrency cap, NOT a runtime worker limit.
    def new_job(self) -> object: ...
    # Atomic JOB_LIST assignment, suspended, no inherited handles, fixed recipe
    # argv/cwd/replacement environment. Bounded diagnostics, no unread pipes.
    # Native implementation must adopt/close partial outputs before throwing.
    def create_suspended(self, job: object, command: tuple[str, ...], cwd: str,
                         environment: tuple[tuple[str, str], ...]) -> _CompilerChild: ...
    def member(self, process: object, job: object) -> bool: ...
    def resume(self, thread: object) -> int: ...
    def wait(self, process: object, milliseconds: int) -> int: ...
    def exit_code(self, process: object) -> int: ...
    def active(self, job: object) -> int: ...
    def stop(self, job: object) -> None: ...
    def pause(self, milliseconds: int) -> None: ...
    def close(self, handle: object) -> None: ...


def _call(action: Callable[..., _T], *args: object) -> _T:
    try:
        return action(*args)
    except BaseException:
        # Even a backend raising our exception type cannot inject diagnostic
        # text, paths or fake refusal labels. Cancellation uses cancelled().
        raise ValidatorBuildOwnerUnknown('build_backend_unknown') from None


def _normalized(error: BaseException) -> ValidatorBuildOwnerRefused:
    if type(error) is ValidatorBuildOwnerRefused:
        return ValidatorBuildOwnerRefused(str(error))
    if type(error) is ValidatorBuildOwnerUnknown:
        return ValidatorBuildOwnerUnknown(str(error))
    return ValidatorBuildOwnerUnknown('build_owner_unknown')


class _ValidatorBuildOwner:
    """One-shot two-compiler transaction with mandatory original BUILD deadline.

    Internal/no live default. Does not accept an arbitrary or forged recipe:
    reconstructs it with the existing closed reviewer BEFORE any backend call.
    Deadline uses the supplied SAME-process clock and includes setup, both
    compiles, observation, output reading and closes. It is NOT a provisioning
    deadline and cannot authorize/restart a later protected operation.

    Uncertain owners are strongly retained locally; the eventual independent
    supervisor must additionally cover blocked calls and owner process death.
    No dispose/retry/reset/reconcile/finalizer operation. Cooperative checks
    cannot interrupt a blocked adapter/CLR operation.
    """

    def __init__(self, review: object, *, source_files: object, toolchain_files: object,
                 kernel: _BuildKernel, clock: Callable[[], float], deadline: float) -> None:
        self._recipe = build.plan_validation_build(review, source_files=source_files, toolchain_files=toolchain_files)
        self._api, self._clock = kernel, clock
        self._lock = threading.Lock()
        self._used = False
        self._last = -math.inf
        self._inputs: _BuildInputs | None = None
        self._input_close_attempted = False
        self._release_allowed = True
        self._handles: list[object] = []
        self._seen: list[object] = []
        self._uncertain_closes: list[object] = []
        self._job: object | None = None
        self._child: _CompilerChild | None = None
        self._creation_attempted = self._stop_attempted = False
        now = self._now()
        if (type(deadline) not in (int, float) or not math.isfinite(deadline)
                or not 0 <= deadline <= 1e15 or not _STOP_SECONDS + 1 <= deadline - now <= _MAX_SECONDS):
            raise ValidatorBuildOwnerRefused('build_deadline')
        self._deadline = float(deadline)

    @property
    def retains_inputs(self) -> bool:
        # Strong reference/retention status, NOT a claim that every lock is held.
        return self._inputs is not None

    def _now(self) -> float:
        value = _call(self._clock)
        if (type(value) not in (int, float) or not math.isfinite(value)
                or not 0 <= value <= 1e15 or value < self._last):
            raise ValidatorBuildOwnerUnknown('build_clock_unknown')
        self._last = float(value)
        return self._last

    def _check(self, *, starting: bool = False) -> None:
        if self._now() >= self._deadline - (_STOP_SECONDS if starting else 0):
            raise ValidatorBuildOwnerRefused('build_deadline')
        cancelled = _call(self._api.cancelled)
        if type(cancelled) is not bool:
            raise ValidatorBuildOwnerUnknown('build_cancellation_unknown')
        if cancelled:
            raise ValidatorBuildOwnerRefused('build_cancelled')

    def _own(self, handle: object) -> bool:
        if handle is None or any(handle is old for old in self._seen):
            return False
        self._seen.append(handle)
        self._handles.append(handle)
        return True

    def _count(self) -> int:
        count = _call(self._api.active, self._job)
        # Job accounting can still include exiting helpers. Its observation
        # bound is the fixed total extent, NOT the native active-process limit.
        if type(count) is not int or not 0 <= count <= build.BUILD_TOTAL_PROCESS_LIMIT:
            raise ValidatorBuildOwnerUnknown('build_job_unknown')
        return count

    def _wait(self, milliseconds: int) -> int:
        if self._child is None:
            raise ValidatorBuildOwnerUnknown('build_child_unknown')
        value = _call(self._api.wait, self._child.process, milliseconds)
        if type(value) is not int or value not in (0, 258):
            raise ValidatorBuildOwnerUnknown('build_wait_unknown')
        return value

    def _stop(self) -> None:
        if not self._stop_attempted:
            self._stop_attempted = True  # disarm BEFORE native termination
            _call(self._api.stop, self._job)

    def _observe_end(self, *, force: bool) -> None:
        failure = None
        if force:
            try:
                self._stop()
            except BaseException:
                failure = ValidatorBuildOwnerUnknown('build_stop_unknown')
        end = min(self._deadline, self._now() + _STOP_SECONDS)
        empty = False
        for _ in range(_STOP_SECONDS * 1000 // _POLL_MS + 1):
            now = self._now()
            if now >= end:
                break
            count, wait = self._count(), self._wait(0)
            if count == 0 and wait == 0:
                empty = True
                break
            if not self._stop_attempted:
                try:
                    self._stop()
                except BaseException:
                    failure = ValidatorBuildOwnerUnknown('build_stop_unknown')
            delay = min(_POLL_MS, math.floor((end - self._now()) * 1000))
            if delay < 1:
                break
            _call(self._api.pause, delay)
        if failure is not None:
            raise failure
        if not empty:
            raise ValidatorBuildOwnerUnknown('build_termination_unknown')

    def _close_handles(self) -> None:
        unknown = False
        while self._handles:
            handle = self._handles.pop()  # disarm even if close outcome is unknown
            try:
                _call(self._api.close, handle)
            except BaseException:
                self._uncertain_closes.append(handle)
                unknown = True
        if unknown:
            raise ValidatorBuildOwnerUnknown('build_close_unknown')

    def _compile(self, command: tuple[str, ...]) -> int:
        self._job = self._child = None
        self._creation_attempted = self._stop_attempted = False
        failure = None
        code = None
        empty = False
        try:
            self._check(starting=True)
            job = _call(self._api.new_job)
            if not self._own(job):
                raise ValidatorBuildOwnerUnknown('build_job_handle_unknown')
            self._job = job
            if self._inputs is None:
                raise ValidatorBuildOwnerUnknown('build_inputs_unknown')
            _call(self._inputs.reverify)
            self._check(starting=True)
            self._release_allowed = False
            self._creation_attempted = True
            child = _call(self._api.create_suspended, job, command,
                          self._recipe.working_directory, self._recipe.environment)
            if type(child) is not _CompilerChild:
                raise ValidatorBuildOwnerUnknown('build_child_unknown')
            self._child = child
            # Adopt both outputs BEFORE rejecting malformed/aliased pairs.
            process, thread = self._own(child.process), self._own(child.thread)
            if not process or not thread or type(child.pid) is not int or not 1 <= child.pid <= 0xffffffff:
                raise ValidatorBuildOwnerUnknown('build_child_handles_unknown')
            if _call(self._api.member, child.process, job) is not True or self._count() != 1:
                raise ValidatorBuildOwnerUnknown('build_membership_unknown')
            _call(self._inputs.reverify)
            self._check(starting=True)
            resumed = _call(self._api.resume, child.thread)
            if type(resumed) is not int or resumed != 1:
                raise ValidatorBuildOwnerUnknown('build_resume_unknown')
            for _ in range(_MAX_SECONDS * 1000 // _WAIT_MS + 1):
                self._check(starting=True)
                ms = min(_WAIT_MS, math.floor((self._deadline - _STOP_SECONDS - self._last) * 1000))
                if ms < 1:
                    raise ValidatorBuildOwnerRefused('build_deadline')
                if self._wait(ms) == 0:
                    code = _call(self._api.exit_code, child.process)
                    if type(code) is not int or not 0 <= code <= 0xffffffff:
                        raise ValidatorBuildOwnerUnknown('build_exit_unknown')
                    break
            if code is None:
                raise ValidatorBuildOwnerUnknown('build_wait_progress_unknown')
        except BaseException as error:
            failure = _normalized(error)
        if self._job is not None and self._creation_attempted:
            try:
                self._observe_end(force=failure is not None)
                empty = True
            except BaseException:
                failure = ValidatorBuildOwnerUnknown('build_termination_unknown')
        try:
            self._close_handles()
        except BaseException:
            self._release_allowed = False
            failure = ValidatorBuildOwnerUnknown('build_close_unknown')
        try:
            if self._now() >= self._deadline:
                raise ValidatorBuildOwnerUnknown('build_deadline_outcome_unknown')
        except BaseException:
            self._release_allowed = False
            failure = ValidatorBuildOwnerUnknown('build_deadline_outcome_unknown')
        if self._creation_attempted:
            self._release_allowed = empty and (failure is None or type(failure) is ValidatorBuildOwnerRefused)
        elif failure is not None and type(failure) is ValidatorBuildOwnerUnknown:
            self._release_allowed = False
        if failure is not None:
            raise failure
        if code is None:
            raise ValidatorBuildOwnerUnknown('build_exit_unknown')
        return code

    def _artifacts(self, value: object) -> tuple[LocalBuildArtifact, ...]:
        if type(value) is not dict or set(value) != set(self._recipe.expected_outputs):
            raise ValidatorBuildOwnerRefused('build_output_inventory')
        result = []
        for name in self._recipe.expected_outputs:
            raw = value[name]
            if type(raw) is not bytes or not 1 <= len(raw) <= 16 * 1024**2:
                raise ValidatorBuildOwnerRefused('build_output_bytes')
            if name.endswith('.config') and raw != request._CONFIG:
                raise ValidatorBuildOwnerRefused('build_output_config')
            result.append(LocalBuildArtifact(name, raw, hashlib.sha256(raw).hexdigest()))
        # Binary bytes are deliberately only observations. No PE/CLR signature,
        # source attribution, origin or independent finished-artifact review here.
        return tuple(result)

    def run(self) -> LocalBuildObservation:
        with self._lock:
            if self._used:
                raise ValidatorBuildOwnerRefused('build_one_shot')
            self._used = True
            failure = None
            result = None
            try:
                self._check(starting=True)
                _call(self._api.require_unelevated_host, self._recipe)
                self._check(starting=True)
                self._inputs = _call(self._api.prepare, self._recipe)
                if self._inputs is None:
                    raise ValidatorBuildOwnerUnknown('build_inputs_unknown')
                self._check(starting=True)
                _call(self._inputs.reverify)
                for command in self._recipe.commands:
                    if self._compile(command) != 0:
                        raise ValidatorBuildOwnerRefused('build_compiler_exit')
                _call(self._inputs.reverify)
                self._check()
                raw = _call(self._inputs.outputs)
                self._check()
                artifacts = self._artifacts(raw)
                _call(self._inputs.reverify)
                self._check()
                result = LocalBuildObservation(artifacts)
            except BaseException as error:
                failure = _normalized(error)
            if self._inputs is not None and self._release_allowed and not self._input_close_attempted:
                self._input_close_attempted = True
                try:
                    _call(self._inputs.close)
                    self._inputs = None
                    if self._now() >= self._deadline:
                        raise ValidatorBuildOwnerUnknown('build_deadline_outcome_unknown')
                    cancelled = _call(self._api.cancelled)
                    if type(cancelled) is not bool:
                        raise ValidatorBuildOwnerUnknown('build_cancellation_unknown')
                    if cancelled and failure is None:
                        failure = ValidatorBuildOwnerRefused('build_cancelled')
                except BaseException:
                    failure = ValidatorBuildOwnerUnknown('build_input_close_unknown')
            if self._inputs is not None:
                _RETAINED.append(self)
            if failure is not None:
                raise failure from None
            if result is None:
                raise ValidatorBuildOwnerUnknown('build_result_unknown')
            return result
