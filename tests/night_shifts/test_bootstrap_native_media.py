"""Real pinned ISO codec, MEMORY ONLY; no file/image write, mount or VM.

The inherited seed fixture explicitly substitutes public asset pins. Canonical
ISO bytes are data-format observations, not real input provenance, native Linux/
NoCloud success or host receipts. No embedded code is ever executed.
"""
from __future__ import annotations

import hashlib
import io
import json
import time
import zipfile
from dataclasses import FrozenInstanceError, replace
from importlib.metadata import PackageNotFoundError
from types import SimpleNamespace

import pytest

from night_shifts import bootstrap_native_media as media
from night_shifts.bootstrap_native_handoff import render_native_validation_handoff
from night_shifts.maintenance_tls_prototype import AttemptBinding
from tests.night_shifts import test_bootstrap_recovery_handoff as existing

support = existing.support


@pytest.fixture
def sample(support):
    pytest.importorskip('pycdlib', reason='pinned optional ISO codec required; no native fallback')
    return media.build_native_validation_iso(support[0], support[1], expected_seed_sha256=existing.sha(support[1]))


def build(support):
    return media.build_native_validation_iso(support[0], support[1], expected_seed_sha256=existing.sha(support[1]))


def handoff(support):
    return render_native_validation_handoff(support[0], support[1], expected_seed_sha256=existing.sha(support[1]))


def inspect(support, image, digest=None):
    return media.inspect_native_validation_iso(support[0], support[1], expected_seed_sha256=existing.sha(support[1]),
                                              image=image, expected_image_sha256=digest or existing.sha(image))


def test_real_iso_exact_three_namespaces_and_public_descriptor(support, sample):
    library, _ = media._library()
    expected = handoff(support).files()
    assert len(sample.image) == sample.size_bytes <= media.MAX_MEDIA_BYTES
    assert hashlib.sha256(sample.image).hexdigest() == sample.sha256
    assert sample.image[:16 * 2048] == b'\x00' * (16 * 2048)
    iso = library.PyCdlib()
    iso.open_fp(io.BytesIO(sample.image))
    try:
        assert iso.has_rock_ridge() and iso.has_joliet() and not iso.has_udf()
        assert iso.eltorito_boot_catalog is None and len(iso.svds) == 1
        assert iso.pvd.volume_identifier == b'CIDATA'.ljust(32, b' ')
        for namespace in ('iso_path', 'rr_path', 'joliet_path'):
            for name, alias in media._LAYOUT:
                output = io.BytesIO()
                path = alias if namespace == 'iso_path' else '/' + name
                iso.get_file_from_iso_fp(output, **{namespace: path})
                assert output.getvalue() == expected[name]
        assert iso.pvd.volume_expiration_date.date_str == media._NO_DATE
    finally:
        iso.close()
    descriptor = sample.review_bytes()
    value = json.loads(descriptor)
    assert len(descriptor) <= media.MAX_DESCRIPTOR_BYTES and descriptor.endswith(b'\n')
    assert value['scope'] == 'local_media_consistency_only' and value['purpose'] == 'native-validation-cidata-only'
    assert value['image'] == dict(sha256=sample.sha256, bytes=sample.size_bytes,
        volume_label='CIDATA', logical_block_bytes=2048, bootable=False)
    assert set(value['files']) == set(expected)
    assert value['attempt_id'] == support[0].attempt_id and value['vm_id'] == support[0].vm_id
    assert not {'approved', 'accepted', 'native_pass', 'vm_absent', 'gate_a'} & value.keys()
    assert 'image=' not in repr(sample) and b'#cloud-config' not in descriptor
    with pytest.raises(FrozenInstanceError):
        sample.sha256 = '0' * 64


def test_inspector_regenerates_current_handoff_and_exact_whole_image(support, sample):
    assert inspect(support, sample.image, sample.sha256) == sample
    assert build(support) == sample


def test_output_is_independent_of_codec_clock_and_local_timezone_without_global_clock_patch(support, sample, monkeypatch):
    from pycdlib import dates, headervd, pycdlib as engine
    original_time, original_localtime = time.time, time.localtime
    clock = SimpleNamespace(**vars(time))
    clock.time = lambda: 1_200_000_000.0
    local = SimpleNamespace(**vars(time))
    local.localtime = lambda stamp: time.gmtime(stamp + 9 * 3600)
    monkeypatch.setattr(engine, 'time', clock)
    monkeypatch.setattr(headervd, 'time', clock)
    monkeypatch.setattr(dates, 'time', local)
    assert build(support).image == sample.image
    assert time.time is original_time and time.localtime is original_localtime


