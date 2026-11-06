"""Unwired create-new Windows validator provisioning BODY, not a bootstrap.

NEVER run checkout code elevated. A separately reviewed protected bootstrap must
establish runtime/code/import provenance and permanent install-attempt authority
BEFORE importing this closed dependency set. This body cannot supply that trust,
install its own trusted entry point, authorize execution or supervise any VM.
No CLI, tool, process launch, credentials, policy activation, repair or deletion.
"""
from __future__ import annotations

import ctypes as c
import hashlib
import json
import math
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from threading import Lock
from time import monotonic as _now
from time import time as _utc
from typing import cast

from night_shifts import bootstrap_native_deployment as deployment
from night_shifts import maintenance_store_native_prototype as native

CHUNK_BYTES = 65536
MAX_RECORD_BYTES = 32768
_GUID_ROOT = r'\\\\\?\\Volume\{[0-9a-fA-F-]{36}\}\\'
_LEAVES = frozenset(n.rsplit('/', 1)[-1] for n in deployment.BUNDLE_NAMES) | {
    'validator-inputs.zip', 'deployment.zip', 'recovery.iso', 'installation.json'}
_DIRECTORY_NAMES = tuple(sorted({n.rsplit('/', 1)[0] for n in deployment.BUNDLE_NAMES if '/' in n}
    | {'payload', 'payload/night_shifts', 'payload/night_shifts/guest',
       'payload/pycdlib-1.21.0.dist-info', 'runtime', 'inputs', 'media'},
    key=lambda n: (n.count('/'), n)))


class ProvisionRefused(RuntimeError):
    """Fixed labels only; no path, source, input, native or exception text."""


class ProvisionUnknown(ProvisionRefused):
    """Uncertain operation/close; retained artifacts are NOT acceptance or retry."""


@dataclass(frozen=True)
class ValidationProvisionPlan:
    """Forgeable independently reviewed inputs, not installation/execution grants."""

    installation_id: str
    source_identity: native.FileIdentity
    parent_identity: native.FileIdentity
    bundle_sha256: str
    bundle_bytes: int
    pins: deployment.ValidationDeploymentPins


@dataclass(frozen=True)
class LocalProvisionedInputs:
    """Local observations after checked closes; NOT a receipt or activation grant."""

    installation_id: str
    root_path: str
    root_identity: native.FileIdentity
    media_path: str
    media_identity: native.FileIdentity
    record_sha256: str


class _Budget:
    def __init__(self, deadline: float) -> None:
        now = _now()
        if type(deadline) not in (int, float) or not now < deadline <= now + 900:
            raise ProvisionRefused('deadline')
        self.deadline = deadline

    def check(self) -> None:
        if _now() >= self.deadline:
            raise ProvisionRefused('deadline')


def _plan(value: ValidationProvisionPlan) -> None:
    if (type(value) is not ValidationProvisionPlan or type(value.installation_id) is not str
            or re.fullmatch('[0-9a-f]{32}', value.installation_id) is None
            or not deployment._digest(value.bundle_sha256) or type(value.bundle_bytes) is not int
            or not 0 < value.bundle_bytes <= deployment.MAX_BUNDLE_BYTES):
        raise ProvisionRefused('plan')
    for identity in (value.source_identity, value.parent_identity):
        if (type(identity) is not native.FileIdentity or type(identity.volume) is not int
                or not 0 <= identity.volume < 2**32 or type(identity.index) is not int
                or not 0 < identity.index < 2**64):
            raise ProvisionRefused('plan')
    try:
        deployment._pins(value.pins)
    except deployment.DeploymentBundleRefused:
        raise ProvisionRefused('plan') from None


def _path(path: str) -> tuple[str, tuple[str, ...]]:
    try:
        return native._path_parts(path)
    except native.NativeStoreRefused:
        raise ProvisionRefused('path') from None


