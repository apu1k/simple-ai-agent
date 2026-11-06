"""Offline Python worker projection/handoff models, NOT native execution.

Synthetic request/bundle bytes, fake clocks and provisioner/Windows backends only.
No protected caller, carried runtime, approval, claim, process launch or VM.
"""
from __future__ import annotations

import ast
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest

from night_shifts import bootstrap_native_install_request as profile
from night_shifts import bootstrap_native_provision as m
from tests.night_shifts import test_bootstrap_native_provision as provision_models

candidate = provision_models.candidate
env = provision_models.env


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode('ascii')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture
def wire():
    # Execute only the inert fixture function, never its sibling module body.
    path = Path(__file__).with_name('test_native_validator_request_guardian.py')
    functions = [n for n in ast.parse(path.read_text(encoding='utf-8')).body
                 if isinstance(n, ast.FunctionDef) and n.name == '_candidate']
    assert len(functions) == 1
    namespace = {'profile': profile, '_sha': sha, '_canonical': canonical}
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(path), 'exec'), namespace)
    outer = profile.build_validation_install_request(namespace['_candidate']())
    bound = profile.bind_validation_install_request(outer, expected_bytes=len(outer), expected_sha256=sha(outer))
    raw = bound.worker_request
    return SimpleNamespace(raw=raw, document=json.loads(raw), outer=sha(outer))


@pytest.fixture
def probe(monkeypatch):
    state = SimpleNamespace(now=100.0, wall=1000.0, events=[], hook=lambda _: None,
        result=m.LocalProvisionedInputs('a' * 32, 'MODEL_ROOT', m.native.FileIdentity(42, 50),
            'MODEL_MEDIA', m.native.FileIdentity(42, 51), 'f' * 64))
    monkeypatch.setattr(m, '_now', lambda: state.now)
    monkeypatch.setattr(m, '_utc', lambda: state.wall)

    class FakeProvisioner:
        def __init__(self, source, parent, plan, *, deadline):
            state.events.append(('construct', source, parent, plan, deadline))
            state.hook('construct')

        def run(self):
            state.events.append(('run',))
            state.hook('run')
            return state.result

    monkeypatch.setattr(m, 'NativeValidationProvisioner', FakeProvisioner)
    return state


def handoff(wire, *, raw=None, **changes):
    pin = wire.raw if raw is None else raw
    args = dict(expected_bytes=len(pin), expected_sha256=sha(pin), request_sha256=wire.outer,
                budget_seconds=10, expires_unix=1900, deadline=108.0)
    args.update(changes)
    return m.ProvisionWorkerHandoff(**args)


def no_retry(body, raw, probe):
    events = list(probe.events)
    with pytest.raises(m.ProvisionRefused, match='^one_shot$'):
        body.run(raw)
    assert probe.events == events


def test_host_projection_maps_all_provision_fields_without_new_budget(wire, probe):
    body = handoff(wire)
    assert probe.events == []
    probe.now = 102.5
    assert body.run(wire.raw) is probe.result
    constructor, run = probe.events
    assert constructor[:3] == ('construct', r'C:\Inputs', r'C:\Outputs')
    plan, deadline = constructor[3:]
    assert deadline == 108.0 and run == ('run',)
    assert plan.installation_id == wire.document['installation_id']
    assert plan.source_identity == m.native.FileIdentity(42, 30)
    assert plan.parent_identity == m.native.FileIdentity(42, 40)
    assert plan.bundle_sha256 == wire.document['provision']['bundle']['sha256']
    assert plan.bundle_bytes == wire.document['provision']['bundle']['bytes']
    assert asdict(plan.pins) == wire.document['provision']['pins']
    no_retry(body, wire.raw, probe)


@pytest.mark.parametrize('field,value', [
    ('expected_bytes', 0), ('expected_bytes', True), ('expected_bytes', 8193),
    ('expected_sha256', None), ('expected_sha256', 'A' * 64), ('request_sha256', 'x' * 64),
    ('budget_seconds', 5), ('budget_seconds', 901), ('budget_seconds', True),
    ('expires_unix', 0), ('expires_unix', True), ('expires_unix', 253402300800),
    ('deadline', None), ('deadline', True), ('deadline', float('nan')),
    ('deadline', float('inf')), ('deadline', 100.0), ('deadline', 99.0),
])
def test_invalid_constructor_has_no_provisioning(wire, probe, field, value):
    with pytest.raises(m.ProvisionRefused):
        handoff(wire, **{field: value})
    assert probe.events == []


