"""Bounded PE/CLI DATA inspection for fixed build outputs. Never loads code.

Metadata consistency is not compiler provenance, independent artifact review,
installation acceptance or permission to execute either produced assembly.
"""
from __future__ import annotations

from dataclasses import dataclass
from xml.etree import ElementTree as ET

from night_shifts import bootstrap_native_build as build


class BuildArtifactRefused(RuntimeError):
    """Fixed-label malformed or unexpected artifact data."""


@dataclass(frozen=True)
class LocalExecutableMetadata:
    name: str
    entry: str
    references: tuple[str, ...]


# ECMA-335 II.22 table columns. s/b/g are heap indexes, tN table indexes;
# other identifiers are the closed coded-index forms below.
_SCHEMAS = (
    'u2 s g g g', 'ResolutionScope s s', 'u4 s s TypeDefOrRef t4 t6', 't4',
    'u2 s b', 't6', 'u4 u2 u2 s b t8', 't8', 'u2 u2 s', 't2 TypeDefOrRef',
    'MemberRefParent s b', 'u2 HasConstant b', 'HasCustomAttribute CustomAttributeType b',
    'HasFieldMarshal b', 'u2 HasDeclSecurity b', 'u2 u4 t2', 'u4 t4', 'b',
    't2 t20', 't20', 'u2 s TypeDefOrRef', 't2 t23', 't23', 'u2 s b',
    'u2 t6 HasSemantics', 't2 MethodDefOrRef MethodDefOrRef', 's', 'b',
    'u2 MemberForwarded s t26', 'u4 t4', 'u4 u4', 'u4',
    'u4 u2 u2 u2 u2 u4 b s s', 'u4', 'u4 u4 u4',
    'u2 u2 u2 u2 u4 b s s b', 'u4 t35', 'u4 u4 u4 t35', 'u4 s b',
    'u4 u4 s s Implementation', 'u4 u4 s Implementation', 't2 t2',
    'u2 u2 TypeOrMethodDef s', 'MethodDefOrRef b', 't42 TypeDefOrRef',
)
_CODED = {
    'TypeDefOrRef': (2, (2, 1, 27)), 'HasConstant': (2, (4, 8, 23)),
    'HasCustomAttribute': (5, (6, 4, 1, 2, 8, 9, 10, 0, 14, 23, 20, 17, 26, 27, 32, 35, 38, 39, 40, 42, 44, 43)),
    'HasFieldMarshal': (1, (4, 8)), 'HasDeclSecurity': (2, (2, 6, 32)),
    'MemberRefParent': (3, (2, 1, 26, 6, 27)), 'HasSemantics': (1, (20, 23)),
    'MethodDefOrRef': (1, (6, 10)), 'MemberForwarded': (1, (4, 6)),
    'Implementation': (2, (38, 35, 39)), 'CustomAttributeType': (3, (6, 10)),
    'ResolutionScope': (2, (0, 26, 35, 1)), 'TypeOrMethodDef': (1, (2, 6)),
}


def _need(ok: bool) -> None:
    if not ok:
        raise BuildArtifactRefused('build_artifact_shape')


def _uint(raw: bytes, offset: int, size: int = 4) -> int:
    _need(0 <= offset <= len(raw) - size and size in (1, 2, 4, 8))
    return int.from_bytes(raw[offset:offset + size], 'little')


def _slice(raw: bytes, offset: int, size: int) -> bytes:
    _need(size >= 0 and 0 <= offset <= len(raw) - size)
    return raw[offset:offset + size]


