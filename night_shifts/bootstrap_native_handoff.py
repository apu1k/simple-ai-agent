"""Fixed validation-only NoCloud FILES in memory; NOT ISO/boot authorization.

No output paths, downloads, media writes, native tools, keys, policy load or VM.
Snapshots are consistency data; future protected author/runner must independently
review, pin/read-lock COMPLETE media and own one fresh diskless VM/watchdog.
The public probe seed/inventory and publication handoff remain unchanged.
"""
from __future__ import annotations

import base64
import hashlib
import stat
from dataclasses import dataclass, field
from pathlib import Path

from night_shifts.bootstrap_probe_seed import validate_public_probe_seed
from night_shifts.guest import bootstrap_native_boot as boot
from night_shifts.maintenance_tls_prototype import AttemptBinding

MAX_COMMAND_BYTES = 100000
MAX_USER_DATA = 128 * 1024


class NativeHandoffRefused(RuntimeError):
    """Fixed labels only; never source, archive or public payload text."""


@dataclass(frozen=True)
class NativeValidationHandoff:
    """Credential-free bytes only, not native execution, media or host receipt."""

    user_data: bytes = field(repr=False)
    meta_data: bytes
    network_config: bytes
    support_zip: bytes = field(repr=False)
    validator_zip: bytes = field(repr=False)
    bootstrap_sha256: str
    seed_sha256: str
    payload_sha256: str
    policy_sha256: str

    def files(self) -> dict[str, bytes]:
        return {'user-data': self.user_data, 'meta-data': self.meta_data,
                'network-config': self.network_config, 'support.zip': self.support_zip,
                'validator.zip': self.validator_zip}


def _snapshot(name: str) -> bytes:
    if name not in boot.NATIVE_SOURCES:
        raise NativeHandoffRefused('source_inventory')
    path = Path(__file__).with_name(name) if '/' not in name else Path(__file__).parent / name
    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not 0 < before.st_size <= boot.MAX_ENTRY:
            raise NativeHandoffRefused('source_shape')
        raw = path.read_bytes()
        after = path.lstat()
        if len(raw) != before.st_size or any(getattr(before, key) != getattr(after, key)
            for key in ('st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_gid', 'st_nlink',
                        'st_size', 'st_mtime_ns', 'st_ctime_ns')):
            raise NativeHandoffRefused('source_changed')
        return raw.decode('utf-8').replace('\r\n', '\n').encode('utf-8')
    except (OSError, UnicodeError):
        raise NativeHandoffRefused('source_read') from None


def render_native_validation_handoff(
    binding: AttemptBinding, support_zip: bytes, *, expected_seed_sha256: str,
) -> NativeValidationHandoff:
    """Render only fixed catalog/argv; no caller source/command/file overrides.

    Validates the existing public seed with its full validator; copies its public
    source bytes unchanged, snapshots eleven fixed native components, then builds
    and validates a separate canonical source ZIP. No extraction or activation.
    """
    public = validate_public_probe_seed(support_zip, binding, expected_sha256=expected_seed_sha256)
    sources = {name: public[name] for name in (*boot.EMPTY_FILES,
               *('night_shifts/' + name for name in boot._PUBLIC_SOURCES))}
    for name in boot.NATIVE_SOURCES:
        sources['night_shifts/' + name] = _snapshot(name)
    context = {'attempt_id': binding.attempt_id, 'vm_id': binding.vm_id,
               'seed_sha256': expected_seed_sha256}
    manifest = boot._manifest(sources, context, 'native-validator-only')
    payload = boot._zip({**sources, 'manifest.json': manifest})
    context['payload_sha256'] = hashlib.sha256(payload).hexdigest()
    boot.validate_inputs(context, support_zip, payload)
    source = sources[boot.BOOT_ENTRY]
    bootstrap_sha = hashlib.sha256(source).hexdigest()
    code = (
        'import base64,hashlib,os\n'
        'try:\n'
        ' s=base64.b64decode(' + repr(base64.b64encode(source).decode('ascii')) + ',validate=True)\n'
        ' if hashlib.sha256(s).hexdigest()!=' + repr(bootstrap_sha) + ': raise ValueError()\n'
        ' g={"__name__":"_night_shift_native_boot"}\n'
        ' exec(compile(s,"<fixed-native-boot>","exec",dont_inherit=True),g)\n'
        ' g["boot"](' + repr(context) + ',trusted_source=s)\n'
        'except BaseException:\n'
        ' try: os.write(1,' + repr(boot._UNKNOWN) + ')\n'
        ' except BaseException: pass\n'
        ' os._exit(125)\n'
        'os._exit(0)\n'
    )
    if len(code.encode('ascii')) > MAX_COMMAND_BYTES:
        raise NativeHandoffRefused('command_bound')
    cloud = {'users': [], 'disable_root': True, 'ssh_pwauth': False, 'package_update': False,
             'package_upgrade': False, 'manage_etc_hosts': False,
             'runcmd': [['/usr/bin/env', '-i', 'LANG=C', 'LC_ALL=C', '/usr/bin/python3.12',
                        '-I', '-B', '-S', '-c', code]]}
    user_data = b'#cloud-config\n' + boot._json(cloud)
    meta_data = boot._json({'instance-id': 'night-shift-native-' + binding.attempt_id,
                            'local-hostname': 'night-shift-native-validation'})
    network = boot._json({'version': 2, 'ethernets': {}})
    if len(user_data) > MAX_USER_DATA or len(meta_data) > 512:
        raise NativeHandoffRefused('handoff_bound')
    return NativeValidationHandoff(user_data, meta_data, network, support_zip, payload,
        bootstrap_sha, expected_seed_sha256, context['payload_sha256'], boot.POLICY_SHA256)
