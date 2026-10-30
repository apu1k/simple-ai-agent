"""Offline syscall models only: no native RAM file, ELF write/exec or mount.

These models exercise refusal/ownership ordering, not Linux path/mount semantics,
LSM permissions or ABI behavior. All native adapters are substituted before use.
"""
from __future__ import annotations

import errno
import hashlib
import io
import stat
import zipfile
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from night_shifts import bootstrap_native_ram as ram
from night_shifts.bootstrap_native_fixture import inert_fixture_bytes
from night_shifts.guest import bootstrap_native_worker as worker
from night_shifts.maintenance_tls_prototype import AttemptBinding

BINDING = AttemptBinding('1' * 32, '00000000-0000-4000-8000-000000000001')
SEED = b'SYNTHETIC-PINNED-DATA-NOT-A-BOOTABLE-SEED'
SEED_SHA = hashlib.sha256(SEED).hexdigest()
_REAL_READ = ram._read_system
MOUNTS = (
    b'1 0 0:1 / / ro,nodev,nosuid,noexec - tmpfs tmpfs ro\n'
    b'2 1 0:2 / /run/night-shift-bootstrap rw,nodev,nosuid - tmpfs tmpfs rw\n'
    b'3 1 0:3 / /var/lib/hyperv rw,nodev,nosuid,noexec - tmpfs tmpfs rw\n'
)


@dataclass
class Node:
    path: str
    ino: int
    dev: int = 1
    mode: int = stat.S_IFDIR | 0o755
    data: bytes = b''
    uid: int = 0
    gid: int = 0
    nlink: int = 1
    mtime: int = 100
    ctime: int = 100

    def info(self):
        return SimpleNamespace(st_ino=self.ino, st_dev=self.dev, st_mode=self.mode,
                               st_size=len(self.data), st_uid=self.uid, st_gid=self.gid,
                               st_nlink=self.nlink, st_mtime_ns=self.mtime, st_ctime_ns=self.ctime)