@pytest.mark.parametrize('field', ['system-area', 'label', 'metadata', 'file-data', 'tail'])
def test_self_rehashed_changed_byte_never_reaches_iso_reader(support, sample, monkeypatch, field):
    raw = bytearray(sample.image)
    offset = {'system-area': 0, 'label': 16 * 2048 + 40, 'metadata': 16 * 2048 + 813,
              'file-data': sample.image.index(handoff(support).meta_data), 'tail': len(raw) - 1}[field]
    raw[offset] ^= 1
    monkeypatch.setattr(media, '_audit_views', lambda *args: pytest.fail('untrusted image reached codec reader'))
    with pytest.raises(media.NativeMediaRefused, match='^image_not_canonical$'):
        inspect(support, bytes(raw))


@pytest.mark.parametrize('kind', ['prefix', 'suffix', 'missing-sector', 'truncated'])
def test_changed_extent_or_trailing_data_is_not_salvaged(support, sample, kind):
    raw = {'prefix': b'JUNK' + sample.image, 'suffix': sample.image + b'JUNK',
           'missing-sector': sample.image[:-2048], 'truncated': sample.image[:100]}[kind]
    with pytest.raises(media.NativeMediaRefused):
        inspect(support, raw)


def test_external_image_pin_checked_before_source_render_or_codec(support, sample, monkeypatch):
    monkeypatch.setattr(media, '_render', lambda *a: pytest.fail('render before image pin'))
    monkeypatch.setattr(media, '_library', lambda: pytest.fail('codec before image pin'))
    with pytest.raises(media.NativeMediaRefused, match='^image_digest$'):
        inspect(support, sample.image, '0' * 64)


@pytest.mark.parametrize('raw', [None, 'not bytes', bytearray(b'x'), b''])
def test_input_types_fail_before_codec_or_current_sources(support, raw, monkeypatch):
    monkeypatch.setattr(media, '_render', lambda *a: pytest.fail('render before image bound'))
    with pytest.raises(media.NativeMediaRefused, match='^image_digest$'):
        media.inspect_native_validation_iso(support[0], support[1], expected_seed_sha256=existing.sha(support[1]),
                                            image=raw, expected_image_sha256='0' * 64)


def test_oversize_input_is_bounded_before_parser(support, monkeypatch):
    monkeypatch.setattr(media, '_library', lambda: pytest.fail('parser before size bound'))
    raw = b'X' * (media.MAX_MEDIA_BYTES + 1)
    with pytest.raises(media.NativeMediaRefused, match='^image_digest$'):
        inspect(support, raw)


def test_wrong_seed_pin_refuses_before_iso_authoring(support, monkeypatch):
    monkeypatch.setattr(media, '_library', lambda: pytest.fail('author before seed pin'))
    with pytest.raises(media.NativeMediaRefused, match='^handoff_refused$'):
        media.build_native_validation_iso(support[0], support[1], expected_seed_sha256='0' * 64)


def test_mixed_binding_and_media_refuse_without_new_acceptance_semantics(support, sample):
    other = AttemptBinding('2' * 32, '00000000-0000-4000-8000-000000000002')
    with pytest.raises(media.NativeMediaRefused):
        media.inspect_native_validation_iso(other, support[1], expected_seed_sha256=existing.sha(support[1]),
                                            image=sample.image, expected_image_sha256=sample.sha256)


@pytest.mark.parametrize('value', ['X' * 64, True, None, '0' * 63])
def test_seed_digest_contract_is_canonical_before_snapshot(support, monkeypatch, value):
    monkeypatch.setattr(media, 'render_native_validation_handoff', lambda *a, **k: pytest.fail('snapshot before context'))
    with pytest.raises(media.NativeMediaRefused, match='^context$'):
        media.build_native_validation_iso(support[0], support[1], expected_seed_sha256=value)


