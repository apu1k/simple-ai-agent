"""Native UNELEVATED build characterization, plus closed-platform/data checks.

Ordinary random temporary trees, inert generated profile, OBSERVED test compiler
pins only. No production profile, protected installation, VM, produced-EXE launch
or Main invocation. Unknown outcomes retain trees/owners, never reset or sweep.
"""
from __future__ import annotations

import ast
import copy
import ctypes as c
import os
import shutil
import tempfile
import time
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from night_shifts import bootstrap_native_build as build
from night_shifts import bootstrap_native_build_artifacts as artifacts
from night_shifts import bootstrap_native_build_owner as owner
from night_shifts import bootstrap_native_build_stage as stage_module
from night_shifts import bootstrap_native_build_windows as windows
from night_shifts import bootstrap_native_builder as builder
from night_shifts import maintenance_store_native_prototype as native
from night_shifts.ubuntu_preparation_control import AclRule, AclSnapshot
from tests.night_shifts.test_bootstrap_native_build import _candidate, _pins

ROOT = Path(__file__).resolve().parents[2]
SID = 'S-1-5-21-1-2-3-1001'


def _private(*, directory=False, inherited=False):
    flags = 16 if inherited else (3 if directory else 0)
    return native.Observation(native.FileIdentity(1, 2), 16 if directory else 32, 1, 0,
                              AclSnapshot(SID, tuple(AclRule(sid, 0x1f01ff, flags, 0)
                                                   for sid in (SID, 'S-1-5-18', 'S-1-5-32-544'))), not inherited)


def _policy(value, *, directory=False, tool=False, private=True, inherited=False):
    data = object.__new__(stage_module._BuildStage)
    data.sid = SID
    data._policy(value, directory=directory, tool=tool, private=private, inherited=inherited)


@pytest.mark.parametrize('directory,inherited', [(False, False), (True, False), (False, True)])
def test_private_created_and_inherited_output_profiles_are_explicit(directory, inherited):
    _policy(_private(directory=directory, inherited=inherited), directory=directory, inherited=inherited)


@pytest.mark.parametrize('fault', ['owner', 'unprotected', 'world', 'extra', 'deny', 'flags', 'write_inherit',
                                  'hardlink', 'reparse', 'sparse', 'compressed'])
def test_private_staging_and_outputs_do_not_relax_permissions_or_object_shape(fault):
    value = _private()
    acl = value.acl
    if fault == 'owner':
        value = replace(value, acl=replace(acl, owner='S-1-1-0'))
    elif fault == 'unprotected':
        value = replace(value, protected=False)
    elif fault in ('hardlink', 'reparse', 'sparse', 'compressed'):
        value = replace(value, links=2) if fault == 'hardlink' else replace(
            value, attributes=value.attributes | {'reparse': 0x400, 'sparse': 0x200, 'compressed': 0x800}[fault])
    else:
        rule = acl.rules[0]
        if fault == 'world':
            rule = replace(rule, sid='S-1-1-0')
        elif fault == 'deny':
            rule = replace(rule, kind=1)
        elif fault in ('flags', 'write_inherit'):
            rule = replace(rule, flags=8 if fault == 'flags' else 16)
        rules = (rule, *acl.rules[1:])
        if fault == 'extra':
            rules += (AclRule('S-1-1-0', 0x120089, 0, 0),)
        value = replace(value, acl=replace(acl, rules=rules))
    with pytest.raises((windows.BuildNativeRefused, native.NativeStoreRefused)):
        _policy(value)


def test_os_tool_file_policy_distinguishes_sibling_creation_from_file_data_writes():
    value = _private()
    value = replace(value, protected=False, acl=AclSnapshot('S-1-5-18', (AclRule('S-1-1-0', 0x120089, 0, 0),)))
    _policy(value, private=False, tool=True)
    for mask in (2, 4, 0x40, 0x40000, 0x80000, 0x10000000):
        changed = replace(value, acl=replace(value.acl, rules=(AclRule('S-1-1-0', mask, 0, 0),)))
        with pytest.raises(windows.BuildNativeRefused):
            _policy(changed, private=False, tool=True)


