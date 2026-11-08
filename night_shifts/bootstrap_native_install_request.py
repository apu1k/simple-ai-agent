"""Memory-only installation-request contract; unwired HOST reviewer, stdlib only.

No acquisition, snapshots, carried-code import, approval, claim, clock, process or
VM operation. Independent reviewed byte pins are mandatory. This host module is
NOT in the carried Python bundle/import inventory and cannot establish pre-load
trust or supply the protected approval channel. Never run checkout code elevated.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import cast

MAX_REQUEST_BYTES = 32768
MAX_WORKER_BYTES = 8192
MAX_REVIEW_BYTES = 65536
MAX_GUARDIAN_PROFILE_BYTES = 2048
GUARDIAN_PROFILE_SCOPE = 'reviewed_guardian_build_references_not_authorization'
OPERATION = 'native_validator_provision_once'
SCOPE = 'reviewed_installation_inputs_not_authorization'
WORKER_SCOPE = 'bound_worker_request_not_authorization'
# Independent catalogs: cross-layer regressions bind these to the deployment
# and pre-import boundary. The request cannot choose any executable/import name.
RUNTIME_NAMES = tuple(sorted((
    'python.exe', 'pythonw.exe', 'python314.dll', 'python3.dll', 'vcruntime140.dll',
    'vcruntime140_1.dll', 'LICENSE.txt', 'pyexpat.pyd', 'select.pyd', 'unicodedata.pyd',
    'winsound.pyd', '_asyncio.pyd', '_bz2.pyd', '_ctypes.pyd', '_decimal.pyd',
    '_elementtree.pyd', '_hashlib.pyd', '_lzma.pyd', '_multiprocessing.pyd', '_overlapped.pyd',
    '_queue.pyd', '_remote_debugging.pyd', '_socket.pyd', '_sqlite3.pyd', '_ssl.pyd',
    '_uuid.pyd', '_wmi.pyd', '_zoneinfo.pyd', '_zstd.pyd', 'libcrypto-3.dll', 'libffi-8.dll',
    'libssl-3.dll', 'libtommath.dll', 'sqlite3.dll', 'python314.zip', 'python314._pth', 'python.cat',
)))
CODE_NAMES = tuple(sorted((
    '__init__.py', 'guest/__init__.py', 'bootstrap_daemon_asset.py', 'bootstrap_probe_seed.py',
    'bootstrap_native_deployment.py', 'bootstrap_native_provision.py', 'bootstrap_native_handoff.py',
    'bootstrap_native_media.py', 'bootstrap_native_media_store.py', 'bootstrap_native_fixture.py',
    'bootstrap_native_denials.py', 'bootstrap_native_supervision.py', 'bootstrap_native_ram.py',
    'bootstrap_native_child_plan.py', 'bootstrap_native_owner.py', 'bootstrap_native_capture.py',
    'bootstrap_native_sequence.py', 'guest/bootstrap_native_child.py', 'guest/bootstrap_native_worker.py',
    'guest/bootstrap_native_boot.py', 'guest/bootstrap_public_probe.py', 'guest/bootstrap-public-probe.apparmor',
    'guest/publish_public_bootstrap.py', 'public_bootstrap_kvp.py', 'maintenance_credentials_prototype.py',
    'maintenance_tls_prototype.py', 'maintenance_store_native_prototype.py', 'ubuntu_preparation_control.py',
    'hyperv_image_preflight.py',
)))
CODEC_NAMES = tuple(sorted((
    *('pycdlib/' + name for name in ('__init__.py', 'dates.py', 'dr.py', 'eltorito.py', 'facade.py',
        'headervd.py', 'inode.py', 'inplaceeditor.py', 'isohybrid.py', 'path_table_record.py', 'pycdlib.py',
        'pycdlibexception.py', 'pycdlibio.py', 'rockridge.py', 'udf.py', 'utils.py', 'py.typed')),
    *('pycdlib-1.21.0.dist-info/' + name for name in ('METADATA', 'WHEEL', 'licenses/COPYING')),
)))
IMPORT_NAMES = tuple(sorted((*('runtime/' + n for n in RUNTIME_NAMES),
    *('payload/night_shifts/' + n for n in CODE_NAMES), *('payload/' + n for n in CODEC_NAMES))))
LAUNCH_NAMES = tuple(sorted(('validator-install-guardian.exe', 'validator-install-guardian.exe.config',
    'validator-provision-worker.exe', 'validator-provision-worker.exe.config')))
_PTH = b'python314.zip\r\n.\r\n\r\n# Uncomment to run site.main() automatically\r\n#import site\r\n'
_CONFIG = (b'<?xml version="1.0" encoding="utf-8"?>\n<configuration><startup useLegacyV2RuntimeActivationPolicy="false">'
    b'<supportedRuntime version="v4.0" sku=".NETFramework,Version=v4.8"/></startup>'
    b'<runtime><loadFromRemoteSources enabled="false"/></runtime></configuration>\n')
_EMPTY = frozenset(('payload/night_shifts/__init__.py', 'payload/night_shifts/guest/__init__.py'))
_ROOT_FIELDS = ('version', 'scope', 'operation', 'installation_id', 'operator_sid', 'budget_seconds',
    'expires_unix', 'launch_anchor', 'import_anchor', 'provision')


class InstallRequestRefused(RuntimeError):
    """Fixed labels only, not input/path/parser text or approval/acceptance."""


@dataclass(frozen=True)
class BoundInstallRequest:
    """Local immutable byte projections, not permission to install or execute."""

    request_sha256: str
    worker_request: bytes
    review: bytes


def _json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True) + '\n').encode('ascii')


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _fields(value: object, names: tuple[str, ...]) -> dict[str, object]:
    if type(value) is not dict or set(value) != set(names):
        raise InstallRequestRefused('schema')
    return cast(dict[str, object], value)


def _number(value: object, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise InstallRequestRefused('number')
    return value


def _digest(value: object) -> str:
    if type(value) is not str or re.fullmatch('[0-9a-f]{64}', value) is None:
        raise InstallRequestRefused('digest')
    return value


def _identity(value: object) -> tuple[int, int]:
    fields = _fields(value, ('volume', 'index'))
    return (_number(fields['volume'], 0, 2**32 - 1), _number(fields['index'], 1, 2**64 - 1))


def _path(value: object, maximum: int = 240) -> str:
    if type(value) is not str or not 4 <= len(value) <= maximum or re.match(r'^[A-Z]:\\', value) is None:
        raise InstallRequestRefused('path')
    for part in value[3:].split('\\'):
        if (not 1 <= len(part) <= 120 or re.fullmatch(r'[A-Za-z0-9_ .()\-]+', part) is None
                or part in ('.', '..') or part.endswith((' ', '.'))
                or re.fullmatch(r'(CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])(\..*)?', part, re.I)):
            raise InstallRequestRefused('path')
    return value


def _pin(value: object, maximum: int, *, empty: bool = False) -> tuple[int, str]:
    fields = _fields(value, ('bytes', 'sha256'))
    return _number(fields['bytes'], 0 if empty else 1, maximum), _digest(fields['sha256'])


def _files(value: object, names: tuple[str, ...], *, launch: bool) -> dict[str, dict[str, object]]:
    if type(value) is not list or len(value) != len(names):
        raise InstallRequestRefused('inventory')
    result: dict[str, dict[str, object]] = {}
    for item, expected in zip(value, names):
        fields = _fields(item, ('name', 'bytes', 'sha256'))
        if type(fields['name']) is not str or fields['name'] != expected:
            raise InstallRequestRefused('inventory')
        size, digest = _pin({'bytes': fields['bytes'], 'sha256': fields['sha256']},
            16 * 1024**2 if launch else 32 * 1024**2, empty=expected in _EMPTY)
        fixed = (b'' if expected in _EMPTY else (_PTH if expected == 'runtime/python314._pth'
                 else (_CONFIG if expected.endswith('.exe.config') else None)))
        if fixed is not None and (size != len(fixed) or digest != _sha(fixed)):
            raise InstallRequestRefused('fixed_pin')
        result[expected] = {'bytes': size, 'sha256': digest}
    if not launch and sum(cast(int, pin['bytes']) for pin in result.values()) > 96 * 1024**2 - MAX_WORKER_BYTES:
        raise InstallRequestRefused('closure_bound')
    return result


def _worker(value: dict[str, object], digest: str) -> bytes:
    imp = cast(dict[str, object], value['import_anchor'])
    launch = cast(dict[str, object], value['launch_anchor'])
    return _json({**{name: value[name] for name in ('budget_seconds', 'expires_unix', 'installation_id',
        'operation', 'operator_sid', 'provision')}, 'version': 1, 'scope': WORKER_SCOPE,
        'request_sha256': digest, 'import_anchor': {name: imp[name] for name in ('identity', 'path')},
        'launch_anchor': {name: launch[name] for name in ('identity', 'path', 'scratch_identity')}})


def _validate(value: object) -> dict[str, object]:
    root = _fields(value, _ROOT_FIELDS)
    if (type(root['version']) is not int or root['version'] != 1 or type(root['scope']) is not str
            or root['scope'] != SCOPE or type(root['operation']) is not str or root['operation'] != OPERATION
            or type(root['installation_id']) is not str or re.fullmatch('[0-9a-f]{32}', root['installation_id']) is None):
        raise InstallRequestRefused('schema')
    sid = root['operator_sid']
    if type(sid) is not str or len(sid) > 80 or re.fullmatch(r'S-1-5-21-[0-9]+-[0-9]+-[0-9]+-[0-9]+', sid) is None:
        raise InstallRequestRefused('sid')
    for part in sid.split('-')[4:]:
        if str(int(part)) != part or int(part) > 2**32 - 1:
            raise InstallRequestRefused('sid')
    _number(root['budget_seconds'], 6, 900)
    _number(root['expires_unix'], 1, 253402300799)  # Shape only, NEVER current-time authorization.
    imp = _fields(root['import_anchor'], ('path', 'identity', 'files'))
    launch = _fields(root['launch_anchor'], ('path', 'identity', 'scratch_identity', 'files'))
    provision = _fields(root['provision'], ('source', 'output_parent', 'bundle', 'pins'))
    source = _fields(provision['source'], ('path', 'identity'))
    parent = _fields(provision['output_parent'], ('path', 'identity'))
    paths = (_path(launch['path'], 200), _path(imp['path']), _path(source['path']), _path(parent['path']))
    if len(paths[3] + '\\native-validator-' + cast(str, root['installation_id'])) > 240:
        raise InstallRequestRefused('output_path')
    identities = [_identity(item['identity']) for item in (launch, imp, source, parent)]
    scratch = _identity(launch['scratch_identity'])
    if scratch[0] != identities[0][0] or len(set((*identities, scratch))) != 5:
        raise InstallRequestRefused('identity_alias')
    folded = [path.lower() for path in paths]
    if any(a == b or a.startswith(b + '\\') or b.startswith(a + '\\')
           for i, a in enumerate(folded) for b in folded[i + 1:]):
        raise InstallRequestRefused('path_overlap')
    _files(launch['files'], LAUNCH_NAMES, launch=True)
    files = _files(imp['files'], IMPORT_NAMES, launch=False)
    _pin(provision['bundle'], 64 * 1024**2)
    pins = _fields(provision['pins'], ('code_tree_sha256', 'codec_tree_sha256', 'runtime_sha256',
        'runtime_bytes', 'recovery_sha256', 'recovery_bytes'))
    for name in ('code_tree_sha256', 'codec_tree_sha256', 'runtime_sha256', 'recovery_sha256'):
        _digest(pins[name])
    _number(pins['runtime_bytes'], 1, 32 * 1024**2)
    if _number(pins['recovery_bytes'], 20 * 2048, 8 * 1024**3) % 2048:
        raise InstallRequestRefused('recovery_size')
    for prefix, field in (('payload/night_shifts/', 'code_tree_sha256'), ('payload/', 'codec_tree_sha256')):
        tree = {name[len('payload/'):]: pin for name, pin in files.items()
                if name.startswith(prefix) and (field == 'code_tree_sha256' or not name.startswith('payload/night_shifts/'))}
        if _sha(_json(tree)) != pins[field]:
            raise InstallRequestRefused('tree_pin')
    if len(_worker(root, '0' * 64)) > MAX_WORKER_BYTES:
        raise InstallRequestRefused('worker_bound')
    return root


def build_validation_install_request(value: object) -> bytes:
    """Encode reviewed synthetic/actual plan DATA; do not acquire or approve it."""
    raw = _json(_validate(value))
    if len(raw) > MAX_REQUEST_BYTES:
        raise InstallRequestRefused('request_bound')
    return raw


def bind_validation_install_request(raw: bytes, *, expected_bytes: int, expected_sha256: str) -> BoundInstallRequest:
    """Independent whole-byte pin BEFORE JSON parsing; local consistency only."""
    if (type(raw) is not bytes or type(expected_bytes) is not int or not 0 < expected_bytes <= MAX_REQUEST_BYTES
            or len(raw) != expected_bytes):
        raise InstallRequestRefused('request_pin')
    _digest(expected_sha256)
    if _sha(raw) != expected_sha256:
        raise InstallRequestRefused('request_pin')
    try:
        root = _validate(json.loads(raw.decode('ascii')))
    except (ValueError, UnicodeError, RecursionError):
        raise InstallRequestRefused('request_json') from None
    if _json(root) != raw:
        raise InstallRequestRefused('canonical')
    worker = _worker(root, expected_sha256)
    parent = cast(dict[str, object], cast(dict[str, object], root['provision'])['output_parent'])
    review = _json({'version': 1, 'scope': 'local_install_request_consistency_only',
        'request_sha256': expected_sha256, 'request_bytes': len(raw), 'worker_request_bytes': len(worker),
        'worker_request_sha256': _sha(worker), 'inputs': root,
        'output_directory': cast(str, parent['path']) + '\\native-validator-' + cast(str, root['installation_id'])})
    if len(review) > MAX_REVIEW_BYTES:
        raise InstallRequestRefused('review_bound')
    return BoundInstallRequest(expected_sha256, worker, review)


def build_validation_guardian_profile(value: object) -> bytes:
    """Emit memory-only fixed C# build DATA, never compile/install/approve it.

    Only independent anchor identity/SID/host references are embedded. Request
    and policy hashes MUST NOT enter this profile: the request pins the binaries
    built from it, so embedding those hashes would create a circular pin.
    The future separately trusted build/install/starter must review these bytes
    and establish pre-load provenance; emitted source is not authorization.
    """
    root = _fields(value, ('version', 'scope', 'operator_sid', 'approval_anchor', 'launch_root'))
    _number(root['version'], 1, 1)
    if type(root['scope']) is not str or root['scope'] != GUARDIAN_PROFILE_SCOPE:
        raise InstallRequestRefused('guardian_profile_scope')
    anchor = _fields(root['approval_anchor'], ('path', 'identity'))
    approval = _path(anchor['path'])
    launch = _path(root['launch_root'], 200)
    volume, index = _identity(anchor['identity'])
    if (approval.lower() == launch.lower() or approval.lower().startswith(launch.lower() + '\\')
            or launch.lower().startswith(approval.lower() + '\\')):
        raise InstallRequestRefused('guardian_profile_overlap')
    sid = root['operator_sid']
    if (type(sid) is not str or len(sid) > 80
            or re.fullmatch(r'S-1-5-21-[0-9]+-[0-9]+-[0-9]+-[0-9]+', sid) is None):
        raise InstallRequestRefused('sid')
    if any(str(int(part)) != part or int(part) > 2**32 - 1 for part in sid.split('-')[4:]):
        raise InstallRequestRefused('sid')
    # Path/SID alphabets exclude quotes, line breaks and source delimiters. Never
    # accept code, source members, commands, plugins, request hashes or options.
    source = (
        '// GENERATED REVIEW DATA ONLY; not authorization or pre-load trust.\n'
        '// Independently review before compilation; never build/load checkout elevated.\n'
        'namespace AiAgent.ValidatorEntry {\n'
        '    internal static class ReviewedGuardianProfile {\n'
        '        internal static GuardianEntryProfile Create() {\n'
        f'            return new GuardianEntryProfile(@"{approval}",{volume}u,{index}UL,"{sid}",@"{launch}");\n'
        '        }\n'
        '    }\n'
        '}\n'
    ).encode('ascii')
    if len(source) > MAX_GUARDIAN_PROFILE_BYTES:
        raise InstallRequestRefused('guardian_profile_bound')
    return source