@pytest.mark.parametrize('deadline', [
    pytest.param(10**1000, id='huge_positive'),
    pytest.param(-(10**1000), id='huge_negative'),
])
def test_out_of_float_range_deadline_has_fixed_label_before_clocks(wire, probe, monkeypatch, deadline):
    def unexpected_clock():
        pytest.fail('clock entered before invalid deadline refusal')
    monkeypatch.setattr(m, '_now', unexpected_clock)
    monkeypatch.setattr(m, '_utc', unexpected_clock)
    with pytest.raises(m.ProvisionRefused, match='^worker_window$') as caught:
        handoff(wire, deadline=deadline)
    assert caught.value.__context__ is None
    assert probe.events == []


@pytest.mark.parametrize('field,value', [('now', float('nan')), ('now', float('inf')),
    ('wall', float('nan')), ('wall', float('inf')), ('wall', -1), ('wall', 1900)])
def test_invalid_initial_clock_or_expiry(wire, probe, field, value):
    setattr(probe, field, value)
    with pytest.raises(m.ProvisionRefused):
        handoff(wire)
    assert probe.events == []


def test_far_expiry_refuses_without_constructing_provisioner(wire, probe):
    with pytest.raises(m.ProvisionRefused, match='worker_window'):
        handoff(wire, expires_unix=1000 + 86401)
    assert probe.events == []


@pytest.mark.parametrize('raw', [None, bytearray(b'{}'), memoryview(b'{}'), '{}', b'', b'{}'])
def test_invalid_input_is_terminal_before_provisioner(wire, probe, raw):
    body = handoff(wire)
    with pytest.raises(m.ProvisionRefused, match='worker_pin'):
        body.run(raw)
    assert probe.events == []
    no_retry(body, wire.raw, probe)


def test_hash_precedes_json_parser(wire, probe, monkeypatch):
    body = handoff(wire)
    monkeypatch.setattr(m.json, 'loads', lambda *_a, **_k: pytest.fail('parser entered before pin'))
    with pytest.raises(m.ProvisionRefused, match='worker_pin'):
        body.run(b'x' * len(wire.raw))
    assert probe.events == []


@pytest.mark.parametrize('raw', [b'not json', b'\xff', b'[]', b'null', b'{"x":1,"x":2}',
    b'{"x":NaN}', b'{"x":Infinity}', b'[' * 2000 + b']' * 2000])
def test_pinned_malformed_json_has_fixed_labels_and_is_terminal(wire, probe, raw):
    body = handoff(wire, raw=raw)
    with pytest.raises(m.ProvisionRefused) as caught:
        body.run(raw)
    assert str(caught.value).startswith('worker_')
    assert probe.events == []
    no_retry(body, wire.raw, probe)


