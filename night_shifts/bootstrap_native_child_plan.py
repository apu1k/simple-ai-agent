"""Render a fixed setpriv/fresh-Python child plan IN MEMORY, never execute it.

Only the current fixed bootstrap and hard-pinned worker snapshots are accepted.
No caller-selected command, source, path, environment, boot or deployment API.
An immutable externally reviewed complete-media boundary is still required;
self-computed source hashes or this plan cannot authenticate a guest/launcher.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import re
import stat
import time
from dataclasses import dataclass, field
from pathlib import Path

from night_shifts.guest.bootstrap_native_child import MAX_CONTEXT_BYTES, MAX_SOURCE_BYTES, WORKER_SHA256
from night_shifts.maintenance_tls_prototype import AttemptBinding

MAX_COMMAND_BYTES = 100000
_SET_PRIV = (
    '/usr/bin/setpriv', '--bounding-set=-all', '--inh-caps=-all', '--ambient-caps=-all',
    '--no-new-privs', '--reuid=0', '--regid=0', '--clear-groups', '--',
    '/usr/bin/python3.12', '-I', '-B', '-S', '-c',
)


class NativeChildPlanRefused(RuntimeError):
    """Fixed label only; never source, arguments or native exception text."""


@dataclass(frozen=True)
class NativeChildPlan:
    """Plan only, NOT a spawned child, resource handle, authorization or receipt.

    Future owner must use argv directly (shell=False), close_fds=True, precisely
    pass_fds, stdin/stdout/stderr=DEVNULL, this exact environment and cwd='/',
    retaining exact child ownership independently. No preexec_fn is needed.
    """

    argv: tuple[str, ...] = field(repr=False)
    pass_fds: tuple[int, int]
    environment: tuple[tuple[str, str], ...] = (('LANG', 'C'), ('LC_ALL', 'C'))
    cwd: str = '/'


def _source(name: str) -> bytes:
    if name not in ('bootstrap_native_child.py', 'bootstrap_native_worker.py'):
        raise NativeChildPlanRefused('source')
    path = Path(__file__).with_name('guest') / name
    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not 0 < before.st_size <= MAX_SOURCE_BYTES:
            raise NativeChildPlanRefused('source')
        raw = path.read_bytes()
        after = path.lstat()
        if len(raw) != before.st_size or any(
            getattr(before, name) != getattr(after, name)
            for name in ('st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_gid', 'st_nlink',
                         'st_size', 'st_mtime_ns', 'st_ctime_ns')
        ):
            raise NativeChildPlanRefused('source_changed')
        return raw.decode('utf-8').replace('\r\n', '\n').encode('utf-8')
    except (OSError, UnicodeError):
        raise NativeChildPlanRefused('source') from None


def _remaining(deadline: float, previous: float) -> float:
    now = time.monotonic()
    if (type(now) not in (int, float) or not math.isfinite(now) or not previous <= now <= 1e15
            or not 0 < deadline - now <= 5):
        raise NativeChildPlanRefused('deadline')
    return float(now)


def render_native_child_plan(
    binding: AttemptBinding, case_id: str, mode: str, *, seed_sha256: str,
    deadline: float, report_fd: int, gate_fd: int,
) -> NativeChildPlan:
    """Render only; deadline must be from the intended supervisor's guest clock.

    Original report WRITE/gate READ ends must already be distinct nonblocking
    root-owned pipes. The standalone child verifies that and remaps them itself.
    Preparing a plan does not create pipes, spawn, reap, stop or release a gate.
    """
    if (type(binding) is not AttemptBinding or type(case_id) is not str
            or case_id not in ('runtime_write', 'pool_sibling_write', 'outside_exec', 'allowed_pools')
            or type(mode) is not str or mode not in ('control', 'confined')
            or (case_id == 'allowed_pools' and mode != 'confined')
            or type(seed_sha256) is not str or re.fullmatch('[0-9a-f]{64}', seed_sha256) is None
            or type(deadline) not in (int, float) or not 0 <= deadline <= 1e15 or not math.isfinite(deadline)
            or any(type(fd) is not int or not 3 <= fd < 1 << 20 for fd in (report_fd, gate_fd))
            or report_fd == gate_fd):
        raise NativeChildPlanRefused('context')
    started = _remaining(deadline, 0)
    context = {'attempt_id': binding.attempt_id, 'vm_id': binding.vm_id, 'seed_sha256': seed_sha256,
               'case_id': case_id, 'mode': mode, 'deadline': repr(float(deadline)),
               'report_fd': report_fd, 'gate_fd': gate_fd}
    raw = json.dumps(context, sort_keys=True, separators=(',', ':')).encode('ascii')
    if len(raw) > MAX_CONTEXT_BYTES:
        raise NativeChildPlanRefused('context')
    entry, worker = _source('bootstrap_native_child.py'), _source('bootstrap_native_worker.py')
    if hashlib.sha256(worker).hexdigest() != WORKER_SHA256:
        raise NativeChildPlanRefused('worker_digest')
    entry64, worker64, context64 = (base64.b64encode(item).decode('ascii') for item in (entry, worker, raw))
    # Bootstrap text is itself part of the complete immutable media review. Its
    # self-hash detects substitution here, not an untrusted media/host provider.
    code = (
        'import base64,hashlib,os\n'
        'try:\n'
        ' s=base64.b64decode(' + repr(entry64) + ',validate=True)\n'
        ' if hashlib.sha256(s).hexdigest()!=' + repr(hashlib.sha256(entry).hexdigest()) + ': raise ValueError()\n'
        ' g={"__name__":"_night_shift_native_child"}\n'
        ' exec(compile(s,"<fixed-native-child>","exec",dont_inherit=True),g)\n'
        ' r=g["enter"](base64.b64decode(' + repr(context64) + ',validate=True),'
        'base64.b64decode(' + repr(worker64) + ',validate=True))\n'
        ' if type(r) is not int or r!=0: raise ValueError()\n'
        'except BaseException:\n'
        ' os._exit(125)\n'
        'os._exit(0)\n'
    )
    if len(code.encode('ascii')) > MAX_COMMAND_BYTES:
        raise NativeChildPlanRefused('command_bound')
    _remaining(deadline, started)
    return NativeChildPlan((*_SET_PRIV, code), (report_fd, gate_fd))
