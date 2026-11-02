"""Offline deployment-input tests; no installer/interpreter/media/VM execution.

Most inputs are EXPLICIT synthetic public-asset/tree-pin substitutions and an
inert, non-runnable PE/stdlib model. The real snapshot test only reads reviewed
checkout/installed codec bytes. New filesystem observations are models, not ACL,
Windows file-lock, publisher, protected deployment or native-boot evidence.
"""
from __future__ import annotations

import ast
import builtins
import io
import json
import stat
import zipfile
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from night_shifts import bootstrap_native_deployment as m


def runtime_files():
    pe = b'MZ' + b'\0' * 58 + (64).to_bytes(4, 'little') + b'PE\0\0\x64\x86' + b'\0' * 10
    files = {name: pe if name.endswith(('.exe', '.dll', '.pyd')) else b'inert model'
             for name in m.RUNTIME_NAMES}
    files['python314._pth'] = m._PTH
    files['python314.zip'] = b'PK\x03\x04INERT-NOT-A-RUNTIME'
    return files


def archive(files, *, compression=zipfile.ZIP_STORED, transform=None):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=compression) as handle:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100444 << 16
            info.compress_type = compression
            if transform:
                transform(info)
            handle.writestr(info, data)
    return output.getvalue()


@pytest.fixture
def candidate(monkeypatch):
    code = {name: b'' if name in m.EMPTY_FILES else b'pass\n' for name in m.CODE_NAMES}
    codec = dict.fromkeys(m.CODEC_NAMES, b'pass\n')
    codec[m.CODEC_METADATA + 'METADATA'] = b'Metadata-Version: 2.4\nName: pycdlib\nVersion: 1.21.0\n\nModel\n'
    codec[m.CODEC_METADATA + 'WHEEL'] = b'Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n'
    codec[m.CODEC_METADATA + 'licenses/COPYING'] = b'INERT TEST LICENSE'
    public = {m.PACKAGE_NAME: b'NOT-A-PACKAGE', 'COPYING': b'copying-model', 'GPL-2.0': b'gpl-model'}
    # This explicit substitution is NOT verification of the real package/licenses.
    monkeypatch.setattr(m, 'PUBLIC_PINS', {n: (len(d), m._sha(d)) for n, d in public.items()})
    monkeypatch.setattr(m, '_snapshots', lambda: (dict(code), dict(codec)))
    runtime = archive(runtime_files(), compression=zipfile.ZIP_DEFLATED)
    pins = m.ValidationDeploymentPins(m._tree(code), m._tree(codec), m._sha(runtime), len(runtime), 'a' * 64, 40960)
    value = SimpleNamespace(code=code, codec=codec, public=public, runtime=runtime, pins=pins)
    value.build = lambda: m.build_validation_deployment_bundle(value.runtime, public[m.PACKAGE_NAME],
        copying=public['COPYING'], gpl=public['GPL-2.0'], pins=value.pins)
    value.inspect = lambda raw: m.inspect_validation_deployment_bundle(raw,
        expected_bundle_sha256=m._sha(raw), pins=value.pins)
    return value


