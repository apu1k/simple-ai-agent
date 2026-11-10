"""HOST build-owner fault models only; no compiler, native adapter or VM.

The existing recipe's disposable executable tests are separate. All inputs here
are inert; fake job accounting/handles cannot prove Windows child absence.
"""
from __future__ import annotations

import ast
import dataclasses
import hashlib
import inspect
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from night_shifts import bootstrap_native_build as build
from night_shifts import bootstrap_native_build_owner as owner
from night_shifts import bootstrap_native_install_request as request
from tests.night_shifts.test_bootstrap_native_build import _candidate

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def model_retention_only(monkeypatch):
    # Only inert fakes are retained here; never reset a live owner registry.
    monkeypatch.setattr(owner, '_RETAINED', [])


@dataclasses.dataclass(eq=False)
class Handle:
    kind: str
    number: int
    closed: bool = False
    closes: int = 0


class Clock:
    def __init__(self):
        self.time = 10.0

    def __call__(self):
        return self.time


class Inputs:
    def __init__(self, kernel):
        self.kernel = kernel
        self.verifies = 0
        self.closed = False
        self.closes = 0
        self.data = {name: request._CONFIG if name.endswith('.config') else b'inert output ' + name.encode()
                     for name in request.LAUNCH_NAMES}

    def reverify(self):
        assert not self.closed
        self.verifies += 1
        self.kernel.event(f'verify:{self.verifies}')

    def outputs(self):
        assert not self.closed and self.kernel.creates == 2 and self.kernel.count == 0
        self.kernel.event('outputs')
        return self.data

    def close(self):
        assert not self.closed and self.closes == 0 and self.kernel.count == 0
        self.closes += 1
        self.closed = True
        self.kernel.event('inputs:close')


class Kernel:
    def __init__(self, clock):
        self.clock = clock
        self.events = []
        self.handles = []
        self.inputs = Inputs(self)
        self.recipe = None
        self.commands = []
        self.creates = self.jobs = self.count = 0
        self.stops = {}
        self.exited = False
        self.cancel = False
        self.fault = self.hook = self.child_override = None
        self.mode = 'normal'
        self.code = 0
        self.count_override = self.wait_override = self.resume_override = None
        self.member_value = True

    def event(self, name):
        self.events.append(name)
        if self.hook is not None:
            self.hook(name)
        if self.fault == name:
            raise RuntimeError('PRIVATE_BACKEND_CANARY')

    def handle(self, kind):
        value = Handle(kind, self.jobs)
        self.handles.append(value)
        return value

    def cancelled(self):
        self.event('cancel')
        return self.cancel

    def require_unelevated_host(self, recipe):
        assert self.recipe is None
        self.event('host')

    def prepare(self, recipe):
        self.event('prepare')
        self.recipe = recipe
        return self.inputs

    def new_job(self):
        assert self.recipe is not None and self.count == 0
        self.jobs += 1
        self.event(f'job:{self.jobs}')
        return self.handle('job')

    def create_suspended(self, job, command, cwd, environment):
        assert not self.inputs.closed and not job.closed
        assert command == self.recipe.commands[self.creates]
        assert cwd == self.recipe.working_directory and environment == self.recipe.environment
        self.creates += 1
        self.commands.append(command)
        self.event(f'create:{self.creates}')
        self.count, self.exited = 1, False
        child = owner._CompilerChild(self.handle('process'), self.handle('thread'), 100 + self.creates)
        return child if self.child_override is None else self.child_override(child, job)

    def member(self, process, job):
        self.event(f'member:{self.jobs}')
        return self.member_value

    def resume(self, thread):
        self.event(f'resume:{self.jobs}')
        return 1 if self.resume_override is None else self.resume_override

    def wait(self, process, milliseconds):
        self.event(f'wait:{self.jobs}:{milliseconds}')
        if self.wait_override is not None:
            return self.wait_override
        if milliseconds:
            if self.mode in ('timeout', 'stuck'):
                self.clock.time += milliseconds / 1000
            elif self.mode != 'frozen_wait':
                self.exited = True
                if self.mode != 'residual':
                    self.count = 0
        return 0 if self.exited else 258

    def exit_code(self, process):
        self.event(f'exit:{self.jobs}')
        return self.code

    def active(self, job):
        self.event(f'active:{self.jobs}')
        return self.count if self.count_override is None else self.count_override

    def stop(self, job):
        self.stops[self.jobs] = self.stops.get(self.jobs, 0) + 1
        assert self.stops[self.jobs] == 1
        self.event(f'stop:{self.jobs}')
        if self.mode != 'stuck':
            self.count, self.exited = 0, True

    def pause(self, milliseconds):
        self.event(f'pause:{self.jobs}')
        self.clock.time += milliseconds / 1000

    def close(self, handle):
        assert not handle.closed
        handle.closed, handle.closes = True, handle.closes + 1
        self.event(f'close:{handle.number}:{handle.kind}')


