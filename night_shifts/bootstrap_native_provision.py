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
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from time import monotonic as _now

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