class Model:
    def __init__(self):
        self.now, self.cancelled = 100.0, False
        self.nodes = {}
        for path in ('/', '/run', ram._RUNTIME, '/var', '/var/lib', ram._POOL):
            self.nodes[path] = Node(path, len(self.nodes) + 1,
                                    2 if path == ram._RUNTIME else 3 if path == ram._POOL else 1)
        path = ram._RUNTIME + '/support.zip'
        self.nodes[path] = Node(path, 7, 2, stat.S_IFREG | 0o400, SEED)
        self.fds, self.events, self.closed = {}, [], []
        self.next_fd = 10
        self.short_write = self.write_error = self.inheritable = False
        self.bad_mount_fd = self.mutate_read = False
        self.create_mode, self.close_errors = None, set()
        self.system = {
            '/proc/self/attr/current': b'unconfined\n', '/proc/self/mountinfo': MOUNTS,
            '/sys/class/dmi/id/product_uuid': BINDING.vm_id.encode(),
            '/proc/swaps': b'Filename Type Size Used Priority\n',
            '/sys/class/block/sr0/ro': b'1\n', '/sys/class/net/lo/flags': b'0x8\n',
            '/proc/1/comm': b'init\n', '/proc/111/comm': b'python3.12\n',
        }
        self.listings = {'/sys/block': ['loop0', 'sr0'], '/sys/class/net': ['lo'], '/proc': ['1', '111']}
        self.links = {p + '/ns/' + name: p + '_' + name for p in ('/proc/1', '/proc/self') for name in ('mnt', 'net')}
        self.os = SimpleNamespace(
            O_RDONLY=0, O_WRONLY=1, O_RDWR=2, O_CREAT=64, O_EXCL=128,
            O_CLOEXEC=1 << 16, O_NOFOLLOW=1 << 17, O_NONBLOCK=1 << 18, O_DIRECTORY=1 << 19,
            getuid=lambda: 0, geteuid=lambda: 0, getgid=lambda: 0, getegid=lambda: 0,
            getgroups=lambda: [], environ={'LANG': 'C', 'LC_ALL': 'C'},
            get_inheritable=lambda fd: self.inheritable,
            open=self.open, close=self.close, stat=self.stat,
            fstat=lambda fd: self.fds[fd].info(), listdir=self.listdir,
            readlink=lambda path: self.links[path], pread=self.pread, pwrite=self.pwrite,
            major=lambda device: 0, minor=lambda device: device)

    def path(self, name, dir_fd):
        return name if name.startswith('/') else self.fds[dir_fd].path.rstrip('/') + '/' + name

    def open(self, name, flags, mode=0o777, *, dir_fd=None):
        path = self.path(name, dir_fd)
        self.events.append(('open', path, flags, mode))
        if flags & self.os.O_CREAT:
            assert flags & self.os.O_EXCL and flags & self.os.O_NOFOLLOW
            if path in self.nodes:
                raise FileExistsError(errno.EEXIST, 'CANARY_NATIVE_ERROR')
            parent = self.fds[dir_fd]
            self.nodes[path] = Node(path, max(node.ino for node in self.nodes.values()) + 1,
                                    parent.dev, stat.S_IFREG | (mode if self.create_mode is None else self.create_mode))
        if path not in self.nodes:
            raise FileNotFoundError(errno.ENOENT, 'CANARY_NATIVE_ERROR')
        node = self.nodes[path]
        if stat.S_ISLNK(node.mode):
            raise OSError(errno.ELOOP, 'CANARY_NATIVE_ERROR')
        if flags & self.os.O_DIRECTORY and not stat.S_ISDIR(node.mode):
            raise NotADirectoryError(errno.ENOTDIR, 'CANARY_NATIVE_ERROR')
        fd = self.next_fd
        self.next_fd += 1
        self.fds[fd] = node
        return fd

    def close(self, fd):
        self.closed.append(fd)
        self.fds.pop(fd)
        if fd in self.close_errors:
            raise OSError(errno.EINTR, 'CANARY_NATIVE_ERROR')

    def stat(self, name, *, dir_fd=None, follow_symlinks=True):
        assert follow_symlinks is False
        return self.nodes[self.path(name, dir_fd)].info()

    def listdir(self, path):
        if isinstance(path, int):
            prefix = self.fds[path].path + '/'
            return [name[len(prefix):] for name in self.nodes if name.startswith(prefix) and '/' not in name[len(prefix):]]
        return self.listings[path]

    def read_system(self, path, limit, budget):
        budget.check()
        self.events.append(('system', path))
        if path.startswith('/proc/self/fdinfo/'):
            fd = int(path.rsplit('/', 1)[1])
            value = ('mnt_id:\t' + str(99 if self.bad_mount_fd else self.fds[fd].dev) + '\n').encode()
        else:
            if path not in self.system:
                raise FileNotFoundError(errno.ENOENT, 'CANARY_NATIVE_ERROR')
            value = self.system[path]
        assert len(value) <= limit
        return value

    def pread(self, fd, count, offset):
        self.events.append(('pread', fd, count, offset))
        node = self.fds[fd]
        raw = node.data[offset:offset + count]
        if self.mutate_read:
            node.ctime += 1
        return raw

    def pwrite(self, fd, data, offset):
        assert offset == 0
        self.events.append(('pwrite', fd, data))
        self.fds[fd].data = data[:-1] if self.short_write else data
        if self.write_error:
            raise OSError(errno.EIO, 'CANARY_NATIVE_ERROR')
        return len(data) - int(self.short_write)


@pytest.fixture
def model(monkeypatch):
    state = Model()
    monkeypatch.setattr(ram, 'os', state.os)
    monkeypatch.setattr(ram, '_read_system', state.read_system)
    monkeypatch.setattr(ram, 'time', SimpleNamespace(monotonic=lambda: state.now))
    monkeypatch.setattr(ram, 'platform', SimpleNamespace(machine=lambda: 'x86_64', release=lambda: '6.8.0-139-generic'))
    monkeypatch.setattr(ram, 'sys', SimpleNamespace(platform='linux', version_info=(3, 12, 3),
                        flags=SimpleNamespace(isolated=True, no_site=True), dont_write_bytecode=True))
    return state


