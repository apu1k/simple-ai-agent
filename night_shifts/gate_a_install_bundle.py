"""Build a reviewable, offline Gate A task bundle without elevation or downloads."""
from __future__ import annotations

import argparse
import hashlib
import io
import re
import stat
import zipfile
from pathlib import Path, PurePosixPath

from night_shifts.gate_a_run import REPO, TEST_FILE

_WHEELS = {
    'pytest': ('_pytest', 'pytest', 'py.py'), 'iniconfig': ('iniconfig',), 'pluggy': ('pluggy',),
    'pygments': ('pygments',), 'packaging': ('packaging',), 'colorama': ('colorama',),
}
_PYTHON_REQUIRED = {'python.exe', 'python314.zip', 'python314.dll'}
_PYTHON_PATH = b'python314.zip\n.\n..\\app\n..\\app\\vendor\n'
_LIMIT = 64 * 1024 * 1024
_PART = re.compile(r'[a-zA-Z0-9_][A-Za-z0-9_.-]*')
_RESERVED = re.compile(r'CON|NUL|PRN|AUX|COM[0-9]|LPT[0-9]', re.IGNORECASE)


def _parts(name: str) -> list[str]:
    parts = name.split('/')
    if (len(name) > 175 or not all(_PART.fullmatch(p) and not p.endswith('.')
                                   and not _RESERVED.fullmatch(p.split('.')[0]) for p in parts)):
        raise ValueError(f'unsafe bundle path: {name!r}')
    return parts


def _read_archive(path: Path) -> dict[str, bytes]:
    contents: dict[str, bytes] = {}
    seen: set[str] = set()
    with path.open('rb') as stream:
        raw = stream.read(_LIMIT + 1)
    if len(raw) > _LIMIT:
        raise ValueError('archive exceeds input limit')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        files = archive.infolist()
        if len(files) > 4096 or sum(i.file_size for i in files) > _LIMIT:
            raise ValueError('archive exceeds expansion limit')
        for item in files:
            _parts(item.filename.rstrip('/') if item.is_dir() else item.filename)
            if item.is_dir():
                continue
            if item.filename.lower() in seen or stat.S_ISLNK(item.external_attr >> 16):
                raise ValueError('archive contains duplicate or linked members')
            seen.add(item.filename.lower())
            contents[item.filename] = archive.read(item)
    return contents


def _wheel(name: str, path: Path) -> dict[str, bytes]:
    if not re.fullmatch(re.escape(name) + r'-.+-py[23][\w.]*-none-any\.whl', path.name, re.IGNORECASE):
        raise ValueError(f'expected the reviewed pure Python {name} wheel')
    package = _read_archive(path)
    for filename in package:
        first = _parts(filename)[0]
        if first not in _WHEELS[name] and not (first.startswith(name + '-') and first.endswith('.dist-info')):
            raise ValueError(f'unexpected wheel member: {filename}')
        if filename.lower().endswith(('.pth', '.pyc', '.dll', '.pyd', '.exe')):
            raise ValueError(f'unexpected wheel startup hook or native payload: {filename}')
    return {'app/vendor/' + filename: data for filename, data in package.items()}


def build_bundle(output: Path, python_zip: Path, wheels: dict[str, Path]) -> str:
    if set(wheels) != _WHEELS.keys():
        raise ValueError('supply exactly the six named wheels')
    runtime = _read_archive(python_zip)
    if not _PYTHON_REQUIRED <= runtime.keys():
        raise ValueError('use the reviewed x64 CPython 3.14 Windows embeddable ZIP')
    files = {'python/' + name: data for name, data in runtime.items()
             if '/' not in name and (name in _PYTHON_REQUIRED or name == 'LICENSE.txt'
                                     or name.endswith(('.dll', '.pyd')))}
    files['python/python314._pth'] = _PYTHON_PATH
    files['app/gate-a-pytest.ini'] = b'[pytest]\n'
    for name, path in wheels.items():
        for filename, data in _wheel(name, path).items():
            if filename in files:
                raise ValueError(f'duplicate bundled dependency file: {filename}')
            files[filename] = data
    # No checkout .env, Git metadata, config, conftest, or external pytest plugins.
    source_paths = [p for p in (REPO / 'night_shifts').rglob('*') if p.is_file()
                    and p.suffix in ('.py', '.ps1') and '__pycache__' not in p.parts]
    source_paths.append(REPO / TEST_FILE)
    for path in source_paths:
        if path.resolve() != path or not path.is_file():
            raise ValueError(f'refusing linked source: {path}')
        name = 'app/' + path.relative_to(REPO).as_posix()
        files[name] = path.read_bytes()
    if len(files) > 4096 or sum(map(len, files.values())) > _LIMIT:
        raise ValueError('bundle exceeds installation limits')
    blob = io.BytesIO()
    with zipfile.ZipFile(blob, 'w', compression=zipfile.ZIP_STORED) as out:
        seen: set[str] = set()
        for name, data in sorted(files.items()):
            _parts(name)
            if name.lower() in seen:
                raise ValueError(f'duplicate bundle member: {name}')
            seen.add(name.lower())
            out.writestr(zipfile.ZipInfo(PurePosixPath(name).as_posix()), data)
    data = blob.getvalue()
    if len(data) > _LIMIT:
        raise ValueError('bundle exceeds installation limits')
    with output.open('xb') as stream:
        stream.write(data)
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--python-zip', required=True, type=Path)
    for name in _WHEELS:
        parser.add_argument('--' + name, required=True, type=Path)
    args = parser.parse_args()
    print(build_bundle(args.output, args.python_zip, {name: getattr(args, name) for name in _WHEELS}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
