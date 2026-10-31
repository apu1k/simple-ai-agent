"""In-memory canonical input/NoCloud tests ONLY. No ZIP extraction or execution.

The inherited public-seed fixture substitutes daemon/license pins explicitly;
synthetic assets are NOT accepted as real boot evidence. Generated source is
parsed/compiled as data, never executed or written to media.
"""
from __future__ import annotations

import ast
import base64
import hashlib
import io
import json
import zipfile
from dataclasses import FrozenInstanceError

import pytest

from night_shifts import bootstrap_native_handoff as handoff
from night_shifts import bootstrap_probe_seed as public_seed
from night_shifts.guest import bootstrap_native_boot as boot
from tests.night_shifts import test_bootstrap_recovery_handoff as existing

support = existing.support


def render(support):
    return handoff.render_native_validation_handoff(support[0], support[1], expected_seed_sha256=existing.sha(support[1]))


def context(support, result):
    return dict(attempt_id=support[0].attempt_id, vm_id=support[0].vm_id,
                seed_sha256=result.seed_sha256, payload_sha256=result.payload_sha256)


def entries(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def repack(values, ctx, purpose):
    values = {name: raw for name, raw in values.items() if name != 'manifest.json'}
    return boot._zip({**values, 'manifest.json': boot._manifest(values, ctx, purpose)})


def test_deterministic_five_fixed_files_and_minimal_environment_argv(support):
    a, b = render(support), render(support)
    assert a == b and set(a.files()) == {'user-data', 'meta-data', 'network-config', 'support.zip', 'validator.zip'}
    assert a.support_zip == support[1]
    cloud = json.loads(a.user_data.split(b'\n', 1)[1])
    assert cloud['users'] == [] and cloud['disable_root'] is True and cloud['ssh_pwauth'] is False
    assert cloud['package_update'] is cloud['package_upgrade'] is False
    assert not {'write_files', 'bootcmd', 'packages', 'storage', 'autoinstall', 'mounts'} & cloud.keys()
    assert len(cloud['runcmd']) == 1
    argv = cloud['runcmd'][0]
    assert argv[:-1] == ['/usr/bin/env', '-i', 'LANG=C', 'LC_ALL=C', '/usr/bin/python3.12', '-I', '-B', '-S', '-c']
    assert len(argv[-1].encode('ascii')) <= handoff.MAX_COMMAND_BYTES
    assert len(a.user_data) <= handoff.MAX_USER_DATA
    assert json.loads(a.network_config) == {'version': 2, 'ethernets': {}}
    assert json.loads(a.meta_data)['instance-id'] == 'night-shift-native-' + support[0].attempt_id
    assert 'user_data=' not in repr(a) and 'validator_zip=' not in repr(a)
    with pytest.raises(FrozenInstanceError):
        a.payload_sha256 = '0' * 64


def test_generated_root_wrapper_is_only_decoded_and_compiled_as_data(support):
    result = render(support)
    code = json.loads(result.user_data.split(b'\n', 1)[1])['runcmd'][0][-1]
    tree = ast.parse(code, feature_version=(3, 12))
    compile(code, '<native-handoff-data-only>', 'exec', dont_inherit=True)
    blobs = [base64.b64decode(node.args[0].value, validate=True) for node in ast.walk(tree)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
             and node.func.attr == 'b64decode' and isinstance(node.args[0], ast.Constant)]
    source = entries(result.validator_zip)[boot.BOOT_ENTRY]
    assert blobs == [source] and hashlib.sha256(source).hexdigest() == result.bootstrap_sha256
    exits = [node.args[0].value for node in ast.walk(tree) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute) and node.func.attr == '_exit']
    assert set(exits) == {0, 125} and 'subprocess' not in code


def test_closed_payload_catalog_and_public_copies_match_without_inventory_expansion(support):
    result = render(support)
    ctx = context(support, result)
    sources = boot.validate_inputs(ctx, support[1], result.validator_zip)
    assert tuple(boot.PUBLIC_NAMES) == public_seed.ENTRY_NAMES
    assert tuple(boot._PUBLIC_SOURCES) == public_seed.SOURCE_FILES
    assert len(boot.SOURCE_NAMES) == 24 and len(sources) == 23
    assert set(entries(result.validator_zip)) == set(boot.SOURCE_NAMES)
    for name in (*boot.EMPTY_FILES, *('night_shifts/' + name for name in public_seed.SOURCE_FILES)):
        assert sources[name] == support[2][name]
    assert boot.WORKER_SHA256 == hashlib.sha256(sources['night_shifts/guest/bootstrap_native_worker.py']).hexdigest()
    assert boot.POLICY_SHA256 == result.policy_sha256 == hashlib.sha256(sources[boot.POLICY_ENTRY]).hexdigest()
    for name, source in sources.items():
        if not name.endswith('.py'):
            continue
        tree = ast.parse(source.decode('utf-8'), filename=name, feature_version=(3, 12))
        compile(source, name, 'exec', dont_inherit=True)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith('night_shifts'):
                target = node.module.replace('.', '/')
                assert target + '.py' in sources or target + '/__init__.py' in sources, (name, target)
    # No import/evaluation of any archived module is performed by this check.


