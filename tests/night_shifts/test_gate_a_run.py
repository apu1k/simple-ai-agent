from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from night_shifts import gate_a_run as gate
from night_shifts.guest import finalize_image_copy as cleanup
from night_shifts.guest import wsl_finalize_copy as helper

ARTIFACTS = {'etc/night-shift-diagnostic-027/operation.json': 'a' * 64}
VM_A = 'night-shift-' + 'a' * 32
VM_B = 'night-shift-' + 'b' * 32


@pytest.mark.skipif(not hasattr(__import__('ctypes'), 'windll'), reason='Windows only')
def test_host_environment_fills_stripped_launcher_env() -> None:
    env: dict[str, str] = {}
    gate.ensure_host_environment(env)
    assert env['COMPUTERNAME'] and env['SystemRoot'] == env['WINDIR']
    parts = [p.lower() for p in env['PATH'].split(';')]
    assert any(p.endswith('system32\\windowspowershell\\v1.0') for p in parts)
    assert any(p.endswith('system32') for p in parts)
    before = env['PATH']
    gate.ensure_host_environment(env)
    assert env['PATH'] == before  # idempotent


def _done(argv, code: int = 0, out: str = '', err: str = '') -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(list(argv), code, out, err)


class FakeHost:
    def __init__(self, *, helper_status: str = 'success', detach: bool = True,
                 pytest_codes: dict[str, int] | None = None, leave_vm: bool = False):
        self.helper_status = helper_status
        self.detach = detach
        self.pytest_codes = pytest_codes or {}
        self.leave_vm = leave_vm
        self.attached: Path | None = None
        self.calls: list[list[str]] = []
        self.vms = {'night-shift-diagnostic', VM_A}

    def __call__(self, argv, timeout, env):
        argv = list(argv)
        self.calls.append(argv)
        if argv[:2] == ['wsl.exe', '--mount']:
            self.attached = Path(argv[3])
            return _done(argv)
        if argv[:2] == ['wsl.exe', '--unmount']:
            if self.detach:
                self.attached = None
            return _done(argv)
        if '/usr/bin/lsblk' in argv:
            disks = [{'path': '/dev/sda', 'type': 'disk'}]
            if self.attached is not None:
                disks.append({'path': '/dev/sdd', 'type': 'disk'})
            return _done(argv, out=json.dumps({'blockdevices': disks}))
        if '/usr/bin/python3' in argv:
            assert argv[argv.index('--device') + 1] == '/dev/sdd'
            assert self.attached is not None
            self.attached.write_bytes(b'cleaned image')
            receipt = {'status': self.helper_status, 'unmounted': True}
            return _done(argv, 0 if self.helper_status == 'success' else 1, json.dumps(receipt) + '\n')
        if argv[0] == 'powershell.exe':
            return _done(argv, out='\n'.join(sorted(self.vms)) + '\n')
        if 'pytest' in argv:
            assert env['NIGHT_SHIFT_HYPERV_INTEGRATION'] == '1'
            case = argv[argv.index('pytest') + 1].split('::')[1]
            if self.leave_vm:
                self.vms.add(VM_B)
            code = self.pytest_codes.get(case, 0)
            return _done(argv, code, '1 passed in 1.00s\n' if code == 0 else '1 failed in 1.00s\n')
        raise AssertionError(argv)


def _config(tmp_path: Path, **overrides) -> gate.GateAConfig:
    source = tmp_path / 'source.vhdx'
    source.write_bytes(b'diagnostic image')
    profile = tmp_path / 'profile.json'
    profile.write_text(json.dumps(ARTIFACTS))
    values = dict(workspace_root=tmp_path / 'work', source=source,
                  source_sha256=hashlib.sha256(b'diagnostic image').hexdigest(), profile=profile)
    values.update(overrides)
    return gate.GateAConfig(**values)


def test_full_run_cleans_copy_detaches_and_runs_every_case(tmp_path: Path):
    host = FakeHost()
    report = gate.GateARun(_config(tmp_path), runner=host).execute()

    assert report['status'] == 'passed', report
    assert report['wsl_detach'] == 'verified'
    assert report['base_image_sha256'] == hashlib.sha256(b'cleaned image').hexdigest()
    assert list(report['cases']) == list(gate.CASES)
    assert report['leftovers'] == {'inventory': 'ok', 'new_vms': [], 'sandbox_dirs': []}
    assert (tmp_path / 'source.vhdx').read_bytes() == b'diagnostic image'
    stage = Path(report['run_dir']) / 'wsl'
    request = json.loads((stage / 'request.json').read_bytes())
    assert request['mode'] == 'finalize' and request['artifacts'] == ARTIFACTS
    assert all(b'\r' not in (stage / name).read_bytes() for name in gate.STAGED)
    assert json.loads(Path(report['run_dir'], 'report.json').read_text())['status'] == 'passed'


def test_cleanup_failure_still_detaches_and_skips_hyperv(tmp_path: Path):
    host = FakeHost(helper_status='failed')
    report = gate.GateARun(_config(tmp_path), runner=host).execute()

    assert report['status'] == 'failed'
    assert report['wsl_detach'] == 'verified'
    assert ['wsl.exe', '--unmount'] in [c[:2] for c in host.calls]
    assert not any('pytest' in c for c in host.calls)