class _PE:
    def __init__(self, raw: bytes) -> None:
        _need(type(raw) is bytes and 512 <= len(raw) <= 16 * 1024**2 and raw[:2] == b'MZ')
        self.raw = raw
        pe = _uint(raw, 0x3c)
        _need(64 <= pe <= len(raw) - 264 and raw[pe:pe + 4] == b'PE\0\0')
        count, optional, flags = _uint(raw, pe + 6, 2), _uint(raw, pe + 20, 2), _uint(raw, pe + 22, 2)
        _need(_uint(raw, pe + 4, 2) == 0x8664 and 1 <= count <= 32 and optional == 240
              and bool(flags & 2) and not flags & 0x2000 and _uint(raw, pe + 24, 2) == 0x20b)
        _need(_uint(raw, pe + 24 + 108) == 16)
        self.directories = pe + 24 + 112
        headers = _uint(raw, pe + 24 + 60)
        _need(pe + 24 + optional + count * 40 <= headers <= len(raw))
        self.sections: list[tuple[int, int, int, int]] = []
        for index in range(count):
            at = pe + 24 + optional + index * 40
            virtual, rva, size, start = (_uint(raw, at + off) for off in (8, 12, 16, 20))
            _need(size > 0 and start >= headers and start <= len(raw) - size and rva > 0
                  and rva + max(size, virtual) <= 0xffffffff)
            for old_rva, old_virtual, old_start, old_size in self.sections:
                _need(start + size <= old_start or old_start + old_size <= start)
                _need(rva + max(size, virtual) <= old_rva or old_rva + old_virtual <= rva)
            self.sections.append((rva, max(size, virtual), start, size))

    def data(self, rva: int, size: int) -> bytes:
        _need(size > 0 and 0 < rva <= 0xffffffff - size)
        matches = [(start + rva - base, size) for base, _virtual, start, raw_size in self.sections
                   if base <= rva and rva + size <= base + raw_size]
        _need(len(matches) == 1)
        return _slice(self.raw, *matches[0])

    def directory(self, index: int) -> bytes:
        at = self.directories + index * 8
        return self.data(_uint(self.raw, at), _uint(self.raw, at + 4))

    def manifest(self) -> bytes:
        resource = self.directory(2)

        def entries(offset: int) -> dict[int, int]:
            _need(_uint(resource, offset + 12, 2) == 0)
            count = _uint(resource, offset + 14, 2)
            _need(1 <= count <= 16)
            result = {}
            for index in range(count):
                at = offset + 16 + index * 8
                key, target = _uint(resource, at), _uint(resource, at + 4)
                _need(key < 0x80000000 and key not in result)
                result[key] = target
            return result

        def subdirectory(target: int) -> int:
            _need(bool(target & 0x80000000))
            return target & 0x7fffffff

        root = entries(0)
        # csc can add a Win32 VERSION resource as well as the fixed manifest.
        _need(24 in root and set(root) <= {16, 24})
        ids = entries(subdirectory(root[24]))
        _need(set(ids) == {1})
        languages = entries(subdirectory(ids[1]))
        _need(len(languages) == 1)
        leaf = next(iter(languages.values()))
        _need(leaf < 0x80000000)
        rva, size = _uint(resource, leaf), _uint(resource, leaf + 4)
        _need(1 <= size <= 8192 and _uint(resource, leaf + 12) == 0)
        return self.data(rva, size)


def _xml_shape(element: ET.Element) -> tuple[object, ...]:
    return (element.tag, tuple(sorted(element.attrib.items())), (element.text or '').strip(),
            tuple(_xml_shape(child) for child in element), (element.tail or '').strip())


class _Metadata:
    def __init__(self, raw: bytes) -> None:
        _need(raw[:4] == b'BSJB')
        length = _uint(raw, 12)
        _need(1 <= length <= 256 and length % 4 == 0)
        offset = 16 + length
        _need(_uint(raw, offset, 2) == 0)
        count = _uint(raw, offset + 2, 2)
        _need(1 <= count <= 8)
        offset += 4
        self.streams: dict[str, bytes] = {}
        spans = []
        for _ in range(count):
            start, size = _uint(raw, offset), _uint(raw, offset + 4)
            end = raw.find(b'\0', offset + 8, min(len(raw), offset + 40))
            _need(end >= offset + 9)
            name = _slice(raw, offset + 8, end - offset - 8).decode('ascii')
            _need(name in ('#~', '#Strings', '#US', '#GUID', '#Blob') and name not in self.streams)
            self.streams[name] = _slice(raw, start, size)
            spans.append((start, size))
            offset = (end + 4) & ~3
        _need({'#~', '#Strings', '#Blob'} <= set(self.streams))
        for i, (start, size) in enumerate(spans):
            _need(start >= offset)
            for other, extent in spans[:i]:
                _need(start + size <= other or other + extent <= start)
        self.tables = self.streams['#~']
        _need(_uint(self.tables, 0) == 0 and _uint(self.tables, 4, 1) == 2
              and _uint(self.tables, 5, 1) == 0)
        self.heap_flags = _uint(self.tables, 6, 1)
        _need(self.heap_flags & ~7 == 0)
        valid = _uint(self.tables, 8, 8)
        _need(valid >> len(_SCHEMAS) == 0)
        self.rows = [0] * len(_SCHEMAS)
        cursor = 24
        for table in range(len(_SCHEMAS)):
            if valid & (1 << table):
                self.rows[table] = _uint(self.tables, cursor)
                _need(self.rows[table] <= 1000000)
                cursor += 4
        self.offsets = []
        for table, schema in enumerate(_SCHEMAS):
            self.offsets.append(cursor)
            cursor += sum(self.width(column) for column in schema.split()) * self.rows[table]
        _need(cursor <= len(self.tables))

    def width(self, column: str) -> int:
        if column in ('u2', 'u4'):
            return int(column[1:])
        if column in ('s', 'g', 'b'):
            return 4 if self.heap_flags & {'s': 1, 'g': 2, 'b': 4}[column] else 2
        if column.startswith('t'):
            return 4 if self.rows[int(column[1:])] >= 65536 else 2
        bits, tables = _CODED[column]
        return 4 if max(self.rows[table] for table in tables) >= 1 << (16 - bits) else 2

    def row(self, table: int, index: int) -> list[int]:
        _need(1 <= index <= self.rows[table])
        columns = _SCHEMAS[table].split()
        at = self.offsets[table] + (index - 1) * sum(self.width(column) for column in columns)
        result = []
        for column in columns:
            size = self.width(column)
            result.append(_uint(self.tables, at, size))
            at += size
        return result

    def text(self, index: int) -> str:
        raw = self.streams['#Strings']
        _need(0 <= index < len(raw))
        end = raw.find(b'\0', index, min(index + 513, len(raw)))
        _need(end >= index)
        return raw[index:end].decode('utf-8')

    def blob(self, index: int) -> bytes:
        raw = self.streams['#Blob']
        first = _uint(raw, index, 1)
        if first < 0x80:
            size, prefix = first, 1
        elif first < 0xc0:
            size, prefix = ((first & 0x3f) << 8) | _uint(raw, index + 1, 1), 2
        else:
            _need(first < 0xe0)
            size, prefix = ((first & 0x1f) << 24) | int.from_bytes(_slice(raw, index + 1, 3), 'big'), 4
        return _slice(raw, index + prefix, size)