def test_trustedinstaller_is_an_os_build_trust_assumption_not_a_stage_owner_or_acl_repair():
    value = replace(_private(), acl=AclSnapshot(stage_module._TI, (AclRule(stage_module._TI, 0x1f01ff, 0, 0),)))
    _policy(value, tool=True, private=False)
    with pytest.raises(windows.BuildNativeRefused):
        _policy(value)


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), 9.0])
def test_native_window_is_shared_with_owner_and_stage_clock_guard(monkeypatch, bad):
    readings = iter([10.0, 11.0, bad])
    monkeypatch.setattr(windows.time, 'monotonic', lambda: next(readings))
    window = windows._Window(40.0, lambda: False)
    assert window.seconds() == 10 and window.seconds() == 11
    with pytest.raises(windows.BuildNativeRefused):
        window.seconds()


def test_native_kernel_has_no_ambient_recipe_or_pre_host_operations():
    kernel = windows._WindowsBuildKernel(windows._Window(time.monotonic() + 25, lambda: False))
    for call in (kernel.new_job, lambda: kernel.prepare(None), lambda: kernel.create_suspended(None, (), 'C:\\', ())):
        with pytest.raises(windows.BuildNativeRefused):
            call()
    assert kernel.api is None and not kernel.jobs


@pytest.mark.parametrize('field,bad', [('version', True), ('main', 'Injected.Main'), ('scope', 'trusted_build')])
def test_public_entry_reconstructs_closed_review_before_native_calls(monkeypatch, field, bad):
    review, sources, tools = _candidate()
    review[field] = bad
    monkeypatch.setattr(windows, '_Windows', lambda: pytest.fail('invalid review reached native loader'))
    with pytest.raises(build.ValidatorBuildRefused):
        builder.build_validation_candidate(review, source_files=sources, toolchain_files=tools, deadline=time.monotonic() + 20)


def test_public_entry_has_no_profile_pin_discovery_cli_or_tool_wiring():
    for name in ('bootstrap_native_builder', 'bootstrap_native_build_windows', 'bootstrap_native_build_stage',
                 'bootstrap_native_build_artifacts'):
        path = ROOT / 'night_shifts' / (name + '.py')
        tree = ast.parse(path.read_text(encoding='utf-8'))
        assert path.name not in build.request.CODE_NAMES
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in ('Popen', 'run', 'check_call', 'check_output', 'rmtree', 'unlink', 'chmod') or name == 'bootstrap_native_builder'
        for folder, pattern in [('runtime', '*.py'), ('scripts', '*.ps1')]:
            for source in (ROOT / folder).glob(pattern):
                assert name not in source.read_text(encoding='utf-8-sig')


@contextmanager
def _native_case():
    if os.name != 'nt':
        pytest.skip('requires ordinary x64 Windows/NTFS/Framework compiler; NOT protected-route evidence')
    parent = Path(tempfile.mkdtemp(prefix='nb-'))
    case = SimpleNamespace(parent=parent, stage=parent / 'build', clean=False)
    retained, retained_stages = len(owner._RETAINED), len(stage_module._RETAINED_STAGES)
    try:
        root = Path(os.environ['SystemRoot'])
        framework = root / 'Microsoft.NET/Framework64/v4.0.30319'
        sources = {name: (ROOT / 'scripts' / name).read_bytes() for name in build.SOURCE_NAMES}
        tools = {name: (framework / name).read_bytes() for name in build.TOOLCHAIN_NAMES}
        review, sources, tools = _candidate(sources, tools)
        review['windows_root'], review['staging_root'] = str(root), str(case.stage)
        # OBSERVED topology is fixture consistency data, NOT independent review.
        api = windows._Windows()
        api.operator()
        review['toolchain_aliases'] = {name: list(api.aliases(str(framework / name))) for name in build.TOOLCHAIN_NAMES}
        case.review, case.sources, case.tools = review, sources, tools
        yield case
    finally:
        # Cleanup ONLY this disposable fixture after its caller explicitly
        # confirmed the known outcome AND neither registry acquired uncertainty.
        # Unexpected failures deliberately retain the random tree, not sweep it.
        if case.clean and len(owner._RETAINED) == retained and len(stage_module._RETAINED_STAGES) == retained_stages:
            shutil.rmtree(parent)


