from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from night_shifts import gate_a_install_bundle as bundle
from night_shifts import gate_a_installed as installed
from night_shifts import gate_a_task
from night_shifts.gate_a_run import GateAError


def _archive(path: Path, files: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, 'w') as target:
        for name, data in files.items():
            target.writestr(name, data)
    return path


def test_build_isolated_bundle_from_fixed_sources(tmp_path: Path):
    runtime = _archive(tmp_path / 'embed.zip', dict.fromkeys(bundle._PYTHON_REQUIRED, b'inert') | {
        'python314._pth': b'import site\n',
    })
    wheels = {name: _archive(tmp_path / f'{name}-1.0-py3-none-any.whl', {roots[0] + '/__init__.py': b''})
              for name, roots in bundle._WHEELS.items()}
    output = tmp_path / 'bundle.zip'
    digest = bundle.build_bundle(output, runtime, wheels)
    assert hashlib.sha256(output.read_bytes()).hexdigest() == digest
    with zipfile.ZipFile(output) as result:
        assert result.read('python/python314._pth') == bundle._PYTHON_PATH
        assert b'import site' not in bundle._PYTHON_PATH
        assert 'app/night_shifts/gate_a_installed.py' in result.namelist()
        assert 'app/tests/night_shifts/test_hyperv_real_host.py' in result.namelist()
        assert 'app/gate-a-pytest.ini' in result.namelist()
        assert 'app/.env' not in result.namelist()
    with pytest.raises(FileExistsError):
        bundle.build_bundle(output, runtime, wheels)


@pytest.mark.parametrize('name', ['../outside.py', 'pytest/.hidden', 'C:/evil.py', 'pytest/COM1.py',
                                 'pytest/loader.pth', 'pytest/hook.dll'])
def test_wheel_refuses_escaping_and_startup_payloads(tmp_path: Path, name: str):
    archive = _archive(tmp_path / 'pytest-1.0-py3-none-any.whl', {name: b''})
    with pytest.raises(ValueError):
        bundle._wheel('pytest', archive)


@pytest.mark.parametrize(('outcome', 'published'), [('passed', 'passed'), ('cleanup_unknown', 'cleanup_unknown'),
                                                    ('raise', 'running_or_unknown')])
def test_runner_writes_start_receipt_before_host_work_and_refuses_uncertain_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, outcome: str, published: str,
):
    runs = tmp_path / 'runs'
    runs.mkdir()
    latest = runs / 'latest.json'
    calls: list[Path] = []

    def execute():
        initial = json.loads(latest.read_text(encoding='utf-8'))
        assert initial['status'] == 'running_or_unknown'
        assert initial['image_sha256'] == installed.IMAGE_SHA256
        calls.append(Path(initial['run_dir']))
        if outcome == 'raise':
            raise RuntimeError('injected failure')
        return {'status': outcome, 'seconds': 1.0, 'cases': {}, 'leftovers': None}

    def factory(config, **kwargs):
        assert config.base_image == tmp_path / 'base.vhdx'
        assert config.base_image_sha256 == installed.IMAGE_SHA256
        assert config.workspace_root == runs
        return SimpleNamespace(run_dir=runs / 'gate-a-fake', execute=execute)

    monkeypatch.setattr(installed, 'GateARun', factory)
    assert installed._installed_runner(tmp_path) == (0 if outcome == 'passed' else 1)
    assert gate_a_task.status(tmp_path)['status'] == published
    if outcome != 'passed':
        with pytest.raises(GateAError, match='no automatic retry'):
            installed._installed_runner(tmp_path)
        assert len(calls) == 1


def test_protected_pytest_ignores_ambient_configuration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    observed: list[str] = []

    def fake(argv, timeout, env):
        observed.extend(argv)
        return subprocess.CompletedProcess(argv, 0, '', '')

    monkeypatch.setattr(installed, '_run', fake)
    run = installed._fixed_child_runner(tmp_path)
    run([sys.executable, '-m', 'pytest'], 1, {})
    assert observed == [sys.executable, '-I', '-B', '-m', 'pytest', '-c', str(tmp_path / 'app/gate-a-pytest.ini'),
                        '--noconftest']


def test_client_dispatches_one_fixed_task_and_does_not_claim_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    calls: list[list[str]] = []

    def fake(argv, **kwargs):
        calls.append(argv)
        assert kwargs['timeout'] == 10
        return subprocess.CompletedProcess(argv, 0, 'accepted', '')

    monkeypatch.setattr(gate_a_task, 'windows_directory', lambda: tmp_path / 'Windows')
    monkeypatch.setattr(gate_a_task.subprocess, 'run', fake)
    assert gate_a_task.start(tmp_path)['status'] == 'submitted'
    assert calls == [[str(tmp_path / 'Windows/System32/schtasks.exe'), '/Run', '/TN', r'\AiAgentGateA']]
    (tmp_path / 'runs').mkdir()
    (tmp_path / 'runs' / 'latest.json').write_text('{"status":"running_or_unknown"}', encoding='ascii')
    assert gate_a_task.start(tmp_path)['status'] == 'not_submitted'
    assert len(calls) == 1