def _setup(*, deadline=40.0):
    clock = Clock()
    kernel = Kernel(clock)
    review, sources, tools = _candidate()
    value = owner._ValidatorBuildOwner(review, source_files=sources, toolchain_files=tools,
                                       kernel=kernel, clock=clock, deadline=deadline)
    return value, kernel, clock


def _failure(value, kind):
    with pytest.raises(kind) as caught:
        value.run()
    assert type(caught.value) is kind
    assert 'CANARY' not in str(caught.value)
    return str(caught.value)


def _closed(kernel):
    assert all(handle.closed and handle.closes == 1 for handle in kernel.handles)


def test_two_exact_commands_share_one_deadline_and_return_only_byte_observations():
    value, kernel, _ = _setup()
    result = value.run()
    assert type(result) is owner.LocalBuildObservation
    assert result.scope == 'local_build_process_and_bytes_not_review_or_installation'
    assert tuple(artifact.name for artifact in result.artifacts) == request.LAUNCH_NAMES
    assert all(artifact.raw == kernel.inputs.data[artifact.name]
               and artifact.sha256 == hashlib.sha256(artifact.raw).hexdigest() for artifact in result.artifacts)
    assert kernel.commands == list(kernel.recipe.commands)
    assert kernel.jobs == kernel.creates == 2 and not kernel.stops
    assert kernel.inputs.verifies == 7 and kernel.inputs.closes == 1 and not value.retains_inputs
    assert not owner._RETAINED
    _closed(kernel)
    events = [name for name in kernel.events if name != 'cancel']
    assert events.index('host') < events.index('prepare') < events.index('verify:1') < events.index('job:1')
    assert events.index('verify:2') < events.index('create:1') < events.index('verify:3') < events.index('resume:1')
    assert events.index('close:1:job') < events.index('job:2')
    assert events[-4:] == ['verify:6', 'outputs', 'verify:7', 'inputs:close']
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.artifacts = ()
    kernel.inputs.data.clear()
    assert len(result.artifacts) == 4


@pytest.mark.parametrize('key,bad', [('scope', 'trusted_build'), ('version', True), ('main', 'Injected.Main'),
                                    ('staging_root', r'C:\Windows\Build'), ('policy_sha256', 'a' * 64)])
def test_review_reconstructed_before_any_backend_or_clock_call(key, bad):
    review, sources, tools = _candidate()
    review[key] = bad
    kernel = Kernel(Clock())
    with pytest.raises(build.ValidatorBuildRefused):
        owner._ValidatorBuildOwner(review, source_files=sources, toolchain_files=tools, kernel=kernel,
                                   clock=lambda: pytest.fail('invalid review sampled clock'), deadline=40)
    assert not kernel.events


@pytest.mark.parametrize('deadline', [True, None, '40', float('nan'), float('inf'), -1, 10, 15.99, 310.01, 1e16])
def test_build_window_is_required_bounded_and_not_a_runtime_budget(deadline):
    review, sources, tools = _candidate()
    clock = Clock()
    kernel = Kernel(clock)
    with pytest.raises(owner.ValidatorBuildOwnerRefused):
        owner._ValidatorBuildOwner(review, source_files=sources, toolchain_files=tools,
                                   kernel=kernel, clock=clock, deadline=deadline)
    assert not kernel.events


@pytest.mark.parametrize('bad', [True, None, '10', float('nan'), float('inf'), -1, 1e16])
def test_clock_shape_rejected_before_backend(bad):
    review, sources, tools = _candidate()
    kernel = Kernel(Clock())
    with pytest.raises(owner.ValidatorBuildOwnerUnknown):
        owner._ValidatorBuildOwner(review, source_files=sources, toolchain_files=tools,
                                   kernel=kernel, clock=lambda: bad, deadline=40)
    assert not kernel.events


