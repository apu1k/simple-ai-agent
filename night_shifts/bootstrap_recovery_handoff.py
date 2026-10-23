"""Offline NoCloud FILES for the opt-in RAM-only recovery launcher, not an ISO.

No paths supplied by callers, downloads, writes, commands, key generation or VM
operations. Applying source/rendering bytes does NOT authorize policy loading,
mounting media, running the daemon, or deploying boot media. A future protected
runner must authenticate/pin all media and the exact fresh diskless VM BEFORE
cloud-init executes any user-data. Internal hashes alone are not that authority.
"""
from __future__ import annotations

import base64
import hashlib
import json
import stat
from dataclasses import dataclass, field
from pathlib import Path

from night_shifts.bootstrap_probe_seed import validate_public_probe_seed
from night_shifts.maintenance_tls_prototype import AttemptBinding

MAX_COMMAND_BYTES = 100000  # below Linux's per-argument 128 KiB limit
MAX_USER_DATA = 128 * 1024
MAX_LAUNCHER_BYTES = 64 * 1024
POLICY_ENTRY = 'night_shifts/guest/bootstrap-public-probe.apparmor'


class RecoveryHandoffRefused(RuntimeError):
    """Fixed labels only; no source, media or public payload text."""


@dataclass(frozen=True)
class RecoveryHandoff:
    """Credential-free in-memory files, NOT boot/deployment/native evidence."""

    user_data: bytes = field(repr=False)
    meta_data: bytes
    network_config: bytes
    support_zip: bytes = field(repr=False)
    launcher_sha256: str
    seed_sha256: str
    policy_sha256: str

    def files(self) -> dict[str, bytes]:
        return {'user-data': self.user_data, 'meta-data': self.meta_data,
                'network-config': self.network_config, 'support.zip': self.support_zip}


def _json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True) + '\n').encode('ascii')


def _launcher_source() -> bytes:
    path = Path(__file__).with_name('guest') / 'bootstrap_recovery_launcher.py'
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or not 0 < info.st_size <= MAX_LAUNCHER_BYTES):
        raise RecoveryHandoffRefused('launcher_shape')
    raw = path.read_bytes()
    if len(raw) != info.st_size:
        raise RecoveryHandoffRefused('launcher_changed')
    try:
        return raw.decode('utf-8').replace('\r\n', '\n').encode('utf-8')
    except UnicodeError:
        raise RecoveryHandoffRefused('launcher_encoding') from None


def render_recovery_handoff(
    binding: AttemptBinding, support_zip: bytes, *, expected_seed_sha256: str,
) -> RecoveryHandoff:
    """Render only fixed NoCloud bytes; no arbitrary scripts, keys or files.

    Only actual reviewed data from the fixed builder is accepted by its validator.
    This snapshots the current launcher, not an independently authenticated guest.
    The root handoff is code on public media; the future exact-VM controller must
    protect and read-lock the COMPLETE media before use, not trust self-supplied
    digests from a guest or a broadly readable serial pipe.
    """
    entries = validate_public_probe_seed(support_zip, binding, expected_sha256=expected_seed_sha256)
    source = _launcher_source()
    launcher_sha = hashlib.sha256(source).hexdigest()
    policy_sha = hashlib.sha256(entries[POLICY_ENTRY]).hexdigest()
    context = {'attempt_id': binding.attempt_id, 'vm_id': binding.vm_id,
               'seed_sha256': expected_seed_sha256, 'policy_sha256': policy_sha}
    # Source is carried in the trusted user-data, not imported from the seed or
    # found via cwd/PATH. The large ZIP stays a data file on the same pinned CIDATA
    # optical volume, avoiding Linux's per-argument size limit. No write_files.
    code = (
        'import base64,hashlib\n'
        'try:\n'
        ' s=base64.b64decode(' + repr(base64.b64encode(source).decode('ascii')) + ',validate=True)\n'
        ' if hashlib.sha256(s).hexdigest()!=' + repr(launcher_sha) + ': raise ValueError()\n'
        ' g={"__name__":"_night_shift_trusted_recovery"}\n'
        ' exec(compile(s,"<trusted-recovery-launcher>","exec"),g)\n'
        ' g["boot"](' + repr(context) + ',trusted_source=s)\n'
        'except Exception:\n'
        ' print(\'{"outcome":"unknown","reason":"recovery_boot_unknown"}\')\n'
        ' raise SystemExit(1)\n'
    )
    if len(code.encode('ascii')) > MAX_COMMAND_BYTES:
        raise RecoveryHandoffRefused('command_bound')
    cloud = {
        'users': [], 'disable_root': True, 'ssh_pwauth': False,
        'package_update': False, 'package_upgrade': False, 'manage_etc_hosts': False,
        'runcmd': [['/usr/bin/python3.12', '-I', '-B', '-S', '-c', code]],
    }
    user_data = b'#cloud-config\n' + _json(cloud)
    meta_data = _json({'instance-id': 'night-shift-bootstrap-' + binding.attempt_id,
                       'local-hostname': 'night-shift-bootstrap'})
    network = _json({'version': 2, 'ethernets': {}})
    if len(user_data) > MAX_USER_DATA or len(meta_data) > 512:
        raise RecoveryHandoffRefused('seed_bound')
    return RecoveryHandoff(user_data, meta_data, network, support_zip,
                           launcher_sha, expected_seed_sha256, policy_sha)