def inspect_fixed_executable(name: str, raw: bytes) -> LocalExecutableMetadata:
    """Inspect bytes only. Forgeable return data cannot authorize installation."""
    try:
        expected = dict((*build.ENTRY_POINTS, *build.SETUP_ENTRY_POINTS, build.COMMAND_ENTRY_POINT))
        _need(type(name) is str and name in expected)
        pe = _PE(raw)
        clr = pe.directory(14)
        _need(len(clr) == 72 and _uint(clr, 0) == 72 and _uint(clr, 16) == 1)
        token = _uint(clr, 20)
        _need(token >> 24 == 6 and token & 0xffffff != 0)
        metadata = _Metadata(pe.data(_uint(clr, 8), _uint(clr, 12)))
        method_index = token & 0xffffff
        method = metadata.row(6, method_index)
        _need(metadata.text(method[3]) == 'Main' and method[1] == 0 and bool(method[2] & 0x10)
              and not method[2] & (0x2000 | 0x400) and metadata.blob(method[4]) == b'\0\x01\x08\x1d\x0e')
        pe.data(method[0], 1)
        owners = []
        for index in range(1, metadata.rows[2] + 1):
            row = metadata.row(2, index)
            limit = metadata.row(2, index + 1)[5] if index < metadata.rows[2] else metadata.rows[6] + 1
            _need(1 <= row[5] <= limit <= metadata.rows[6] + 1)
            if row[5] <= method_index < limit:
                owners.append(metadata.text(row[2]) + '.' + metadata.text(row[1]))
        _need(owners == [expected[name]] and metadata.rows[32] == 1)
        assembly = metadata.row(32, 1)
        _need(metadata.text(assembly[7]) == name[:-4])
        refs = []
        for index in range(1, metadata.rows[35] + 1):
            row = metadata.row(35, index)
            ref = metadata.text(row[6])
            _need(row[:5] == [4, 0, 0, 0, 0] and metadata.text(row[7]) == ''
                  and metadata.blob(row[5]) == bytes.fromhex('b77a5c561934e089')
                  and metadata.blob(row[8]) == b'')
            refs.append(ref)
        required = {'mscorlib', 'System'} if name == build.COMMAND_ENTRY_POINT[0] else {'mscorlib', 'System', 'System.Runtime.Serialization'}
        _need(len(refs) == len(set(refs)) and required <= set(refs)
              and set(refs) <= {ref[:-4] for ref in build.REFERENCE_NAMES})
        manifest = pe.manifest()
        _need(b'<!' not in manifest and _xml_shape(ET.fromstring(manifest)) == _xml_shape(ET.fromstring(build.MANIFEST_BYTES)))
        return LocalExecutableMetadata(name, owners[0], tuple(sorted(refs)))
    except (ValueError, UnicodeError, IndexError, KeyError, ET.ParseError, BuildArtifactRefused):
        raise BuildArtifactRefused('build_artifact_refused') from None
