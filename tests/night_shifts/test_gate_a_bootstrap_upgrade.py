from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from night_shifts import gate_a_run as gate
from night_shifts.guest import finalize_image_copy as cleanup
from night_shifts.guest import wsl_finalize_copy as helper

ARTIFACTS = {'etc/night-shift-diagnostic-027/operation.json': 'a' * 64}
OLD = b'old guest script\n'
NEW = b'new guest script\n'

# path()/regular() require root-owned directories; Windows reports uid 0.
needs_root_owner = pytest.mark.skipif(
    os.name == 'posix' and getattr(os, 'geteuid', lambda: 0)() != 0,
    reason='needs root-owned files on POSIX',
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_request_pins_installed_bootstrap_and_stages_the_upgrade():
    files = gate.build_request(ARTIFACTS)
    request = json.loads(files['request.json'])
    upgrade = json.loads(files['bootstrap-upgrade.json'])

    assert request['payload']['bootstrap'] == gate.INSTALLED_BOOTSTRAP_SHA256
    assert upgrade == {'from': gate.INSTALLED_BOOTSTRAP_SHA256,
                       'to': _sha(files['protocol_test_bootstrap.py'])}
    assert upgrade['from'] != upgrade['to']  # the image must get the ready handshake


def _image(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / 'root'
    target = root / cleanup.audit._BOOTSTRAP
    target.parent.mkdir(parents=True)
    target.write_bytes(OLD)
    return root, target


@needs_root_owner
def test_replace_bootstrap_swaps_exact_script_and_audits_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root, target = _image(tmp_path)
    audited: list[tuple[str, str]] = []
    monkeypatch.setattr(cleanup.audit, '_payload', lambda b, u: audited.append((b, u)))

    receipt = helper.replace_bootstrap(root, {'from': _sha(OLD), 'to': _sha(NEW)}, NEW, 'c' * 64)

    assert target.read_bytes() == NEW
    assert not target.with_name(target.name + '.new').exists()
    assert audited == [(_sha(NEW), 'c' * 64)]
    assert receipt == {'bootstrap_from': _sha(OLD), 'bootstrap_to': _sha(NEW)}


@needs_root_owner
@pytest.mark.parametrize('upgrade', [
    {'from': '0' * 64, 'to': _sha(NEW)},          # image has a different script
    {'from': _sha(OLD), 'to': '0' * 64},          # staged replacement differs
    {'from': _sha(OLD), 'to': _sha(NEW), 'x': 1},  # unexpected shape
])
def test_replace_bootstrap_refuses_before_writing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, upgrade):
    root, target = _image(tmp_path)
    monkeypatch.setattr(cleanup.audit, '_payload', lambda b, u: pytest.fail('audited a refused swap'))

    with pytest.raises(cleanup.FinalizationError):
        helper.replace_bootstrap(root, upgrade, NEW, 'c' * 64)
    assert target.read_bytes() == OLD
    assert not target.with_name(target.name + '.new').exists()