@pytest.mark.parametrize('fault,retained', [
    ('host', False), ('prepare', False), ('verify:1', False), ('job:1', True), ('verify:2', True),
    ('create:1', True), ('member:1', True), ('active:1', True), ('verify:3', True), ('resume:1', True),
    ('wait:1:100', True), ('exit:1', True), ('wait:1:0', True),
    ('close:1:thread', True), ('close:1:process', True), ('close:1:job', True),
    ('job:2', True), ('verify:4', True), ('create:2', True), ('member:2', True), ('verify:5', True),
    ('resume:2', True), ('wait:2:100', True), ('exit:2', True),
    ('verify:6', False), ('outputs', False), ('verify:7', False), ('inputs:close', True),
])
def test_backend_faults_are_normalized_never_retried_and_conditionally_retain_inputs(fault, retained):
    value, kernel, _ = _setup()
    kernel.fault = fault
    _failure(value, owner.ValidatorBuildOwnerUnknown)
    assert fault in kernel.events
    assert value.retains_inputs is retained
    assert any(item is value for item in owner._RETAINED) is retained
    _closed(kernel)
    if retained and fault != 'inputs:close':
        assert kernel.inputs.closes == 0
    before = list(kernel.events)
    assert _failure(value, owner.ValidatorBuildOwnerRefused) == 'build_one_shot'
    assert kernel.events == before
    assert all(count == 1 for count in kernel.stops.values())


@pytest.mark.parametrize('kind', [RuntimeError, KeyboardInterrupt, SystemExit, owner.ValidatorBuildOwnerRefused,
                                  owner.ValidatorBuildOwnerUnknown])
def test_backend_cannot_smuggle_native_exception_or_false_refusal_text(kind):
    value, kernel, _ = _setup()

    def hook(name):
        if name == 'create:1':
            raise kind('PRIVATE_BACKEND_CANARY')

    kernel.hook = hook
    _failure(value, owner.ValidatorBuildOwnerUnknown)
    assert value.retains_inputs and kernel.creates == 1 and owner._RETAINED == [value]


@pytest.mark.parametrize('code', [1, 7, 126, 259, 0xffffffff])
def test_checked_nonzero_exit_stops_transaction_but_releases_known_absent_inputs(code):
    value, kernel, _ = _setup()
    kernel.code = code
    assert _failure(value, owner.ValidatorBuildOwnerRefused) == 'build_compiler_exit'
    assert kernel.creates == 1 and kernel.inputs.closes == 1 and not value.retains_inputs
    assert not kernel.stops
    _closed(kernel)


@pytest.mark.parametrize('field,bad', [('member_value', False), ('member_value', 1), ('count_override', True),
    ('count_override', 2), ('count_override', 4), ('count_override', -1), ('resume_override', True), ('resume_override', 0),
    ('resume_override', 2), ('wait_override', True), ('wait_override', 1), ('wait_override', 0xffffffff),
    ('code', True), ('code', -1), ('code', 1 << 32)])
def test_invalid_kernel_observations_never_become_build_success(field, bad):
    value, kernel, _ = _setup()
    setattr(kernel, field, bad)
    _failure(value, owner.ValidatorBuildOwnerUnknown)
    assert value.retains_inputs and 'outputs' not in kernel.events
    _closed(kernel)


@pytest.mark.parametrize('shape', ['null', 'same', 'job_alias', 'pid_bool', 'pid_zero'])
def test_malformed_child_pair_adopts_distinct_outputs_before_rejection(shape):
    value, kernel, _ = _setup()

    def child_shape(child, job):
        if shape == 'null':
            # The fake owns a partially created output it does NOT transfer.
            # This is model cleanup, never live native reconciliation.
            kernel.close(child.process)
            return owner._CompilerChild(None, child.thread, child.pid)
        if shape in ('same', 'job_alias'):
            kernel.close(child.thread)
            return owner._CompilerChild(child.process, child.process if shape == 'same' else job, child.pid)
        return owner._CompilerChild(child.process, child.thread, True if shape == 'pid_bool' else 0)

    kernel.child_override = child_shape
    _failure(value, owner.ValidatorBuildOwnerUnknown)
    assert value.retains_inputs and 'resume:1' not in kernel.events
    _closed(kernel)


