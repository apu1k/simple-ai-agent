"""Offline store/ABI models only: NO native opens, media writes, elevation or VM.

Seed asset pins are explicitly substituted by the inherited synthetic fixture.
The real ISO codec runs in memory; Windows adapters below are entirely replaced.
"""
from __future__ import annotations

import ast
import ctypes as c
import hashlib
import inspect
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from night_shifts import bootstrap_native_media_store as s
from night_shifts import maintenance_store_native_prototype as n
from night_shifts.bootstrap_native_media import build_native_validation_iso
from night_shifts.maintenance_credentials_prototype import ADMINS_SID, FULL_CONTROL, SYSTEM_SID
from night_shifts.ubuntu_preparation_control import AclRule, AclSnapshot
from tests.night_shifts import test_bootstrap_recovery_handoff as assets

support = assets.support
ROOT = '\\\\?\\Volume{00000000-0000-4000-8000-000000000001}\\'
ANCHOR = r'C:\Protected\Media'
RECOVERY = b'R' * (20 * 2048)
USER = 'S-1-5-21-1-2-3-1001'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def observation(index, *, directory=True, size=0):
    return n.Observation(n.FileIdentity(42, index), 0x10 if directory else 0x80, 1, size,
        AclSnapshot(ADMINS_SID, (AclRule(SYSTEM_SID, FULL_CONTROL, 3 if directory else 0),
                                AclRule(ADMINS_SID, FULL_CONTROL, 3 if directory else 0))), True)


@pytest.fixture
def plan(support):
    pytest.importorskip('pycdlib', reason='pinned optional codec, memory only; no fallback')
    image = build_native_validation_iso(support[0], support[1], expected_seed_sha256=sha(support[1]))
    return s.ValidationMediaPlan(support[0], n.FileIdentity(42, 3), sha(RECOVERY), len(RECOVERY),
                                 sha(support[1]), image.sha256)


class Handle:
    def __init__(self, api, path):
        self.api, self.path, self.value = api, path, len(api.handles) + 1
        self.close_calls = 0
        api.handles.append(self)

    def __exit__(self, *_):
        if self.value:
            self.value = 0
            self.close_calls += 1
            self.api.events.append(('close', self.path))
            if self.api.close_fault == self.path:
                raise OSError('SYNTHETIC_CANARY')


class FakeApi:
    def __init__(self, binding):
        self.events, self.handles = [], []
        self.child = ROOT + 'Protected\\Media\\validation-media-' + binding.attempt_id
        self.anchor = ROOT + 'Protected\\Media'
        self.values = {ROOT: observation(1), ROOT + 'Protected': observation(2), self.anchor: observation(3),
                       self.anchor + '\\recovery.iso': observation(4, directory=False, size=len(RECOVERY))}
        self.data = {self.anchor + '\\recovery.iso': RECOVERY}
        self.close_fault = None
        self.write_fault = False
        self.flush_fault = False
        self.read_fault = False
        self.collision = False
        self.writer_drift = False
        self.reopen_replacement = False
        self.late_recovery_drift = False
        self.admin = True

    def require_admin(self):
        self.events.append(('admin',))
        if not self.admin:
            raise n.NativeStoreRefused('enabled_administrator_required')

    def root(self, drive):
        assert drive == 'C:\\'
        self.events.append(('root', drive))
        return Handle(self, ROOT)

    def relative(self, parent, name, **options):
        path = parent.path.rstrip('\\') + '\\' + name
        self.events.append(('relative', name, options))
        assert options['directory'] is True
        if options['create']:
            assert path == self.child and options['sddl'] == n._sddl(directory=True)
            if self.collision:
                raise n.NativeStoreRefused('relative_create', 183)
            assert path not in self.values
            self.values[path] = observation(5)
        else:
            assert path in self.values and 'sddl' not in options
        return Handle(self, path)

    def observe(self, handle):
        assert handle.value
        return self.values[handle.path]

    def final_name(self, handle):
        assert handle.value
        return handle.path

    def leaf(self, parent, name, *, create):
        assert name in ('recovery.iso', 'cidata.iso', 'review.json')
        path = parent.path + '\\' + name
        self.events.append(('leaf', name, create))
        if create:
            assert name != 'recovery.iso' and path not in self.values
            self.values[path] = observation(6 if name == 'cidata.iso' else 7, directory=False)
            self.data[path] = b''
        else:
            assert path in self.values
            if self.reopen_replacement and name == 'cidata.iso':
                self.values[path] = replace(self.values[path], identity=n.FileIdentity(42, 99))
        return Handle(self, path)

    def write(self, handle, data, budget):
        budget.check()
        self.events.append(('write', handle.path))
        if self.write_fault:
            raise s.MediaStoreUnknown('write_unknown')
        self.data[handle.path] = data
        before = self.values[handle.path]
        self.values[handle.path] = replace(before, size=len(data), attributes=before.attributes | 0x20)
        if self.writer_drift:
            self.values[handle.path] = replace(self.values[handle.path], protected=False)
        if self.late_recovery_drift:
            self.data[self.anchor + '\\recovery.iso'] = b'X' * len(RECOVERY)
        if self.flush_fault:
            raise s.MediaStoreUnknown('flush_unknown')
        budget.check()

    def verify_bytes(self, handle, size, digest, expected, budget):
        budget.check()
        self.events.append(('verify', handle.path))
        if self.read_fault:
            raise s.MediaStoreUnknown('read_unknown')
        data = self.data[handle.path]
        if len(data) != size or sha(data) != digest or (expected is not None and data != expected):
            raise s.MediaStoreRefused('file_digest')
        budget.check()