def unpack(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as handle:
        return {info.filename: handle.read(info) for info in handle.infolist()}


def rewritten(raw, pins, mutate):
    files = unpack(raw)
    files.pop('manifest.json')
    mutate(files)
    files['manifest.json'] = m._manifest(files, pins)
    return archive(files)


def test_canonical_bundle_inventory_and_nonactivating_recipe(candidate):
    first = candidate.build()
    assert first == candidate.build()
    files = unpack(first)
    assert tuple(sorted(files)) == m.BUNDLE_NAMES
    assert files['inputs/runtime.zip'] == candidate.runtime
    assert files['runtime/python.exe'] == runtime_files()['python.exe']
    assert all(not files['payload/' + n] for n in m.EMPTY_FILES)
    manifest = json.loads(files['manifest.json'])
    assert manifest['files'] == m._inventory({n: d for n, d in files.items() if n != 'manifest.json'})
    review = json.loads(candidate.inspect(first))
    assert review['scope'] == 'local_deployment_consistency_only'
    assert review['recipe']['recovery_reference']['verified_here'] is False
    assert review['recipe']['binding'] == 'derive-only-after-observed-fresh-off-vm-guid'
    assert review['file_count'] == len(m.BUNDLE_NAMES) - 1
    assert len(candidate.inspect(first)) <= m.MAX_REVIEW_BYTES
    assert not {'accepted', 'installed', 'authorized', 'vm_id', 'attempt_id', 'gate_a', 'cleanup'} & review.keys()


def test_inspector_never_rereads_or_imports_local_snapshots(candidate, monkeypatch):
    raw = candidate.build()
    monkeypatch.setattr(m, '_snapshots', lambda: pytest.fail('inspector touched checkout'))
    assert candidate.inspect(raw)


def test_review_inventory_is_bounded_and_tree_pinned(candidate):
    raw = m.review_validation_deployment_sources()
    value = json.loads(raw)
    assert value['code_tree_sha256'] == candidate.pins.code_tree_sha256
    assert value['codec_tree_sha256'] == candidate.pins.codec_tree_sha256
    assert value['files'] == m._inventory({**candidate.code, **candidate.codec})
    assert len(raw) <= m.MAX_REVIEW_BYTES


@pytest.mark.parametrize('change', [
    {'code_tree_sha256': None}, {'code_tree_sha256': 'A' * 64}, {'codec_tree_sha256': 'f' * 63},
    {'runtime_sha256': b'a' * 64}, {'recovery_sha256': '../x'},
    {'runtime_bytes': True}, {'runtime_bytes': 0}, {'runtime_bytes': m.MAX_RUNTIME_BYTES + 1},
    {'runtime_bytes': 1.0}, {'recovery_bytes': False}, {'recovery_bytes': 40959},
    {'recovery_bytes': 40961}, {'recovery_bytes': 8 * 1024**3 + 2048},
])
def test_bad_pins_refuse_before_any_input_parser(candidate, monkeypatch, change):
    candidate.pins = replace(candidate.pins, **change)
    monkeypatch.setattr(m, '_unzip', lambda *_: pytest.fail('parsed with bad pins'))
    with pytest.raises(m.DeploymentBundleRefused, match='^pins$'):
        candidate.build()
    with pytest.raises(m.DeploymentBundleRefused, match='^pins$'):
        candidate.inspect(b'x')


def test_pin_object_is_exact_type(candidate):
    with pytest.raises(m.DeploymentBundleRefused, match='^pins$'):
        m._pins(None)


@pytest.mark.parametrize('bad', [b'', b'not zip', bytearray(b'x'), None])
def test_bundle_pin_precedes_archive_parser(candidate, monkeypatch, bad):
    monkeypatch.setattr(m, '_unzip', lambda *_: pytest.fail('untrusted archive parsed'))
    with pytest.raises(m.DeploymentBundleRefused, match='bundle_pin'):
        m.inspect_validation_deployment_bundle(bad, expected_bundle_sha256='f' * 64, pins=candidate.pins)


def test_runtime_and_public_pins_precede_parsing(candidate, monkeypatch):
    monkeypatch.setattr(m, '_unzip', lambda *_: pytest.fail('untrusted runtime parsed'))
    candidate.runtime += b'changed'
    with pytest.raises(m.DeploymentBundleRefused, match='runtime_pin'):
        candidate.build()
    candidate.public['COPYING'] += b'changed'
    with pytest.raises(m.DeploymentBundleRefused, match='public_input_pin'):
        candidate.build()


@pytest.mark.parametrize('tree', ['code', 'codec'])
def test_builder_refuses_source_drift(candidate, tree):
    getattr(candidate, tree)[next(iter(getattr(candidate, tree)))] += b'changed'
    with pytest.raises(m.DeploymentBundleRefused, match='source_pin'):
        candidate.build()


@pytest.mark.parametrize('name', ['payload/night_shifts/bootstrap_native_owner.py', 'payload/pycdlib/pycdlib.py'])
def test_rehashing_manifest_and_bundle_does_not_bypass_tree_pins(candidate, name):
    raw = rewritten(candidate.build(), candidate.pins, lambda f: f.__setitem__(name, b'changed'))
    with pytest.raises(m.DeploymentBundleRefused, match='source_pin'):
        candidate.inspect(raw)


def test_rehashing_runtime_file_still_requires_original_archive_correspondence(candidate):
    raw = rewritten(candidate.build(), candidate.pins,
                    lambda f: f.__setitem__('runtime/python.exe', b'changed'))
    with pytest.raises(m.DeploymentBundleRefused, match='runtime_correspondence'):
        candidate.inspect(raw)


def test_rehashing_original_runtime_archive_does_not_bypass_its_pin(candidate):
    raw = rewritten(candidate.build(), candidate.pins,
                    lambda f: f.__setitem__('inputs/runtime.zip', candidate.runtime + b'changed'))
    with pytest.raises(m.DeploymentBundleRefused, match='runtime_pin'):
        candidate.inspect(raw)


def test_public_input_pins_rechecked_on_inspection(candidate):
    raw = rewritten(candidate.build(), candidate.pins, lambda f: f.__setitem__('inputs/COPYING', b'changed'))
    with pytest.raises(m.DeploymentBundleRefused, match='public_input_pin'):
        candidate.inspect(raw)


def test_nonempty_initializer_refuses_even_with_updated_tree_pin(candidate):
    raw = candidate.build()
    candidate.code[m.EMPTY_FILES[0]] = b'print("not evaluated")\n'
    candidate.pins = replace(candidate.pins, code_tree_sha256=m._tree(candidate.code))
    changed = rewritten(raw, candidate.pins,
        lambda f: f.__setitem__('payload/' + m.EMPTY_FILES[0], candidate.code[m.EMPTY_FILES[0]]))
    with pytest.raises(m.DeploymentBundleRefused, match='package_initializer'):
        candidate.inspect(changed)


@pytest.mark.parametrize('suffix,prefix', [(b'trailer', b''), (b'', b'prefix')])
def test_prefix_or_trailer_is_not_normalized_even_if_rehashed(candidate, suffix, prefix):
    with pytest.raises(m.DeploymentBundleRefused, match='bundle_canonical'):
        candidate.inspect(prefix + candidate.build() + suffix)


@pytest.mark.parametrize('mutation', ['extra', 'missing', 'case', 'traversal'])
def test_exact_output_inventory(candidate, mutation):
    files = unpack(candidate.build())
    if mutation == 'missing':
        files.pop('runtime/python.exe')
    elif mutation == 'case':
        files['runtime/PYTHON.exe'] = files.pop('runtime/python.exe')
    else:
        files['../outside.py' if mutation == 'traversal' else 'payload/sitecustomize.py'] = b'pass'
    with pytest.raises(m.DeploymentBundleRefused, match='archive_inventory'):
        candidate.inspect(archive(files))


@pytest.mark.parametrize('mutation', ['manifest', 'compression', 'timestamp', 'mode'])
def test_noncanonical_output_not_salvaged(candidate, mutation):
    files = unpack(candidate.build())
    if mutation == 'manifest':
        files['manifest.json'] = json.dumps(json.loads(files['manifest.json']), indent=2).encode()
    def transform(info):
        if mutation == 'timestamp':
            info.date_time = (2000, 1, 1, 0, 0, 0)
        if mutation == 'mode':
            info.external_attr = 0o100644 << 16
    raw = archive(files, compression=zipfile.ZIP_DEFLATED if mutation == 'compression' else zipfile.ZIP_STORED,
                  transform=transform)
    with pytest.raises(m.DeploymentBundleRefused, match='bundle_canonical'):
        candidate.inspect(raw)


@pytest.mark.parametrize('pth', [b'import site\n', b'../payload\n', b'python314.zip\n.\n', m._PTH + b'other\n'])
def test_runtime_path_profile_has_no_fallback(candidate, pth):
    files = runtime_files()
    files['python314._pth'] = pth
    raw = archive(files)
    pins = replace(candidate.pins, runtime_sha256=m._sha(raw), runtime_bytes=len(raw))
    with pytest.raises(m.DeploymentBundleRefused, match='runtime_path'):
        m._runtime(raw, pins)


@pytest.mark.parametrize('pe', [b'not PE', b'MZ' + b'\0' * 100,
    b'MZ' + b'\0' * 58 + (64).to_bytes(4, 'little') + b'PE\0\0\x4c\x01',
    b'MZ' + b'\0' * 58 + (2**32 - 1).to_bytes(4, 'little')])
def test_runtime_architecture_checks_do_not_execute(candidate, pe):
    files = runtime_files()
    files['python.exe'] = pe
    raw = archive(files)
    pins = replace(candidate.pins, runtime_sha256=m._sha(raw), runtime_bytes=len(raw))
    with pytest.raises(m.DeploymentBundleRefused, match='runtime_architecture'):
        m._runtime(raw, pins)


@pytest.mark.parametrize('change', [
    {'flag_bits': 1}, {'flag_bits': 8}, {'compress_type': zipfile.ZIP_BZIP2},
    {'external_attr': 0o120777 << 16}, {'external_attr': 0x10}, {'create_system': 99},
    {'extra': b'xx'}, {'comment': b'x'}, {'file_size': m.MAX_ENTRY_BYTES + 1},
])
def test_unsafe_archive_shapes_refuse_before_entry_reads(monkeypatch, change):
    info = zipfile.ZipInfo('x')
    info.file_size = 1
    for key, value in change.items():
        setattr(info, key, value)
    class ModelArchive:
        comment = b''
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass
        def infolist(self):
            return [info]
        def open(self, *_):
            pytest.fail('read before shape refusal')
    monkeypatch.setattr(m.zipfile, 'ZipFile', lambda *_: ModelArchive())
    with pytest.raises(m.DeploymentBundleRefused, match='archive_shape'):
        m._unzip(b'x', ('x',), m.MAX_EXPANDED_BYTES)


def test_expanded_total_checked_before_reading(monkeypatch):
    raw = archive({'a': b'123', 'b': b'456'})
    monkeypatch.setattr(zipfile.ZipFile, 'open', lambda *_: pytest.fail('read before bound'))
    with pytest.raises(m.DeploymentBundleRefused, match='archive_shape'):
        m._unzip(raw, ('a', 'b'), 5)


def test_duplicate_runtime_entry_is_not_collapsed(candidate):
    output = io.BytesIO(candidate.runtime)
    with zipfile.ZipFile(output, 'a') as handle, pytest.warns(UserWarning, match='Duplicate name'):
        handle.writestr('python.exe', b'duplicate')
    raw = output.getvalue()
    pins = replace(candidate.pins, runtime_sha256=m._sha(raw), runtime_bytes=len(raw))
    with pytest.raises(m.DeploymentBundleRefused, match='archive_inventory'):
        m._runtime(raw, pins)


def test_resource_bounds_precede_serialization(candidate, monkeypatch):
    monkeypatch.setattr(m, 'MAX_BUNDLE_BYTES', 100)
    with pytest.raises(m.DeploymentBundleRefused, match='bundle_bound'):
        candidate.build()
    monkeypatch.setattr(m, 'MAX_REVIEW_BYTES', 1)
    with pytest.raises(m.DeploymentBundleRefused, match='review_bound'):
        m.review_validation_deployment_sources()


@pytest.mark.parametrize('replacement', [
    b'Name: other\nVersion: 1.21.0\n', b'Name: pycdlib\nVersion: 1.22.0\n',
    b'Name: pycdlib\nVersion: 1.21.0\nVersion: 1.21.0\n',
    b'Name: pycdlib\nVersion: 1.21.0\nRequires-Dist: injected\n',
])
def test_codec_metadata_consistency_checks(candidate, replacement):
    candidate.codec[m.CODEC_METADATA + 'METADATA'] = replacement
    with pytest.raises(m.DeploymentBundleRefused, match='codec_metadata'):
        m._codec(candidate.codec)


def model_info(**changes):
    value = dict(st_dev=1, st_ino=2, st_mode=stat.S_IFREG | 0o444, st_nlink=1,
                 st_size=4, st_mtime_ns=1, st_ctime_ns=1, st_file_attributes=0, st_birthtime_ns=1)
    return SimpleNamespace(**{**value, **changes})


class ModelStream(io.BytesIO):
    def fileno(self):
        return 42


class ModelPath:
    parents = ()
    def __init__(self, before, after=None):
        self.before, self.after, self.calls = before, after or before, 0
    def lstat(self):
        self.calls += 1
        return self.before if self.calls == 1 else self.after
    def open(self, mode):
        assert mode == 'rb'
        return ModelStream(b'data')


def test_snapshot_regular_read_is_bounded_model_only(monkeypatch):
    info = model_info()
    monkeypatch.setattr(m.os, 'fstat', lambda _: info)
    assert m._read_snapshot(ModelPath(info), 4) == b'data'


@pytest.mark.parametrize('change,label', [
    ({'st_mode': stat.S_IFLNK}, 'snapshot_link'), ({'st_file_attributes': 0x400}, 'snapshot_link'),
    ({'st_mode': stat.S_IFDIR}, 'snapshot_shape'), ({'st_nlink': 2}, 'snapshot_shape'),
    ({'st_size': 5}, 'snapshot_shape'),
])
def test_snapshot_shape_refusal_models(change, label):
    with pytest.raises(m.DeploymentBundleRefused, match=label):
        m._read_snapshot(ModelPath(model_info(**change)), 4)


@pytest.mark.parametrize('field', ['st_dev', 'st_ino', 'st_mode', 'st_nlink', 'st_size',
                                    'st_mtime_ns', 'st_ctime_ns', 'st_file_attributes', 'st_birthtime_ns'])
def test_snapshot_after_read_drift_refuses_model_only(monkeypatch, field):
    info = model_info()
    monkeypatch.setattr(m.os, 'fstat', lambda _: info)
    after = model_info(**{field: getattr(info, field) + 1})
    with pytest.raises(m.DeploymentBundleRefused, match='snapshot_changed'):
        m._read_snapshot(ModelPath(info, after), 4)


@pytest.mark.parametrize('windows', [False, True])
def test_path_descriptor_ctime_difference_has_only_windows_bridge(monkeypatch, windows):
    path_info, descriptor_info = model_info(), model_info(st_ctime_ns=7)
    monkeypatch.setattr(m, '_WINDOWS', windows)
    monkeypatch.setattr(m.os, 'fstat', lambda _: descriptor_info)
    if windows:
        assert m._read_snapshot(ModelPath(path_info), 4) == b'data'
    else:
        with pytest.raises(m.DeploymentBundleRefused, match='snapshot_changed'):
            m._read_snapshot(ModelPath(path_info), 4)


@pytest.mark.parametrize('field', ['st_dev', 'st_ino', 'st_mode', 'st_nlink', 'st_size',
                                    'st_mtime_ns', 'st_file_attributes', 'st_birthtime_ns'])
def test_windows_bridge_still_requires_all_other_fields(monkeypatch, field):
    path_info = model_info()
    descriptor_info = model_info(st_ctime_ns=7, **{field: getattr(path_info, field) + 1})
    monkeypatch.setattr(m, '_WINDOWS', True)
    monkeypatch.setattr(m.os, 'fstat', lambda _: descriptor_info)
    with pytest.raises(m.DeploymentBundleRefused, match='snapshot_changed'):
        m._read_snapshot(ModelPath(path_info), 4)


@pytest.mark.parametrize('field', ['st_dev', 'st_ino', 'st_mode', 'st_nlink', 'st_size',
                                    'st_mtime_ns', 'st_ctime_ns', 'st_file_attributes', 'st_birthtime_ns'])
def test_descriptor_drift_refuses_even_with_windows_ctime_bridge(monkeypatch, field):
    path_info, opened = model_info(), model_info(st_ctime_ns=7)
    changed = SimpleNamespace(**{**vars(opened), field: getattr(opened, field) + 1})
    observations = iter((opened, changed))
    monkeypatch.setattr(m, '_WINDOWS', True)
    monkeypatch.setattr(m.os, 'fstat', lambda _: next(observations))
    with pytest.raises(m.DeploymentBundleRefused, match='snapshot_changed'):
        m._read_snapshot(ModelPath(path_info), 4)


def test_path_ctime_drift_refuses_even_with_windows_bridge(monkeypatch):
    before, after, descriptor_info = model_info(), model_info(st_ctime_ns=2), model_info(st_ctime_ns=7)
    monkeypatch.setattr(m, '_WINDOWS', True)
    monkeypatch.setattr(m.os, 'fstat', lambda _: descriptor_info)
    with pytest.raises(m.DeploymentBundleRefused, match='snapshot_changed'):
        m._read_snapshot(ModelPath(before, after), 4)


@pytest.mark.parametrize('location', ['C:/not-a-path-object', Path('relative'), object()])
def test_codec_locator_must_be_an_absolute_filesystem_path(monkeypatch, location):
    reads = []
    def read(path, maximum):
        reads.append(path)
        return b'pass\n'
    provider = SimpleNamespace(version='1.21.0', locate_file=lambda _: location)
    monkeypatch.setattr(m, '_read_snapshot', read)
    monkeypatch.setattr(m.metadata, 'distribution', lambda _: provider)
    with pytest.raises(m.DeploymentBundleRefused, match='codec_location'):
        m._snapshots()
    assert len(reads) == len(m.CODE_FILES)


def test_fixed_asset_pins_match_existing_review_without_importing_in_candidate():
    from night_shifts import bootstrap_daemon_asset as asset, bootstrap_probe_seed as seed
    assert m.PUBLIC_PINS == {
        asset.PACKAGE_NAME: (asset.PACKAGE_BYTES, asset.PACKAGE_SHA256),
        'COPYING': (496, seed.COPYING_SHA256), 'GPL-2.0': (18729, seed.GPL_SHA256)}


def test_fixed_code_catalog_contains_public_native_and_host_dependency_closure():
    from night_shifts import bootstrap_probe_seed as seed
    from night_shifts.guest import bootstrap_native_boot as boot
    root = Path(m.__file__).parent
    assert set(seed.SOURCE_FILES) | set(boot.NATIVE_SOURCES) <= set(m.CODE_FILES)
    for name in m.CODE_FILES:
        if not name.endswith('.py'):
            continue
        for node in ast.walk(ast.parse((root / name).read_text(encoding='utf-8'))):
            if isinstance(node, ast.ImportFrom) and (node.module or '').startswith('night_shifts'):
                suffix = (node.module or '').removeprefix('night_shifts').lstrip('.').replace('.', '/')
                if (root / (suffix + '.py')).is_file():
                    assert suffix + '.py' in m.CODE_FILES
                else:
                    for alias in node.names:
                        leaf = '/'.join(filter(None, (suffix, alias.name))) + '.py'
                        assert leaf in m.CODE_FILES


def test_candidate_stdlib_only_unwired_and_excluded_from_existing_payloads():
    from night_shifts import inspection_bundle
    from night_shifts.bootstrap_probe_seed import SOURCE_FILES
    root = Path(m.__file__).parent
    tree = ast.parse(Path(m.__file__).read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or '']
            assert all(not n.startswith(('night_shifts', 'pycdlib', 'runtime', 'tools')) for n in names)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in ('exec', 'eval', '__import__', 'compile')
    assert 'bootstrap_native_deployment.py' not in SOURCE_FILES
    assert 'bootstrap_native_deployment.py' not in inspection_bundle.FILES
    for path in root.rglob('*.py'):
        if path == Path(m.__file__):
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if isinstance(node, ast.ImportFrom):
                assert 'bootstrap_native_deployment' not in (node.module or '')
                assert all(a.name != 'bootstrap_native_deployment' for a in node.names)
            if isinstance(node, ast.Import):
                assert all('bootstrap_native_deployment' not in a.name for a in node.names)


def test_real_source_and_codec_snapshot_reads_only_no_codec_import(monkeypatch):
    try:
        dist = m.metadata.distribution('pycdlib')
    except m.metadata.PackageNotFoundError:
        pytest.skip('optional pinned codec unavailable; not a deployment success')
    if dist.version != '1.21.0':
        pytest.skip('different optional codec; not a deployment success')
    # Actively refuse package imports during the real snapshot, not only a
    # source-AST assertion about this candidate's direct imports.
    original_import = builtins.__import__
    def guarded_import(name, *args, **kwargs):
        if name.split('.')[0] in ('night_shifts', 'pycdlib'):
            pytest.fail('executable package imported during data snapshot')
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', guarded_import)
    code, codec = m._snapshots()
    assert tuple(sorted(code)) == m.CODE_NAMES
    assert tuple(sorted(codec)) == m.CODEC_NAMES
    assert all(b'\r\n' not in d for d in code.values())
    assert m._tree(code) and m._tree(codec)
    assert b'Version: 1.21.0' in codec[m.CODEC_METADATA + 'METADATA']