@pytest.mark.parametrize('mode,kind,retained', [('timeout', owner.ValidatorBuildOwnerRefused, False),
    ('stuck', owner.ValidatorBuildOwnerUnknown, True), ('frozen_wait', owner.ValidatorBuildOwnerUnknown, True)])
def test_wait_and_termination_have_time_and_iteration_bounds(mode, kind, retained):
    value, kernel, clock = _setup()
    kernel.mode = mode
    _failure(value, kind)
    assert kernel.stops == {1: 1} and kernel.creates == 1
    assert value.retains_inputs is retained and clock.time <= 40.001
    assert len(kernel.events) < 10000
    _closed(kernel)


def test_residual_accounting_is_stopped_before_another_compiler_starts():
    value, kernel, _ = _setup()
    kernel.mode = 'residual'
    value.run()
    assert kernel.stops == {1: 1, 2: 1} and kernel.inputs.closes == 1
    assert kernel.events.index('stop:1') < kernel.events.index('create:2')
    _closed(kernel)


@pytest.mark.parametrize('accounted', [2, 3])
def test_build_helper_residual_accounting_is_bounded_and_stopped_not_misclassified_as_a_worker(accounted):
    value, kernel, _ = _setup()
    kernel.mode = 'residual'
    injected = False

    def hook(name):
        nonlocal injected
        if name == 'active:1' and kernel.exited and not injected:
            injected = True
            kernel.count = accounted

    kernel.hook = hook
    value.run()
    assert injected and kernel.stops == {1: 1, 2: 1}
    assert not value.retains_inputs and kernel.inputs.closes == 1
    _closed(kernel)


@pytest.mark.parametrize('fault', ['stop:1', 'pause:1'])
def test_cleanup_faults_do_not_retry_termination_or_release_inputs(fault):
    value, kernel, _ = _setup()
    kernel.mode = 'stuck'
    kernel.fault = fault
    _failure(value, owner.ValidatorBuildOwnerUnknown)
    assert fault in kernel.events and kernel.stops == {1: 1} and value.retains_inputs
    _closed(kernel)


@pytest.mark.parametrize('where,delay,creates,kind', [
    ('prepare', 26, 0, owner.ValidatorBuildOwnerRefused),
    ('verify:2', 26, 0, owner.ValidatorBuildOwnerRefused),
    ('wait:1:100', 26, 1, owner.ValidatorBuildOwnerRefused),
    ('outputs', 31, 2, owner.ValidatorBuildOwnerUnknown),
])
def test_every_phase_consumes_same_earlier_build_window(where, delay, creates, kind):
    value, kernel, clock = _setup()

    def hook(name):
        if name == where:
            clock.time += delay

    kernel.hook = hook
    _failure(value, kind)
    assert kernel.creates == creates and kernel.inputs.closes == 1 and not value.retains_inputs
    _closed(kernel)


def test_second_compiler_does_not_receive_a_fresh_budget():
    value, kernel, clock = _setup()

    def hook(name):
        if name == 'wait:1:100':
            clock.time += 26

    kernel.hook = hook
    assert _failure(value, owner.ValidatorBuildOwnerRefused) == 'build_deadline'
    assert kernel.creates == 1 and kernel.inputs.closes == 1 and not value.retains_inputs


@pytest.mark.parametrize('where', ['host', 'create:1', 'verify:3', 'wait:1:100', 'outputs'])
@pytest.mark.parametrize('bad', [9.0, float('nan'), float('inf')])
def test_one_clock_guard_spans_constructor_setup_creation_and_output(where, bad):
    value, kernel, clock = _setup()

    def hook(name):
        if name == where:
            clock.time = bad

    kernel.hook = hook
    _failure(value, owner.ValidatorBuildOwnerUnknown)
    if where in ('create:1', 'verify:3', 'wait:1:100'):
        assert value.retains_inputs
    if where in ('host', 'create:1', 'verify:3'):
        assert 'resume:1' not in kernel.events
    _closed(kernel)