@pytest.mark.parametrize('path,value', [
    ('version', True), ('version', 2), ('scope', 'approved'), ('operation', 'arbitrary'),
    ('installation_id', 'A' * 32), ('installation_id', '../x'),
    ('operator_sid', 'S-1-5-18'), ('operator_sid', 'S-1-5-21-01-2-3-1001'),
    ('operator_sid', 'S-1-5-21-4294967296-2-3-1001'),
    ('request_sha256', 'e' * 64), ('budget_seconds', 11), ('budget_seconds', True),
    ('expires_unix', 1901), ('launch_anchor.path', r'c:\Launch'),
    ('launch_anchor.path', r'C:\CON'), ('import_anchor.path', r'C:\Imports\..\Else'),
    ('provision.source.path', r'\\server\share'), ('provision.output_parent.path', r'C:\Outputs:ads'),
    ('provision.output_parent.path', 'C:' + chr(92) + 'O' * 120 + chr(92) + 'P' * 70),
    ('provision.bundle.bytes', True), ('provision.bundle.bytes', 64 * 1024**2 + 1),
    ('provision.bundle.sha256', 'B' * 64), ('provision.pins.runtime_bytes', 0),
    ('provision.pins.recovery_bytes', 40961), ('provision.pins.recovery_bytes', 8 * 1024**3 + 2048),
    ('provision.pins.code_tree_sha256', None), ('provision.pins.codec_tree_sha256', 'x' * 64),
    ('provision.source.identity.volume', True), ('provision.source.identity.index', 0),
    ('provision.source.identity.index', 2**64), ('launch_anchor.scratch_identity.volume', 99),
    ('provision.source.path', r'C:\Imports\Child'), ('provision.source.path', r'C:\IMPORTS'),
    ('provision.output_parent.path', r'C:\Private Anchor'),
    ('provision.output_parent.identity', {'volume': 42, 'index': 30}),
    ('import_anchor.identity', {'volume': 77, 'index': 3}),
])
def test_pinned_invalid_schema_never_reaches_provisioner(wire, probe, path, value):
    target = wire.document
    parts = path.split('.')
    for part in parts[:-1]:
        target = target[part]
    target[parts[-1]] = value
    raw = canonical(wire.document)
    body = handoff(wire, raw=raw)
    with pytest.raises(m.ProvisionRefused):
        body.run(raw)
    assert probe.events == []
    no_retry(body, wire.raw, probe)


@pytest.mark.parametrize('location', ['', 'launch_anchor', 'import_anchor', 'provision',
    'provision.bundle', 'provision.pins', 'provision.source', 'provision.source.identity'])
@pytest.mark.parametrize('mode', ['extra', 'missing'])
def test_exact_nested_key_sets(wire, probe, location, mode):
    target = wire.document
    for part in filter(None, location.split('.')):
        target = target[part]
    if mode == 'extra':
        target['SYNTHETIC_UNKNOWN'] = 1
    else:
        del target[next(iter(target))]
    raw = canonical(wire.document)
    with pytest.raises(m.ProvisionRefused):
        handoff(wire, raw=raw).run(raw)
    assert probe.events == []


@pytest.mark.parametrize('mode', ['space', 'newline_missing', 'newline_extra', 'order',
    'float', 'escaped', 'duplicate', 'trailing'])
def test_whole_pin_does_not_allow_noncanonical_projection(wire, probe, mode):
    raw = wire.raw
    variants = {
        'space': b' ' + raw, 'newline_missing': raw[:-1], 'newline_extra': raw + b'\n',
        'order': (json.dumps(wire.document, sort_keys=True, indent=1) + '\n').encode('ascii'),
        'float': raw.replace(b'"budget_seconds":10', b'"budget_seconds":10.0'),
        'escaped': raw.replace(b'"operation"', b'"\\u006fperation"'),
        'duplicate': raw.replace(b'"version":1', b'"version":1,"version":1'),
        'trailing': raw + b'{}',
    }
    raw = variants[mode]
    with pytest.raises(m.ProvisionRefused):
        handoff(wire, raw=raw).run(raw)
    assert probe.events == []


@pytest.mark.parametrize('field,value', [('now', 108.0), ('now', 99.0), ('now', float('nan')),
    ('now', float('inf')), ('wall', 1900.0), ('wall', float('nan'))])
def test_reception_consumes_original_window(wire, probe, field, value):
    body = handoff(wire)
    setattr(probe, field, value)
    with pytest.raises(m.ProvisionRefused):
        body.run(wire.raw)
    assert probe.events == []
    no_retry(body, wire.raw, probe)


def test_decoding_consumes_original_window(wire, probe, monkeypatch):
    original = m._worker_bind
    def bind(*args):
        result = original(*args)
        probe.now = 108.0
        return result
    monkeypatch.setattr(m, '_worker_bind', bind)
    body = handoff(wire)
    with pytest.raises(m.ProvisionRefused, match='worker_window'):
        body.run(wire.raw)
    assert probe.events == []
    no_retry(body, wire.raw, probe)


def test_expiry_after_provisioner_construction_prevents_run(wire, probe):
    body = handoff(wire)
    probe.hook = lambda _: setattr(probe, 'now', 108.0)
    with pytest.raises(m.ProvisionRefused, match='worker_window'):
        body.run(wire.raw)
    assert [event[0] for event in probe.events] == ['construct']


