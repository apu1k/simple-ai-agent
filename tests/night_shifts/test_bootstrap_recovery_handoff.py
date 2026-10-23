"""Offline bytes and synthetic native-phase traces ONLY; no VM/daemon/tools.

All package pins are explicitly substituted in parser fixtures. AppArmor parser,
kernel policy transition, mounts, chroot, unshare, setpriv and cloud-init are NOT
executed. These tests establish ordering/refusal, not native compatibility.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import stat
import subprocess
from types import SimpleNamespace

import pytest

from night_shifts import bootstrap_probe_seed as seed
from night_shifts import bootstrap_recovery_handoff as handoff
from night_shifts.guest import bootstrap_recovery_launcher as launcher
from night_shifts.maintenance_tls_prototype import AttemptBinding


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture
def support(monkeypatch):
    copying, gpl, daemon = b'C' * 496, b'G' * 18729, b'SYNTHETIC_NOT_EXECUTABLE'
    monkeypatch.setattr(seed, 'COPYING_SHA256', sha(copying))
    monkeypatch.setattr(seed, 'GPL_SHA256', sha(gpl))
    monkeypatch.setattr(seed, 'DAEMON_BYTES', len(daemon))
    monkeypatch.setattr(seed, 'DAEMON_SHA256', sha(daemon))
    monkeypatch.setattr(seed, 'extract_reviewed_daemon', lambda package: daemon)
    binding = AttemptBinding('1' * 32, '00000000-0000-4000-8000-000000000001')
    raw = seed.build_public_probe_seed(binding, b'SYNTHETIC', copying=copying, gpl=gpl)
    entries = seed.validate_public_probe_seed(raw, binding, expected_sha256=sha(raw))
    context = dict(attempt_id=binding.attempt_id, vm_id=binding.vm_id, seed_sha256=sha(raw),
                   policy_sha256=sha(entries[handoff.POLICY_ENTRY]))
    return binding, raw, entries, context


def render(support):
    binding, raw, entries, context = support
    return handoff.render_recovery_handoff(binding, raw, expected_seed_sha256=sha(raw))


def test_deterministic_credential_free_files_and_list_argv(support):
    a, b = render(support), render(support)
    assert a == b
    assert set(a.files()) == {'user-data', 'meta-data', 'network-config', 'support.zip'}
    assert a.support_zip == support[1]
    assert a.user_data.startswith(b'#cloud-config\n')
    cloud = json.loads(a.user_data.split(b'\n', 1)[1])
    assert cloud['users'] == []
    assert cloud['disable_root'] is True and cloud['ssh_pwauth'] is False
    assert cloud['package_update'] is cloud['package_upgrade'] is False
    assert not ({'autoinstall', 'storage', 'write_files', 'packages', 'bootcmd'} & cloud.keys())
    assert len(cloud['runcmd']) == 1
    command = cloud['runcmd'][0]
    assert command[:5] == ['/usr/bin/python3.12', '-I', '-B', '-S', '-c']
    assert len(command) == 6 and len(command[5].encode()) <= handoff.MAX_COMMAND_BYTES
    compile(command[5], '<synthetic-handoff>', 'exec')
    assert len(a.user_data) <= handoff.MAX_USER_DATA
    assert json.loads(a.network_config) == {'version': 2, 'ethernets': {}}
    assert json.loads(a.meta_data)['instance-id'] == 'night-shift-bootstrap-' + support[0].attempt_id


def test_external_seed_pin_before_launcher_snapshot(support, monkeypatch):
    monkeypatch.setattr(handoff, '_launcher_source', lambda: pytest.fail('must refuse before source'))
    with pytest.raises(seed.ProbeSeedRefused, match='^seed_digest$'):
        handoff.render_recovery_handoff(support[0], support[1], expected_seed_sha256='0' * 64)


def test_argument_limit_is_enforced_not_silently_truncated(support, monkeypatch):
    monkeypatch.setattr(handoff, '_launcher_source', lambda: b'#' * 100000)
    with pytest.raises(handoff.RecoveryHandoffRefused, match='^command_bound$'):
        render(support)


def test_embedded_boot_error_has_only_fixed_public_summary(support, monkeypatch):
    # Executing this known synthetic function is NOT executing the real launcher.
    monkeypatch.setattr(handoff, '_launcher_source', lambda: b'def boot(*a, **k):\n raise RuntimeError("CANARY")\n')
    command = json.loads(render(support).user_data.split(b'\n', 1)[1])['runcmd'][0][-1]
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout), pytest.raises(SystemExit) as error:
        exec(compile(command, '<synthetic-only>', 'exec'), {})
    assert error.value.code == 1
    assert json.loads(stdout.getvalue()) == {'outcome': 'unknown', 'reason': 'recovery_boot_unknown'}
    assert 'CANARY' not in stdout.getvalue()


@pytest.mark.parametrize('change', [
    {'attempt_id': 'bad'}, {'vm_id': 'BAD'}, {'vm_id': '00000000-0000-0000-0000-000000000000'},
    {'seed_sha256': 'g' * 64}, {'policy_sha256': 'A' * 64}, {'extra': 'CANARY'},
])
def test_context_refuses_commands_or_noncanonical_identities(support, change):
    with pytest.raises(launcher.RecoveryLaunchRefused, match='^context$'):
        launcher.check_context({**support[3], **change})


@pytest.mark.parametrize('deadline', ['nan', 'inf', '-1', '999999999999999999999'])
def test_internal_budget_refuses_invalid_or_unbounded_deadline(support, deadline):
    with pytest.raises(launcher.RecoveryLaunchRefused, match='^context$'):
        launcher.check_context({**support[3], 'deadline': deadline}, internal=True)


def test_full_seed_pin_precedes_zip_open(support, monkeypatch):
    monkeypatch.setattr(launcher, 'zipfile', SimpleNamespace(ZipFile=lambda *a: pytest.fail('must not parse')))
    with pytest.raises(launcher.RecoveryLaunchRefused, match='^digest$'):
        launcher._policy(b'CANARY', support[3])


def test_independent_policy_pin_is_also_required(support):
    with pytest.raises(launcher.RecoveryLaunchRefused, match='^digest$'):
        launcher._policy(support[1], {**support[3], 'policy_sha256': '0' * 64})


def internal(context):
    return {**context, 'deadline': str(launcher.time.monotonic() + 70)}


@pytest.mark.parametrize('worker', [False, True])
def test_native_command_has_no_shell_input_or_unbounded_capture(support, monkeypatch, worker):
    calls = []

    def run(args, **options):
        calls.append((args, options))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(launcher, 'subprocess', SimpleNamespace(run=run, DEVNULL=subprocess.DEVNULL,
                                                             TimeoutExpired=subprocess.TimeoutExpired))
    launcher._command(['/usr/bin/mount', '--bind', '/usr', '/fixed-root/usr'], internal(support[3]), worker=worker)
    args, options = calls[0]
    assert 'shell' not in options
    assert options['stdin'] == options['stderr'] == subprocess.DEVNULL
    assert options['stdout'] is None if worker else options['stdout'] == subprocess.DEVNULL
    assert options['close_fds'] is True and options['cwd'] == '/'
    assert options['env'] == {'PATH': '/usr/bin:/usr/sbin', 'LANG': 'C', 'LC_ALL': 'C'}
    assert 0 < options['timeout'] <= (70 if worker else 3)


@pytest.mark.parametrize('kind', ['timeout', 'spawn', 'nonzero'])
def test_command_uncertainty_has_no_retry_or_raw_exception(support, monkeypatch, kind):
    calls = []

    def run(*a, **k):
        calls.append(True)
        if kind == 'timeout':
            raise subprocess.TimeoutExpired('CANARY', 1)
        if kind == 'spawn':
            raise OSError('CANARY')
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(launcher, 'subprocess', SimpleNamespace(run=run, DEVNULL=subprocess.DEVNULL,
                                                             TimeoutExpired=subprocess.TimeoutExpired))
    with pytest.raises(launcher.RecoveryLaunchUnknown) as error:
        launcher._command(['/usr/bin/mount'], internal(support[3]))
    assert calls == [True] and 'CANARY' not in str(error.value)


@pytest.fixture
def boot_model(support, monkeypatch):
    calls = []
    policy = support[2][handoff.POLICY_ENTRY]
    monkeypatch.setattr(launcher, '_early_checks', lambda c: calls.append('early'))
    monkeypatch.setattr(launcher, '_read', lambda p, n: b'5\n' if p.endswith('/device/type') else support[1])
    monkeypatch.setattr(launcher, '_new', lambda p, b, *a: calls.append(('new', p, b)))
    monkeypatch.setattr(launcher, '_command', lambda a, c, **k: calls.append(('command', a, k)))
    monkeypatch.setattr(launcher, 'os', SimpleNamespace(
        umask=lambda n: calls.append(('umask', n)),
        mkdir=lambda p, m: calls.append(('mkdir', p, m)),
        path=SimpleNamespace(realpath=lambda p: '/dev/sr1'),
        stat=lambda p: SimpleNamespace(st_mode=stat.S_IFBLK | 0o600)))
    return calls, policy


def test_boot_checks_then_fixed_optical_parse_add_unshare_order(support, boot_model):
    calls, policy = boot_model
    launcher.boot(support[3], trusted_source=b'# trusted synthetic source\n')
    assert calls[0] == 'early'
    commands = [c[1] for c in calls if isinstance(c, tuple) and c[0] == 'command']
    assert commands[0] == ['/usr/bin/mount', '-t', 'iso9660', '-o', 'ro,nodev,nosuid,noexec',
                            '/dev/sr1', launcher.STAGE + '/media']
    assert commands[1] == ['/usr/sbin/apparmor_parser', '-Q', '-K', launcher.STAGE + '/profile']
    assert commands[2] == ['/usr/sbin/apparmor_parser', '-a', '-K', launcher.STAGE + '/profile']
    assert commands[3][:6] == ['/usr/bin/unshare', '--mount', '--net', '--propagation', 'private',
                               '/usr/bin/python3.12']
    assert ('new', launcher.STAGE + '/profile', policy) in calls
    assert all('--replace' not in c and '-r' not in c for c in commands)


def test_early_refusal_before_any_mutation(support, boot_model, monkeypatch):
    calls, policy = boot_model

    def refuse(_):
        raise launcher.RecoveryLaunchRefused('target_disk')

    monkeypatch.setattr(launcher, '_early_checks', refuse)
    with pytest.raises(launcher.RecoveryLaunchRefused, match='^target_disk$'):
        launcher.boot(support[3], trusted_source=b'# source')
    assert calls == []


def test_existing_stage_is_terminal_not_reused(support, boot_model, monkeypatch):
    calls, policy = boot_model

    def collide(*a):
        raise FileExistsError('CANARY')

    monkeypatch.setattr(launcher.os, 'mkdir', collide)
    with pytest.raises(FileExistsError):
        launcher.boot(support[3], trusted_source=b'# source')
    assert not any(isinstance(c, tuple) and c[0] in ('new', 'command') for c in calls)


def test_namespace_root_is_new_ram_readonly_with_bounded_privilege_drop(support, monkeypatch):
    calls = []
    monkeypatch.setattr(launcher, 'sys', SimpleNamespace(platform='linux'))
    monkeypatch.setattr(launcher, '_read', lambda p, n: support[1] if p.endswith('support.zip') else b'# source')
    monkeypatch.setattr(launcher, '_new', lambda p, b: calls.append(('new', p)))
    monkeypatch.setattr(launcher, '_command', lambda a, c, **k: calls.append(('command', a)))
    monkeypatch.setattr(launcher, 'os', SimpleNamespace(
        geteuid=lambda: 0, readlink=lambda p: p,
        mkdir=lambda p, m: calls.append(('mkdir', p)),
        symlink=lambda t, p: calls.append(('symlink', p)),
        chroot=lambda p: calls.append(('chroot', p)), chdir=lambda p: calls.append(('chdir', p))))
    launcher.namespace(internal(support[3]))
    commands = [v for k, v in calls if k == 'command']
    assert commands[0][:3] == ['/usr/bin/mount', '-t', 'tmpfs']
    assert 'rw,nodev,nosuid,noexec,size=16M,mode=0755' in commands[0]
    assert commands[-2] == ['/usr/bin/mount', '-o', 'remount,ro,nodev,nosuid,noexec', launcher.STAGE + '/root']
    assert commands[-1][:8] == ['/usr/bin/setpriv', '--bounding-set=-all', '--inh-caps=-all',
                                '--ambient-caps=-all', '--no-new-privs', '--reuid=0', '--regid=0', '--clear-groups']
    assert commands[-1][8:14] == ['--', '/usr/bin/python3.12', '-I', '-B', '-S', '/entry.py']
    assert calls.index(('chroot', launcher.STAGE + '/root')) < calls.index(('command', commands[-1]))
    assert all(p.startswith(launcher.STAGE + '/root/') for k, p in calls if k in ('mkdir', 'new', 'symlink'))


def cap_status():
    return ('NoNewPrivs:\t1\n' + ''.join(k + ':\t0000000000000000\n'
            for k in ('CapInh', 'CapPrm', 'CapEff', 'CapBnd', 'CapAmb'))).encode()


@pytest.fixture
def confined_model(support, monkeypatch):
    calls = []
    stdout = io.StringIO()
    monkeypatch.setattr(launcher, 'sys', SimpleNamespace(
        platform='linux', flags=SimpleNamespace(isolated=True, no_site=True), dont_write_bytecode=True,
        modules={}, path=[], stdout=stdout))

    def read(path, limit):
        if path == '/proc/self/status':
            return cap_status()
        if path == '/proc/self/attr/current':
            return (launcher.PROFILE + ' (enforce)\n').encode()
        return support[1]

    monkeypatch.setattr(launcher, '_read', read)
    monkeypatch.setattr(launcher, 'os', SimpleNamespace(
        O_WRONLY=1, O_NOFOLLOW=2, O_CLOEXEC=4,
        open=lambda *a: calls.append('open-profile') or 99,
        write=lambda fd, value: calls.append(value) or len(value), close=lambda fd: calls.append('close-profile')))

    def load(name):
        calls.append(('import', name))
        if name.endswith('maintenance_tls_prototype'):
            return SimpleNamespace(AttemptBinding=AttemptBinding)
        return SimpleNamespace(run_guest_probe=lambda *a, **k: b'{"outcome":"local_published","direct_child_stopped":true}\n')

    monkeypatch.setattr(launcher, 'importlib', SimpleNamespace(import_module=load))
    return calls, stdout


def test_profile_transition_and_full_pin_before_any_seed_import(support, confined_model):
    calls, stdout = confined_model
    launcher.confined(internal(support[3]))
    assert calls[:3] == ['open-profile', b'changeprofile night-shift-kvp-public-probe', 'close-profile']
    assert calls[3:] == [('import', 'night_shifts.maintenance_tls_prototype'),
                         ('import', 'night_shifts.guest.bootstrap_public_probe')]
    assert launcher.sys.path == [launcher.SEED_PATH]
    assert json.loads(stdout.getvalue())['direct_child_stopped'] is True


def test_bad_complete_pin_never_transitions_or_imports(support, confined_model):
    calls, stdout = confined_model
    context = {**internal(support[3]), 'seed_sha256': '0' * 64}
    with pytest.raises(launcher.RecoveryLaunchRefused, match='^digest$'):
        launcher.confined(context)
    assert calls == [] and stdout.getvalue() == ''


def test_remaining_capability_never_imports_or_transitions(support, confined_model, monkeypatch):
    calls, stdout = confined_model
    monkeypatch.setattr(launcher, '_read', lambda *a: cap_status().replace(b'0000000000000000', b'0000000000000001', 1))
    with pytest.raises(launcher.RecoveryLaunchRefused, match='^capabilities$'):
        launcher.confined(internal(support[3]))
    assert calls == []


def test_wrong_profile_has_no_fallback_import(support, confined_model, monkeypatch):
    calls, stdout = confined_model
    original = launcher._read
    monkeypatch.setattr(launcher, '_read', lambda p, n: b'unconfined\n' if p.endswith('/attr/current') else original(p, n))
    with pytest.raises(launcher.RecoveryLaunchRefused, match='^profile_transition$'):
        launcher.confined(internal(support[3]))
    assert not any(isinstance(v, tuple) and v[0] == 'import' for v in calls)


def test_preloaded_application_module_is_not_reused(support, confined_model):
    calls, stdout = confined_model
    launcher.sys.modules['night_shifts'] = object()
    with pytest.raises(launcher.RecoveryLaunchRefused, match='^import_collision$'):
        launcher.confined(internal(support[3]))
    assert not any(isinstance(v, tuple) and v[0] == 'import' for v in calls)


def test_native_entrypoints_refuse_windows_without_native_io(support, monkeypatch):
    monkeypatch.setattr(launcher, 'sys', SimpleNamespace(platform='win32'))
    monkeypatch.setattr(launcher, 'os', SimpleNamespace(open=lambda *a: pytest.fail('native open')))
    for call in (lambda: launcher._read('/CANARY', 1), lambda: launcher._new('/CANARY', b'x'),
                 lambda: launcher._early_checks(support[3]),
                 lambda: launcher.namespace(internal(support[3])),
                 lambda: launcher.confined(internal(support[3]))):
        with pytest.raises(launcher.RecoveryLaunchRefused):
            call()


def test_invalid_phase_prints_no_supplied_argument(support, monkeypatch):
    stdout = io.StringIO()
    monkeypatch.setattr(launcher, 'sys', SimpleNamespace(argv=['launcher.py', '--CANARY', 'CANARY'], stdout=stdout))
    assert launcher.main() == 1
    assert json.loads(stdout.getvalue()) == {'outcome': 'unknown', 'reason': 'recovery_phase_unknown'}
    assert 'CANARY' not in stdout.getvalue()
