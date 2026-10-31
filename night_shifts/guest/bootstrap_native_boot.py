"""Standalone validation-only guest acquisition SOURCE CANDIDATE; UNWIRED.

Stdlib only until complete pinned inputs and sealed source tree are checked.
boot/namespace/supervise WOULD mutate a fresh isolated guest; never call on the
workstation/retained guest. No host operation, installer, fallback or receipt.
Internal phase argv is not an execution grant; complete media and a protected
exact-owned diskless VM/watchdog must be independently reviewed and approved.
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
from typing import NoReturn, Protocol, cast
from uuid import UUID

STAGE = '/run/night-shift-native-validation'
MEDIA = STAGE + '/media'
ROOT = STAGE + '/root'
SEED_PATH = '/run/night-shift-bootstrap/support.zip'
PROFILE = 'night-shift-kvp-public-probe'
POLICY_ENTRY = 'night_shifts/guest/bootstrap-public-probe.apparmor'
BOOT_ENTRY = 'night_shifts/guest/bootstrap_native_boot.py'
POLICY_SHA256 = '05e702c364a532679456826e22d6d28e108222ea387df6a690141e60194a166a'
WORKER_SHA256 = '2b6fc9a513525eb2d39a6a4c50ef050620228fc4ff596925c9a279fd86a9d3d2'
MAX_SEED = 512 * 1024
MAX_PAYLOAD = 1024 * 1024
MAX_ENTRY = 128 * 1024
MAX_BOOT_SECONDS = 90
_PUBLIC_SOURCES = (
    'bootstrap_daemon_asset.py', 'bootstrap_probe_seed.py',
    'guest/bootstrap_public_probe.py', 'guest/bootstrap-public-probe.apparmor',
    'guest/publish_public_bootstrap.py', 'public_bootstrap_kvp.py',
    'maintenance_credentials_prototype.py', 'maintenance_tls_prototype.py',
    'ubuntu_preparation_control.py', 'hyperv_image_preflight.py',
)
NATIVE_SOURCES = (
    'bootstrap_native_fixture.py', 'bootstrap_native_denials.py',
    'bootstrap_native_supervision.py', 'bootstrap_native_ram.py',
    'bootstrap_native_child_plan.py', 'bootstrap_native_owner.py',
    'bootstrap_native_capture.py', 'bootstrap_native_sequence.py',
    'guest/bootstrap_native_child.py', 'guest/bootstrap_native_worker.py',
    'guest/bootstrap_native_boot.py',
)
EMPTY_FILES = ('night_shifts/__init__.py', 'night_shifts/guest/__init__.py')
PUBLIC_NAMES = tuple(sorted((*EMPTY_FILES, *('night_shifts/' + name for name in _PUBLIC_SOURCES),
                             'COPYING', 'GPL-2.0', 'SOURCE.txt', 'hv_kvp_daemon', 'public.json', 'manifest.json')))
SOURCE_NAMES = tuple(sorted((*EMPTY_FILES,
    *('night_shifts/' + name for name in (*_PUBLIC_SOURCES, *NATIVE_SOURCES)), 'manifest.json')))
_FIELDS = {'attempt_id', 'vm_id', 'seed_sha256', 'payload_sha256'}
_TOOLS = ('/usr/bin/env', '/usr/bin/mount', '/usr/bin/unshare', '/usr/bin/setpriv',
          '/usr/sbin/apparmor_parser', '/usr/bin/python3.12')
_UNKNOWN = b'{"kind":"local_native_boot_unknown","scope":"local_consistency_only"}\n'


class NativeBootRefused(RuntimeError):
    """Fixed labels only, never source/archive/native output."""


class NativeBootUnknown(NativeBootRefused):
    """Possible guest mutation; no retry, rollback, publication or VM absence."""


class _Linux(Protocol):
    O_NOFOLLOW: int
    O_CLOEXEC: int
    O_NONBLOCK: int

    def getuid(self) -> int: ...
    def geteuid(self) -> int: ...
    def getgid(self) -> int: ...
    def getegid(self) -> int: ...
    def getgroups(self) -> list[int]: ...
    def chroot(self, path: str, /) -> None: ...
    def execve(self, path: str, argv: list[str], env: dict[str, str], /) -> NoReturn: ...


def _linux() -> _Linux:
    if sys.platform != 'linux':
        raise NativeBootRefused('linux_required')
    return cast(_Linux, os)


def _json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True) + '\n').encode('ascii')


def check_context(value: object, *, internal: bool = False) -> dict[str, str]:
    if (type(value) is not dict or set(value) != _FIELDS | ({'deadline'} if internal else set())
            or any(type(item) is not str or len(item) > 128 for item in value.values())):
        raise NativeBootRefused('context')
    if (re.fullmatch('[0-9a-f]{32}', value['attempt_id']) is None
            or any(re.fullmatch('[0-9a-f]{64}', value[key]) is None for key in ('seed_sha256', 'payload_sha256'))):
        raise NativeBootRefused('context')
    try:
        vm = UUID(value['vm_id'])
        if not vm.int or str(vm) != value['vm_id']:
            raise ValueError
        if internal:
            deadline, now = float(value['deadline']), time.monotonic()
            if (type(now) not in (int, float) or not 0 <= now <= 1e15 or not math.isfinite(now)
                    or not 0 <= deadline <= 1e15 or not math.isfinite(deadline)
                    or not 0 < deadline - now <= MAX_BOOT_SECONDS):
                raise ValueError
    except (ValueError, OverflowError):
        raise NativeBootRefused('context') from None
    return dict(value)


class _Budget:
    def __init__(self, deadline: str) -> None:
        self.end, self.last = float(deadline), 0.0
        self.check()

    def check(self, maximum: float = MAX_BOOT_SECONDS) -> float:
        now = time.monotonic()
        if (type(now) not in (int, float) or not self.last <= now <= 1e15 or not math.isfinite(now)
                or not math.isfinite(self.end) or not 0 < self.end - now <= MAX_BOOT_SECONDS):
            raise NativeBootUnknown('deadline_unknown')
        self.last = float(now)
        return min(self.end - now, maximum)


def _close(fd: int) -> None:
    try:
        os.close(fd)
    except BaseException:
        raise NativeBootUnknown('descriptor_cleanup_unknown') from None


def _read(path: str, limit: int, budget: _Budget) -> bytes:
    native = _linux()
    budget.check()
    fd = os.open(path, os.O_RDONLY | native.O_NOFOLLOW | native.O_CLOEXEC | native.O_NONBLOCK)
    try:
        raw = bytearray()
        while True:
            budget.check()
            part = os.read(fd, limit + 1 - len(raw))
            if not part:
                return bytes(raw)
            raw.extend(part)
            if len(raw) > limit:
                raise NativeBootRefused('input_bound')
    finally:
        _close(fd)


def _new(path: str, raw: bytes, budget: _Budget) -> None:
    native = _linux()
    budget.check()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | native.O_NOFOLLOW
                 | native.O_CLOEXEC | native.O_NONBLOCK, 0o400)
    try:
        if os.write(fd, raw) != len(raw):
            raise NativeBootUnknown('write_unknown')
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid or info.st_gid or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) != 0o400 or info.st_size != len(raw)):
            raise NativeBootUnknown('file_identity_unknown')
    finally:
        _close(fd)  # Never retry a possibly consumed fd number.
    if _read(path, len(raw), budget) != raw:
        raise NativeBootUnknown('write_unknown')


def _zip(entries: dict[str, bytes]) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_STORED) as archive:
        for name, raw in sorted(entries.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100444 << 16
            archive.writestr(info, raw)
    return stream.getvalue()


def _manifest(entries: dict[str, bytes], context: dict[str, str], purpose: str) -> bytes:
    return _json({'version': 1, 'purpose': purpose, 'attempt_id': context['attempt_id'], 'vm_id': context['vm_id'],
                  'files': {name: {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
                            for name, raw in sorted(entries.items())}})


def _archive(raw: bytes, digest: str, names: tuple[str, ...], limit: int,
             context: dict[str, str], purpose: str) -> dict[str, bytes]:
    if type(raw) is not bytes or not 0 < len(raw) <= limit or hashlib.sha256(raw).hexdigest() != digest:
        raise NativeBootRefused('input_digest')
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            infos = archive.infolist()
            if archive.comment or tuple(item.filename for item in infos) != names:
                raise NativeBootRefused('input_inventory')
            entries: dict[str, bytes] = {}
            for info in infos:
                if (info.compress_type != zipfile.ZIP_STORED or info.flag_bits or info.extra or info.comment
                        or info.date_time != (1980, 1, 1, 0, 0, 0) or info.create_system != 3
                        or info.external_attr != 0o100444 << 16 or not 0 <= info.file_size <= MAX_ENTRY):
                    raise NativeBootRefused('input_shape')
                entries[info.filename] = archive.read(info)
        manifest = entries.pop('manifest.json')
        if (manifest != _manifest(entries, context, purpose)
                or _zip({**entries, 'manifest.json': manifest}) != raw
                or any(entries[name] for name in EMPTY_FILES)):
            raise NativeBootRefused('input_manifest')
        return entries
    except NativeBootRefused:
        raise
    except (zipfile.BadZipFile, KeyError, ValueError, RuntimeError, OverflowError):
        raise NativeBootRefused('input_shape') from None


def validate_inputs(context: dict[str, str], seed: bytes, payload: bytes) -> dict[str, bytes]:
    """Pure stdlib full-pin/shape check; NEVER import/extract/execute any entry.

    Pinning a caller's own untrusted digest is not provenance. Full public-seed
    semantic validation also runs after sealed imports, BEFORE fixture creation.
    """
    public = _archive(seed, context['seed_sha256'], PUBLIC_NAMES, MAX_SEED, context, 'public-plumbing-only')
    sources = _archive(payload, context['payload_sha256'], SOURCE_NAMES, MAX_PAYLOAD, context, 'native-validator-only')
    for name in (*EMPTY_FILES, *('night_shifts/' + item for item in _PUBLIC_SOURCES)):
        if sources[name] != public[name]:
            raise NativeBootRefused('support_source_mismatch')
    if (hashlib.sha256(sources[POLICY_ENTRY]).hexdigest() != POLICY_SHA256
            or hashlib.sha256(sources['night_shifts/guest/bootstrap_native_worker.py']).hexdigest() != WORKER_SHA256):
        raise NativeBootRefused('review_pin')
    for name, raw in sources.items():
        if name in EMPTY_FILES:
            continue
        try:
            if not raw or b'\r' in raw or not raw.endswith(b'\n'):
                raise ValueError
            raw.decode('utf-8')
        except (UnicodeError, ValueError):
            raise NativeBootRefused('source_encoding') from None
    return sources


def _runtime(context: dict[str, str], budget: _Budget, *, private: bool, empty_groups: bool) -> None:
    native = _linux()
    budget.check()
    groups = native.getgroups()
    if (platform.machine() != 'x86_64' or platform.release() != '6.8.0-139-generic'
            or sys.version_info[:2] != (3, 12) or not sys.flags.isolated or not sys.flags.no_site
            or not sys.dont_write_bytecode or native.getuid() or native.geteuid() or native.getgid() or native.getegid()
            or dict(os.environ) != {'LANG': 'C', 'LC_ALL': 'C'}
            or (groups != [] if empty_groups else any(group != 0 for group in groups))
            or os.listdir('/proc/self/task') != [str(os.getpid())]
            or _read('/proc/self/attr/current', 256, budget).strip() != b'unconfined'):
        raise NativeBootRefused('runtime')
    observed = _read('/sys/class/dmi/id/product_uuid', 128, budget).decode('ascii').strip().lower()
    if str(UUID(observed)) != context['vm_id']:
        raise NativeBootRefused('guest_vm')
    if os.readlink('/proc/self/ns/pid') != os.readlink('/proc/1/ns/pid'):
        raise NativeBootRefused('pid_view')
    if private and any(os.readlink('/proc/self/ns/' + name) == os.readlink('/proc/1/ns/' + name)
                       for name in ('mnt', 'net')):
        raise NativeBootRefused('namespace')
    blocks = sorted(os.listdir('/sys/block'))
    if (not blocks or len(blocks) > 64 or any(re.fullmatch(r'(loop|sr)[0-9]+', name) is None for name in blocks)
            or sorted(os.listdir('/sys/class/net')) != ['lo']
            or _read('/proc/swaps', 4096, budget).split() != [b'Filename', b'Type', b'Size', b'Used', b'Priority']):
        raise NativeBootRefused('disk_network_swap')
    for name in blocks:
        base = '/sys/class/block/' + name
        if name.startswith('loop'):
            try:
                backing = _read(base + '/loop/backing_file', 4096, budget)
            except FileNotFoundError:
                continue
            if not backing.strip():
                raise NativeBootRefused('loop_backing')
        if _read(base + '/ro', 16, budget).strip() != b'1':
            raise NativeBootRefused('writable_block')
    if private and int(_read('/sys/class/net/lo/flags', 32, budget).strip(), 16) & 1:
        raise NativeBootRefused('network')
    names = os.listdir('/proc')
    if len(names) > 8192:
        raise NativeBootRefused('process_bound')
    for name in names:
        if name.isdecimal():
            try:
                if _read('/proc/' + name + '/comm', 256, budget).strip() == b'hv_kvp_daemon':
                    raise NativeBootRefused('existing_daemon')
            except FileNotFoundError:
                pass


def _profile(budget: _Budget, *, present: bool) -> None:
    if _read('/sys/module/apparmor/parameters/enabled', 16, budget).strip() != b'Y':
        raise NativeBootRefused('apparmor_unavailable')
    rows = _read('/sys/kernel/security/apparmor/profiles', 131072, budget).decode('ascii').splitlines()
    matching = [row for row in rows if row.partition(' ')[0] == PROFILE
                or row.partition(' ')[0].startswith(PROFILE + '//')]
    if matching != ([PROFILE + ' (enforce)'] if present else []):
        raise NativeBootRefused('profile_state')


def _sealed_view(raw: bytes) -> None:
    """Stdlib mount refusal BEFORE source import, then real checker repeats it."""
    expected = {'/', '/usr', '/etc', '/proc', '/dev', '/sys', '/run/night-shift-bootstrap', '/var/lib/hyperv'}
    mounts: dict[str, tuple[str, set[str]]] = {}
    for line in raw.decode('ascii').splitlines():
        words = line.split(' ')
        try:
            split = words.index('-')
            path, options, fs = words[4], set(words[5].split(',')), words[split + 1]
            if (len(words) != split + 4 or split < 6 or any('\\' in word for word in words)
                    or path in mounts or ('rw' in options) == ('ro' in options)):
                raise ValueError
            mounts[path] = fs, options
        except (ValueError, IndexError):
            raise NativeBootRefused('sealed_mounts') from None
    if set(mounts) != expected:
        raise NativeBootRefused('sealed_mounts')
    for path, (fs, options) in mounts.items():
        ram = path in ('/run/night-shift-bootstrap', '/var/lib/hyperv')
        required = {'rw' if ram else 'ro', 'nosuid'}
        if ram or path in ('/', '/sys'):
            required.add('nodev')
        if path not in ('/usr', '/run/night-shift-bootstrap'):
            required.add('noexec')
        if (not required <= options or (path in ('/usr', '/run/night-shift-bootstrap') and 'noexec' in options)
                or ((ram or path == '/') and fs != 'tmpfs')
                or (path == '/sys' and fs != 'sysfs') or (path == '/proc' and fs != 'proc')
                or (path == '/dev' and fs != 'devtmpfs')):
            raise NativeBootRefused('sealed_mounts')


def _command(argv: list[str], budget: _Budget, *, phase: bool = False) -> None:
    # Private fixed-source call sites only. No shell, stdin or PATH lookup.
    # Internal phase stdout is only the fixed bounded local summary, not tools.
    try:
        result = subprocess.run(argv, shell=False, stdin=subprocess.DEVNULL,
            stdout=None if phase else subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env={'LANG': 'C', 'LC_ALL': 'C'}, cwd='/', close_fds=True,
            timeout=budget.check(MAX_BOOT_SECONDS if phase else 3))
    except BaseException:
        raise NativeBootUnknown('command_unknown') from None
    budget.check()
    if result.returncode != 0:
        raise NativeBootUnknown('phase_unknown' if phase else 'native_change_unknown')


def _token(context: dict[str, str]) -> str:
    return base64.b64encode(_json(context)).decode('ascii')


def boot(context: dict[str, str], *, trusted_source: bytes) -> None:
    """Future fixed NoCloud entry only; NO execution authority from parameters."""
    context = check_context(context)
    _linux()
    context['deadline'] = repr(time.monotonic() + MAX_BOOT_SECONDS)
    budget = _Budget(context['deadline'])
    _runtime(context, budget, private=False, empty_groups=False)
    _profile(budget, present=False)
    mounts = _read('/proc/self/mountinfo', 131072, budget).decode('ascii').splitlines()
    run = [row.split() for row in mounts if len(row.split()) >= 10 and row.split()[4] == '/run']
    info = os.lstat('/run')
    if (len(run) != 1 or '\\' in ' '.join(run[0]) or 'rw' not in run[0][5].split(',')
            or run[0][run[0].index('-') + 1] != 'tmpfs' or not stat.S_ISDIR(info.st_mode)
            or info.st_uid or info.st_gid or info.st_mode & 0o022):
        raise NativeBootRefused('run_not_ram')
    for tool in _TOOLS:
        info = os.stat(tool)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid or info.st_gid
                or info.st_mode & 0o022 or not info.st_mode & 0o100):
            raise NativeBootRefused('tool_security')
    os.umask(0o077)
    for path in (STAGE, MEDIA, ROOT):
        budget.check()
        os.mkdir(path, 0o700)
    optical = os.path.realpath('/dev/disk/by-label/CIDATA')
    if (re.fullmatch('/dev/sr[0-9]+', optical) is None or not stat.S_ISBLK(os.stat(optical).st_mode)
            or _read('/sys/class/block/' + optical[5:] + '/device/type', 16, budget).strip() != b'5'):
        raise NativeBootRefused('support_optical')
    _command(['/usr/bin/mount', '-n', '--internal-only', '-t', 'iso9660', '-o',
              'ro,nodev,nosuid,noexec', optical, MEDIA], budget)
    seed = _read(MEDIA + '/support.zip', MAX_SEED, budget)
    payload = _read(MEDIA + '/validator.zip', MAX_PAYLOAD, budget)
    sources = validate_inputs(context, seed, payload)
    if type(trusted_source) is not bytes or trusted_source != sources[BOOT_ENTRY]:
        raise NativeBootRefused('entry_source')
    budget.check()
    _new(STAGE + '/profile', sources[POLICY_ENTRY], budget)
    _new(STAGE + '/entry.py', trusted_source, budget)
    _command(['/usr/sbin/apparmor_parser', '-Q', '-K', STAGE + '/profile'], budget)
    _profile(budget, present=False)
    _command(['/usr/sbin/apparmor_parser', '-a', '-K', STAGE + '/profile'], budget)
    _profile(budget, present=True)
    _command(['/usr/bin/unshare', '--mount', '--net', '--propagation', 'private',
              '/usr/bin/python3.12', '-I', '-B', '-S', STAGE + '/entry.py', '--namespace', _token(context)],
             budget, phase=True)


def namespace(context: dict[str, str]) -> None:
    context = check_context(context, internal=True)
    budget = _Budget(context['deadline'])
    _runtime(context, budget, private=True, empty_groups=False)
    _profile(budget, present=True)
    seed = _read(MEDIA + '/support.zip', MAX_SEED, budget)
    payload = _read(MEDIA + '/validator.zip', MAX_PAYLOAD, budget)
    sources = validate_inputs(context, seed, payload)
    if _read(STAGE + '/entry.py', MAX_ENTRY, budget) != sources[BOOT_ENTRY]:
        raise NativeBootRefused('entry_source')
    mount = ['/usr/bin/mount', '-n', '--internal-only']
    _command([*mount, '-t', 'tmpfs', '-o', 'rw,nodev,nosuid,noexec,size=16M,mode=0755', 'tmpfs', ROOT], budget)
    for name in ('usr', 'etc', 'proc', 'sys', 'dev', 'run', 'var', 'var/lib', 'var/lib/hyperv',
                 'run/night-shift-bootstrap', 'tmp', 'validator', 'validator/night_shifts', 'validator/night_shifts/guest'):
        budget.check()
        os.mkdir(ROOT + '/' + name, 0o755)
    for name, target in (('bin', 'usr/bin'), ('sbin', 'usr/sbin'), ('lib', 'usr/lib'), ('lib64', 'usr/lib64')):
        os.symlink(target, ROOT + '/' + name)
    for name in ('usr', 'etc', 'proc', 'dev'):
        target = ROOT + '/' + name
        _command([*mount, '--bind', '/' + name, target], budget)
        options = 'remount,bind,ro,nosuid' + ('' if name == 'usr' else ',noexec')
        _command([*mount, '-o', options, target], budget)
    _command([*mount, '-t', 'sysfs', '-o', 'ro,nodev,nosuid,noexec', 'sysfs', ROOT + '/sys'], budget)
    _command([*mount, '-t', 'tmpfs', '-o', 'rw,nodev,nosuid,size=1M,mode=0700',
              'tmpfs', ROOT + '/run/night-shift-bootstrap'], budget)
    _command([*mount, '-t', 'tmpfs', '-o', 'rw,nodev,nosuid,noexec,size=256K,mode=0755',
              'tmpfs', ROOT + '/var/lib/hyperv'], budget)
    _new(ROOT + SEED_PATH, seed, budget)
    _new(ROOT + '/validator.zip', payload, budget)
    _new(ROOT + '/entry.py', sources[BOOT_ENTRY], budget)
    for name, raw in sources.items():
        _new(ROOT + '/validator/' + name, raw, budget)
    _command([*mount, '-o', 'remount,ro,nodev,nosuid,noexec', ROOT], budget)
    native = _linux()
    native.chroot(ROOT)
    os.chdir('/')
    budget.check()
    # Trusted supervisor retains root capabilities for kmsg. ONLY worker launch
    # drops all sets/sets NNP before the fixed transition. Same-PID fresh exec.
    native.execve('/usr/bin/setpriv', ['/usr/bin/setpriv', '--reuid=0', '--regid=0', '--clear-groups', '--',
        '/usr/bin/python3.12', '-I', '-B', '-S', '/entry.py', '--supervise', _token(context)],
        {'LANG': 'C', 'LC_ALL': 'C'})
    raise NativeBootUnknown('exec_returned_unknown')


def supervise(context: dict[str, str]) -> None:
    context = check_context(context, internal=True)
    budget = _Budget(context['deadline'])
    _runtime(context, budget, private=True, empty_groups=True)
    mountinfo = _read('/proc/self/mountinfo', 131072, budget)
    _sealed_view(mountinfo)  # BEFORE even pinned support package imports.
    seed = _read(SEED_PATH, MAX_SEED, budget)
    sources = validate_inputs(context, seed, _read('/validator.zip', MAX_PAYLOAD, budget))
    if _read('/entry.py', MAX_ENTRY, budget) != sources[BOOT_ENTRY]:
        raise NativeBootRefused('entry_source')
    for path in ('/validator', '/validator/night_shifts', '/validator/night_shifts/guest'):
        info = os.lstat(path)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid or info.st_gid or info.st_mode & 0o022:
            raise NativeBootRefused('sealed_source')
    for name, raw in sources.items():
        path = '/validator/' + name
        info = os.lstat(path)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid or info.st_gid or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) != 0o400 or info.st_size != len(raw)
                or _read(path, len(raw), budget) != raw):
            raise NativeBootRefused('sealed_source')
    if any(name == 'night_shifts' or name.startswith('night_shifts.') for name in sys.modules):
        raise NativeBootRefused('import_collision')
    budget.check()
    sys.path.insert(0, '/validator')
    binding_module = importlib.import_module('night_shifts.maintenance_tls_prototype')
    seed_module = importlib.import_module('night_shifts.bootstrap_probe_seed')
    binding = binding_module.AttemptBinding(context['attempt_id'], context['vm_id'])
    seed_module.validate_public_probe_seed(seed, binding, expected_sha256=context['seed_sha256'])
    probe = importlib.import_module('night_shifts.guest.bootstrap_public_probe')
    probe.check_mounts(mountinfo.decode('ascii'))
    ram = importlib.import_module('night_shifts.bootstrap_native_ram')
    sequence = importlib.import_module('night_shifts.bootstrap_native_sequence')
    owner = importlib.import_module('night_shifts.bootstrap_native_owner')
    fixtures, report, failed = None, None, False
    try:
        fixtures = ram.NativeRamFixtures(binding, seed_sha256=context['seed_sha256'],
                                         deadline=min(budget.end, time.monotonic() + 5))
        result = sequence.NativeValidationSequence(fixtures, deadline=min(budget.end, time.monotonic() + 60)).run()
        report = result.summary_bytes()
        if owner._RETAINED:
            raise NativeBootUnknown('child_cleanup_unknown')
        budget.check()
    except BaseException:
        failed = True
    finally:
        if fixtures is not None:
            try:
                fixtures.close()
            except BaseException:
                failed = True
    if failed:
        raise NativeBootUnknown('supervision_unknown') from None
    expected = _json({'kind': 'local_native_sequence_observation', 'scope': 'local_consistency_only',
        'attempt_id': context['attempt_id'], 'vm_id': context['vm_id'], 'workers_observed': 11,
        'paired_cases': ['runtime_write', 'pool_sibling_write', 'outside_exec'],
        'confined_pool_controls': 2, 'allowed_pool_files': 5})
    if type(report) is not bytes or report != expected or len(report) > 512:
        raise NativeBootRefused('summary_bound')
    budget.check()
    if os.write(1, report) != len(report):
        raise NativeBootUnknown('summary_unknown')
    budget.check()


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise NativeBootRefused('context')
        result[key] = value
    return result


def main() -> int:
    """Internal phases only. Future NoCloud bytes supply the root entry."""
    try:
        if len(sys.argv) != 3 or sys.argv[1] not in ('--namespace', '--supervise') or len(sys.argv[2]) > 4096:
            raise NativeBootRefused('phase')
        raw = base64.b64decode(sys.argv[2], validate=True)
        if len(raw) > 4096:
            raise NativeBootRefused('context')
        context = json.loads(raw, object_pairs_hook=_unique)
        if sys.argv[1] == '--namespace':
            namespace(context)
        else:
            supervise(context)
        return 0
    except BaseException:
        try:
            os.write(1, _UNKNOWN)
        except BaseException:
            pass
        return 125


if __name__ == '__main__':
    raise SystemExit(main())
