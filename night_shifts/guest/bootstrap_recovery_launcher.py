"""Standalone trusted-recovery handoff SOURCE CANDIDATE; no import side effects.

Only stdlib before the complete seed pin is checked. NOT installed/approved to
run. Later authority must pin the whole NoCloud media and actual trusted recovery
boot; matching a guest string, script hash or manifest is not boot attestation.
Native tools/policy transition/confinement require a separately approved Linux
validation. No host/VM operation, installer, target disk, retry or cleanup API.
"""
from __future__ import annotations

import base64
import hashlib
import importlib
import io
import json
import math
import os
import platform
import re
import stat
import subprocess
import sys
import time
import zipfile
from uuid import UUID

STAGE = '/run/night-shift-bootstrap-launch'
PROFILE = 'night-shift-kvp-public-probe'
SEED_PATH = '/run/night-shift-bootstrap/support.zip'
PROFILE_ENTRY = 'night_shifts/guest/bootstrap-public-probe.apparmor'
TOOLS = ('/usr/bin/mount', '/usr/bin/unshare', '/usr/bin/setpriv',
         '/usr/sbin/apparmor_parser', '/usr/bin/python3.12')
MAX_SEED = 512 * 1024
MAX_SOURCE = 64 * 1024
_FIELDS = {'attempt_id', 'vm_id', 'seed_sha256', 'policy_sha256'}


class RecoveryLaunchRefused(RuntimeError):
    """Fixed labels only; no native stderr, guest files or command arguments."""


class RecoveryLaunchUnknown(RecoveryLaunchRefused):
    """A native mutation/execution may have occurred; never retry/repair."""


def check_context(value: object, *, internal: bool = False) -> dict[str, str]:
    if type(value) is not dict or set(value) != _FIELDS | ({'deadline'} if internal else set()):
        raise RecoveryLaunchRefused('context')
    if any(type(v) is not str for v in value.values()):
        raise RecoveryLaunchRefused('context')
    if (re.fullmatch('[0-9a-f]{32}', value['attempt_id']) is None
            or any(re.fullmatch('[0-9a-f]{64}', value[k]) is None
                   for k in ('seed_sha256', 'policy_sha256'))):
        raise RecoveryLaunchRefused('context')
    try:
        vm = UUID(value['vm_id'])
        if not vm.int or str(vm) != value['vm_id']:
            raise ValueError
        if internal:
            deadline = float(value['deadline'])
            if not math.isfinite(deadline) or not 0 < deadline - time.monotonic() <= 75:
                raise ValueError
    except ValueError:
        raise RecoveryLaunchRefused('context') from None
    return dict(value)


def _remaining(context: dict[str, str], maximum: float = 3) -> float:
    left = float(context['deadline']) - time.monotonic()
    if left <= 0:
        raise RecoveryLaunchUnknown('deadline_unknown')
    return min(left, maximum)


def _read(path: str, limit: int) -> bytes:
    if sys.platform != 'linux':
        raise RecoveryLaunchRefused('linux_required')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    try:
        raw = bytearray()
        while True:
            chunk = os.read(fd, limit + 1 - len(raw))
            if not chunk:
                return bytes(raw)
            raw.extend(chunk)
            if len(raw) > limit:
                raise RecoveryLaunchRefused('input_bound')
    finally:
        os.close(fd)


def _new(path: str, raw: bytes, mode: int = 0o400) -> None:
    if sys.platform != 'linux':
        raise RecoveryLaunchRefused('linux_required')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, mode)
    try:
        if os.write(fd, raw) != len(raw):
            raise RecoveryLaunchUnknown('write_unknown')
    finally:
        os.close(fd)
    if _read(path, len(raw)) != raw:
        raise RecoveryLaunchUnknown('write_unknown')


def _command(args: list[str], context: dict[str, str], *, worker: bool = False) -> None:
    # Fixed argv only from the trusted implementation below, no shell/env/PATH
    # discovery. Native tools cannot print raw stdout/stderr. Only trusted worker
    # phases inherit stdout for their bounded PUBLIC summary; no daemon output.
    try:
        result = subprocess.run(
            args, stdin=subprocess.DEVNULL,
            stdout=None if worker else subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env={'PATH': '/usr/bin:/usr/sbin', 'LANG': 'C', 'LC_ALL': 'C'},
            cwd='/', close_fds=True, timeout=_remaining(context, 70 if worker else 3),
        )
    except (OSError, subprocess.TimeoutExpired):
        # Includes process creation without a returned handle and a tool timeout.
        # run() terminating a direct child is NOT resource/VM cleanup evidence.
        raise RecoveryLaunchUnknown('command_unknown') from None
    if result.returncode != 0:
        raise RecoveryLaunchUnknown('worker_unknown' if worker else 'native_change_unknown')