@contextmanager
def _refusal_target(monkeypatch, case):
    original, trace = builder._WindowsBuildKernel, SimpleNamespace(labels=[], kernels=[], stage_creates=0)

    class Recorded(original):
        def __init__(self, window):
            super().__init__(window)
            trace.kernels.append(self)

    def checked(original_check):
        def check(ok, label):
            if not ok:
                trace.labels.append(label)
            return original_check(ok, label)
        return check

    relative = windows._Windows.relative_build

    def opened(api, parent, name, **kwargs):
        if name == case.stage.name and kwargs.get('create') and kwargs.get('directory'):
            trace.stage_creates += 1
        return relative(api, parent, name, **kwargs)

    # Observe exact fixed labels/phase without bypassing or replacing refusal.
    with monkeypatch.context() as patch:
        patch.setattr(builder, '_WindowsBuildKernel', Recorded)
        patch.setattr(windows._Windows, 'relative_build', opened)
        patch.setattr(windows, '_require', checked(windows._require))
        patch.setattr(stage_module, '_require', checked(stage_module._require))
        yield trace


def _run(case):
    return builder.build_validation_candidate(case.review, source_files=case.sources, toolchain_files=case.tools,
                                              deadline=time.monotonic() + 25)


@pytest.mark.parametrize('directory,kernel_object,rights,flags', [(False, False, 'FA', ''),
    (True, False, 'FA', 'OICI'), (False, True, 'GA', '')])
def test_native_descriptor_rights_match_object_type_without_adding_principals(directory, kernel_object, rights, flags):
    api = object.__new__(windows._Windows)
    seen = []

    def convert(text, revision, output, _size):
        assert revision == 1
        seen.append(text)
        c.cast(output, c.POINTER(c.c_void_p))[0] = 123  # inert fake allocation
        return True

    api.a = SimpleNamespace(ConvertStringSecurityDescriptorToSecurityDescriptorW=convert)
    pointer = api.descriptor(SID, directory, kernel_object=kernel_object)
    assert pointer.value == 123
    assert seen == [f'O:{SID}G:{SID}D:P(A;{flags};{rights};;;{SID})(A;{flags};{rights};;;SY)(A;{flags};{rights};;;BA)']
    with pytest.raises(windows.BuildNativeRefused, match='^native_build_descriptor_kind$'):
        api.descriptor(SID, True, kernel_object=True)
    assert len(seen) == 1


@pytest.mark.parametrize('total,active,allowed', [(1, 1, True), (3, 2, True), (3, 0, True),
    (3, 3, True), (0, 0, False), (4, 1, False), (3, 4, False), (1, 2, False)])
def test_native_accounting_bounds_observations_without_claiming_a_total_creation_quota(total, active, allowed):
    api = object.__new__(windows._Windows)

    def query(handle, kind, output, size, returned):
        assert handle == 123 and kind == 1 and size == c.sizeof(windows._Accounting) and returned is None
        data = c.cast(output, c.POINTER(windows._Accounting)).contents
        data.total, data.active = total, active
        return True

    api.k = SimpleNamespace(QueryInformationJobObject=query)
    kernel = windows._WindowsBuildKernel(windows._Window(time.monotonic() + 25, lambda: False))
    kernel.api = api
    job = windows._Job(native._Handle(api, 123))  # inert fake handle, no acquire/close
    kernel.jobs.append(job)
    if allowed:
        assert kernel.active(job) == active
        assert job.observed_total == total and job.observed_peak_active == active and job.empty == (active == 0)
    else:
        with pytest.raises(windows.BuildNativeRefused, match='^native_build_process_extent$'):
            kernel.active(job)
        assert job.observed_total == job.observed_peak_active == 0


