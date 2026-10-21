"""Offline synthetic archive tests; no downloads/staging lookup/binary execution.

Private-parser fixtures explicitly replace the output hash/length. They cannot
establish distro provenance, release freshness, real daemon behavior or deployment.
The public factory pins are never replaced by a caller-facing testing interface.
"""
from __future__ import annotations

import hashlib
import io
import tarfile

import pytest

from night_shifts import bootstrap_daemon_asset as asset


ENTRY = './usr/lib/linux-tools-6.8.0-139/hv_kvp_daemon'
SYNTHETIC = b'\x7fELF\x02\x01\x01SYNTHETIC-NOT-EXECUTABLE'


def ar_part(name, raw):
    header = (name.ljust(16) + '0'.ljust(12) + '0'.ljust(6) + '0'.ljust(6)
              + '100644'.ljust(8) + str(len(raw)).ljust(10) + '`\n').encode('ascii')
    assert len(header) == 60
    return header + raw + (b'\n' if len(raw) % 2 else b'')


def debian_ar(*, version=b'2.0\n', data=b'data'):
    return (b'!<arch>\n' + ar_part('debian-binary', version)
            + ar_part('control.tar.zst', b'control') + ar_part('data.tar.zst', data))


def tar_bytes(entries):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w', format=tarfile.USTAR_FORMAT) as archive:
        for name, changes, raw in entries:
            info = tarfile.TarInfo(name)
            info.mode = 0o755
            info.uid = info.gid = 0
            info.size = len(raw)
            for key, value in changes.items():
                setattr(info, key, value)
            archive.addfile(info, io.BytesIO(raw) if info.isfile() else None)
    return output.getvalue()


@pytest.fixture
def synthetic_policy(monkeypatch):
    # Private parser only, no public package digest bypass in the runtime API.
    monkeypatch.setattr(asset, 'DAEMON_BYTES', len(SYNTHETIC))
    monkeypatch.setattr(asset, 'DAEMON_SHA256', hashlib.sha256(SYNTHETIC).hexdigest())


def test_fixed_review_pins_and_explicit_single_entry():
    assert asset.PACKAGE_NAME == 'linux-cloud-tools-6.8.0-139_6.8.0-139.139_amd64.deb'
    assert asset.PACKAGE_BYTES == 148096
    assert asset.PACKAGE_SHA256 == 'd07e7f7804374bd33bb31ca51a46b23f497ef530cefef00244a4e92d01727f6c'
    assert asset.DAEMON_ENTRY == ENTRY
    assert asset.DAEMON_BYTES == 44712
    assert asset.DAEMON_SHA256 == '612a3f9fb420d0d891fcfeeb2df8c6be55dbd015b3853e800aa793341ae2c21b'


@pytest.mark.parametrize('raw', [None, b'', b'!<arch>\n', bytearray(), b'x' * 148096,
                                 b'x' * 148097],
                         ids=['none', 'empty', 'short', 'mutable', 'wrong-hash', 'oversized'])
def test_public_factory_rejects_before_decompression(raw, monkeypatch):
    monkeypatch.setattr(asset, '_ar_data', lambda _: pytest.fail('must refuse before parsing'))
    with pytest.raises(asset.DaemonAssetRefused, match='^package_digest$'):
        asset.extract_reviewed_daemon(raw)


def test_private_ar_observed_shape_only():
    assert asset._ar_data(debian_ar(data=b'selected-data')) == b'selected-data'


@pytest.mark.parametrize('change', [
    lambda raw: b'badmagic' + raw[8:],
    lambda raw: raw[:-1],
    lambda raw: raw + b'x',
    lambda raw: raw.replace(b'data.tar.zst', b'evil.tar.zst'),
    lambda raw: raw.replace(b'data.tar.zst', b'control.zst '),
    lambda raw: raw.replace(b'`\n', b'xx', 1),
    lambda raw: raw[:56] + b'-1        ' + raw[66:],
    lambda raw: raw[:56] + b'9999999999' + raw[66:],
    lambda raw: raw.replace(b'control\n', b'control!'),
    lambda raw: debian_ar(version=b'3.0\n'),
    lambda raw: raw + ar_part('data.tar.zst', b'other'),
])
def test_private_ar_malformed_order_sizes_padding_and_duplicates(change):
    with pytest.raises(asset.DaemonAssetRefused, match='^ar_shape$'):
        asset._ar_data(change(debian_ar()))