def _digest(raw: bytes, expected: str, maximum: int) -> None:
    if not 0 < len(raw) <= maximum or hashlib.sha256(raw).hexdigest() != expected:
        raise RecoveryLaunchRefused('digest')


def _policy(raw: bytes, context: dict[str, str]) -> bytes:
    # Full seed pin BEFORE even opening the ZIP, and no imports/extractall.
    _digest(raw, context['seed_sha256'], MAX_SEED)
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)) or not 1 <= len(names) <= 32:
                raise RecoveryLaunchRefused('seed_inventory')
            info = archive.getinfo(PROFILE_ENTRY)
            if info.compress_type != zipfile.ZIP_STORED or not 0 < info.file_size <= 8192:
                raise RecoveryLaunchRefused('policy_shape')
            policy = archive.read(info)
    except (zipfile.BadZipFile, KeyError, ValueError):
        raise RecoveryLaunchRefused('seed_inventory') from None
    _digest(policy, context['policy_sha256'], 8192)
    return policy


def _guest_identity(context: dict[str, str]) -> None:
    observed = _read('/sys/class/dmi/id/product_uuid', 128).decode('ascii').strip().lower()
    if str(UUID(observed)) != context['vm_id']:
        raise RecoveryLaunchRefused('guest_vm')


def _early_checks(context: dict[str, str]) -> None:
    if (sys.platform != 'linux' or platform.machine() != 'x86_64'
            or platform.release() != '6.8.0-139-generic' or sys.version_info[:2] != (3, 12)
            or not sys.flags.isolated or not sys.dont_write_bytecode or not sys.flags.no_site):
        raise RecoveryLaunchRefused('recovery_runtime')
    if os.getuid() != 0 or os.geteuid() != 0 or os.getgid() != 0 or os.getegid() != 0:
        raise RecoveryLaunchRefused('recovery_root')
    _guest_identity(context)
    blocks = sorted(os.listdir('/sys/block'))
    if (not blocks or len(blocks) > 64
            or any(re.fullmatch(r'(loop|sr)[0-9]+', n) is None for n in blocks)):
        raise RecoveryLaunchRefused('target_disk')
    # Unconfigured loop devices have no backing_file attribute and may report
    # ro=0 despite exposing no backing storage. Only an actual missing attribute
    # permits that case; permission/read errors must not masquerade as absence.
    for name in blocks:
        base = '/sys/class/block/' + name
        if name.startswith('loop'):
            try:
                backing = _read(base + '/loop/backing_file', 4096)
            except FileNotFoundError:
                continue
            if not backing.strip():
                raise RecoveryLaunchRefused('loop_backing')
        if _read(base + '/ro', 16).strip() != b'1':
            raise RecoveryLaunchRefused('writable_block')
    if sorted(os.listdir('/sys/class/net')) != ['lo']:
        raise RecoveryLaunchRefused('network')
    if _read('/proc/swaps', 4096).decode('ascii').split() != ['Filename', 'Type', 'Size', 'Used', 'Priority']:
        raise RecoveryLaunchRefused('swap')
    # Exact mountpoint, not a containing tmpfs guess; fixed staging is beneath it.
    mount_lines = _read('/proc/self/mountinfo', 131072).decode('ascii').splitlines()
    run = [line.split() for line in mount_lines if len(line.split()) >= 10 and line.split()[4] == '/run']
    if (len(run) != 1 or '\\' in ' '.join(run[0]) or 'rw' not in run[0][5].split(',')
            or run[0][run[0].index('-') + 1] != 'tmpfs'):
        raise RecoveryLaunchRefused('run_not_ram')
    info = os.lstat('/run')
    if not stat.S_ISDIR(info.st_mode) or info.st_uid or info.st_gid or info.st_mode & 0o022:
        raise RecoveryLaunchRefused('run_security')
    if _read('/sys/module/apparmor/parameters/enabled', 16).strip() != b'Y':
        raise RecoveryLaunchRefused('apparmor_unavailable')
    profiles = _read('/sys/kernel/security/apparmor/profiles', 131072).decode('ascii').splitlines()
    if any(line.partition(' ')[0] == PROFILE for line in profiles):
        raise RecoveryLaunchRefused('profile_collision')
    for tool in TOOLS:
        info = os.stat(tool)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid or info.st_gid
                or info.st_mode & 0o022 or not info.st_mode & 0o100):
            raise RecoveryLaunchRefused('tool_security')