def test_native_wait_samples_cumulative_accounting_before_and_after_the_wait():
    api = object.__new__(windows._Windows)
    calls = []

    def query(_handle, _kind, output, _size, _returned):
        calls.append('accounting')
        data = c.cast(output, c.POINTER(windows._Accounting)).contents
        data.total, data.active = 1, 1
        return True

    def wait(handle, milliseconds):
        assert handle == 124 and milliseconds == 100
        calls.append('wait')
        return 258

    api.k = SimpleNamespace(QueryInformationJobObject=query, WaitForSingleObject=wait)
    kernel = windows._WindowsBuildKernel(windows._Window(time.monotonic() + 25, lambda: False))
    kernel.api = api
    job = windows._Job(native._Handle(api, 123))
    process = windows._Owned(api, 124, 'process')
    kernel.jobs.append(job)
    kernel.process_jobs[id(process)] = job
    assert kernel.wait(process, 100) == 258
    assert calls == ['accounting', 'wait', 'accounting']


def test_native_x64_abi_layouts_without_starting_any_process():
    if os.name != 'nt':
        pytest.skip('Windows x64 ABI')
    assert c.sizeof(c.c_void_p) == 8
    for kind, size in [(windows._Security, 24), (windows._Basic, 64), (windows._Limits, 144),
                       (windows._Accounting, 48), (windows._Startup, 104), (windows._StartupEx, 112),
                       (windows._ProcessInfo, 24)]:
        assert c.sizeof(kind) == size
    assert windows._StartupEx.attributes.offset == 104
    assert windows._ProcessInfo.pid.offset == 16


def test_native_build_both_executables_with_real_atomic_jobs_held_inputs_and_data_only_inspection(monkeypatch):
    original, recorded = builder._WindowsBuildKernel, []
    with _native_case() as case:
        class RecordingKernel(original):
            def __init__(self, window):
                super().__init__(window)
                self.checked_resumes = 0
                self.checked_job_limits = []
                self.stage_lease = None
                recorded.append(self)

            def prepare(self, recipe):
                self.stage_lease = super().prepare(recipe)
                return self.stage_lease

            def new_job(self):
                job = super().new_job()
                limits = windows._Limits()
                assert self.api.k.QueryInformationJobObject(job.handle.value, 9, c.byref(limits), c.sizeof(limits), None)
                assert limits.basic.flags == 0x2008 and limits.basic.active == 2
                self.checked_job_limits.append(int(limits.basic.active))
                return job

            def resume(self, thread):
                # Actual share-read locks, not an in-memory ownership assertion.
                source = case.stage / build.SOURCE_NAMES[0]
                with pytest.raises(OSError):
                    source.open('r+b').close()
                with pytest.raises(OSError):
                    source.unlink()
                assert self.active(self.jobs[-1]) == 1
                self.checked_resumes += 1
                return super().resume(thread)

        monkeypatch.setattr(builder, '_WindowsBuildKernel', RecordingKernel)
        result = _run(case)
        assert len(recorded) == 1
        kernel = recorded[0]
        assert kernel.created == kernel.finished == kernel.checked_resumes == 2
        assert kernel.checked_job_limits == [2, 2]  # accounting does NOT raise the native cap
        assert all(job.closed and job.root_exited and job.empty and job.code == 0 for job in kernel.jobs)
        assert all(job.observed_total == build.BUILD_TOTAL_PROCESS_LIMIT
                   and 1 <= job.observed_peak_active <= build.BUILD_TOTAL_PROCESS_LIMIT for job in kernel.jobs)
        assert {'tool:cvtres.exe', 'tool:cvtres.exe.config'} <= set(kernel.stage_lease.inputs)
        assert kernel.stage_lease.closed and all(handle.value == 0 for handle in kernel.stage_lease.all)
        assert {path.name for path in (case.stage / 'out').iterdir()} == set(build.request.LAUNCH_NAMES)
        assert tuple(item.name for item in result.artifacts) == build.request.LAUNCH_NAMES
        for item in result.artifacts:
            assert item.raw == (case.stage / 'out' / item.name).read_bytes()
            if item.name.endswith('.exe'):
                metadata = artifacts.inspect_fixed_executable(item.name, item.raw)
                assert metadata.entry == dict(build.ENTRY_POINTS)[item.name]
        # Neither produced executable, either Main, carried Python, claims or
        # Hyper-V is invoked. Only the two fixed compiler processes ran.
        case.clean = True