@pytest.fixture
def env(plan, support, monkeypatch):
    api = FakeApi(plan.binding)
    clock = [100.0]
    monkeypatch.setattr(s, '_now', lambda: clock[0])
    original_close = s._Windows._close

    class Factory:
        _close = staticmethod(original_close)

        def __new__(cls):
            return api

    monkeypatch.setattr(s, '_Windows', Factory)
    return SimpleNamespace(api=api, plan=plan, seed=support[1], clock=clock,
        review=s.render_validation_media_set_review(plan, support[1]))


def acquire(env, **overrides):
    kwargs = dict(expected_review_sha256=sha(env.review), deadline=200.0)
    kwargs.update(overrides)
    return s.materialize_validation_media(ANCHOR, env.plan, env.seed, **kwargs)


def assert_closed(api):
    assert api.handles and all(h.value == 0 and h.close_calls == 1 for h in api.handles)


def test_review_is_bounded_local_complete_set_without_native_io(env):
    value = json.loads(env.review)
    assert env.api.events == [] and len(env.review) <= s.MAX_REVIEW_BYTES
    assert value['scope'] == 'local_media_set_consistency_only'
    assert value['files']['recovery.iso']['sha256'] == sha(RECOVERY)
    assert value['files']['cidata.iso']['sha256'] == env.plan.cidata_sha256
    assert value['anchor_identity'] == {'volume': 42, 'index': 3}
    assert value['cidata_review']['scope'] == 'local_media_consistency_only'
    assert not {'accepted', 'approved', 'gate_a', 'vm_absent', 'native_pass'} & value.keys()
    assert s.render_validation_media_set_review(env.plan, env.seed) == env.review


def test_full_model_creates_only_fixed_outputs_and_holds_three_readers(env):
    with acquire(env) as held:
        paths = held.checked_paths()
        assert paths == s.HeldMediaPaths(env.api.anchor + '\\recovery.iso', env.api.child + '\\cidata.iso',
                                        env.api.child + '\\review.json')
        assert len([e for e in env.api.events if e[0] == 'write']) == 2
        assert [e for e in env.api.events if e[0] == 'leaf' and e[2]] == [
            ('leaf', 'cidata.iso', True), ('leaf', 'review.json', True)]
        assert sum(bool(h.value) for h in env.api.handles) == 7  # root + 3 directories + 3 leaves
        assert env.api.data[paths.review] == env.review
        # Recovery verification precedes the create-new attempt claim.
        check = env.api.events.index(('verify', paths.recovery_iso))
        claim = next(i for i, e in enumerate(env.api.events) if e[0] == 'relative' and e[2]['create'])
        assert check < claim
    assert_closed(env.api)
    held.close()
    assert_closed(env.api)
    with pytest.raises(s.MediaStoreRefused, match='held_set_terminal'):
        held.checked_paths()


