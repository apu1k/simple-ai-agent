#!/usr/bin/env python3
"""Clean ONE bare-attached Gate A image copy inside WSL.

Invoked only by ``night_shifts.gate_a_run`` as root in WSL, from a staging
directory holding LF-normalized copies of the reviewed guest modules. It mounts
the copy's ext4 partition, runs the existing fail-closed ``finalize()`` policy,
flushes, unmounts and prints one JSON receipt line. It never boots the image.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

try:
    from night_shifts.guest import finalize_image_copy as cleanup
except ModuleNotFoundError:  # Staged standalone copy inside WSL.
    import importlib

    cleanup = importlib.import_module('finalize_image_copy')

DISK_BYTES = 20 * 1024**3


def run(*argv: str) -> str:
    result = subprocess.run(argv, capture_output=True, text=True, timeout=120, check=False)
    if result.returncode != 0:
        raise cleanup.FinalizationError(f'{argv[0]} exited {result.returncode}')
    return result.stdout


def check_layout(tree: Any, device: str) -> str:
    """Accept only the expected 20 GiB vfat+ext4 disk, unmounted; return the ext4 partition."""
    cleanup.require(re.fullmatch(r'/dev/sd[a-z]{1,2}', device) is not None)
    disks = tree['blockdevices']
    cleanup.require(isinstance(disks, list) and len(disks) == 1)
    disk = disks[0]
    cleanup.require(disk['path'] == device and disk['type'] == 'disk' and int(disk['size']) == DISK_BYTES)
    parts = disk.get('children') or []
    cleanup.require([(p['path'], p['type'], p['fstype']) for p in parts]
                    == [(device + '1', 'part', 'vfat'), (device + '2', 'part', 'ext4')])
    cleanup.require(all(not any(entry.get('mountpoints') or []) for entry in [disk, *parts]))
    return device + '2'


def replace_bootstrap(root: Path, upgrade: Any, replacement: bytes, unit_sha256: str) -> dict[str, str]:
    """Install the reviewed guest script over the exact one the image shipped with."""
    cleanup.require(isinstance(upgrade, dict) and set(upgrade) == {'from', 'to'})
    cleanup.require(all(isinstance(v, str) and cleanup.DIGEST.fullmatch(v) for v in upgrade.values()))
    cleanup.require(hashlib.sha256(replacement).hexdigest() == upgrade['to'])
    name = cleanup.audit._BOOTSTRAP
    cleanup.require(hashlib.sha256(cleanup.regular(root, name)).hexdigest() == upgrade['from'])
    target = cleanup.path(root, name)
    staged = target.with_name(target.name + '.new')
    cleanup.require(not cleanup.present(staged))
    with staged.open('xb') as stream:
        stream.write(replacement)
        stream.flush()
        os.fsync(stream.fileno())
    staged.chmod(0o644)
    os.replace(staged, target)
    cleanup.audit._payload(upgrade['to'], unit_sha256)
    return {'bootstrap_from': upgrade['from'], 'bootstrap_to': upgrade['to']}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--device', required=True)
    parser.add_argument('--workdir', required=True)
    args = parser.parse_args(argv)
    receipt: dict[str, Any] = {'version': 1, 'status': 'failed', 'unmounted': False}
    root: Path | None = None
    mounted = False
    try:
        cleanup.require(getattr(os, 'geteuid', lambda: -1)() == 0)
        cleanup.require('microsoft' in Path('/proc/sys/kernel/osrelease').read_text().lower())
        work = Path(args.workdir)
        request = cleanup.validate_request(json.loads((work / 'request.json').read_bytes()))
        cleanup.require(request['mode'] == 'finalize')
        receipt['id'] = request['id']
        unit = (work / 'night-shift-protocol-test.service').read_bytes()
        tree = json.loads(run('/usr/bin/lsblk', '--json', '--tree', '-b',
                              '-o', 'PATH,TYPE,SIZE,FSTYPE,MOUNTPOINTS', args.device))
        partition = check_layout(tree, args.device)
        root = Path('/run/night-shift-wsl-finalize-' + request['id'])
        root.mkdir(mode=0o700)
        run('/usr/bin/mount', '-t', 'ext4', '-o', 'rw,nodev,nosuid,noexec', partition, str(root))
        mounted = True
        receipt.update(cleanup.finalize(root, request, unit))
        receipt.update(replace_bootstrap(root, json.loads((work / 'bootstrap-upgrade.json').read_bytes()),
                                         (work / 'protocol_test_bootstrap.py').read_bytes(),
                                         request['payload']['unit']))
        run('/usr/bin/sync')
        receipt['status'] = 'success'
    except Exception as exc:
        receipt['status'] = 'failed'
        receipt['error'] = f'{type(exc).__name__}: {exc}'[:500]
    finally:
        try:
            if mounted and root is not None:
                run('/usr/bin/umount', str(root))
            if root is not None and root.exists():
                cleanup.require(str(root) not in run('/usr/bin/findmnt', '--json', '-o', 'TARGET'))
                root.rmdir()
            receipt['unmounted'] = True
        except Exception as exc:
            receipt['status'] = 'failed'
            receipt['unmount_error'] = f'{type(exc).__name__}: {exc}'[:500]
    print(json.dumps(receipt, sort_keys=True), flush=True)
    return 0 if receipt['status'] == 'success' else 1


if __name__ == '__main__':
    raise SystemExit(main())