def test_native_occupied_stage_is_not_repaired_overwritten_or_used_for_compilation(monkeypatch):
    with _native_case() as case:
        case.stage.mkdir()
        marker = case.stage / 'retained-marker'
        marker.write_bytes(b'KEEP EXISTING TREE')
        before = marker.stat()
        with _refusal_target(monkeypatch, case) as trace:
            with pytest.raises(owner.ValidatorBuildOwnerUnknown):
                _run(case)
        assert trace.labels == ['native_build_relative_open'] and trace.stage_creates == 1
        assert len(trace.kernels) == 1 and not trace.kernels[0].jobs and trace.kernels[0].created == 0
        assert marker.read_bytes() == b'KEEP EXISTING TREE'
        assert marker.stat().st_ino == before.st_ino
        assert {path.name for path in case.stage.iterdir()} == {'retained-marker'}
        case.clean = True


@pytest.mark.parametrize('name', ['csc.exe', 'cvtres.exe', 'cvtres.exe.config'])
def test_native_actual_tool_byte_mismatch_refuses_before_staging_or_compiler_creation(monkeypatch, name):
    with _native_case() as case:
        case.tools = copy.copy(case.tools)
        raw = case.tools[name]
        case.tools[name] = bytes([raw[0] ^ 1]) + raw[1:]  # same size: MUST reach byte-hash guard
        case.review['toolchain_pins'] = _pins(case.tools)
        with _refusal_target(monkeypatch, case) as trace:
            with pytest.raises(owner.ValidatorBuildOwnerUnknown):
                _run(case)
        assert trace.labels == ['build_stage_input_pin'] and trace.stage_creates == 0
        assert len(trace.kernels) == 1 and not trace.kernels[0].jobs and trace.kernels[0].created == 0
        assert not case.stage.exists()
        case.clean = True


@pytest.mark.parametrize('fault,label', [('unreviewed', 'build_stage_tool_links'), ('wrong_inventory', 'build_stage_tool_aliases')])
def test_native_unapproved_os_alias_topology_refuses_before_stage_or_compiler(monkeypatch, fault, label):
    with _native_case() as case:
        name = next((key for key, paths in case.review['toolchain_aliases'].items() if len(paths) > 1), None)
        if name is None:
            pytest.skip('installed selected OS inputs are all single-link; multi-link fault requires that topology')
        selected = case.review['windows_root'] + '\\Microsoft.NET\\Framework64\\v4.0.30319\\' + name
        paths = case.review['toolchain_aliases'][name]
        if fault == 'unreviewed':
            case.review['toolchain_aliases'][name] = [selected]
        else:
            index = next(i for i, path in enumerate(paths) if path.lower() != selected.lower())
            paths[index] = case.review['windows_root'] + '\\not-an-approved-alias\\' + name
        with _refusal_target(monkeypatch, case) as trace:
            with pytest.raises(owner.ValidatorBuildOwnerUnknown):
                _run(case)
        assert trace.labels == [label] and trace.stage_creates == 0
        assert len(trace.kernels) == 1 and not trace.kernels[0].jobs and trace.kernels[0].created == 0
        assert not case.stage.exists()
        case.clean = True