@pytest.mark.parametrize('field,value', [
    ('anchor_identity', n.FileIdentity(42, 0)), ('anchor_identity', n.FileIdentity(True, 3)),
    ('recovery_sha256', 'A' * 64), ('seed_sha256', None), ('cidata_sha256', '0' * 63),
    ('recovery_bytes', True), ('recovery_bytes', 1), ('recovery_bytes', 40961),
    ('recovery_bytes', s.MAX_RECOVERY_BYTES + 2048), ('binding', None),
])
def test_plan_contract_refuses_before_native_io(env, field, value):
    env.plan = replace(env.plan, **{field: value})
    with pytest.raises(s.MediaStoreRefused, match='^plan$'):
        acquire(env)
    assert env.api.events == []


@pytest.mark.parametrize('value', [None, True, float('nan'), float('inf'), 100.0, 1001.0])
def test_deadline_refuses_before_render_or_native(env, monkeypatch, value):
    monkeypatch.setattr(s, '_render', lambda *a: pytest.fail('render before deadline'))
    with pytest.raises(s.MediaStoreRefused, match='^deadline$'):
        acquire(env, deadline=value)
    assert env.api.events == []


@pytest.mark.parametrize('which', ['cidata', 'review', 'seed'])
def test_independent_pins_refuse_before_any_native_io(env, which):
    if which == 'cidata':
        env.plan = replace(env.plan, cidata_sha256='0' * 64)
    elif which == 'seed':
        env.plan = replace(env.plan, seed_sha256='0' * 64)
    with pytest.raises(s.MediaStoreRefused):
        acquire(env, expected_review_sha256='0' * 64 if which == 'review' else sha(env.review))
    assert env.api.events == []


def test_expiry_during_render_still_prevents_native_io(env, monkeypatch):
    original = s._render

    def slow(*args):
        value = original(*args)
        env.clock[0] = 200.0
        return value
    monkeypatch.setattr(s, '_render', slow)
    with pytest.raises(s.MediaStoreRefused, match='^deadline$'):
        acquire(env)
    assert env.api.events == []


def test_admin_gate_does_not_open_any_path(env):
    env.api.admin = False
    with pytest.raises(s.MediaStoreUnknown, match='^materialization_unknown$'):
        acquire(env)
    assert env.api.events == [('admin',)] and env.api.handles == []


@pytest.mark.parametrize('fault', ['anchor-id', 'recovery-size', 'recovery-bytes', 'recovery-acl',
                                   'recovery-hardlink', 'recovery-reparse', 'ancestor-acl', 'anchor-private'])
def test_preclaim_faults_never_create_any_output(env, fault):
    api = env.api
    recovery = api.anchor + '\\recovery.iso'
    if fault == 'anchor-id':
        api.values[api.anchor] = replace(api.values[api.anchor], identity=n.FileIdentity(42, 99))
    elif fault == 'recovery-size':
        api.values[recovery] = replace(api.values[recovery], size=1)
    elif fault == 'recovery-bytes':
        api.data[recovery] = b'X' * len(RECOVERY)
    elif fault == 'recovery-acl':
        old = api.values[recovery]
        api.values[recovery] = replace(old, acl=replace(old.acl, rules=old.acl.rules + (AclRule(USER, 0x120089),)))
    elif fault == 'recovery-hardlink':
        api.values[recovery] = replace(api.values[recovery], links=2)
    elif fault == 'recovery-reparse':
        api.values[recovery] = replace(api.values[recovery], attributes=0x480)
    elif fault == 'ancestor-acl':
        old = api.values[ROOT]
        api.values[ROOT] = replace(old, acl=replace(old.acl, rules=old.acl.rules + (AclRule(USER, 0x40),)))
    else:
        api.values[api.anchor] = replace(api.values[api.anchor], protected=False)
    with pytest.raises(s.MediaStoreRefused):
        acquire(env)
    assert not any(e[0] == 'write' or (e[0] == 'relative' and e[2]['create']) for e in api.events)
    assert_closed(api)


@pytest.mark.parametrize('fault', ['collision', 'write_fault', 'flush_fault', 'read_fault',
                                   'writer_drift', 'reopen_replacement', 'late_recovery_drift'])