def test_synthetic_tar_returns_only_selected_elf(synthetic_policy):
    raw = tar_bytes([
        ('.', {'type': tarfile.DIRTYPE}, b''),
        ('./usr/lib/linux-tools-6.8.0-139/hv_fcopy_daemon', {}, b'NEVER-RETURN-FCOPY'),
        (ENTRY, {}, SYNTHETIC),
        ('./usr/lib/linux-tools-6.8.0-139/hv_vss_daemon', {}, b'NEVER-RETURN-VSS'),
        ('./postinst', {}, b'NEVER-EXECUTE-INSTALLER'),
    ])
    assert asset._daemon_from_tar(raw) == SYNTHETIC


@pytest.mark.parametrize('name,changes,raw', [
    ('/absolute', {}, b'x'),
    ('./../escape', {}, b'x'),
    ('./a//b', {}, b'x'),
    ('./a/./b', {}, b'x'),
    ('relative', {}, b'x'),
    ('./a\\b', {}, b'x'),
    ('./symlink', {'type': tarfile.SYMTYPE, 'linkname': ENTRY}, b''),
    ('./hardlink', {'type': tarfile.LNKTYPE, 'linkname': ENTRY}, b''),
    ('./device', {'type': tarfile.CHRTYPE}, b''),
    ('./fifo', {'type': tarfile.FIFOTYPE}, b''),
    ('./wrong-user', {'uid': 1}, b'x'),
    ('./wrong-group', {'gid': 1}, b'x'),
    ('./group-write', {'mode': 0o775}, b'x'),
    ('./other-write', {'mode': 0o757}, b'x'),
    ('./setuid', {'mode': 0o4755}, b'x'),
], ids=['absolute', 'parent', 'empty-part', 'dot-part', 'relative', 'backslash',
        'symlink', 'hardlink', 'device', 'fifo', 'user', 'group', 'group-write',
        'other-write', 'setuid'])
def test_unsafe_members_are_never_followed_or_written(name, changes, raw, synthetic_policy):
    candidate = tar_bytes([(ENTRY, {}, SYNTHETIC), (name, changes, raw)])
    with pytest.raises(asset.DaemonAssetRefused, match='^tar_shape$'):
        asset._daemon_from_tar(candidate)


def test_duplicates_missing_wrong_mode_size_and_digest(synthetic_policy):
    for entries, reason in [
        ([(ENTRY, {}, SYNTHETIC), (ENTRY, {}, SYNTHETIC)], 'tar_shape'),
        ([('./other', {}, SYNTHETIC)], 'daemon_shape'),
        ([(ENTRY, {'mode': 0o644}, SYNTHETIC)], 'daemon_shape'),
        ([(ENTRY, {}, SYNTHETIC + b'x')], 'daemon_shape'),
        ([(ENTRY, {}, b'x' * len(SYNTHETIC))], 'daemon_digest'),
    ]:
        with pytest.raises(asset.DaemonAssetRefused, match='^' + reason + '$'):
            asset._daemon_from_tar(tar_bytes(entries))


def test_tar_count_and_input_bounds(synthetic_policy, monkeypatch):
    entries = [(ENTRY, {}, SYNTHETIC)] + [(f'./extra-{i}', {}, b'x') for i in range(32)]
    with pytest.raises(asset.DaemonAssetRefused, match='^tar_shape$'):
        asset._daemon_from_tar(tar_bytes(entries))
    monkeypatch.setattr(asset, 'MAX_TAR_BYTES', 32)
    for raw in (b'', b'x' * 33, bytearray(b'x')):
        with pytest.raises(asset.DaemonAssetRefused, match='^tar_shape$'):
            asset._daemon_from_tar(raw)


def test_stdlib_zstd_bounds_and_no_concatenated_or_trailing_frames(monkeypatch):
    zstd = pytest.importorskip('compression.zstd', reason='review-only extraction requires Python 3.14')
    frame = zstd.compress(b'public-only')
    assert asset._zstd_tar(frame) == b'public-only'
    for raw in (b'', frame[:-1], frame + frame, frame + b'junk'):
        with pytest.raises(asset.DaemonAssetRefused, match='^zstd_shape$'):
            asset._zstd_tar(raw)
    monkeypatch.setattr(asset, 'MAX_TAR_BYTES', 3)
    with pytest.raises(asset.DaemonAssetRefused, match='^zstd_shape$'):
        asset._zstd_tar(frame)
