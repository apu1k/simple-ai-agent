"""Offline provisioning BODY/ABI models; never native file writes or installation.

The inherited fixture explicitly substitutes public/source/runtime pins and inert
non-runnable PE/stdlib data. Every Windows/token/filesystem observation below is
replaced. No protected bootstrap, input copy, ACL change, interpreter, ISO or VM.
"""
from __future__ import annotations

import ast
import ctypes as c
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from night_shifts import bootstrap_native_provision as m
from night_shifts.maintenance_credentials_prototype import ADMINS_SID, FULL_CONTROL, SYSTEM_SID
from night_shifts.ubuntu_preparation_control import AclRule, AclSnapshot
from tests.night_shifts import test_bootstrap_native_deployment as assets

candidate = assets.candidate
WindowsAdapter = m._Windows
ROOT = '\\\\?\\Volume{00000000-0000-4000-8000-000000000001}\\'
SOURCE, PARENT = r'C:\Input', r'C:\Protected'
RECOVERY = b'R' * (33 * 2048)  # Two streaming chunks, not an ISO.
USER = 'S-1-5-21-1-2-3-1001'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def observation(index, *, directory=True, size=0, private=True):
    flags = 3 if directory else 0
    acl = AclSnapshot(ADMINS_SID, (AclRule(SYSTEM_SID, FULL_CONTROL, flags),
                                 AclRule(ADMINS_SID, FULL_CONTROL, flags)))
    if not private:
        acl = AclSnapshot(USER, (AclRule(USER, FULL_CONTROL, flags),))
    return m.native.Observation(m.native.FileIdentity(42, index), 0x10 if directory else 0x80,
                               1, size, acl, private)


class Handle:
    def __init__(self, api, path):
        self.api, self.path, self.value = api, path, len(api.handles) + 1
        self.calls = 0
        api.handles.append(self)
    def __exit__(self, *_):
        if self.value:
            self.value = 0
            self.calls += 1
            self.api.events.append(('close', self.path))
            if self.path == self.api.close_fault:
                raise OSError('SYNTHETIC_CANARY')