def test_faults_are_terminal_with_no_retry_or_artifact_deletion(env, fault):
    setattr(env.api, fault, True)
    with pytest.raises(s.MediaStoreRefused) as error:
        acquire(env)
    assert 'SYNTHETIC_CANARY' not in str(error.value)
    assert len([e for e in env.api.events if e[0] == 'write']) <= (2 if fault == 'late_recovery_drift' else 1)
    assert sum(e[0] == 'relative' and e[2]['create'] for e in env.api.events) <= 1
    assert_closed(env.api)
    if fault not in ('collision', 'read_fault'):
        assert env.api.child in env.api.values  # Retained; never deleted/repaired.


@pytest.mark.parametrize('leaf', ['cidata.iso', 'review.json', 'recovery.iso'])
def test_postacquisition_byte_drift_closes_everything_and_permanently_disables_paths(env, leaf):
    held = acquire(env)
    path = (env.api.anchor if leaf == 'recovery.iso' else env.api.child) + '\\' + leaf
    env.api.data[path] = b'X' * len(env.api.data[path])
    with pytest.raises(s.MediaStoreRefused, match='file_digest'):
        held.checked_paths()
    assert_closed(env.api)
    with pytest.raises(s.MediaStoreRefused, match='held_set_terminal'):
        held.verify()


def test_postacquisition_deadline_is_not_refreshed(env):
    held = acquire(env)
    env.clock[0] = 200.0
    with pytest.raises(s.MediaStoreRefused, match='deadline'):
        held.checked_paths()
    assert_closed(env.api)


def test_directory_storage_length_change_is_not_file_content_drift(env):
    held = acquire(env)
    old = env.api.values[env.api.child]
    env.api.values[env.api.child] = replace(old, size=4096)
    held.verify()
    held.close()
    assert_closed(env.api)


def test_acl_change_after_acquisition_is_terminal(env):
    held = acquire(env)
    old = env.api.values[env.api.child]
    env.api.values[env.api.child] = replace(old, protected=False)
    with pytest.raises(s.MediaStoreUnknown):
        held.verify()
    assert_closed(env.api)


def test_writer_close_uncertainty_never_reopens_leaf_or_retries_close(env):
    env.api.close_fault = env.api.child + '\\cidata.iso'
    with pytest.raises(s.MediaStoreUnknown, match='handle_close_unknown'):
        acquire(env)
    assert ('leaf', 'cidata.iso', False) not in env.api.events
    assert_closed(env.api)


def test_final_close_uncertainty_attempts_all_other_closes_once(env):
    held = acquire(env)
    env.api.close_fault = env.api.anchor + '\\recovery.iso'
    with pytest.raises(s.MediaStoreUnknown, match='handle_close_unknown'):
        held.close()
    assert_closed(env.api)
    held.close()
    assert_closed(env.api)
    with pytest.raises(s.MediaStoreRefused, match='held_set_terminal'):
        held.checked_paths()


# ABI models call ONLY Python stand-ins, not Windows APIs. They complement,
# rather than confer native validation on, the high-level substituted flow.
@pytest.mark.parametrize('create', [False, True])
def test_leaf_nt_open_abi_has_no_overwrite_reparse_or_write_sharing(create):
    api = object.__new__(s._Windows)
    calls = []

    def descriptor(text, revision, output, ignored):
        assert text == n._sddl(directory=False) and revision == 1
        output._obj.value = 123
        return 1

    def nt(output, access, attrs, status, allocation, attributes, share, disposition, options, ea, length):
        a = attrs._obj
        calls.append((access, share, disposition, options, a.attributes, a.root))
        assert c.wstring_at(a.name.contents.buffer) == 'cidata.iso'
        assert not allocation and not attributes and not ea and not length
        output._obj.value = 99
        status._obj.information = 2 if create else 1
        return 0

    api.a = SimpleNamespace(ConvertStringSecurityDescriptorToSecurityDescriptorW=descriptor)
    api.n = SimpleNamespace(NtCreateFile=nt)
    freed = []
    api.k = SimpleNamespace(LocalFree=lambda value: freed.append(value.value), CloseHandle=lambda h: 1)
    parent = SimpleNamespace(value=17)
    leaf = api.leaf(parent, 'cidata.iso', create=create)
    assert calls == [(0x120080 | (0xC0000000 if create else 0x80000000), 0 if create else 1,
                      2 if create else 1, 0x200060, 0x1040, 17)]
    assert freed == ([123] if create else [])
    leaf.__exit__()