def _token(context: dict[str, str]) -> str:
    return base64.b64encode(json.dumps(context, sort_keys=True, separators=(',', ':')).encode('ascii')).decode('ascii')


def boot(context: dict[str, str], *, trusted_source: bytes) -> None:
    """Future NoCloud entry only. Mutates NEW GUEST RAM/policy, never the host.

    Call authority must come from pinned complete media and a fresh reviewed
    diskless VM, not parameters themselves. This function intentionally has no
    convenient CLI, installer or automatic fallback for an ordinary workstation.
    """
    context = check_context(context)
    if type(trusted_source) is not bytes or not 0 < len(trusted_source) <= MAX_SOURCE:
        raise RecoveryLaunchRefused('launcher_source')
    _early_checks(context)  # no writes before early disk/RAM/identity checks
    context['deadline'] = str(time.monotonic() + 70)
    os.umask(0o077)
    os.mkdir(STAGE, 0o700)  # one fresh attempt, never reuse/reset/remove
    for name in ('media', 'root'):
        os.mkdir(STAGE + '/' + name, 0o700)
    # Only the fixed NoCloud optical volume; no arbitrary disk/mount path API.
    optical = os.path.realpath('/dev/disk/by-label/CIDATA')
    if re.fullmatch(r'/dev/sr[0-9]+', optical) is None or not stat.S_ISBLK(os.stat(optical).st_mode):
        raise RecoveryLaunchRefused('support_optical')
    if _read('/sys/class/block/' + optical[5:] + '/device/type', 16).strip() != b'5':
        raise RecoveryLaunchRefused('support_optical')
    _command(['/usr/bin/mount', '-t', 'iso9660', '-o', 'ro,nodev,nosuid,noexec',
              optical, STAGE + '/media'], context)
    raw = _read(STAGE + '/media/support.zip', MAX_SEED)
    policy = _policy(raw, context)
    _new(STAGE + '/profile', policy)
    _new(STAGE + '/launcher.py', trusted_source)
    _command(['/usr/sbin/apparmor_parser', '-Q', '-K', STAGE + '/profile'], context)
    # Add only. Never --replace, remove a profile, relax it, use cache or retry.
    _command(['/usr/sbin/apparmor_parser', '-a', '-K', STAGE + '/profile'], context)
    _command(['/usr/bin/unshare', '--mount', '--net', '--propagation', 'private',
              '/usr/bin/python3.12', '-I', '-B', '-S', STAGE + '/launcher.py',
              '--namespace', _token(context)], context, worker=True)


def namespace(context: dict[str, str]) -> None:
    """Private child phase: minimal root, no changes to the live root or /var."""
    context = check_context(context, internal=True)
    if sys.platform != 'linux' or os.geteuid() != 0:
        raise RecoveryLaunchRefused('namespace_context')
    # A forged phase invocation cannot use the ordinary recovery namespace.
    for name in ('mnt', 'net'):
        if os.readlink('/proc/self/ns/' + name) == os.readlink('/proc/1/ns/' + name):
            raise RecoveryLaunchRefused('namespace_missing')
    raw = _read(STAGE + '/media/support.zip', MAX_SEED)
    _policy(raw, context)
    source = _read(STAGE + '/launcher.py', MAX_SOURCE)
    root = STAGE + '/root'
    _command(['/usr/bin/mount', '-t', 'tmpfs', '-o',
              'rw,nodev,nosuid,noexec,size=16M,mode=0755', 'tmpfs', root], context)
    for name in ('usr', 'etc', 'proc', 'sys', 'dev', 'run', 'var', 'var/lib',
                 'var/lib/hyperv', 'run/night-shift-bootstrap', 'tmp'):
        os.mkdir(root + '/' + name, 0o755)
    for name, target in (('bin', 'usr/bin'), ('sbin', 'usr/sbin'),
                         ('lib', 'usr/lib'), ('lib64', 'usr/lib64')):
        os.symlink(target, root + '/' + name)
    for name in ('usr', 'etc', 'proc', 'dev'):
        target = root + '/' + name
        _command(['/usr/bin/mount', '--bind', '/' + name, target], context)
        options = 'remount,bind,ro,nosuid' + ('' if name == 'usr' else ',noexec')
        _command(['/usr/bin/mount', '-o', options, target], context)
    # A bind of the old /sys retains the original network-namespace view.
    # Mount a fresh read-only sysfs AFTER unshare so the probe sees its own lo.
    _command(['/usr/bin/mount', '-t', 'sysfs', '-o', 'ro,nodev,nosuid,noexec',
              'sysfs', root + '/sys'], context)
    _command(['/usr/bin/mount', '-t', 'tmpfs', '-o',
              'rw,nodev,nosuid,size=1M,mode=0700', 'tmpfs', root + '/run/night-shift-bootstrap'], context)
    _command(['/usr/bin/mount', '-t', 'tmpfs', '-o',
              'rw,nodev,nosuid,noexec,size=256K,mode=0755', 'tmpfs', root + '/var/lib/hyperv'], context)
    _new(root + SEED_PATH, raw)
    _new(root + '/entry.py', source)
    _command(['/usr/bin/mount', '-o', 'remount,ro,nodev,nosuid,noexec', root], context)
    os.chroot(root)
    os.chdir('/')
    _command(['/usr/bin/setpriv', '--bounding-set=-all', '--inh-caps=-all',
              '--ambient-caps=-all', '--no-new-privs', '--reuid=0', '--regid=0',
              '--clear-groups', '--', '/usr/bin/python3.12', '-I', '-B', '-S',
              '/entry.py', '--confined', _token(context)], context, worker=True)


