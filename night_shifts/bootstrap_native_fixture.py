"""Fixed inert Linux x86-64 exec-control fixture, returned IN MEMORY ONLY.

Not a compiler, installer, executable writer or native test. No CLI or execution
API. The later reviewed guest supervisor may place these exact pinned bytes only
at its create-new RAM fixture path in a separately authorized validation VM.
"""
from __future__ import annotations

import hashlib
import struct

FIXTURE_BYTES = 188
FIXTURE_SHA256 = '20ca4e55db7e6a7010eca0fb65eca069aebeff95a8b8ad147ef46cbcd36d018d'
EXIT_STATUS = 37
# mov eax,60; mov edi,37; syscall  -- Linux x86-64 exit(37), nothing else.
_CODE = bytes.fromhex('b83c000000bf250000000f05')


class NativeFixtureRefused(RuntimeError):
    """Fixed label only; no fixture bytes or caller data."""


def validate_inert_fixture(raw: bytes) -> None:
    """Accept exactly the pinned fixture, never arbitrary caller-supplied ELF."""
    if (type(raw) is not bytes or len(raw) != FIXTURE_BYTES
            or hashlib.sha256(raw).hexdigest() != FIXTURE_SHA256):
        raise NativeFixtureRefused('fixture_digest')


def inert_fixture_bytes() -> bytes:
    """Return the fixed ET_EXEC ELF without writing or executing it.

    ELF64 little-endian x86-64, one RX PT_LOAD, one RW/non-X GNU_STACK;
    no interpreter, dynamic loader, relocations, sections, imports or RWX load.
    Entry is the first of exactly three instructions. Header and code bytes are
    pinned together, independently of a future media's internal manifest.
    """
    base = 0x400000
    entry = 64 + 2 * 56
    ident = b'\x7fELF' + bytes((2, 1, 1, 0)) + bytes(8)
    header = struct.pack('<16sHHIQQQIHHHHHH', ident, 2, 62, 1, base + entry,
                         64, 0, 0, 64, 56, 2, 0, 0, 0)
    load = struct.pack('<IIQQQQQQ', 1, 5, 0, base, base,
                       FIXTURE_BYTES, FIXTURE_BYTES, 4096)
    stack = struct.pack('<IIQQQQQQ', 0x6474e551, 6, 0, 0, 0, 0, 0, 16)
    raw = header + load + stack + _CODE
    validate_inert_fixture(raw)
    return raw
