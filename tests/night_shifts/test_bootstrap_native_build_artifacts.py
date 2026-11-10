"""Bounded synthetic PE/CLI data; never load or invoke an assembly."""
from __future__ import annotations

import struct

import pytest

from night_shifts import bootstrap_native_build as build
from night_shifts import bootstrap_native_build_artifacts as artifacts


def _image(index=0, *, extra_reference=None, manifest=None):
    name, entry = build.ENTRY_POINTS[index]
    namespace, typename = entry.rsplit('.', 1)
    strings, blobs = bytearray(b'\0'), bytearray(b'\0')

    def text(value):
        at = len(strings)
        strings.extend(value.encode() + b'\0')
        return at

    def blob(value):
        assert len(value) < 128
        at = len(blobs)
        blobs.extend(bytes([len(value)]) + value)
        return at

    module, type_name, ns, main = (text(value) for value in (name, typename, namespace, 'Main'))
    assembly_name = text(name[:-4])
    signature = blob(b'\0\x01\x08\x1d\x0e')
    key = blob(bytes.fromhex('b77a5c561934e089'))
    refs = ['mscorlib', 'System', 'System.Runtime.Serialization']
    if extra_reference is not None:
        refs.append(extra_reference)
    rows = {
        0: struct.pack('<HHHHH', 0, module, 0, 0, 0),
        2: struct.pack('<IHHHHH', 0x100001, type_name, ns, 0, 1, 1),
        6: struct.pack('<IHHHHH', 0x2100, 0, 0x91, main, signature, 1),
        32: struct.pack('<IHHHHIHHH', 0x8004, 0, 0, 0, 0, 0, 0, assembly_name, 0),
        35: b''.join(struct.pack('<HHHHIHHHH', 4, 0, 0, 0, 0, key, text(ref), 0, 0) for ref in refs),
    }
    valid = sum(1 << table for table in rows)
    tables = struct.pack('<IBBBBQQ', 0, 2, 0, 0, 1, valid, 0)
    tables += b''.join(struct.pack('<I', len(refs) if table == 35 else 1) for table in sorted(rows))
    tables += b''.join(rows[table] for table in sorted(rows))
    streams = [('#~', tables), ('#Strings', bytes(strings)), ('#Blob', bytes(blobs))]
    root = b'BSJB' + struct.pack('<HHII', 1, 1, 0, 12) + b'v4.0.30319\0\0' + struct.pack('<HH', 0, len(streams))
    assert len(root) == 32
    header_size = sum(8 + ((len(key) + 4) & ~3) for key, _ in streams)
    offset, headers, body = len(root) + header_size, bytearray(), bytearray()
    for stream_name, raw in streams:
        encoded = stream_name.encode() + b'\0'
        encoded += b'\0' * (-len(encoded) % 4)
        headers.extend(struct.pack('<II', offset, len(raw)) + encoded)
        body.extend(raw)
        offset += len(raw)
    metadata = root + headers + body
    image = bytearray(0x2200)
    image[:2] = b'MZ'
    struct.pack_into('<I', image, 0x3c, 0x80)
    image[0x80:0x84] = b'PE\0\0'
    struct.pack_into('<HHIIIHH', image, 0x84, 0x8664, 1, 0, 0, 0, 240, 0x22)
    optional = 0x98
    struct.pack_into('<H', image, optional, 0x20b)
    struct.pack_into('<I', image, optional + 60, 0x200)
    struct.pack_into('<I', image, optional + 108, 16)
    struct.pack_into('<II', image, optional + 112 + 14 * 8, 0x2000, 72)
    struct.pack_into('<II', image, optional + 112 + 2 * 8, 0x3800, 0x600)
    section = optional + 240
    image[section:section + 8] = b'.text\0\0\0'
    struct.pack_into('<IIII', image, section + 8, 0x2000, 0x2000, 0x2000, 0x200)
    struct.pack_into('<IHHIIII', image, 0x200, 72, 2, 5, 0x2200, len(metadata), 1, 0x06000001)
    image[0x300] = 0x2a
    image[0x400:0x400 + len(metadata)] = metadata
    # Numeric RT_MANIFEST / id 1 / language 0, no executable resource load.
    resource = 0x1a00
    for at, key, target in [(0, 24, 0x80000018), (24, 1, 0x80000030), (48, 0, 72)]:
        struct.pack_into('<HHII', image, resource + at + 12, 0, 1, key, target)
    manifest = build.MANIFEST_BYTES if manifest is None else manifest
    struct.pack_into('<IIII', image, resource + 72, 0x3860, len(manifest), 0, 0)
    image[resource + 96:resource + 96 + len(manifest)] = manifest
    return name, bytes(image)