def confined(context: dict[str, str]) -> None:
    """No seed imports until full pin, zero capabilities/NNP and enforced label."""
    context = check_context(context, internal=True)
    if sys.platform != 'linux' or not sys.flags.isolated or not sys.flags.no_site or not sys.dont_write_bytecode:
        raise RecoveryLaunchRefused('confined_context')
    status = dict(line.split(':', 1) for line in _read('/proc/self/status', 131072).decode('ascii').splitlines())
    if (status.get('NoNewPrivs', '').strip() != '1'
            or any(status.get(k, '').strip() != '0000000000000000'
                   for k in ('CapInh', 'CapPrm', 'CapEff', 'CapBnd', 'CapAmb'))):
        raise RecoveryLaunchRefused('capabilities')
    raw = _read(SEED_PATH, MAX_SEED)
    _policy(raw, context)
    # No libapparmor fallback, exec helper or weaker profile if this transition
    # is unavailable with NNP/zero caps. Native validation remains required.
    fd = os.open('/proc/self/attr/current', os.O_WRONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        value = ('changeprofile ' + PROFILE).encode('ascii')
        if os.write(fd, value) != len(value):
            raise RecoveryLaunchUnknown('profile_transition_unknown')
    finally:
        os.close(fd)
    if _read('/proc/self/attr/current', 256).decode('ascii').strip() != PROFILE + ' (enforce)':
        raise RecoveryLaunchRefused('profile_transition')
    if any(n == 'night_shifts' or n.startswith('night_shifts.') for n in sys.modules):
        raise RecoveryLaunchRefused('import_collision')
    sys.path.insert(0, SEED_PATH)
    binding_module = importlib.import_module('night_shifts.maintenance_tls_prototype')
    probe = importlib.import_module('night_shifts.guest.bootstrap_public_probe')
    binding = binding_module.AttemptBinding(context['attempt_id'], context['vm_id'])
    report = probe.run_guest_probe(raw, binding, expected_sha256=context['seed_sha256'])
    # Public fixed-label result only. Not an independent host receipt. The
    # daemon streams remain DEVNULL. Bound all nesting-error summaries as well.
    if type(report) is not bytes or len(report) > 2000:
        raise RecoveryLaunchRefused('report_bound')
    result = json.loads(report)
    sys.stdout.write(report.decode('ascii'))
    if result.get('outcome') != 'local_published' or result.get('direct_child_stopped') is not True:
        raise RecoveryLaunchUnknown('probe_unknown')


def main() -> int:
    """Internal phases only; root boot is supplied by reviewed NoCloud bytes."""
    try:
        if len(sys.argv) != 3 or sys.argv[1] not in ('--namespace', '--confined') or len(sys.argv[2]) > 4096:
            raise RecoveryLaunchRefused('phase')
        context = json.loads(base64.b64decode(sys.argv[2], validate=True))
        if sys.argv[1] == '--namespace':
            namespace(context)
        else:
            confined(context)
        return 0
    except Exception:
        # No traceback/arguments/source/policy/native stderr. A failure after
        # possible mutation cannot imply rollback, no publication or VM stop.
        sys.stdout.write('{"outcome":"unknown","reason":"recovery_phase_unknown"}\n')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