def acquire(state, **kwargs):
    return ram.NativeRamFixtures(kwargs.pop('binding', BINDING), seed_sha256=kwargs.pop('seed_sha256', SEED_SHA),
                                  deadline=kwargs.pop('deadline', state.now + 5),
                                  cancelled=kwargs.pop('cancelled', lambda: state.cancelled), **kwargs)


def test_fixed_catalog_matches_actual_worker_and_all_pins_close_without_deletion(model):
    pins = acquire(model)
    expected = {path + '/' + name: (mode, raw) for path, name, mode, raw in ram._FILES}
    assert len(expected) == 8
    for path, (mode, raw) in expected.items():
        node = model.nodes[path]
        assert node.data == raw and stat.S_IMODE(node.mode) == mode
        assert not node.uid and not node.gid and node.nlink == 1
    for case in ('runtime_write', 'pool_sibling_write'):
        assert model.nodes[worker._PATHS[case]].data == b'V'
    assert model.nodes[worker._PATHS['outside_exec']].data == inert_fixture_bytes()
    assert hashlib.sha256(model.nodes[worker._PATHS['outside_exec']].data).hexdigest() == worker.FIXTURE_SHA256
    assert len([event for event in model.events if event[0] == 'pwrite']) == 8
    assert len(model.fds) == 15
    assert all(event[2] & model.os.O_CLOEXEC and event[2] & model.os.O_NOFOLLOW
               for event in model.events if event[0] == 'open')
    pins.verify(deadline=model.now + 5)
    pins.close()
    pins.close()
    assert not model.fds and len(model.closed) == len(set(model.closed)) == 15
    assert set(expected) <= model.nodes.keys()
    with pytest.raises(ram.NativeRamRefused, match='^terminal$'):
        pins.verify(deadline=model.now + 5)


@pytest.mark.parametrize('path', [ram._RUNTIME + '/denied-write', ram._RUNTIME + '/denied-exec',
                                  ram._POOL + '/.kvp_pool_0', ram._POOL + '/.kvp_pool_denied', ram._RUNTIME + '/unexpected'])
def test_existing_objects_are_never_reused_replaced_or_deleted(model, path):
    original = Node(path, 999, 2, stat.S_IFREG | 0o600, b'KEEP')
    model.nodes[path] = original
    with pytest.raises(ram.NativeRamRefused, match='^ram_inventory$'):
        acquire(model)
    assert model.nodes[path] is original and original.data == b'KEEP'
    assert not model.fds and not any(event[0] == 'pwrite' for event in model.events)


@pytest.mark.parametrize('fault', ['bytes', 'size', 'mode', 'uid', 'gid', 'hardlink', 'symlink'])
def test_seed_is_pinned_before_first_fixture_write(model, fault):
    seed = model.nodes[ram._RUNTIME + '/support.zip']
    if fault == 'bytes':
        seed.data = b'x' * len(SEED)
    elif fault == 'size':
        seed.data = b''
    elif fault == 'mode':
        seed.mode = stat.S_IFREG | 0o600
    elif fault in ('uid', 'gid'):
        setattr(seed, fault, 1)
    elif fault == 'hardlink':
        seed.nlink = 2
    else:
        seed.mode = stat.S_IFLNK | 0o777
    with pytest.raises(ram.NativeRamRefused):
        acquire(model)
    assert not model.fds and not any(event[0] == 'pwrite' for event in model.events)


@pytest.mark.parametrize('path', ['/', '/run', ram._RUNTIME, '/var', '/var/lib', ram._POOL])
@pytest.mark.parametrize('fault', ['writable', 'owner', 'symlink'])
def test_all_ancestors_are_checked_before_creation(model, path, fault):
    node = model.nodes[path]
    if fault == 'writable':
        node.mode |= 0o020
    elif fault == 'owner':
        node.uid = 1
    else:
        node.mode = stat.S_IFLNK | 0o777
    with pytest.raises(ram.NativeRamRefused):
        acquire(model)
    assert not model.fds and not any(event[0] == 'pwrite' for event in model.events)