class FakeApi:
    def __init__(self, raw, clock):
        self.clock, self.events, self.handles = clock, [], []
        self.source, self.parent = ROOT + 'Input', ROOT + 'Protected'
        self.values = {ROOT: observation(1), self.source: observation(2, private=False),
                       self.parent: observation(3)}
        self.data = {self.source + '\\validator-inputs.zip': raw, self.source + '\\recovery.iso': RECOVERY}
        for index, (name, data) in enumerate(self.data.items(), 4):
            self.values[name] = observation(index, directory=False, size=len(data), private=False)
        self.next_id = 10
        self.admin = True
        self.collision = self.write_fault = self.flush_fault = self.replacement = self.writer_acl = False
        self.directory_drift = self.source_drift = self.path_drift = self.alias = False
        self.read_fault = self.close_fault = self.expire_read = None
        self.expire_write = False
        self.install_root = self.parent + '\\native-validator-' + 'a' * 32

    def require_admin(self):
        self.events.append(('admin',))
        if not self.admin:
            raise m.native.NativeStoreRefused('enabled_administrator_required')

    def root(self, drive):
        assert drive == 'C:\\'
        self.events.append(('root', drive))
        return Handle(self, ROOT)

    def _create(self, path, directory):
        if path in self.values or self.collision:
            raise m.native.NativeStoreRefused('relative_create', 183)
        self.values[path] = observation(4 if self.alias else self.next_id, directory=directory)
        self.next_id += 1
        if not directory:
            self.data[path] = b''

    def relative(self, parent, name, **options):
        assert options['directory'] is True
        path = parent.path.rstrip('\\') + '\\' + name
        if options['create']:
            assert options == dict(directory=True, create=True, sddl=m.native._sddl(directory=True), writable=True)
            self.events.append(('mkdir', path))
            self._create(path, True)
        else:
            assert path in self.values and 'sddl' not in options
        return Handle(self, path)

    def leaf(self, parent, name, *, create):
        assert name in m._LEAVES
        path = parent.path.rstrip('\\') + '\\' + name
        self.events.append(('leaf', path, create))
        if create:
            self._create(path, False)
        else:
            assert path in self.values
            if self.replacement and path.startswith(self.install_root):
                self.values[path] = replace(self.values[path], identity=m.native.FileIdentity(42, 9999))
        return Handle(self, path)

    def observe(self, handle):
        assert handle.value
        return self.values[handle.path]

    def final_name(self, handle):
        if self.path_drift and handle.path.startswith(self.install_root):
            return handle.path + '-changed'
        return handle.path

    def chunks(self, handle, size, budget):
        budget.check()
        self.events.append(('read', handle.path))
        if self.expire_read == handle.path:
            self.clock[0] = 200.0
        if self.read_fault == handle.path:
            raise m.ProvisionUnknown('read_unknown')
        data = self.data[handle.path]
        if len(data) != size:
            raise m.ProvisionRefused('read_extent')
        for start in range(0, len(data), m.CHUNK_BYTES):
            budget.check()
            yield data[start:start + m.CHUNK_BYTES]
        budget.check()

    def write(self, handle, data, budget):
        budget.check()
        self.events.append(('write', handle.path, len(data)))
        self.data[handle.path] += data[:len(data) // 2] if self.write_fault else data
        before = self.values[handle.path]
        self.values[handle.path] = replace(before, size=len(self.data[handle.path]), attributes=before.attributes | 0x20)
        if self.writer_acl:
            self.values[handle.path] = replace(self.values[handle.path], protected=False)
        if self.directory_drift:
            self.values[self.install_root] = replace(self.values[self.install_root], protected=False)
        if self.source_drift:
            self.data[self.source + '\\recovery.iso'] = b'X' * len(RECOVERY)
        if self.expire_write:
            self.clock[0] = 200.0
        if self.write_fault:
            raise m.ProvisionUnknown('write_unknown')
        budget.check()

    def flush(self, handle, budget):
        budget.check()
        self.events.append(('flush', handle.path))
        if self.flush_fault:
            raise m.ProvisionUnknown('flush_unknown')


@pytest.fixture
def env(candidate, monkeypatch):
    candidate.pins = replace(candidate.pins, recovery_sha256=sha(RECOVERY), recovery_bytes=len(RECOVERY))
    raw = candidate.build()
    clock = [100.0]
    api = FakeApi(raw, clock)
    monkeypatch.setattr(m, '_now', lambda: clock[0])
    monkeypatch.setattr(m, '_Windows', lambda: api)
    plan = m.ValidationProvisionPlan('a' * 32, m.native.FileIdentity(42, 2), m.native.FileIdentity(42, 3),
                                    sha(raw), len(raw), candidate.pins)
    return SimpleNamespace(api=api, clock=clock, plan=plan, raw=raw)


def provisioner(env, **kwargs):
    return m.NativeValidationProvisioner(SOURCE, PARENT, env.plan, deadline=kwargs.get('deadline', 200.0))


def closed(api):
    assert all(h.value == 0 and h.calls == 1 for h in api.handles)


def no_outputs(api):
    assert not any(e[0] in ('mkdir', 'write') for e in api.events)


def test_complete_model_fixed_tree_inputs_hash_before_create_and_record_last(env):
    body = provisioner(env)
    result = body.run()
    api = env.api
    expected_root = api.install_root
    assert result.root_path == expected_root and result.media_path == expected_root + '\\media'
    outputs = {p[len(expected_root) + 1:].replace('\\', '/'): data for p, data in api.data.items()
               if p.startswith(expected_root + '\\')}
    assert set(outputs) == set(m.deployment.BUNDLE_NAMES) | {'deployment.zip', 'media/recovery.iso', 'installation.json'}
    assert outputs['deployment.zip'] == env.raw and outputs['media/recovery.iso'] == RECOVERY
    record = json.loads(outputs['installation.json'])
    assert record['scope'] == 'local_provisioning_consistency_only' and record['bootstrap'] == 'not_supplied'
    assert set(record['files']) == set(outputs) - {'installation.json'}
    assert result.record_sha256 == sha(outputs['installation.json']) and len(outputs['installation.json']) <= m.MAX_RECORD_BYTES
    assert not {'accepted', 'approved', 'installed', 'gate_a', 'vm_absent'} & record.keys()
    first_create = next(i for i, e in enumerate(api.events) if e[0] == 'mkdir')
    assert api.events.index(('read', api.source + '\\recovery.iso')) < first_create
    assert [e for e in api.events if e[0] == 'write'][-1][1].endswith('installation.json')
    closed(api)
    events = list(api.events)
    with pytest.raises(m.ProvisionRefused, match='one_shot'):
        body.run()
    assert api.events == events


@pytest.mark.parametrize('field,value', [
    ('installation_id', None), ('installation_id', 'A' * 32), ('installation_id', '../x'),
    ('source_identity', m.native.FileIdentity(True, 2)), ('parent_identity', m.native.FileIdentity(42, 0)),
    ('bundle_sha256', 'A' * 64), ('bundle_bytes', True), ('bundle_bytes', 0),
    ('bundle_bytes', m.deployment.MAX_BUNDLE_BYTES + 1), ('pins', None),
])
def test_plan_refuses_without_native_io(env, field, value):
    env.plan = replace(env.plan, **{field: value})
    with pytest.raises(m.ProvisionRefused, match='plan'):
        provisioner(env)
    assert env.api.events == []


@pytest.mark.parametrize('value', [None, True, float('nan'), float('inf'), 100.0, 1001.0])
def test_bad_deadlines_precede_native_io(env, value):
    with pytest.raises(m.ProvisionRefused, match='deadline'):
        provisioner(env, deadline=value)
    assert env.api.events == []


@pytest.mark.parametrize('path', ['relative', r'\\server\share', r'C:\bad:stream', r'C:\..\bad'])
def test_paths_have_no_normalization_or_output_override(env, path):
    with pytest.raises(m.ProvisionRefused, match='path'):
        m.NativeValidationProvisioner(path, PARENT, env.plan, deadline=200.0)
    assert env.api.events == []


def test_admin_failure_is_one_shot_before_paths(env):
    env.api.admin = False
    body = provisioner(env)
    with pytest.raises(m.ProvisionUnknown, match='provision_unknown'):
        body.run()
    assert env.api.events == [('admin',)]
    with pytest.raises(m.ProvisionRefused, match='one_shot'):
        body.run()


@pytest.mark.parametrize('fault', ['source-id', 'parent-id', 'bundle', 'recovery', 'recovery-links', 'ancestor'])
def test_precreation_refusals_leave_no_outputs(env, fault):
    api = env.api
    if fault == 'source-id':
        env.plan = replace(env.plan, source_identity=m.native.FileIdentity(42, 999))
    elif fault == 'parent-id':
        env.plan = replace(env.plan, parent_identity=m.native.FileIdentity(42, 999))
    elif fault in ('bundle', 'recovery'):
        name = 'validator-inputs.zip' if fault == 'bundle' else 'recovery.iso'
        old = api.data[api.source + '\\' + name]
        api.data[api.source + '\\' + name] = b'X' * len(old)
    elif fault == 'recovery-links':
        key = api.source + '\\recovery.iso'
        api.values[key] = replace(api.values[key], links=2)
    else:
        old = api.values[api.parent]
        api.values[api.parent] = replace(old, acl=replace(old.acl, rules=old.acl.rules + (AclRule(USER, 0x40),)))
    with pytest.raises(m.ProvisionRefused):
        provisioner(env).run()
    no_outputs(api)
    closed(api)


@pytest.mark.parametrize('fault', ['collision', 'write_fault', 'flush_fault', 'replacement', 'writer_acl',
                                   'directory_drift', 'source_drift', 'path_drift', 'alias'])
def test_partial_failures_retain_objects_close_once_and_never_retry(env, fault):
    setattr(env.api, fault, True)
    body = provisioner(env)
    with pytest.raises(m.ProvisionRefused):
        body.run()
    closed(env.api)
    events = list(env.api.events)
    with pytest.raises(m.ProvisionRefused, match='one_shot'):
        body.run()
    assert env.api.events == events
    assert not any(e[0] in ('delete', 'repair', 'overwrite') for e in events)


def test_expiry_hashing_recovery_prevents_root_creation(env):
    env.api.expire_read = env.api.source + '\\recovery.iso'
    with pytest.raises(m.ProvisionRefused, match='deadline'):
        provisioner(env).run()
    no_outputs(env.api)
    closed(env.api)


def test_expiry_during_write_closes_without_renewing_budget(env):
    env.api.expire_write = True
    with pytest.raises(m.ProvisionRefused, match='deadline'):
        provisioner(env).run()
    assert env.clock[0] == 200.0
    closed(env.api)


def test_final_close_uncertainty_overrides_written_completion_record(env):
    env.api.close_fault = env.api.source + '\\validator-inputs.zip'
    body = provisioner(env)
    with pytest.raises(m.ProvisionUnknown, match='close_unknown'):
        body.run()
    assert any(name.endswith('installation.json') for name in env.api.data)
    closed(env.api)
    events = list(env.api.events)
    with pytest.raises(m.ProvisionRefused, match='one_shot'):
        body.run()
    assert env.api.events == events


def test_late_deadline_after_checked_closes_cannot_return_success(env):
    original_exit = Handle.__exit__
    def close(handle, *args):
        original_exit(handle, *args)
        if handle.path == ROOT and all(h.value == 0 for h in handle.api.handles):
            env.clock[0] = 200.0
    from unittest.mock import patch
    with patch.object(Handle, '__exit__', close), pytest.raises(m.ProvisionRefused, match='deadline'):
        provisioner(env).run()
    closed(env.api)


def test_leaf_abi_reads_with_no_write_or_delete_sharing():
    adapter = object.__new__(WindowsAdapter)
    captured, closes = [], []
    def create(output, access, attrs, status, allocation, flags, sharing, disposition, options, ea, ea_size):
        value = c.cast(attrs, c.POINTER(m.native._ObjectAttributes)).contents
        captured.append((access, value.root, value.attributes, sharing, disposition, options))
        c.cast(output, c.POINTER(m.native._PTR)).contents.value = 9
        c.cast(status, c.POINTER(m.native._IoStatus)).contents.information = 1
        return 0
    adapter.n = SimpleNamespace(NtCreateFile=create)
    adapter.k = SimpleNamespace(CloseHandle=lambda value: closes.append(value) or 1)
    handle = adapter.leaf(SimpleNamespace(value=42), 'recovery.iso', create=False)
    assert captured == [(0x80120080, 42, 0x1040, 1, 1, 0x200060)]
    m._close(handle)
    m._close(handle)
    assert closes == [9]


def test_leaf_creation_reuses_exact_create_new_private_primitive():
    adapter = object.__new__(WindowsAdapter)
    calls = []
    adapter.relative = lambda *args, **kw: calls.append((args, kw)) or 'model'
    parent = SimpleNamespace(value=42)
    assert adapter.leaf(parent, 'deployment.zip', create=True) == 'model'
    assert calls == [((parent, 'deployment.zip'), dict(directory=False, create=True,
                     sddl=m.native._sddl(directory=False), writable=True))]
    with pytest.raises(m.ProvisionRefused, match='leaf'):
        adapter.leaf(parent, 'arbitrary.bin', create=True)


@pytest.mark.parametrize('fault', ['short', 'failed'])
def test_write_abi_never_retries_partial_or_failed_calls(monkeypatch, fault):
    monkeypatch.setattr(m, '_now', lambda: 100.0)
    adapter = object.__new__(WindowsAdapter)
    calls = []
    def write(handle, data, size, count, overlapped):
        calls.append(size)
        c.cast(count, c.POINTER(m.native._U32)).contents.value = size - 1
        return 0 if fault == 'failed' else 1
    adapter.k = SimpleNamespace(WriteFile=write)
    with pytest.raises(m.ProvisionUnknown, match='write_unknown'):
        adapter.write(SimpleNamespace(value=42), b'data', m._Budget(200.0))
    assert calls == [4]


def test_read_abi_bounds_streaming_and_requires_exact_eof(monkeypatch):
    monkeypatch.setattr(m, '_now', lambda: 100.0)
    adapter = object.__new__(WindowsAdapter)
    data, offset, requests = RECOVERY, [0], []
    def read(handle, buffer, wanted, count, overlapped):
        requests.append(wanted)
        chunk = data[offset[0]:offset[0] + wanted]
        offset[0] += len(chunk)
        c.memmove(buffer, chunk, len(chunk))
        c.cast(count, c.POINTER(m.native._U32)).contents.value = len(chunk)
        return 1
    adapter.k = SimpleNamespace(SetFilePointerEx=lambda *_: 1, ReadFile=read)
    assert b''.join(adapter.chunks(SimpleNamespace(value=42), len(data), m._Budget(200.0))) == data
    assert requests == [m.CHUNK_BYTES, len(data) - m.CHUNK_BYTES, 1]


@pytest.mark.parametrize('fault', ['seek', 'read', 'zero', 'overcount', 'trailing'])
def test_read_faults_are_terminal_without_retry(monkeypatch, fault):
    monkeypatch.setattr(m, '_now', lambda: 100.0)
    adapter = object.__new__(WindowsAdapter)
    calls = []
    def read(handle, buffer, wanted, count, overlapped):
        calls.append(wanted)
        amount = 0 if fault == 'zero' else wanted + 1 if fault == 'overcount' else 1
        c.cast(count, c.POINTER(m.native._U32)).contents.value = amount
        return 0 if fault == 'read' else 1
    adapter.k = SimpleNamespace(SetFilePointerEx=lambda *_: 0 if fault == 'seek' else 1, ReadFile=read)
    with pytest.raises(m.ProvisionRefused):
        list(adapter.chunks(SimpleNamespace(value=42), 0 if fault == 'trailing' else 1, m._Budget(200.0)))
    assert len(calls) == (0 if fault == 'seek' else 1)


def test_candidates_are_data_catalogued_but_provisioner_remains_unwired():
    root = Path(m.__file__).parent
    assert 'bootstrap_native_provision.py' in m.deployment.CODE_FILES
    assert 'payload/night_shifts/bootstrap_native_provision.py' in m.deployment.BUNDLE_NAMES
    assert not hasattr(m, 'main')
    tree = ast.parse(Path(m.__file__).read_text(encoding='utf-8'))
    assert not any(isinstance(n, ast.Attribute) and n.attr in ('write_marker', 'probe_new_store',
        'unlink', 'rmdir', 'remove', 'chmod', 'Popen', 'execve', 'extractall') for n in ast.walk(tree))
    # Exactly one new internal run edge, not a blanket exemption for .run calls.
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr == 'run']
    assert len(calls) == 1 and ast.unparse(calls[0]) == 'body.run'
    worker = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'ProvisionWorkerHandoff')
    method = next(n for n in worker.body if isinstance(n, ast.FunctionDef) and n.name == 'run')
    assert calls[0] in list(ast.walk(method))
    creations = [n for n in ast.walk(method) if isinstance(n, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == 'body' for t in n.targets)]
    assert len(creations) == 1
    assert ast.unparse(creations[0].value) == (
        'NativeValidationProvisioner(source, parent, plan, deadline=self._deadline)')
    runs = [n for n in ast.walk(method) if isinstance(n, ast.Call) and n.func is calls[0]]
    assert len(runs) == 1 and not runs[0].args and not runs[0].keywords
    for path in root.rglob('*.py'):
        if path == Path(m.__file__):
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if isinstance(node, ast.ImportFrom):
                assert 'bootstrap_native_provision' not in (node.module or '')
                assert all(a.name != 'bootstrap_native_provision' for a in node.names)
            if isinstance(node, ast.Import):
                assert all('bootstrap_native_provision' not in a.name for a in node.names)
