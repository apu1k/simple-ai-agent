"""Memory-only setup framing with inert request/file/profile DATA."""
from __future__ import annotations

import copy
import hashlib
import json
import struct
from dataclasses import FrozenInstanceError

import pytest

from night_shifts import bootstrap_native_install_request as request
from night_shifts import bootstrap_native_setup as setup
from tests.night_shifts.test_native_validator_install_request import candidate


def references():
    return {'version': 1, 'scope': setup.SCOPE, 'operator_sid': 'S-1-5-21-1-2-3-1001',
        'parent': {'path': r'C:\SetupParent', 'identity': {'volume': 42, 'index': 2}},
        'indices': {name: index for index, name in enumerate(setup.ANCHORS, 100)}}


def inputs():
    refs, value = references(), candidate()
    root = refs['parent']['path'] + '\\' + setup.LEAF
    for field, name in (('launch_anchor', 'launch'), ('import_anchor', 'imports')):
        value[field]['path'] = root + '\\' + name
        value[field]['identity']['index'] = refs['indices'][name]
    value['launch_anchor']['scratch_identity']['index'] = refs['indices']['launch/scratch']

    def raw(name):
        if name in request._EMPTY:
            return b''
        if name == 'runtime/python314._pth':
            return request._PTH
        if name.endswith('.exe.config'):
            return request._CONFIG
        return b'INERT NONRUNNABLE MODEL:' + name.encode('ascii')

    imports = {name: raw(name) for name in request.IMPORT_NAMES}
    launches = {name: raw(name) for name in request.LAUNCH_NAMES}
    return refs, value, imports, launches


def packet(refs=None, value=None, imports=None, launches=None):
    default = inputs()
    refs = default[0] if refs is None else refs
    value = default[1] if value is None else value
    imports = default[2] if imports is None else imports
    launches = default[3] if launches is None else launches
    raw = request.build_validation_install_request(value)
    return setup.prepare_validation_setup_packet(refs, raw, expected_bytes=len(raw),
        expected_sha256=hashlib.sha256(raw).hexdigest(), import_files=imports, launch_files=launches)


def decode(raw):
    assert raw[:8] == setup.MAGIC
    count, = struct.unpack_from('<I', raw, 8)
    result, offset = {}, 12
    for _ in range(count):
        length, = struct.unpack_from('<H', raw, offset)
        offset += 2
        name = raw[offset:offset + length].decode('ascii')
        offset += length
        size, = struct.unpack_from('<I', raw, offset)
        offset += 4
        assert name not in result
        result[name] = raw[offset:offset + size]
        offset += size
    assert offset == len(raw)
    return result


def test_fixed_packet_determinism_projection_and_non_circular_profile():
    refs, value, imports, launches = inputs()
    result = packet(refs, value, imports, launches)
    files = decode(result.packet)
    assert len(files) == 94 and tuple(files) == setup.PACKET_NAMES
    assert result == packet(refs, value, dict(reversed(list(imports.items()))), launches)
    assert result.sha256 == hashlib.sha256(result.packet).hexdigest()
    assert files['reviewed-profile.cs'] == result.guardian_profile == setup.setup_guardian_profile(refs)
    raw = request.build_validation_install_request(value)
    bound = request.bind_validation_install_request(raw, expected_bytes=len(raw), expected_sha256=hashlib.sha256(raw).hexdigest())
    assert files['imports/provision-request.json'] == bound.worker_request
    policy = json.loads(files['approval/approval.json'])
    assert policy['request_sha256'] == bound.request_sha256
    assert policy['scope'] == 'protected_native_validator_install_approval_once'
    assert bound.request_sha256.encode() not in result.guardian_profile
    assert all(files['imports/' + name] == data for name, data in imports.items())
    assert all(files['launch/' + name] == data for name, data in launches.items())
    with pytest.raises(FrozenInstanceError):
        result.sha256 = '0' * 64