@pytest.mark.parametrize('tool,owner_sid,allowed', [(False, SID, True), (False, 'S-1-5-18', True),
    (True, 'S-1-5-18', True), (True, stage_module._TI, True), (False, 'S-1-1-0', False), (True, SID, False)])
def test_owner_rights_is_only_the_already_verified_owner_not_a_new_trusted_principal(tool, owner_sid, allowed):
    value = replace(_private(directory=True), protected=False,
                    acl=AclSnapshot(owner_sid, (AclRule('S-1-3-4', 0x1f01ff, 3, 0),)))
    if allowed:
        _policy(value, directory=True, private=False, tool=tool)
    else:
        with pytest.raises(windows.BuildNativeRefused):
            _policy(value, directory=True, private=False, tool=tool)
    # Private stage profiles still require explicit user/SYSTEM/BA ACEs.
    with pytest.raises(windows.BuildNativeRefused):
        _policy(value, directory=True, private=True, tool=tool)


@pytest.mark.parametrize('ok,flags,allowed', [(True, 0, True), (True, 1, False), (True, 2, False), (False, 0, False)])
def test_case_sensitive_or_unqueryable_directory_is_not_accepted(ok, flags, allowed):
    api = object.__new__(windows._Windows)

    def query(handle, kind, output, size):
        assert handle == 123 and kind == 23 and size == 4
        c.cast(output, c.POINTER(c.c_uint32))[0] = flags
        return ok

    api.k = SimpleNamespace(GetFileInformationByHandleEx=query)
    handle = native._Handle(api, 123)  # inert number, never acquired or closed
    if allowed:
        api.require_case_insensitive(handle)
    else:
        with pytest.raises(windows.BuildNativeRefused, match='^native_build_case_sensitive_directory$'):
            api.require_case_insensitive(handle)


@pytest.mark.parametrize('different', ['identity', 'size', 'acl'])
def test_reviewed_alias_does_not_accept_a_different_object_or_metadata(different):
    data = object.__new__(stage_module._BuildStage)
    data.sid, data.all, data.identities = SID, [], set()
    before = native.Observation(native.FileIdentity(1, 99), 32, 2, 100,
                                AclSnapshot('S-1-5-18', (AclRule('S-1-5-18', 0x1f01ff, 0, 0),)), False)
    first = stage_module._Held(SimpleNamespace(value=123), before, 'first', False, False, True, False, 2)
    if different == 'identity':
        after = replace(before, identity=native.FileIdentity(1, 100))
    elif different == 'size':
        after = replace(before, size=101)
    else:
        after = replace(before, acl=AclSnapshot('S-1-5-18', (AclRule('S-1-5-18', 0x120089, 0, 0),)))
    data.api = SimpleNamespace(observe=lambda _handle: after, final_name=lambda _handle: 'second')
    with pytest.raises(windows.BuildNativeRefused, match='^build_stage_tool_alias_identity$'):
        data._adopt(SimpleNamespace(value=124), directory=False, tool=True, reviewed_links=2, alias_of=first)
    assert len(data.all) == 1  # ownership adopted before the rejection


def test_native_checked_compiler_error_stops_before_worker_and_keeps_partial_artifacts():
    with _native_case() as case:
        name = build.SOURCE_NAMES[0]
        case.sources[name] = b'not valid C sharp!\n'
        case.review['source_pins'][name] = _pins(case.sources)[name]
        with pytest.raises(owner.ValidatorBuildOwnerRefused) as caught:
            _run(case)
        assert type(caught.value) is owner.ValidatorBuildOwnerRefused
        assert str(caught.value) == 'build_compiler_exit'
        assert case.stage.exists() and not (case.stage / 'out' / build.ENTRY_POINTS[1][0]).exists()
        assert (case.stage / name).read_bytes() == case.sources[name]
        case.clean = True