@pytest.mark.parametrize('path', [worker._PATHS['runtime_write'], worker._PATHS['outside_exec'],
                                  worker._PATHS['pool_sibling_write'], ram._POOL + '/.kvp_pool_4', ram._RUNTIME + '/support.zip'])
@pytest.mark.parametrize('fault', ['replace', 'bytes', 'truncate', 'mode', 'owner', 'hardlink', 'mount', 'symlink'])
def test_pre_post_worker_checks_refuse_changes_terminally(model, path, fault):
    pins = acquire(model)
    node = model.nodes[path]
    if fault == 'replace':
        model.nodes[path] = Node(path, 999, node.dev, node.mode, node.data)
    elif fault == 'bytes':
        node.data = b'x' * len(node.data)
    elif fault == 'truncate':
        node.data = b''
    elif fault == 'mode':
        node.mode ^= 0o100
    elif fault == 'owner':
        node.gid = 1
    elif fault == 'hardlink':
        node.nlink = 2
    elif fault == 'mount':
        node.dev = 77
    else:
        node.mode = stat.S_IFLNK | 0o777
    with pytest.raises(ram.NativeRamRefused):
        pins.verify(deadline=model.now + 5)
    with pytest.raises(ram.NativeRamRefused, match='^terminal$'):
        pins.verify(deadline=model.now + 5)
    pins.close()
    assert not model.fds


@pytest.mark.parametrize('path', ['/', '/run', ram._RUNTIME, '/var', '/var/lib', ram._POOL])
def test_held_ancestor_replacement_is_detected(model, path):
    pins = acquire(model)
    node = model.nodes[path]
    model.nodes[path] = Node(path, 999, node.dev, node.mode)
    with pytest.raises(ram.NativeRamRefused, match='^directory_identity$'):
        pins.verify(deadline=model.now + 5)
    pins.close()


def test_control_timestamps_may_change_between_checks_but_not_during_a_read(model):
    pins = acquire(model)
    for path, node in model.nodes.items():
        if not path.endswith('support.zip') and not stat.S_ISDIR(node.mode):
            node.mtime += 1
            node.ctime += 1
    pins.verify(deadline=model.now + 5)
    model.mutate_read = True
    with pytest.raises(ram.NativeRamRefused, match='^file_changed$'):
        pins.verify(deadline=model.now + 5)
    pins.close()


@pytest.mark.parametrize('fault', ['short', 'error', 'mode'])
def test_uncertain_creation_stops_without_retry_or_unlink(model, fault):
    model.short_write = fault == 'short'
    model.write_error = fault == 'error'
    model.create_mode = 0o400 if fault == 'mode' else None
    with pytest.raises(ram.NativeRamRefused) as error:
        acquire(model)
    assert 'CANARY' not in str(error.value)
    assert len([event for event in model.events if event[0] == 'pwrite']) == (0 if fault == 'mode' else 1)
    assert ram._RUNTIME + '/denied-write' in model.nodes
    assert not model.fds and len(model.closed) == len(set(model.closed))
    before = len(model.events)
    with pytest.raises(ram.NativeRamRefused, match='^ram_inventory$'):
        acquire(model)
    assert not any(event[0] == 'pwrite' for event in model.events[before:])


def test_create_new_refuses_a_collision_after_inventory_check(model):
    original_open = model.os.open
    path = ram._RUNTIME + '/denied-write'
    original = Node(path, 999, 2, stat.S_IFREG | 0o600, b'KEEP')
    def racing_open(name, flags, mode=0o777, *, dir_fd=None):
        if flags & model.os.O_CREAT:
            model.nodes[path] = original
        return original_open(name, flags, mode, dir_fd=dir_fd)
    model.os.open = racing_open
    with pytest.raises(ram.NativeRamUnknown, match='^fixture_io_unknown$'):
        acquire(model)
    assert model.nodes[path] is original and original.data == b'KEEP'
    assert not model.fds and not any(event[0] == 'pwrite' for event in model.events)