def test_unverified_detach_reports_cleanup_unknown(tmp_path: Path):
    host = FakeHost(detach=False)
    report = gate.GateARun(_config(tmp_path), runner=host).execute()

    assert report['status'] == 'cleanup_unknown'
    assert not any('pytest' in c for c in host.calls)


def test_wrong_source_digest_never_attaches(tmp_path: Path):
    host = FakeHost()
    report = gate.GateARun(_config(tmp_path, source_sha256='0' * 64), runner=host).execute()

    assert report['status'] == 'failed'
    assert not any(c[:2] == ['wsl.exe', '--mount'] for c in host.calls)


def test_first_failure_stops_remaining_cases(tmp_path: Path):
    host = FakeHost(pytest_codes={gate.CASES[1]: 1})
    report = gate.GateARun(_config(tmp_path), runner=host).execute()

    assert report['status'] == 'failed'
    assert report['cases'][gate.CASES[0]]['result'] == 'passed'
    assert report['cases'][gate.CASES[1]]['result'] == 'failed'
    assert all(report['cases'][c]['result'] == 'not_started' for c in gate.CASES[2:])


def test_new_sandbox_vm_after_tests_is_cleanup_unknown(tmp_path: Path):
    host = FakeHost(leave_vm=True)
    report = gate.GateARun(_config(tmp_path), runner=host).execute()

    assert report['status'] == 'cleanup_unknown'
    assert report['leftovers']['new_vms'] == [VM_B]
    assert report['preexisting_sandbox_vms'] == [VM_A]


def test_deadline_leaves_cases_unstarted(tmp_path: Path):
    image = tmp_path / 'base.vhdx'
    image.write_bytes(b'cleaned image')
    config = gate.GateAConfig(workspace_root=tmp_path / 'work', base_image=image,
                              base_image_sha256=hashlib.sha256(b'cleaned image').hexdigest(),
                              deadline_seconds=100, case_budget_seconds=300)
    host = FakeHost()
    report = gate.GateARun(config, runner=host).execute()

    assert report['status'] == 'incomplete'
    assert {c['reason'] for c in report['cases'].values()} == {'deadline'}
    assert not any(c[:1] == ['wsl.exe'] for c in host.calls)


def test_interrupted_case_is_cleanup_unknown(tmp_path: Path):
    host = FakeHost()

    def runner(argv, timeout, env):
        if 'pytest' in argv:
            raise subprocess.TimeoutExpired(argv, timeout, output='partial')
        return host(argv, timeout, env)

    report = gate.GateARun(_config(tmp_path), runner=runner).execute()
    assert report['status'] == 'cleanup_unknown'
    assert report['cases'][gate.CASES[0]]['result'] == 'interrupted'


@pytest.mark.parametrize('overrides', [
    {'source': None},
    {'base_image': Path('C:/x.vhdx'), 'base_image_sha256': 'a' * 64},
    {'profile': None},
    {'source_sha256': 'ABC'},
    {'cases': ('test_unknown',)},
    {'distro': 'Ubuntu; rm'},
])
def test_config_rejects_ambiguous_or_invalid_input(tmp_path: Path, overrides):
    with pytest.raises(ValueError):
        _config(tmp_path, **overrides)


def test_wsl_path_conversion():
    assert gate.wsl_path(Path('D:/NightShift/gate-a/run_1')) == '/mnt/d/NightShift/gate-a/run_1'
    for bad in ('relative/path', 'D:/has space/x', "D:/quote'x"):
        with pytest.raises(gate.GateAError):
            gate.wsl_path(Path(bad))


def test_new_disk_requires_exactly_one_addition():
    assert gate.new_disk({'/dev/sda'}, {'/dev/sda', '/dev/sdd'}) == '/dev/sdd'
    for after in ({'/dev/sda'}, {'/dev/sda', '/dev/sdd', '/dev/sde'}, {'/dev/sdd'}):
        with pytest.raises(gate.GateAError):
            gate.new_disk({'/dev/sda'}, after)


def _tree(device: str = '/dev/sdd', size: int = helper.DISK_BYTES, mounted: str | None = None):
    return {'blockdevices': [{
        'path': device, 'type': 'disk', 'size': size, 'fstype': None, 'mountpoints': [None],
        'children': [
            {'path': device + '1', 'type': 'part', 'fstype': 'vfat', 'mountpoints': [None]},
            {'path': device + '2', 'type': 'part', 'fstype': 'ext4', 'mountpoints': [mounted]},
        ],
    }]}


def test_helper_layout_accepts_only_expected_unmounted_disk():
    assert helper.check_layout(_tree(), '/dev/sdd') == '/dev/sdd2'
    for tree, device in ((_tree(size=10), '/dev/sdd'), (_tree(mounted='/mnt/x'), '/dev/sdd'),
                         (_tree(), '/dev/sde'), (_tree(device='/dev/nvme0n1'), '/dev/nvme0n1')):
        with pytest.raises(cleanup.FinalizationError):
            helper.check_layout(tree, device)