@pytest.mark.parametrize('deadline,wall,expected', [(109.0, 1000.0, 109.0),
    (10000.0, 1000.0, 110.0), (108.0, 1899.0, 101.0), (108.0, 1000.0, 108.0)])
def test_window_only_shortens_supplied_deadline(wire, probe, deadline, wall, expected):
    probe.wall = wall
    handoff(wire, deadline=deadline).run(wire.raw)
    assert probe.events[0][-1] == expected


def test_wall_rollback_does_not_renew_monotonic_window(wire, probe):
    body = handoff(wire)
    probe.wall, probe.now = 500.0, 107.0
    body.run(wire.raw)
    assert probe.events[0][-1] == 108.0


@pytest.mark.parametrize('mode', ['refused', 'unknown', 'unexpected', 'late', 'wall_late', 'bad_result'])
def test_post_entry_failure_never_returns_acceptance_or_retries(wire, probe, mode):
    body = handoff(wire)
    def hook(event):
        if event != 'run':
            return
        if mode == 'refused':
            raise m.ProvisionRefused('write_unknown')
        if mode == 'unknown':
            raise m.ProvisionUnknown('close_unknown')
        if mode == 'unexpected':
            raise OSError('SYNTHETIC_CANARY')
        if mode == 'late':
            probe.now = 108.0
        if mode == 'wall_late':
            probe.wall = 1900.0
        if mode == 'bad_result':
            probe.result = object()
    probe.hook = hook
    with pytest.raises(m.ProvisionUnknown) as caught:
        body.run(wire.raw)
    assert 'CANARY' not in str(caught.value)
    assert [event[0] for event in probe.events] == ['construct', 'run']
    no_retry(body, wire.raw, probe)


def test_concurrent_calls_enter_fixed_provisioner_once(wire, probe):
    body = handoff(wire)
    def run(_):
        try:
            return body.run(wire.raw)
        except m.ProvisionRefused as ex:
            assert str(ex) == 'one_shot'
            return None
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(run, range(16)))
    assert sum(result is probe.result for result in results) == 1
    assert [event[0] for event in probe.events] == ['construct', 'run']


def test_actual_provisioner_composition_with_fake_windows(env, wire, monkeypatch):
    monkeypatch.setattr(m, '_utc', lambda: 1000.0)
    # Synthetic references for this composition model, NOT a real outer request
    # approval. The earlier test uses the actual host-derived worker projection.
    wire.document['provision'] = {
        'source': {'path': provision_models.SOURCE, 'identity': {'volume': 42, 'index': 2}},
        'output_parent': {'path': provision_models.PARENT, 'identity': {'volume': 42, 'index': 3}},
        'bundle': {'bytes': len(env.raw), 'sha256': sha(env.raw)}, 'pins': asdict(env.plan.pins),
    }
    raw = canonical(wire.document)
    body = handoff(wire, raw=raw)
    result = body.run(raw)
    assert type(result) is m.LocalProvisionedInputs and result.installation_id == 'a' * 32
    record = json.loads(env.api.data[env.api.install_root + '\\installation.json'])
    assert record['scope'] == 'local_provisioning_consistency_only'
    assert record['bootstrap'] == 'not_supplied'
    provision_models.closed(env.api)
    events = list(env.api.events)
    with pytest.raises(m.ProvisionRefused, match='one_shot'):
        body.run(raw)
    assert env.api.events == events


def test_existing_catalog_no_host_import_or_entrypoint():
    source = Path(m.__file__).read_text(encoding='utf-8')
    tree = ast.parse(source)
    assert not hasattr(m, 'main')
    assert 'bootstrap_native_install_request' not in source
    assert 'bootstrap_native_provision.py' in m.deployment.CODE_FILES
    assert len(m.deployment.BUNDLE_NAMES) == 91
    assert len(profile.IMPORT_NAMES) + 1 == 87
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not {n.name for n in node.names} & {'subprocess', 'argparse', 'sys'}
        if isinstance(node, ast.Attribute):
            assert node.attr not in ('Popen', 'execve', 'extractall', 'unlink', 'rmdir')