@pytest.mark.parametrize('construction_failure', [False, True])
def test_all_descriptors_close_once_even_when_one_close_is_uncertain(model, construction_failure):
    if construction_failure:
        model.short_write = True
        model.close_errors.add(10)
        with pytest.raises(ram.NativeRamUnknown, match='^descriptor_cleanup_unknown$'):
            acquire(model)
    else:
        pins = acquire(model)
        model.close_errors.add(max(model.fds))
        with pytest.raises(ram.NativeRamUnknown, match='^descriptor_cleanup_unknown$'):
            pins.close()
        count = len(model.closed)
        with pytest.raises(ram.NativeRamUnknown, match='^descriptor_cleanup_unknown$'):
            pins.close()
        assert len(model.closed) == count
    assert not model.fds and len(model.closed) == len(set(model.closed))


@pytest.mark.parametrize('fault', ['inheritable', 'fd-mount-id', 'fd-device'])
def test_descriptor_mount_checks_precede_first_fixture_write(model, fault):
    model.inheritable = fault == 'inheritable'
    model.bad_mount_fd = fault == 'fd-mount-id'
    if fault == 'fd-device':
        model.nodes[ram._RUNTIME].dev = 77
    with pytest.raises(ram.NativeRamRefused):
        acquire(model)
    assert not model.fds and not any(event[0] == 'pwrite' for event in model.events)


@pytest.mark.parametrize('fault', ['write-root', 'runtime-noexec', 'pool-exec', 'nested', 'mount-change'])
def test_mount_view_cannot_be_weakened_or_changed(model, fault):
    if fault == 'mount-change':
        pins = acquire(model)
        model.system['/proc/self/mountinfo'] = MOUNTS.replace(b'1 0 ', b'9 0 ')
        with pytest.raises(ram.NativeRamRefused, match='^mount_changed$'):
            pins.verify(deadline=model.now + 5)
        pins.close()
        return
    raw = MOUNTS
    if fault == 'write-root':
        raw = raw.replace(b'/ / ro,', b'/ / rw,')
    elif fault == 'runtime-noexec':
        raw = raw.replace(b'rw,nodev,nosuid - tmpfs', b'rw,nodev,nosuid,noexec - tmpfs')
    elif fault == 'pool-exec':
        raw = raw.replace(b'rw,nodev,nosuid,noexec', b'rw,nodev,nosuid')
    else:
        raw += b'4 2 0:4 / /run/night-shift-bootstrap/other ro - tmpfs tmpfs ro\n'
    model.system['/proc/self/mountinfo'] = raw
    with pytest.raises(ram.NativeRamRefused):
        acquire(model)
    assert not model.fds and not any(event[0] == 'pwrite' for event in model.events)


@pytest.mark.parametrize('fault', ['platform', 'kernel', 'python', 'isolation', 'site', 'bytecode', 'groups',
                                  'root', 'environment', 'label', 'namespace', 'vm', 'disk', 'disk-rw',
                                  'loop-rw', 'swap', 'nic', 'loopback-up', 'daemon'])
def test_native_context_refuses_before_fixture_creation(model, monkeypatch, fault):
    if fault == 'platform':
        monkeypatch.setattr(ram.sys, 'platform', 'win32')
    elif fault == 'kernel':
        monkeypatch.setattr(ram.platform, 'release', lambda: 'other')
    elif fault == 'python':
        monkeypatch.setattr(ram.sys, 'version_info', (3, 13))
    elif fault in ('isolation', 'site'):
        monkeypatch.setattr(ram.sys.flags, 'isolated' if fault == 'isolation' else 'no_site', False)
    elif fault == 'bytecode':
        monkeypatch.setattr(ram.sys, 'dont_write_bytecode', False)
    elif fault == 'groups':
        model.os.getgroups = lambda: [1]
    elif fault == 'root':
        model.os.getuid = lambda: 1
    elif fault == 'environment':
        model.os.environ['PATH'] = '/bin'
    elif fault == 'label':
        model.system['/proc/self/attr/current'] = b'confined (enforce)\n'
    elif fault == 'namespace':
        model.links['/proc/self/ns/mnt'] = model.links['/proc/1/ns/mnt']
    elif fault == 'vm':
        model.system['/sys/class/dmi/id/product_uuid'] = b'00000000-0000-4000-8000-000000000002'
    elif fault == 'disk':
        model.listings['/sys/block'].append('sda')
    elif fault == 'disk-rw':
        model.system['/sys/class/block/sr0/ro'] = b'0\n'
    elif fault == 'loop-rw':
        model.system['/sys/class/block/loop0/loop/backing_file'] = b'backed\n'
        model.system['/sys/class/block/loop0/ro'] = b'0\n'
    elif fault == 'swap':
        model.system['/proc/swaps'] += b'/swap file 1 0 -2\n'
    elif fault == 'nic':
        model.listings['/sys/class/net'].append('eth0')
    elif fault == 'loopback-up':
        model.system['/sys/class/net/lo/flags'] = b'0x9\n'
    else:
        model.system['/proc/111/comm'] = b'hv_kvp_daemon\n'
    with pytest.raises(ram.NativeRamRefused):
        acquire(model)
    assert not model.fds and not any(event[0] == 'pwrite' for event in model.events)