@pytest.mark.parametrize('where,creates', [('host', 0), ('verify:2', 0), ('create:1', 1), ('wait:1:100', 1),
                                        ('outputs', 2), ('inputs:close', 2)])
def test_checked_cancellation_includes_setup_output_and_final_close_but_not_cleanup(where, creates):
    value, kernel, _ = _setup()

    def hook(name):
        if name == where:
            kernel.cancel = True

    kernel.hook = hook
    assert _failure(value, owner.ValidatorBuildOwnerRefused) == 'build_cancelled'
    assert kernel.creates == creates and not value.retains_inputs
    if creates:
        assert kernel.inputs.closes == 1
    _closed(kernel)


@pytest.mark.parametrize('cancel', [None, 1, 'yes'])
def test_cancellation_is_not_truthiness_or_an_authorization_callback(cancel):
    value, kernel, _ = _setup()
    kernel.cancel = cancel
    _failure(value, owner.ValidatorBuildOwnerUnknown)
    assert kernel.creates == 0 and not value.retains_inputs


@pytest.mark.parametrize('fault', ['extra', 'missing', 'case_alias', 'mutable', 'empty', 'text', 'oversized',
                                 'config', 'nonmapping'])
def test_output_shape_checks_do_not_claim_pe_validity_or_independent_review(fault):
    value, kernel, _ = _setup()
    data = kernel.inputs.data
    first = request.LAUNCH_NAMES[0]
    if fault == 'extra':
        data['unexpected.pdb'] = b'x'
    elif fault == 'missing':
        del data[first]
    elif fault == 'case_alias':
        data[first.upper()] = data.pop(first)
    elif fault in ('mutable', 'empty', 'text'):
        data[first] = {'mutable': bytearray(b'x'), 'empty': b'', 'text': 'text'}[fault]
    elif fault == 'oversized':
        data[first] = b'x' * (16 * 1024**2 + 1)
    elif fault == 'config':
        data[first + '.config'] = b'changed'
    else:
        kernel.inputs.data = []
    _failure(value, owner.ValidatorBuildOwnerRefused)
    assert kernel.creates == 2 and kernel.inputs.closes == 1 and not value.retains_inputs
    _closed(kernel)


def test_late_close_cannot_report_success_or_retry_the_consumed_close():
    value, kernel, clock = _setup()

    def hook(name):
        if name == 'inputs:close':
            clock.time = 41

    kernel.hook = hook
    _failure(value, owner.ValidatorBuildOwnerUnknown)
    assert kernel.inputs.closes == 1 and not value.retains_inputs
    before = list(kernel.events)
    _failure(value, owner.ValidatorBuildOwnerRefused)
    assert kernel.events == before


def test_serialized_concurrent_run_has_exactly_one_transaction():
    value, kernel, _ = _setup()

    def run(_):
        try:
            return value.run()
        except owner.ValidatorBuildOwnerRefused as error:
            assert type(error) is owner.ValidatorBuildOwnerRefused and str(error) == 'build_one_shot'
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(run, range(8)))
    assert sum(type(result) is owner.LocalBuildObservation for result in results) == 1
    assert kernel.creates == 2 and kernel.inputs.closes == 1


def test_no_default_adapter_clock_cli_native_io_or_carried_tool_wiring():
    path = ROOT / 'night_shifts/bootstrap_native_build_owner.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    imports |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    assert imports <= {'__future__', 'hashlib', 'math', 'threading', 'dataclasses', 'typing', 'collections.abc', 'night_shifts'}
    assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                   and node.func.id in ('open', 'exec', 'eval', 'compile', '__import__') for node in ast.walk(tree))
    signature = inspect.signature(owner._ValidatorBuildOwner)
    assert signature.parameters['kernel'].default is inspect.Parameter.empty
    assert signature.parameters['clock'].default is inspect.Parameter.empty
    assert signature.parameters['deadline'].default is inspect.Parameter.empty
    assert not hasattr(owner._ValidatorBuildOwner, 'dispose')
    assert not hasattr(owner._ValidatorBuildOwner, '__del__')
    assert path.name not in request.CODE_NAMES
    for folder, pattern in [('runtime', '*.py'), ('scripts', '*.ps1')]:
        for source in (ROOT / folder).glob(pattern):
            assert 'bootstrap_native_build_owner' not in source.read_text(encoding='utf-8-sig')