def test_seed_global_pin_precedes_every_candidate_snapshot(support, monkeypatch):
    monkeypatch.setattr(handoff, '_snapshot', lambda name: pytest.fail('snapshot before seed pin'))
    with pytest.raises(public_seed.ProbeSeedRefused, match='^seed_digest$'):
        handoff.render_native_validation_handoff(support[0], support[1], expected_seed_sha256='0' * 64)


@pytest.mark.parametrize('field', ['seed_sha256', 'payload_sha256'])
def test_whole_input_hash_precedes_zip_parsing(support, monkeypatch, field):
    result = render(support)
    ctx = context(support, result)
    ctx[field] = '0' * 64
    if field == 'seed_sha256':
        monkeypatch.setattr(boot.zipfile, 'ZipFile', lambda *a, **k: pytest.fail('ZIP before full pin'))
    with pytest.raises(boot.NativeBootRefused, match='^input_digest$'):
        boot.validate_inputs(ctx, support[1], result.validator_zip)


@pytest.mark.parametrize('fault', ['missing', 'extra', 'public-copy', 'worker', 'encoding', 'init'])
def test_self_rehashed_bad_payload_is_not_a_valid_input_contract(support, fault):
    result = render(support)
    ctx = context(support, result)
    values = entries(result.validator_zip)
    if fault == 'missing':
        del values[boot.BOOT_ENTRY]
    elif fault == 'extra':
        values['../escape.py'] = b'not code\n'
    elif fault == 'public-copy':
        values['night_shifts/maintenance_tls_prototype.py'] += b'\n'
    elif fault == 'worker':
        values['night_shifts/guest/bootstrap_native_worker.py'] += b'\n'
    elif fault == 'encoding':
        values['night_shifts/bootstrap_native_fixture.py'] = b'\xff\n'
    else:
        values[boot.EMPTY_FILES[0]] = b'x'
    raw = repack(values, ctx, 'native-validator-only')
    ctx['payload_sha256'] = existing.sha(raw)
    with pytest.raises(boot.NativeBootRefused):
        boot.validate_inputs(ctx, support[1], raw)


def test_policy_cannot_be_weakened_even_by_rehashing_both_archive_manifests(support):
    result = render(support)
    ctx = context(support, result)
    public, sources = entries(support[1]), entries(result.validator_zip)
    public[boot.POLICY_ENTRY] = sources[boot.POLICY_ENTRY] = b'UNREVIEWED_SYNTHETIC_POLICY\n'
    seed = repack(public, ctx, 'public-plumbing-only')
    payload = repack(sources, ctx, 'native-validator-only')
    ctx.update(seed_sha256=existing.sha(seed), payload_sha256=existing.sha(payload))
    with pytest.raises(boot.NativeBootRefused, match='^review_pin$'):
        boot.validate_inputs(ctx, seed, payload)


@pytest.mark.parametrize('prefix,suffix', [(b'junk', b''), (b'', b'junk')])
def test_noncanonical_archive_bytes_are_not_salvaged(support, prefix, suffix):
    result = render(support)
    ctx = context(support, result)
    raw = prefix + result.validator_zip + suffix
    ctx['payload_sha256'] = existing.sha(raw)
    with pytest.raises(boot.NativeBootRefused):
        boot.validate_inputs(ctx, support[1], raw)


def test_payload_size_bound_before_parsing(support):
    result = render(support)
    ctx = context(support, result)
    raw = b'x' * (boot.MAX_PAYLOAD + 1)
    ctx['payload_sha256'] = existing.sha(raw)
    with pytest.raises(boot.NativeBootRefused, match='^input_digest$'):
        boot.validate_inputs(ctx, support[1], raw)


@pytest.mark.parametrize('bound', ['MAX_COMMAND_BYTES', 'MAX_USER_DATA'])
def test_no_truncation_when_handoff_bounds_fail(support, monkeypatch, bound):
    monkeypatch.setattr(handoff, bound, 1)
    with pytest.raises(handoff.NativeHandoffRefused):
        render(support)


def test_no_caller_source_path_or_new_production_inventory():
    from night_shifts.inspection_bundle import bundle_bytes
    with pytest.raises(handoff.NativeHandoffRefused, match='^source_inventory$'):
        handoff._snapshot('../outside.py')
    names = {'bootstrap_native_handoff.py', 'guest/bootstrap_native_boot.py'}
    assert not names & set(public_seed.SOURCE_FILES)
    with zipfile.ZipFile(io.BytesIO(bundle_bytes())) as archive:
        assert not {'night_shifts/' + name for name in names} & set(archive.namelist())