@pytest.mark.parametrize('fault', ['cancel', 'expired', 'regression', 'callback', 'non-bool'])
def test_budget_failures_are_terminal_and_preserve_artifacts(model, fault):
    pins = acquire(model)
    def stopped():
        return model.cancelled
    def exploding():
        raise RuntimeError('CANARY_NATIVE_ERROR')
    def nonbool():
        return 1
    callback = stopped
    if fault == 'cancel':
        model.cancelled = True
    elif fault == 'expired':
        model.now = 105.0
    elif fault == 'regression':
        times = iter([100.0, 99.0])
        ram.time.monotonic = lambda: next(times)
    elif fault == 'callback':
        callback = exploding
    else:
        callback = nonbool
    with pytest.raises(ram.NativeRamUnknown, match='^budget_unknown$'):
        pins.verify(deadline=105, cancelled=callback)
    with pytest.raises(ram.NativeRamRefused, match='^terminal$'):
        pins.verify(deadline=105)
    pins.close()
    assert not model.fds and ram._RUNTIME + '/denied-exec' in model.nodes


@pytest.mark.parametrize('kwargs', [dict(binding={}), dict(seed_sha256='X' * 64), dict(deadline=True),
                                    dict(deadline=float('nan')), dict(deadline=106), dict(cancelled=None)])
def test_invalid_context_never_opens_a_descriptor(model, kwargs):
    with pytest.raises(ram.NativeRamRefused):
        acquire(model, **kwargs)
    assert not any(event[0] == 'open' for event in model.events)


@pytest.mark.parametrize('raw,limit,refused', [(b'abc', 3, False), (b'abcd', 3, True), (b'', 3, False)])
def test_bounded_system_reader_closes_once_on_success_or_overflow(model, raw, limit, refused):
    parts = [raw, b'']
    model.os.read = lambda fd, count: parts.pop(0)
    budget = ram._Budget(105, lambda: False)
    if refused:
        with pytest.raises(ram.NativeRamRefused, match='^input_bound$'):
            _REAL_READ('/', limit, budget)
    else:
        assert _REAL_READ('/', limit, budget) == raw
    assert not model.fds and len(model.closed) == 1


def test_system_reader_uncertain_close_is_not_retried(model):
    model.os.read = lambda fd, count: b''
    model.close_errors.add(10)
    with pytest.raises(ram.NativeRamUnknown, match='^descriptor_cleanup_unknown$'):
        _REAL_READ('/', 1, ram._Budget(105, lambda: False))
    assert model.closed == [10] and not model.fds


def test_candidate_stays_out_of_actual_public_and_inspection_payloads():
    from night_shifts.bootstrap_probe_seed import SOURCE_FILES
    from night_shifts.inspection_bundle import bundle_bytes
    assert 'bootstrap_native_ram.py' not in SOURCE_FILES
    with zipfile.ZipFile(io.BytesIO(bundle_bytes())) as archive:
        assert 'night_shifts/bootstrap_native_ram.py' not in archive.namelist()
