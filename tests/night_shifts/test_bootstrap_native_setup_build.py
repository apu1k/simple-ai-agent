"""Closed setup profile/build data, one-compiler ownership and real builds.

Observed fixture tool/product pins are consistency TEST data, never production
approval. Builds are UNELEVATED; production entries are run ONLY to test refusal.
"""
from __future__ import annotations

import copy
import hashlib
import struct
import subprocess
import time
from pathlib import Path

import pytest

from night_shifts import bootstrap_native_build as build
from night_shifts import bootstrap_native_build_owner as owner
from night_shifts import bootstrap_native_builder as builder
from night_shifts import bootstrap_native_setup_build as setup_build
from tests.night_shifts.test_bootstrap_native_build import _pins
from tests.night_shifts.test_bootstrap_native_build_owner import Clock, Inputs, Kernel
from tests.night_shifts.test_bootstrap_native_builder import ROOT, _native_case
from tests.night_shifts.test_bootstrap_native_setup import references


def profile(*, publish=False):
    refs = references()
    return {'version': 1, 'scope': setup_build.HOST_SCOPE, 'operation': 'publish' if publish else 'prepare',
        'attempt_id': 'b' * 32, 'budget_seconds': 20, 'expires_unix': 1600,
        'parent': refs['parent'], 'operator_sid': refs['operator_sid'], 'host_anchor': {'path': r'C:\SetupHost',
        'identity': {'volume': 43, 'index': 10}, 'claims_index': 11, 'receipts_index': 12, 'scratch_index': 13},
        'references': refs if publish else None, 'packet': {'bytes': 3, 'sha256': hashlib.sha256(b'abc').hexdigest()} if publish else None}


def candidate(*, watchdog=False, host_profile=None, sources=None, tools=None):
    p = profile() if host_profile is None else host_profile
    names = setup_build.WATCHDOG_SOURCES if watchdog else setup_build.HOST_SOURCES
    sources = {name: b'// inert source\n' for name in names} if sources is None else sources
    tools = {name: b'inert ' + name.encode('ascii') for name in build.TOOLCHAIN_NAMES} if tools is None else tools
    pin = {'bytes': 123, 'sha256': 'a' * 64} if watchdog else None
    generated = {setup_build.HOST_PROFILE_NAME: setup_build.emit_setup_host_profile(p)}
    if watchdog:
        generated[setup_build.WATCHDOG_PROFILE_NAME] = setup_build.emit_setup_watchdog_profile(pin)
    review = {'version': 1, 'scope': setup_build.WATCHDOG_BUILD_SCOPE if watchdog else setup_build.HOST_BUILD_SCOPE,
        'windows_root': r'C:\Windows', 'staging_root': r'C:\SetupBuild', 'host_profile': p, 'host_pin': pin,
        'source_pins': _pins({**sources, **generated}), 'toolchain_pins': _pins(tools),
        'toolchain_aliases': {name: [r'C:\Windows\Microsoft.NET\Framework64\v4.0.30319' + '\\' + name] for name in build.TOOLCHAIN_NAMES}}
    return review, sources, tools


def plan(watchdog, review, sources, tools):
    call = setup_build.plan_setup_watchdog_build if watchdog else setup_build.plan_setup_host_build
    return call(review, source_files=sources, toolchain_files=tools)


@pytest.mark.parametrize('publish', [False, True])
def test_profile_binding_and_source_are_bounded_deterministic_and_non_circular(publish):
    p = profile(publish=publish)
    binding = setup_build.setup_host_binding(p)
    assert binding[:4] == struct.pack('<i', 1)
    raw = setup_build.emit_setup_host_profile(p)
    assert raw == setup_build.emit_setup_host_profile(dict(reversed(tuple(p.items()))))
    assert len(raw) <= 4096 and b'ReviewedSetupHost' in raw
    assert b'host_sha256' not in raw and b'ReviewedSetupSupervisor' not in raw
    assert len(binding) < 4096