@pytest.mark.parametrize('missing', [False, True])
def test_wrong_or_unavailable_codec_never_falls_back(support, monkeypatch, missing):
    def codec_version(name):
        assert name == 'pycdlib'
        if missing:
            raise PackageNotFoundError(name)
        return '0.0'
    monkeypatch.setattr(media, 'version', codec_version)
    with pytest.raises(media.NativeMediaRefused, match='^library_' + ('unavailable' if missing else 'version') + '$'):
        build(support)


def test_media_builder_never_uses_library_file_writer(support, sample, monkeypatch):
    library, _ = media._library()
    monkeypatch.setattr(library.PyCdlib, 'write', lambda *a, **k: pytest.fail('file writer called'))
    assert build(support).image == sample.image


@pytest.mark.parametrize('kind', ['extra', 'missing', 'content'])
def test_real_namespace_auditor_rejects_inconsistent_author_output(support, sample, kind):
    library, _ = media._library()
    expected = handoff(support).files()
    iso = library.PyCdlib()
    iso.new(vol_ident='CIDATA', rock_ridge='1.09', joliet=3)
    buffers = []
    try:
        for name, alias in media._LAYOUT:
            if kind == 'missing' and name == 'network-config':
                continue
            data = b'X' * len(expected[name]) if kind == 'content' and name == 'meta-data' else expected[name]
            stream = io.BytesIO(data)
            buffers.append(stream)
            iso.add_fp(stream, len(data), iso_path=alias, rr_name=name, joliet_path='/' + name, file_mode=0o100444)
        if kind == 'extra':
            stream = io.BytesIO(b'extra')
            buffers.append(stream)
            iso.add_fp(stream, 5, iso_path='/EXTRA.;1', rr_name='extra', joliet_path='/extra', file_mode=0o100444)
        output = io.BytesIO()
        iso.write_fp(output)
        raw = output.getvalue()
    finally:
        iso.close()
    with pytest.raises(media.NativeMediaRefused):
        media._audit_views(raw, expected)


@pytest.mark.parametrize('phase', ['build', 'inspect'])
def test_codec_close_uncertainty_does_not_return_verified_media(support, sample, monkeypatch, phase):
    library, dates = media._library()
    original = library.PyCdlib
    closes = []

    class CloseUnknown:
        def __init__(self):
            self.inner = original()

        def __getattr__(self, name):
            return getattr(self.inner, name)

        def close(self):
            closes.append(1)
            self.inner.close()
            raise OSError('SYNTHETIC_CANARY')

    monkeypatch.setattr(media, '_library', lambda: (SimpleNamespace(PyCdlib=CloseUnknown), dates))
    with pytest.raises(media.NativeMediaUnknown, match='^image_close_unknown$') as error:
        if phase == 'build':
            media._canonical_image(handoff(support).files())
        else:
            media._audit_views(sample.image, handoff(support).files())
    assert len(closes) == 1 and 'SYNTHETIC_CANARY' not in str(error.value)


def test_buffers_refuse_growth_instead_of_returning_partial_image():
    with media._BoundedBuffer(3) as output:
        assert output.write(b'abc') == 3
        with pytest.raises(media.NativeMediaRefused, match='^buffer_bound$'):
            output.write(b'x')
        assert output.getvalue() == b'abc'


@pytest.mark.parametrize('field,value', [('sha256', '0' * 64), ('size_bytes', True), ('files', ()),
                                       ('payload_sha256', 'X' * 64)])
def test_descriptor_rejects_incoherent_local_fields(sample, field, value):
    with pytest.raises(media.NativeMediaRefused, match='^descriptor_context$'):
        replace(sample, **{field: value}).review_bytes()


def test_descriptor_size_failure_is_not_a_native_receipt(sample, monkeypatch):
    monkeypatch.setattr(media, 'MAX_DESCRIPTOR_BYTES', 1)
    with pytest.raises(media.NativeMediaRefused, match='^descriptor_bound$'):
        sample.review_bytes()


def test_media_candidate_stays_out_of_public_and_installed_inspection_bundle():
    from night_shifts.bootstrap_probe_seed import SOURCE_FILES
    from night_shifts.inspection_bundle import bundle_bytes
    assert 'bootstrap_native_media.py' not in SOURCE_FILES
    with zipfile.ZipFile(io.BytesIO(bundle_bytes())) as archive:
        assert 'night_shifts/bootstrap_native_media.py' not in archive.namelist()