@pytest.mark.parametrize('index', [0, 1])
def test_fixed_entry_signature_references_and_manifest_from_data(index):
    name, raw = _image(index)
    result = artifacts.inspect_fixed_executable(name, raw)
    assert result.name == name and result.entry == build.ENTRY_POINTS[index][1]
    assert result.references == ('System', 'System.Runtime.Serialization', 'mscorlib')


@pytest.mark.parametrize('offset,size,value', [
    (0x3c, 4, 0xffffffff), (0x84, 2, 0x14c), (0x86, 2, 0), (0x94, 2, 224),
    (0x96, 2, 0x2022), (0x98, 2, 0x10b), (0x98 + 108, 4, 0),
    (0x200, 4, 71), (0x210, 4, 3), (0x214, 4, 0x06000000), (0x214, 4, 0x02000001),
    (0x208, 4, 0x100), (0x20c, 4, 0xffffffff),
])
def test_malformed_headers_do_not_load_or_leak_unbounded_parser_errors(offset, size, value):
    name, raw = _image()
    changed = bytearray(raw)
    changed[offset:offset + size] = value.to_bytes(size, 'little')
    with pytest.raises(artifacts.BuildArtifactRefused, match='^build_artifact_refused$'):
        artifacts.inspect_fixed_executable(name, bytes(changed))


@pytest.mark.parametrize('cut', [0, 1, 64, 511, 512, 1024, 2048, 8191])
def test_truncation_is_bounded_data_refusal(cut):
    name, raw = _image()
    with pytest.raises(artifacts.BuildArtifactRefused):
        artifacts.inspect_fixed_executable(name, raw[:cut])


def test_other_main_name_and_reference_selection_refuse():
    name, raw = _image()
    with pytest.raises(artifacts.BuildArtifactRefused):
        artifacts.inspect_fixed_executable(build.ENTRY_POINTS[1][0], raw)
    with pytest.raises(artifacts.BuildArtifactRefused):
        artifacts.inspect_fixed_executable(name, raw.replace(b'Main\0', b'Evil\0'))
    name, raw = _image(extra_reference='Injected')
    with pytest.raises(artifacts.BuildArtifactRefused):
        artifacts.inspect_fixed_executable(name, raw)


@pytest.mark.parametrize('manifest', [
    build.MANIFEST_BYTES.replace(b'asInvoker', b'requireAdministrator'),
    build.MANIFEST_BYTES.replace(b'uiAccess="false"', b'uiAccess="true"'),
    b'<!DOCTYPE x [<!ENTITY y "unsafe">]><x>&y;</x>', b'<broken',
])
def test_manifest_is_exact_fixed_structure_not_a_raw_marker_search(manifest):
    name, raw = _image(manifest=manifest)
    with pytest.raises(artifacts.BuildArtifactRefused):
        artifacts.inspect_fixed_executable(name, raw)


@pytest.mark.parametrize('bad', [b'', b'MZ' + b'x' * 1024, bytearray(b'x' * 512), 'not bytes', None])
def test_input_shape_refuses_without_assembly_loading(bad):
    with pytest.raises(artifacts.BuildArtifactRefused):
        artifacts.inspect_fixed_executable(build.ENTRY_POINTS[0][0], bad)
