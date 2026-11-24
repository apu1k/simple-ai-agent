from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from night_shifts.backends.hyperv import HyperVError
from night_shifts.gate_a_cleanup import cleanup_run
from night_shifts.gate_a_run import GateAError, gate_a_run_lease

SID = 'b' * 32


@pytest.fixture
def run(tmp_path: Path) -> Path:
    run_dir = tmp_path / ('gate-a-' + 'a' * 32)
    run_dir.mkdir()
    base = run_dir / 'base.vhdx'
    base.write_bytes(b'passing base image')
    (run_dir / 'test-evidence.log').write_text('preserve this')
    (run_dir / 'report.json').write_text(json.dumps({
        'run_dir': str(run_dir), 'status': 'running', 'base_image': str(base),
        'base_image_sha256': '1' * 64, 'preexisting_sandbox_vms': ['night-shift-' + 'c' * 32],
    }), encoding='utf-8')
    (run_dir / 'sandboxes').mkdir()
    return run_dir


class FakeHost:
    def __init__(self, *, fail: bool = False, leave_disk: bool = False):
        self.fail = fail
        self.leave_disk = leave_disk
        self.calls: list[tuple[str, ...]] = []

    def run(self, script: Path, arguments: Sequence[str]) -> str:
        assert script.name == 'recover_gate_a_sandbox.ps1'
        self.calls.append(tuple(arguments))
        if self.fail:
            raise HyperVError('host outcome unknown')
        if '-Apply' not in arguments:
            return 'disk_candidate'
        disk = Path(arguments[1]) / 'worker.vhdx'
        if not self.leave_disk:
            disk.unlink(missing_ok=True)
        return 'verified'


def test_preview_is_read_only_then_apply_removes_only_the_sandbox(run: Path):
    workspace = run / 'sandboxes' / SID
    (workspace / 'vm-config' / 'Virtual Machines').mkdir(parents=True)
    disk = workspace / 'worker.vhdx'
    disk.write_bytes(b'copy-on-write disk')
    report_before = (run / 'report.json').read_bytes()
    host = FakeHost()

    preview = cleanup_run(run, apply=False, runner=host)
    assert preview['sandboxes'] == {SID: {'status': 'disk_candidate'}}
    assert disk.exists() and not (run / '.gate-a.lock').exists()
    cleaned = cleanup_run(run, apply=True, runner=host)
    assert cleaned['status'] == 'clean' and cleaned['sandboxes'] == {SID: {'status': 'clean'}}
    assert not workspace.exists()
    assert (run / 'base.vhdx').read_bytes() == b'passing base image'
    assert (run / 'test-evidence.log').read_text() == 'preserve this'
    assert (run / 'report.json').read_bytes() == report_before


def test_active_run_lease_blocks_apply(run: Path):
    host = FakeHost()
    with gate_a_run_lease(run), pytest.raises(GateAError, match='locked'):
        cleanup_run(run, apply=True, runner=host)
    assert host.calls == []


def test_preexisting_vm_and_unexpected_entry_are_not_touched(run: Path):
    known = run / 'sandboxes' / ('c' * 32)
    known.mkdir()
    unknown = run / 'sandboxes' / 'operator-notes'
    unknown.write_text('keep')
    host = FakeHost()
    result = cleanup_run(run, apply=True, runner=host)
    assert result['status'] == 'review_needed'
    assert known.exists() and unknown.read_text() == 'keep' and not host.calls


def test_report_vm_is_checked_even_when_its_folder_is_gone(run: Path):
    report = run / 'report.json'
    data = json.loads(report.read_text())
    data['leftovers'] = {'new_vms': ['night-shift-' + SID]}
    report.write_text(json.dumps(data), encoding='utf-8')
    host = FakeHost()
    assert cleanup_run(run, apply=True, runner=host)['status'] == 'clean'
    assert [call[1] for call in host.calls] == [str(run / 'sandboxes' / SID)]


@pytest.mark.parametrize('mode', ['unexpected_file', 'linked_disk', 'native_failure', 'disk_still_present',
                                 'config_file_remains'])
def test_uncertain_or_unsafe_workspace_is_not_removed(run: Path, mode: str):
    workspace = run / 'sandboxes' / SID
    workspace.mkdir()
    disk = workspace / 'worker.vhdx'
    if mode == 'linked_disk':
        disk.hardlink_to(run / 'base.vhdx')
    else:
        disk.write_bytes(b'disk')
    if mode == 'unexpected_file':
        (workspace / 'unexpected.txt').write_text('keep')
    if mode == 'config_file_remains':
        (workspace / 'vm-config').mkdir()
        (workspace / 'vm-config' / 'unknown.bin').write_text('keep')
    host = FakeHost(fail=mode == 'native_failure', leave_disk=mode == 'disk_still_present')
    assert cleanup_run(run, apply=True, runner=host)['status'] == 'review_needed'
    assert workspace.exists()
    if mode in {'unexpected_file', 'linked_disk'}:
        assert disk.exists() and not host.calls
    if mode == 'config_file_remains':
        assert (workspace / 'vm-config' / 'unknown.bin').read_text() == 'keep'


def test_missing_baseline_does_not_authorize_deletion(run: Path):
    (run / 'sandboxes' / SID).mkdir()
    report = run / 'report.json'
    data = json.loads(report.read_text())
    del data['preexisting_sandbox_vms']
    report.write_text(json.dumps(data), encoding='utf-8')
    host = FakeHost()
    with pytest.raises(GateAError, match='invalid VM inventory'):
        cleanup_run(run, apply=True, runner=host)
    assert host.calls == []
