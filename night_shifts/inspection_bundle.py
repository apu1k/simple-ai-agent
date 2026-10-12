"""Offline, write-once deployment bundle; never install, elevate or call Hyper-V."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import stat
import zipfile
from pathlib import Path

FILES = (
    'inspection_worker.py', 'image_finalization.py', 'maintenance_runner.py',
    'hyperv_image_preflight.py', 'ubuntu_preparation_control.py', 'protocol_image_bundle.py',
    'guest/finalize_image_copy.py', 'guest/protocol_test_bootstrap.py',
    'guest/review_protocol_test_target.py', 'guest/night-shift-protocol-test.service',
    'backends/hyperv_scripts/maintain_image_copy.ps1',
)
MAX_BUNDLE_BYTES = 4 * 1024 * 1024


def bundle_bytes() -> bytes:
    """Snapshot only fixed assets and the installed pure-Python pycdlib package.

    Review these bytes and dependency provenance before approving their digest.
    Empty package initializers deliberately exclude the app/provider imports.
    """
    source = Path(__file__).resolve().parent
    entries = {'night_shifts/__init__.py': b'', 'night_shifts/guest/__init__.py': b'',
               'night_shifts/backends/__init__.py': b''}
    for name in FILES:
        path = source / name
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 128 * 1024:
            raise ValueError('deployment asset is not a bounded regular single-link file')
        entries['night_shifts/' + name] = path.read_bytes()
    spec = importlib.util.find_spec('pycdlib')
    if spec is None or not spec.origin:
        raise ValueError('install the pinned pycdlib development dependency first')
    dependency = Path(spec.origin).parent
    paths = sorted(dependency.glob('*.py'))
    if not 1 <= len(paths) <= 64:
        raise ValueError('unexpected pycdlib package layout')
    for path in paths:
        info = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 1024 * 1024:
            raise ValueError('unsafe pycdlib source')
        entries['pycdlib/' + path.name] = path.read_bytes()
    manifest = {name: hashlib.sha256(raw).hexdigest() for name, raw in sorted(entries.items())}
    entries['manifest.json'] = (json.dumps(manifest, sort_keys=True) + '\n').encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_STORED) as archive:
        for name, raw in sorted(entries.items()):
            item = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            item.external_attr = 0o100644 << 16
            archive.writestr(item, raw)
    result = output.getvalue()
    if len(result) > MAX_BUNDLE_BYTES:
        raise ValueError('deployment bundle exceeds bound')
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    # Operator-only authoring; no overwriting or auto-installing the result.
    if not args.output.is_absolute() or args.output.suffix.lower() != '.zip':
        parser.error('an absolute new .zip output path is required')
    from night_shifts.hyperv_image_preflight import _checked_path
    _checked_path(args.output.parent, 'bundle output parent')
    raw = bundle_bytes()
    with args.output.open('xb') as stream:
        stream.write(raw)
    print(json.dumps({'bundle': str(args.output), 'sha256': hashlib.sha256(raw).hexdigest(),
                      'installed': False, 'launch_authorized': False}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