class _Windows(native._Windows):
    """Relative native primitives only; never the dependency's marker APIs."""

    def leaf(self, parent: native._Handle, name: str, *, create: bool) -> native._Handle:
        if name not in _LEAVES:
            raise ProvisionRefused('leaf')
        if create:
            return self.relative(parent, name, directory=False, create=True,
                                 sddl=native._sddl(directory=False), writable=True)
        native._component(name)
        buffer = c.create_unicode_buffer(name)
        text = native._Unicode(len(name) * 2, (len(name) + 1) * 2, c.cast(buffer, c.c_wchar_p))
        attrs = native._ObjectAttributes(c.sizeof(native._ObjectAttributes), parent.value,
            c.pointer(text), 0x1040, None, None)
        output, status = native._PTR(), native._IoStatus()
        result = self.n.NtCreateFile(c.byref(output), 0x80120080, c.byref(attrs), c.byref(status),
            None, 0, 1, 1, 0x200060, None, 0)  # READ only, SHARE_READ, OPEN, DONT_REPARSE
        if result != 0:
            if output.value:
                _close(native._Handle(self, int(output.value)))
            raise ProvisionRefused('leaf_open')
        handle = native._Handle(self, int(output.value or 0))
        if not handle.value or status.information != 1:
            _close(handle)
            raise ProvisionUnknown('leaf_disposition_unknown')
        return handle

    def final_name(self, handle: native._Handle) -> str:
        output = c.create_unicode_buffer(512)
        length = self.k.GetFinalPathNameByHandleW(handle.value, output, len(output), 1)
        if not 0 < length < len(output) or re.match(_GUID_ROOT, output.value) is None:
            raise ProvisionRefused('volume_guid_path')
        return str(output.value)

    def chunks(self, handle: native._Handle, size: int, budget: _Budget) -> Iterator[bytes]:
        budget.check()
        if not self.k.SetFilePointerEx(handle.value, 0, None, 0):
            raise ProvisionUnknown('seek_unknown')
        buffer, count, total = c.create_string_buffer(CHUNK_BYTES), native._U32(), 0
        while total < size:
            budget.check()
            wanted = min(CHUNK_BYTES, size - total)
            if not self.k.ReadFile(handle.value, buffer, wanted, c.byref(count), None):
                raise ProvisionUnknown('read_unknown')
            if not 0 < count.value <= wanted:
                raise ProvisionRefused('read_extent')
            total += count.value
            yield buffer.raw[:count.value]
        budget.check()
        if not self.k.ReadFile(handle.value, buffer, 1, c.byref(count), None):
            raise ProvisionUnknown('read_unknown')
        if count.value:
            raise ProvisionRefused('read_extent')
        budget.check()

    def write(self, handle: native._Handle, data: bytes, budget: _Budget) -> None:
        budget.check()
        buffer, count = c.create_string_buffer(data), native._U32()
        if (not self.k.WriteFile(handle.value, buffer, len(data), c.byref(count), None)
                or count.value != len(data)):
            raise ProvisionUnknown('write_unknown')  # Never retry a short/failed write.
        budget.check()

    def flush(self, handle: native._Handle, budget: _Budget) -> None:
        budget.check()
        if not self.k.FlushFileBuffers(handle.value):
            raise ProvisionUnknown('flush_unknown')
        budget.check()


def _close(handle: native._Handle) -> None:
    try:
        handle.__exit__()  # Disarms BEFORE the one close attempt.
    except BaseException:
        raise ProvisionUnknown('close_unknown') from None


class _Resources:
    def __init__(self) -> None:
        self.handles: list[native._Handle] = []

    def own(self, handle: native._Handle) -> native._Handle:
        self.handles.append(handle)
        return handle

    def close(self) -> None:
        handles, self.handles = self.handles, []
        failed = False
        for handle in reversed(handles):
            try:
                _close(handle)
            except BaseException:
                failed = True
        if failed:
            raise ProvisionUnknown('close_unknown') from None