@pytest.mark.parametrize('fault', ['missing', 'extra', 'case', 'changed', 'bytearray'])
@pytest.mark.parametrize('which', ['imports', 'launches'])
def test_exact_independently_pinned_inventory(fault, which):
    refs, value, imports, launches = inputs()
    target = imports if which == 'imports' else launches
    name = next(iter(target))
    if fault == 'missing':
        del target[name]
    elif fault == 'extra':
        target['extra.exe'] = b'inert'
    elif fault == 'case':
        target[name.upper()] = target.pop(name)
    elif fault == 'changed':
        target[name] += b'changed'
    else:
        target[name] = bytearray(target[name])
    with pytest.raises(setup.SetupRefused, match='^(inventory|leaf_pin)$'):
        packet(refs, value, imports, launches)


@pytest.mark.parametrize('fault', ['extra', 'version', 'scope', 'sid', 'zero', 'alias', 'parent_alias', 'path', 'quote'])
def test_references_are_closed_canonical_distinct_and_non_executable(fault):
    refs = references()
    if fault == 'extra':
        refs['reset'] = True
    elif fault == 'version':
        refs['version'] = True
    elif fault == 'scope':
        refs['scope'] = 'approved'
    elif fault == 'sid':
        refs['operator_sid'] = 'S-1-5-18'
    elif fault == 'zero':
        refs['indices'][''] = 0
    elif fault == 'alias':
        refs['indices'][''] = refs['indices']['approval']
    elif fault == 'parent_alias':
        refs['indices'][''] = refs['parent']['identity']['index']
    elif fault == 'path':
        refs['parent']['path'] = r'C:\..\Setup'
    else:
        refs['parent']['path'] = 'C:\\Setup"Injected'
    with pytest.raises(setup.SetupRefused):
        setup.setup_guardian_profile(refs)


@pytest.mark.parametrize('fault', ['sid', 'launch', 'imports', 'scratch', 'approval_overlap', 'root_alias', 'parent_alias'])
def test_request_must_bind_the_whole_prepared_tree(fault):
    refs, value, imports, launches = inputs()
    if fault == 'sid':
        value['operator_sid'] = 'S-1-5-21-1-2-3-1002'
    elif fault in ('launch', 'imports'):
        value['launch_anchor' if fault == 'launch' else 'import_anchor']['identity']['index'] = 500
    elif fault == 'scratch':
        value['launch_anchor']['scratch_identity']['index'] = 500
    else:
        place = value['provision']['source']
        if fault == 'approval_overlap':
            place['path'] = refs['parent']['path'] + '\\' + setup.LEAF + '\\approval'
        else:
            place['identity']['index'] = refs['indices'][''] if fault == 'root_alias' else refs['parent']['identity']['index']
    with pytest.raises(setup.SetupRefused):
        packet(refs, value, imports, launches)


@pytest.mark.parametrize('fault', ['hash', 'size', 'mutable', 'noncanonical'])
def test_whole_request_pin_precedes_parsing(fault):
    refs, value, imports, launches = inputs()
    raw = request.build_validation_install_request(value)
    if fault == 'noncanonical':
        raw += b' '
    digest = hashlib.sha256(raw).hexdigest()
    with pytest.raises(setup.SetupRefused, match='^request_or_references$'):
        setup.prepare_validation_setup_packet(refs, bytearray(raw) if fault == 'mutable' else raw,
            expected_bytes=len(raw) + (fault == 'size'), expected_sha256='0' * 64 if fault == 'hash' else digest,
            import_files=imports, launch_files=launches)


def test_no_io_native_loading_or_product_execution_and_no_carried_catalog_expansion():
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    path = root / 'night_shifts/bootstrap_native_setup.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    imported = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert not imported.intersection({'ctypes', 'subprocess', 'os', 'pathlib'})
    assert path.name not in request.CODE_NAMES
    assert setup.LEAF == 'native-validator-bootstrap'
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, 'attr', '')
            assert name not in {'open', 'read_bytes', 'write_bytes', 'Popen', 'run', 'eval', 'exec'}
    changed = copy.deepcopy(references())
    changed['indices']['approval'] = 500
    assert setup.setup_guardian_profile(changed) != setup.setup_guardian_profile(references())
