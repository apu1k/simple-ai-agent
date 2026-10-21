"""Offline extraction of ONE hash-pinned public KVP-daemon candidate.

No downloads, paths, archive extraction to disk, installation, execution, service
control, media authoring or VM operations. Not a production/deployment approval.
The package/source provenance review is external; these pins freeze that review,
not current security freshness or compatibility with a running guest. Existing
inspection bundles/callers do not import this module. Python 3.14 stdlib zstd is
required only when explicitly calling extraction; there is no dependency fallback.
"""
from __future__ import annotations

import hashlib
import io
import tarfile

PACKAGE_NAME = 'linux-cloud-tools-6.8.0-139_6.8.0-139.139_amd64.deb'
PACKAGE_BYTES = 148096
PACKAGE_SHA256 = 'd07e7f7804374bd33bb31ca51a46b23f497ef530cefef00244a4e92d01727f6c'
DAEMON_ENTRY = './usr/lib/linux-tools-6.8.0-139/hv_kvp_daemon'
DAEMON_BYTES = 44712
DAEMON_SHA256 = '612a3f9fb420d0d891fcfeeb2df8c6be55dbd015b3853e800aa793341ae2c21b'
MAX_TAR_BYTES = 8 * 1024 * 1024
_AR_MEMBERS = ('debian-binary', 'control.tar.zst', 'data.tar.zst')


class DaemonAssetRefused(RuntimeError):
    """Fixed labels, never raw archive names, bytes or exception text."""


def _ar_data(raw: bytes) -> bytes:
    """Read the observed three-member Debian ar shape, never execute control."""
    if type(raw) is not bytes or not 8 <= len(raw) <= PACKAGE_BYTES or raw[:8] != b'!<arch>\n':
        raise DaemonAssetRefused('ar_shape')
    position = 8
    parts: list[bytes] = []
    for expected in _AR_MEMBERS:
        header = raw[position:position + 60]
        if len(header) != 60 or header[-2:] != b'`\n':
            raise DaemonAssetRefused('ar_shape')
        try:
            name = header[:16].decode('ascii').rstrip(' ')
            if name.endswith('/'):
                name = name[:-1]
            size_text = header[48:58].decode('ascii').strip(' ')
            if not size_text or not size_text.isascii() or not size_text.isdecimal():
                raise ValueError
            size = int(size_text)
        except (ValueError, UnicodeError):
            raise DaemonAssetRefused('ar_shape') from None
        end = position + 60 + size
        if name != expected or not 0 < size <= PACKAGE_BYTES or end > len(raw):
            raise DaemonAssetRefused('ar_shape')
        parts.append(raw[position + 60:end])
        if size % 2 and raw[end:end + 1] != b'\n':
            raise DaemonAssetRefused('ar_shape')
        position = end + size % 2
    if position != len(raw) or parts[0] != b'2.0\n':
        raise DaemonAssetRefused('ar_shape')
    return parts[2]


def _zstd_tar(raw: bytes) -> bytes:
    try:
        from compression import zstd
    except ImportError:
        raise DaemonAssetRefused('python314_zstd_required') from None
    try:
        # Both output and frame window are bounded; no unlimited decompression.
        decoder = zstd.ZstdDecompressor(options={zstd.DecompressionParameter.window_log_max: 23})
        result = decoder.decompress(raw, max_length=MAX_TAR_BYTES + 1)
        if not decoder.eof or decoder.unused_data or not 0 < len(result) <= MAX_TAR_BYTES:
            raise DaemonAssetRefused('zstd_shape')
        return result
    except (zstd.ZstdError, EOFError, ValueError):
        raise DaemonAssetRefused('zstd_shape') from None


def _daemon_from_tar(raw: bytes) -> bytes:
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_TAR_BYTES:
        raise DaemonAssetRefused('tar_shape')
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode='r:') as archive:
            members = archive.getmembers()
            if archive.pax_headers or not 1 <= len(members) <= 32:
                raise DaemonAssetRefused('tar_shape')
            selected: tarfile.TarInfo | None = None
            seen: set[str] = set()
            for member in members:
                name = member.name
                # Inventory only: never follow links or materialize any member.
                if (name in seen or member.pax_headers or member.linkname
                        or member.type not in (tarfile.REGTYPE, tarfile.DIRTYPE)
                        or member.uid != 0 or member.gid != 0 or member.mode & 0o7022
                        or not (name == '.' or name.startswith('./'))
                        or '\\' in name or '\x00' in name
                        or (name != '.' and any(p in ('', '.', '..') for p in name[2:].split('/')))
                        or not 0 <= member.size <= 2 * 1024 * 1024):
                    raise DaemonAssetRefused('tar_shape')
                seen.add(name)
                if name == DAEMON_ENTRY:
                    selected = member
            if (selected is None or selected.type != tarfile.REGTYPE
                    or selected.mode != 0o755 or selected.size != DAEMON_BYTES):
                raise DaemonAssetRefused('daemon_shape')
            stream = archive.extractfile(selected)
            if stream is None:
                raise DaemonAssetRefused('daemon_shape')
            with stream:
                result = stream.read(DAEMON_BYTES + 1)
            if (len(result) != DAEMON_BYTES
                    or hashlib.sha256(result).hexdigest() != DAEMON_SHA256
                    or not result.startswith(b'\x7fELF\x02\x01\x01')):
                raise DaemonAssetRefused('daemon_digest')
            return result
    except (tarfile.TarError, OSError, ValueError, UnicodeError, OverflowError):
        raise DaemonAssetRefused('tar_shape') from None


def extract_reviewed_daemon(package: bytes) -> bytes:
    """Return only the pinned KVP ELF, never fcopy/VSS, wrappers, links or hooks.

    The entire package must match before parsing/decompression. This function
    cannot refresh trust, choose another version, approve a license distribution,
    create a runtime, start a daemon or establish live compatibility/provenance.
    Future media authoring must retain license/source information separately and
    recheck package, source, code inventory and trusted runtime at its own boundary.
    """
    if (type(package) is not bytes or len(package) != PACKAGE_BYTES
            or hashlib.sha256(package).hexdigest() != PACKAGE_SHA256):
        raise DaemonAssetRefused('package_digest')
    return _daemon_from_tar(_zstd_tar(_ar_data(package)))