@dataclass(frozen=True)
class _Directory:
    handle: native._Handle = field(repr=False)
    before: native.Observation
    path: str
    private: bool
    trusted_ancestor: bool


@dataclass(frozen=True)
class _File:
    handle: native._Handle = field(repr=False)
    before: native.Observation
    path: str
    size: int
    digest: str
    private: bool
    expected: bytes | None = field(repr=False)


def _same(before: native.Observation, after: native.Observation, written: int | None = None) -> None:
    result = native.compare_metadata(before, after, expected_file_size=written,
                                     allow_archive_change=written is not None)
    if not result.matches:
        raise ProvisionRefused('metadata_drift')


def _directories(api: _Windows, entries: list[_Directory], budget: _Budget) -> None:
    for entry in entries:
        budget.check()
        observed = api.observe(entry.handle)
        if entry.private:
            native._check_private(observed, directory=True)
        elif entry.trusted_ancestor:
            native._check_ancestor(observed)
        else:
            native._check_shape(observed, directory=True)
        _same(entry.before, observed)
        if api.final_name(entry.handle).casefold() != entry.path.casefold():
            raise ProvisionRefused('directory_path_drift')


def _metadata(api: _Windows, entry: _File) -> None:
    observed = api.observe(entry.handle)
    if entry.private:
        native._check_private(observed, directory=False)
    else:
        native._check_shape(observed, directory=False)
    _same(entry.before, observed)
    if observed.size != entry.size or api.final_name(entry.handle).casefold() != entry.path.casefold():
        raise ProvisionRefused('file_metadata')


def _verified(api: _Windows, entry: _File, budget: _Budget) -> None:
    _metadata(api, entry)
    digest, total = hashlib.sha256(), 0
    for chunk in api.chunks(entry.handle, entry.size, budget):
        if entry.expected is not None and chunk != entry.expected[total:total + len(chunk)]:
            raise ProvisionRefused('file_bytes')
        digest.update(chunk)
        total += len(chunk)
    if total != entry.size or digest.hexdigest() != entry.digest:
        raise ProvisionRefused('file_digest')
    _metadata(api, entry)
    budget.check()


def _existing(api: _Windows, resources: _Resources, path: str, identity: native.FileIdentity,
              trusted: bool, budget: _Budget) -> list[_Directory]:
    drive, parts = _path(path)
    budget.check()
    handle = resources.own(api.root(drive))
    root = api.final_name(handle)
    if re.fullmatch(_GUID_ROOT, root) is None:
        raise ProvisionRefused('volume_guid_root')
    observed = api.observe(handle)
    entries = [_Directory(handle, observed, root, False, trusted)]
    volume = observed.identity.volume
    for index, name in enumerate(parts):
        _directories(api, entries, budget)
        handle = resources.own(api.relative(handle, name, directory=True, create=False,
                                           writable=trusted and index == len(parts) - 1))
        observed = api.observe(handle)
        if observed.identity.volume != volume:
            raise ProvisionRefused('volume_changed')
        entries.append(_Directory(handle, observed, entries[-1].path.rstrip('\\') + '\\' + name, False, trusted))
    if entries[-1].before.identity != identity:
        raise ProvisionRefused('input_directory_identity')
    _directories(api, entries, budget)
    return entries


def _read(api: _Windows, resources: _Resources, parent: _Directory, name: str, size: int,
          digest: str, private: bool, budget: _Budget, expected: bytes | None = None,
          written: native.Observation | None = None) -> _File:
    budget.check()
    handle = resources.own(api.leaf(parent.handle, name, create=False))
    observed = api.observe(handle)
    if observed.identity.volume != parent.before.identity.volume or observed.size != size:
        raise ProvisionRefused('file_shape')
    if written is not None:
        _same(written, observed)
    entry = _File(handle, observed, parent.path.rstrip('\\') + '\\' + name, size, digest, private, expected)
    _metadata(api, entry)
    return entry