@pytest.mark.parametrize('field,bad', [('version', True), ('scope', 'authorized'), ('operation', 'shell'),
    ('attempt_id', 'A' * 32), ('budget_seconds', 301), ('budget_seconds', True), ('expires_unix', 0),
    ('operator_sid', 'S-1-5-18'), ('references', references()), ('packet', {'bytes': 1, 'sha256': 'a' * 64})])
def test_profile_refuses_invalid_or_circular_data(field, bad):
    p = profile()
    p[field] = bad
    with pytest.raises(setup_build.SetupBuildRefused):
        setup_build.emit_setup_host_profile(p)


@pytest.mark.parametrize('watchdog', [False, True])
def test_fixed_single_target_recipe_uses_existing_security_options_and_exact_pins(watchdog):
    review, sources, tools = candidate(watchdog=watchdog)
    recipe = plan(watchdog, review, sources, tools)
    entry = build.SETUP_ENTRY_POINTS[watchdog]
    assert recipe.entry_points == (entry,) and len(recipe.commands) == 1
    assert recipe.expected_outputs == (entry[0], entry[0] + '.config')
    assert '/main:' + entry[1] in recipe.commands[0]
    assert set(build.COMMON_OPTIONS).issubset(recipe.commands[0])
    assert not set(dict(recipe.environment)).intersection({'DEVPATH', 'COMPLUS_Profiler', 'PYTHONPATH'})
    assert all('guardian_entry' not in name and 'worker_entry' not in name for name, _ in recipe.staging_files)
    assert recipe == plan(watchdog, review, dict(reversed(tuple(sources.items()))), tools)


@pytest.mark.parametrize('watchdog', [False, True])
@pytest.mark.parametrize('fault', ['extra_command', 'extra_source', 'changed_source', 'profile_pin', 'host_pin', 'overlap'])
def test_closed_review_refuses_before_native_loader(monkeypatch, watchdog, fault):
    review, sources, tools = candidate(watchdog=watchdog)
    if fault == 'extra_command':
        review['command'] = ['injected.exe']
    elif fault == 'extra_source':
        sources['injected.cs'] = b'// inert\n'
    elif fault == 'changed_source':
        sources[next(iter(sources))] += b'changed'
    elif fault == 'profile_pin':
        review['source_pins'][setup_build.HOST_PROFILE_NAME]['sha256'] = '0' * 64
    elif fault == 'host_pin':
        review['host_pin'] = None if watchdog else {'bytes': 1, 'sha256': 'a' * 64}
    else:
        review['staging_root'] = review['host_profile']['host_anchor']['path']
    monkeypatch.setattr(builder, '_WindowsBuildKernel', lambda *_: pytest.fail('refused build reached kernel construction'))
    # The owner reconstructs the closed recipe before any native call. Kernel
    # construction itself is inert; exercise that ordering with an inert object.
    with pytest.raises((setup_build.SetupBuildRefused, owner.ValidatorBuildOwnerRefused)):
        owner._ValidatorBuildOwner(review, source_files=sources, toolchain_files=tools,
            kernel=object(), clock=lambda: 10.0, deadline=30.0, setup_phase='watchdog' if watchdog else 'host')


class OneInputs(Inputs):
    def outputs(self):
        assert self.kernel.creates == 1 and self.kernel.count == 0 and not self.closed
        self.kernel.event('outputs')
        return {n: build.request._CONFIG if n.endswith('.config') else b'inert output' for n in self.kernel.recipe.expected_outputs}