@pytest.mark.parametrize('name,create', [('extra.iso', False), ('../cidata.iso', True), ('recovery.iso', True)])
def test_native_leaf_name_is_fixed_before_any_syscall(name, create):
    api = object.__new__(s._Windows)
    with pytest.raises(s.MediaStoreRefused, match='leaf_name'):
        api.leaf(None, name, create=create)


class KernelIO:
    def __init__(self, data=b''):
        self.data, self.offset, self.events = data, 0, []
        self.short_write = False
        self.fail_read = False
        self.fail_seek = False
        self.fail_flush = False
        self.fragment = s.CHUNK_BYTES

    def WriteFile(self, handle, buffer, length, count, ignored):
        self.events.append('write')
        count._obj.value = length - 1 if self.short_write else length
        self.data = c.string_at(buffer, count._obj.value)
        return 1

    def FlushFileBuffers(self, handle):
        self.events.append('flush')
        return not self.fail_flush

    def SetFilePointerEx(self, handle, offset, ignored, method):
        self.events.append('seek')
        self.offset = offset
        return not self.fail_seek

    def ReadFile(self, handle, buffer, requested, count, ignored):
        self.events.append('read')
        if self.fail_read:
            return 0
        raw = self.data[self.offset:self.offset + min(requested, self.fragment)]
        c.memmove(buffer, raw, len(raw))
        count._obj.value = len(raw)
        self.offset += len(raw)
        return 1


def test_stream_hash_and_exact_small_bytes_use_bounded_chunks_and_final_eof(monkeypatch):
    monkeypatch.setattr(s, '_now', lambda: 100.0)
    data = b'abcde' * 20000
    k = KernelIO(data)
    k.fragment = 7777  # Successful short reads are chunks, not retries of a failed call.
    api = object.__new__(s._Windows)
    api.k = k
    api.verify_bytes(SimpleNamespace(value=1), len(data), sha(data), data, s._Budget(200.0))
    assert k.offset == len(data) and k.events[0] == 'seek' and k.events[-1] == 'read'
    assert len(k.events) == 15


@pytest.mark.parametrize('fault', ['seek', 'read', 'truncated', 'suffix', 'digest', 'expected'])
def test_stream_refuses_failed_or_nonexact_input_without_retry(monkeypatch, fault):
    monkeypatch.setattr(s, '_now', lambda: 100.0)
    k = KernelIO(b'payload')
    k.fail_seek, k.fail_read = fault == 'seek', fault == 'read'
    if fault == 'truncated':
        k.data = b'pay'
    if fault == 'suffix':
        k.data += b'X'
    api = object.__new__(s._Windows)
    api.k = k
    with pytest.raises(s.MediaStoreRefused):
        api.verify_bytes(SimpleNamespace(value=1), 7, '0' * 64 if fault == 'digest' else sha(b'payload'),
                         b'changed' if fault == 'expected' else None, s._Budget(200.0))
    assert len(k.events) <= 4


@pytest.mark.parametrize('fault', ['', 'short', 'flush'])
def test_native_write_is_one_call_and_flush_failure_is_terminal(monkeypatch, fault):
    monkeypatch.setattr(s, '_now', lambda: 100.0)
    k = KernelIO()
    k.short_write, k.fail_flush = fault == 'short', fault == 'flush'
    api = object.__new__(s._Windows)
    api.k = k
    if fault:
        with pytest.raises(s.MediaStoreUnknown):
            api.write(SimpleNamespace(value=1), b'payload', s._Budget(200.0))
    else:
        api.write(SimpleNamespace(value=1), b'payload', s._Budget(200.0))
        assert k.data == b'payload'
    assert k.events == (['write'] if fault == 'short' else ['write', 'flush'])


def test_store_stays_outside_public_and_guest_source_catalogs():
    from night_shifts.bootstrap_probe_seed import SOURCE_FILES
    from night_shifts.guest.bootstrap_native_boot import NATIVE_SOURCES
    assert 'bootstrap_native_media_store.py' not in (*SOURCE_FILES, *NATIVE_SOURCES)
    tree = ast.parse(inspect.getsource(s))
    calls = [ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)]
    assert not any(name.endswith(('unlink', 'rmdir', 'chmod', 'write_marker', 'probe_new_store')) for name in calls)
    assert not any(name.startswith(('subprocess.', 'os.system')) for name in calls)