# Worker projection consumer lives in the existing carried member: no new import
# catalog entry or host-reviewer dependency. These references are forgeable DATA.
# Trusted import acquisition, permanent claims, exact operator/host role, process
# containment and authenticated deadline delivery MUST precede this body.
_MAX_WORKER_BYTES = 8192
_WORKER_FIELDS = ('version', 'scope', 'operation', 'installation_id', 'operator_sid',
    'budget_seconds', 'expires_unix', 'request_sha256', 'launch_anchor', 'import_anchor', 'provision')


def _worker_fields(value: object, names: tuple[str, ...]) -> dict[str, object]:
    if type(value) is not dict or set(value) != set(names):
        raise ProvisionRefused('worker_schema')
    return cast(dict[str, object], value)


def _worker_number(value: object, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ProvisionRefused('worker_number')
    return value


def _worker_digest(value: object) -> str:
    if not deployment._digest(value):
        raise ProvisionRefused('worker_digest')
    return cast(str, value)


def _worker_identity(value: object) -> native.FileIdentity:
    fields = _worker_fields(value, ('volume', 'index'))
    return native.FileIdentity(_worker_number(fields['volume'], 0, 2**32 - 1),
                               _worker_number(fields['index'], 1, 2**64 - 1))


def _worker_path(value: object, maximum: int = 240) -> str:
    if (type(value) is not str or not 4 <= len(value) <= maximum
            or re.match(r'^[A-Z]:\\', value) is None):
        raise ProvisionRefused('worker_path')
    _path(value)  # Pure component validation, no native access or normalization.
    return value


def _worker_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for name, value in pairs:
        if name in result:
            raise ProvisionRefused('worker_duplicate')
        result[name] = value
    return result


def _worker_bind(raw: bytes, size: int, digest: str, request: str, seconds: int,
                 until: int) -> tuple[str, str, ValidationProvisionPlan]:
    # Size/type and independent whole-byte pin BEFORE any JSON parser. Immutable
    # bytes only: no mutable caller buffer, file reopen or unbounded stdin read.
    if type(raw) is not bytes or len(raw) != size:
        raise ProvisionRefused('worker_pin')
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ProvisionRefused('worker_pin')
    try:
        value = json.loads(raw.decode('ascii'), object_pairs_hook=_worker_pairs)
    except (ValueError, UnicodeError, RecursionError):
        raise ProvisionRefused('worker_json') from None
    root = _worker_fields(value, _WORKER_FIELDS)
    if (type(root['version']) is not int or root['version'] != 1
            or root['scope'] != 'bound_worker_request_not_authorization'
            or root['operation'] != 'native_validator_provision_once'):
        raise ProvisionRefused('worker_schema')
    installation_id = root['installation_id']
    if type(installation_id) is not str or re.fullmatch('[0-9a-f]{32}', installation_id) is None:
        raise ProvisionRefused('worker_id')
    sid = root['operator_sid']
    if (type(sid) is not str or len(sid) > 80
            or re.fullmatch('S-1-5-21-[0-9]+-[0-9]+-[0-9]+-[0-9]+', sid) is None):
        raise ProvisionRefused('worker_sid')
    for part in sid.split('-')[4:]:
        if str(int(part)) != part or int(part) > 2**32 - 1:
            raise ProvisionRefused('worker_sid')
    if (_worker_digest(root['request_sha256']) != request
            or _worker_number(root['budget_seconds'], 6, 900) != seconds
            or _worker_number(root['expires_unix'], 1, 253402300799) != until):
        raise ProvisionRefused('worker_binding')
    launch = _worker_fields(root['launch_anchor'], ('path', 'identity', 'scratch_identity'))
    imp = _worker_fields(root['import_anchor'], ('path', 'identity'))
    provision = _worker_fields(root['provision'], ('source', 'output_parent', 'bundle', 'pins'))
    source = _worker_fields(provision['source'], ('path', 'identity'))
    parent = _worker_fields(provision['output_parent'], ('path', 'identity'))
    paths = (_worker_path(launch['path'], 200), _worker_path(imp['path']),
             _worker_path(source['path']), _worker_path(parent['path']))
    if len(paths[3] + '\\native-validator-' + installation_id) > 240:
        raise ProvisionRefused('worker_output_path')
    identities = tuple(_worker_identity(item['identity']) for item in (launch, imp, source, parent))
    scratch = _worker_identity(launch['scratch_identity'])
    if scratch.volume != identities[0].volume or len(set((*identities, scratch))) != 5:
        raise ProvisionRefused('worker_identity_alias')
    folded = tuple(path.lower() for path in paths)
    if any(a == b or a.startswith(b + '\\') or b.startswith(a + '\\')
           for i, a in enumerate(folded) for b in folded[i + 1:]):
        raise ProvisionRefused('worker_path_overlap')
    bundle = _worker_fields(provision['bundle'], ('bytes', 'sha256'))
    pins = _worker_fields(provision['pins'], ('code_tree_sha256', 'codec_tree_sha256',
        'runtime_sha256', 'runtime_bytes', 'recovery_sha256', 'recovery_bytes'))
    plan = ValidationProvisionPlan(installation_id, identities[2], identities[3],
        _worker_digest(bundle['sha256']), _worker_number(bundle['bytes'], 1, deployment.MAX_BUNDLE_BYTES),
        deployment.ValidationDeploymentPins(_worker_digest(pins['code_tree_sha256']),
            _worker_digest(pins['codec_tree_sha256']), _worker_digest(pins['runtime_sha256']),
            _worker_number(pins['runtime_bytes'], 1, deployment.MAX_RUNTIME_BYTES),
            _worker_digest(pins['recovery_sha256']),
            _worker_number(pins['recovery_bytes'], 20 * 2048, 8 * 1024**3)))
    _plan(plan)
    # Reject whitespace, duplicate/unknown fields, noncanonical numbers/escapes,
    # alternate order, non-ASCII, trailing input and missing/extra final newline.
    if deployment._json(root) != raw:
        raise ProvisionRefused('worker_canonical')
    return paths[2], paths[3], plan


class ProvisionWorkerHandoff:
    """Unwired one-shot Python-side projection consumer, NOT a launcher or grant.

    Construct BEFORE receiving bytes. The trusted caller must already hold the
    complete import closure and pass an independently bound projection pin plus
    an earlier deadline in THIS Python clock domain, excluding guardian cleanup.
    No cross-process deadline translation, transport or authentication is supplied.
    """

    def __init__(self, *, expected_bytes: int, expected_sha256: str, request_sha256: str,
                 budget_seconds: int, expires_unix: int, deadline: float) -> None:
        self._size = _worker_number(expected_bytes, 1, _MAX_WORKER_BYTES)
        self._digest = _worker_digest(expected_sha256)
        self._request = _worker_digest(request_sha256)
        self._seconds = _worker_number(budget_seconds, 6, 900)
        self._until = _worker_number(expires_unix, 1, 253402300799)
        if type(deadline) not in (int, float):
            raise ProvisionRefused('worker_window')
        try:
            finite = math.isfinite(deadline)
        except OverflowError:
            finite = False
        if not finite:
            raise ProvisionRefused('worker_window')
        self._last = float('-inf')
        now, wall = self._sample()
        remaining = self._until - wall
        if not 0 < remaining <= 86400 or deadline <= now:
            raise ProvisionRefused('worker_window')
        # Only shorten the supplied earlier local deadline. NEVER start a fresh
        # budget in run(), after decoding, or at the provisioner handoff.
        self._deadline = min(deadline, now + self._seconds, now + remaining)
        self._used = False
        self._lock = Lock()

    def _sample(self) -> tuple[float, float]:
        now, wall = _now(), _utc()
        if (not math.isfinite(now) or not math.isfinite(wall)
                or now < self._last or wall < 0):
            raise ProvisionRefused('worker_clock')
        self._last = now
        return now, wall

    def _check(self) -> None:
        now, wall = self._sample()
        if now >= self._deadline or wall >= self._until:
            raise ProvisionRefused('worker_window')

    def run(self, raw: bytes) -> LocalProvisionedInputs:
        with self._lock:
            if self._used:
                raise ProvisionRefused('one_shot')
            self._used = True  # disarm before clock, hash, parser or provisioner
            entered = False
            try:
                self._check()
                source, parent, plan = _worker_bind(raw, self._size, self._digest, self._request,
                                                   self._seconds, self._until)
                self._check()
                body = NativeValidationProvisioner(source, parent, plan, deadline=self._deadline)
                self._check()
                entered = True
                result = body.run()
                self._check()
                if type(result) is not LocalProvisionedInputs or result.installation_id != plan.installation_id:
                    raise ProvisionUnknown('worker_result_unknown')
                return result  # unchanged local consistency data, NOT acceptance
            except ProvisionUnknown:
                raise
            except ProvisionRefused:
                if entered:
                    raise ProvisionUnknown('worker_provision_outcome_unknown') from None
                raise
            except Exception:
                raise ProvisionUnknown('worker_unknown') from None


class NativeValidationProvisioner:
    """One-use body; bootstrap trust/permanent install claim are EXTERNAL.

    Fixed inputs: source_directory/{validator-inputs.zip,recovery.iso}. Only new
    parent_directory/native-validator-<installation_id> may be created. Native
    operations occur ONLY in run(). No output is activation/execution approval.
    """

    def __init__(self, source_directory: str, parent_directory: str, plan: ValidationProvisionPlan,
                 *, deadline: float) -> None:
        self._budget = _Budget(deadline)
        _plan(plan)
        _path(source_directory)
        _path(parent_directory)
        self._source_path, self._parent_path, self._plan = source_directory, parent_directory, plan
        self._used = False

    def run(self) -> LocalProvisionedInputs:
        if self._used:
            raise ProvisionRefused('one_shot')
        self._used = True  # Disarm before ANY native access, including early refusal.
        resources = _Resources()
        budget, plan = self._budget, self._plan
        try:
            budget.check()
            api = _Windows()
            api.require_admin()
            source = _existing(api, resources, self._source_path, plan.source_identity, False, budget)
            parent = _existing(api, resources, self._parent_path, plan.parent_identity, True, budget)
            directories = source + parent
            bundle = _read(api, resources, source[-1], 'validator-inputs.zip', plan.bundle_bytes,
                           plan.bundle_sha256, False, budget)
            raw = b''.join(api.chunks(bundle.handle, bundle.size, budget))
            deployment._checked_blob(raw, plan.bundle_bytes, plan.bundle_sha256, 'bundle_pin')
            _metadata(api, bundle)
            deployment.inspect_validation_deployment_bundle(raw, expected_bundle_sha256=plan.bundle_sha256,
                                                             pins=plan.pins)
            files = deployment._unzip(raw, deployment.BUNDLE_NAMES, deployment.MAX_EXPANDED_BYTES)
            recovery = _read(api, resources, source[-1], 'recovery.iso', plan.pins.recovery_bytes,
                             plan.pins.recovery_sha256, False, budget)
            _verified(api, recovery, budget)  # Complete recovery hash BEFORE output creation.
            _directories(api, directories, budget)
            seen = {entry.before.identity for entry in directories} | {bundle.before.identity, recovery.before.identity}

            def directory(parent_entry: _Directory, name: str) -> _Directory:
                _directories(api, directories, budget)
                handle = resources.own(api.relative(parent_entry.handle, name, directory=True, create=True,
                    sddl=native._sddl(directory=True), writable=True))
                observed = api.observe(handle)
                native._check_private(observed, directory=True)
                if observed.identity.volume != parent_entry.before.identity.volume or observed.identity in seen:
                    raise ProvisionRefused('new_directory_identity')
                seen.add(observed.identity)
                entry = _Directory(handle, observed, parent_entry.path.rstrip('\\') + '\\' + name, True, True)
                directories.append(entry)
                _directories(api, directories, budget)
                return entry

            root = directory(parent[-1], 'native-validator-' + plan.installation_id)
            tree = {'': root}
            for name in _DIRECTORY_NAMES:
                prefix, _, leaf = name.rpartition('/')
                tree[name] = directory(tree[prefix], leaf)
            outputs: dict[str, _File] = {}

            def write(name: str, data: bytes | None, source_file: _File | None = None) -> _File:
                prefix, _, leaf = name.rpartition('/')
                destination = tree[prefix]
                _directories(api, directories, budget)
                writer = resources.own(api.leaf(destination.handle, leaf, create=True))
                before = api.observe(writer)
                native._check_private(before, directory=False)
                if before.size or before.identity.volume != root.before.identity.volume or before.identity in seen:
                    raise ProvisionRefused('new_file_identity')
                seen.add(before.identity)
                _directories(api, directories, budget)
                if source_file is None:
                    if data is None:
                        raise ProvisionRefused('fixed_output')
                    size, digest = len(data), hashlib.sha256(data).hexdigest()
                    api.write(writer, data, budget)
                else:
                    _metadata(api, source_file)
                    size, digest = source_file.size, source_file.digest
                    copied, count = hashlib.sha256(), 0
                    for chunk in api.chunks(source_file.handle, size, budget):
                        api.write(writer, chunk, budget)
                        copied.update(chunk)
                        count += len(chunk)
                    if count != size or copied.hexdigest() != digest:
                        raise ProvisionRefused('copy_digest')
                    _metadata(api, source_file)
                api.flush(writer, budget)
                after = api.observe(writer)
                native._check_private(after, directory=False)
                _same(before, after, written=size)
                _close(writer)
                result = _read(api, resources, destination, leaf, size, digest, True, budget,
                               expected=data, written=after)
                _verified(api, result, budget)
                outputs[name] = result
                return result

            write('deployment.zip', raw)
            for name in deployment.BUNDLE_NAMES:
                write(name, files[name])  # Exact fixed catalog, NEVER extractall or manifest-selected paths.
            write('media/recovery.iso', None, recovery)

            def verify_all() -> None:
                _directories(api, directories, budget)
                for entry in (bundle, recovery, *outputs.values()):
                    _verified(api, entry, budget)
                _directories(api, directories, budget)
                for entry in (bundle, recovery, *outputs.values()):
                    _metadata(api, entry)
                budget.check()

            verify_all()
            record = deployment._json({'version': 1, 'scope': 'local_provisioning_consistency_only',
                'installation_id': plan.installation_id, 'bootstrap': 'not_supplied',
                'bundle_sha256': plan.bundle_sha256, 'recipe': deployment._recipe(plan.pins),
                'root_identity': {'volume': root.before.identity.volume, 'index': root.before.identity.index},
                'media_identity': {'volume': tree['media'].before.identity.volume,
                                   'index': tree['media'].before.identity.index},
                'files': {name: {'bytes': entry.size, 'sha256': entry.digest,
                    'volume': entry.before.identity.volume, 'index': entry.before.identity.index}
                    for name, entry in sorted(outputs.items())}})
            if len(record) > MAX_RECORD_BYTES:
                raise ProvisionRefused('record_bound')
            write('installation.json', record)  # Last file, but NOT a protected acceptance receipt.
            verify_all()
            result = LocalProvisionedInputs(plan.installation_id, root.path, root.before.identity,
                tree['media'].path, tree['media'].before.identity, hashlib.sha256(record).hexdigest())
            resources.close()  # Close uncertainty overrides a fully written record.
            budget.check()
            return result
        except BaseException as error:
            resources.close()  # Attempt all remaining closes; never retry disarmed OS handles.
            if isinstance(error, ProvisionRefused):
                raise
            raise ProvisionUnknown('provision_unknown') from None