@pytest.mark.parametrize('phase', ['host', 'watchdog'])
@pytest.mark.parametrize('fault', [None, 'create:1', 'resume:1', 'wait:1:100', 'stop:1', 'close:1:process'])
def test_existing_build_owner_supports_one_closed_command_and_retains_on_uncertainty(monkeypatch, phase, fault):
    retained = []
    monkeypatch.setattr(owner, '_RETAINED', retained)  # inert model storage ONLY
    review, sources, tools = candidate(watchdog=phase == 'watchdog')
    clock = Clock()
    kernel = Kernel(clock)
    kernel.inputs = OneInputs(kernel)
    if fault == 'stop:1':
        kernel.mode = 'timeout'
    kernel.fault = fault
    tx = owner._ValidatorBuildOwner(review, source_files=sources, toolchain_files=tools,
        kernel=kernel, clock=clock, deadline=40, setup_phase=phase)
    if fault is None:
        result = tx.run()
        assert len(result.artifacts) == 2 and kernel.creates == kernel.jobs == 1 and kernel.inputs.closed
    else:
        with pytest.raises(owner.ValidatorBuildOwnerUnknown):
            tx.run()
        assert tx.retains_inputs and retained == [tx] and not kernel.inputs.closed
    assert all(h.closes <= 1 for h in kernel.handles)


@pytest.fixture(scope='module')
def native_products():
    with _native_case() as case:
        p = profile()
        from night_shifts import bootstrap_native_build_windows as windows
        p['operator_sid'] = windows._Windows().operator()
        p['expires_unix'] = int(time.time()) + 600
        products = {}
        for watchdog, label in ((False, 'host'), (True, 'watchdog')):
            names = setup_build.WATCHDOG_SOURCES if watchdog else setup_build.HOST_SOURCES
            sources = {n: (ROOT / 'scripts' / n).read_bytes() for n in names}
            review, sources, tools = candidate(watchdog=watchdog, host_profile=p, sources=sources, tools=case.tools)
            review['windows_root'] = case.review['windows_root']
            review['toolchain_aliases'] = copy.deepcopy(case.review['toolchain_aliases'])
            review['staging_root'] = str(case.parent / (label + '-build'))
            if watchdog:
                raw = products[build.SETUP_ENTRY_POINTS[0][0]]
                # OBSERVED test bytes only, explicitly NOT independent approval.
                review['host_pin'] = {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
                review['source_pins'][setup_build.WATCHDOG_PROFILE_NAME] = _pins({setup_build.WATCHDOG_PROFILE_NAME:
                    setup_build.emit_setup_watchdog_profile(review['host_pin'])})[setup_build.WATCHDOG_PROFILE_NAME]
            call = builder.build_setup_watchdog_candidate if watchdog else builder.build_setup_host_candidate
            result = call(review, source_files=sources, toolchain_files=tools, deadline=time.monotonic() + 25)
            assert len(result.artifacts) == 2
            products.update({a.name: a.raw for a in result.artifacts})
            for artifact in result.artifacts:
                assert artifact.raw == (Path(review['staging_root']) / 'out' / artifact.name).read_bytes()
        yield products, p, case
        case.clean = True


def test_real_unelevated_transaction_builds_both_setup_products_without_installation(native_products):
    products, _, _ = native_products
    assert set(products) == {n for exe, _ in build.SETUP_ENTRY_POINTS for n in (exe, exe + '.config')}
    from night_shifts.bootstrap_native_build_artifacts import inspect_fixed_executable
    for name, _ in build.SETUP_ENTRY_POINTS:
        info = inspect_fixed_executable(name, products[name])
        assert info.entry == dict(build.SETUP_ENTRY_POINTS)[name]


def test_production_entries_refuse_unelevated_execution_without_setup_mutation(native_products):
    products, _, case = native_products
    root = case.parent / 'refusal-only'
    root.mkdir()
    for name, data in products.items():
        (root / name).write_bytes(data)
    host = build.SETUP_ENTRY_POINTS[0][0]
    args = ['--setup-once-qpc-v1', '1000000', '1000', str(len(products[host])), hashlib.sha256(products[host]).hexdigest()]
    for name, argv in ((host, args), (build.SETUP_ENTRY_POINTS[1][0], [])):
        result = subprocess.run([str(root / name), *argv], cwd=root, capture_output=True, timeout=10, check=False)
        assert result.returncode == 126 and not result.stdout and not result.stderr
    assert {p.name for p in root.iterdir()} == set(products)
    # Precise production-role refusal is separately asserted by compiled models;
    # exit code alone does not establish its intended refusal point or provenance.
