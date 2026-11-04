"""Offline host/CLR request-codec tests. No native acquisition or launch.

All pins, identities, archives and executable inputs are inert synthetic DATA.
Compile five actual C# sources, but invoke only the request codec/plan factories.
Ordinary temporary compiler/model/corpus files are not a protected installation.
"""
from __future__ import annotations

import ast
import base64
import copy
import hashlib
import json
import os
import re
import subprocess
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from night_shifts import bootstrap_native_deployment as deployment
from night_shifts import bootstrap_native_install_request as m

ROOT = Path(__file__).resolve().parents[2]
CS = ROOT / 'scripts/native_validator_install_request.cs'
SOURCES = (CS, ROOT / 'scripts/native_validator_install_boundary.cs', ROOT / 'scripts/native_validator_install_windows.cs',
           ROOT / 'scripts/native_validator_launch_boundary.cs', ROOT / 'scripts/native_validator_launch_windows.cs')
BAD_FIELDS = {
    'version_bool': (('version',), True), 'scope': (('scope',), 'authorized'),
    'operation': (('operation',), 'run_anything'), 'id': (('installation_id',), 'A' * 32),
    'sid': (('operator_sid',), 'S-1-5-18'), 'sid_leading_zero': (('operator_sid',), 'S-1-5-21-01-2-3-1001'),
    'sid_overflow': (('operator_sid',), 'S-1-5-21-1-2-3-4294967296'),
    'budget_bool': (('budget_seconds',), True), 'budget_small': (('budget_seconds',), 5),
    'budget_large': (('budget_seconds',), 901), 'expiry_zero': (('expires_unix',), 0),
    'expiry_large': (('expires_unix',), 253402300800),
    'drive_case': (('launch_anchor', 'path'), r'c:\Launch'),
    'unc': (('launch_anchor', 'path'), r'\\host\Launch'),
    'dot': (('import_anchor', 'path'), r'C:\Import\..\Other'),
    'ads': (('import_anchor', 'path'), r'C:\Import:stream'),
    'reserved': (('provision', 'source', 'path'), r'C:\NUL.txt'),
    'trailing': (('provision', 'source', 'path'), 'C:\\Input '),
    'unicode': (('provision', 'source', 'path'), 'C:\\Input\u00e9'),
    'overlap': (('provision', 'source', 'path'), r'C:\Launch\inside'),
    'case_overlap': (('import_anchor', 'path'), r'C:\LAUNCH'),
    'identity_alias': (('import_anchor', 'identity', 'index'), 10),
    'index_zero': (('import_anchor', 'identity', 'index'), 0),
    'index_bool': (('import_anchor', 'identity', 'index'), True),
    'index_overflow': (('import_anchor', 'identity', 'index'), 2**64),
    'volume_negative': (('import_anchor', 'identity', 'volume'), -1),
    'volume_overflow': (('import_anchor', 'identity', 'volume'), 2**32),
    'scratch_volume': (('launch_anchor', 'scratch_identity', 'volume'), 43),
    'bundle_zero': (('provision', 'bundle', 'bytes'), 0),
    'bundle_large': (('provision', 'bundle', 'bytes'), 64 * 1024**2 + 1),
    'runtime_zero': (('provision', 'pins', 'runtime_bytes'), 0),
    'runtime_large': (('provision', 'pins', 'runtime_bytes'), 32 * 1024**2 + 1),
    'recovery_alignment': (('provision', 'pins', 'recovery_bytes'), 40961),
    'recovery_small': (('provision', 'pins', 'recovery_bytes'), 2048),
    'recovery_large': (('provision', 'pins', 'recovery_bytes'), 8 * 1024**3 + 2048),
    'code_tree': (('provision', 'pins', 'code_tree_sha256'), '0' * 64),
    'codec_tree': (('provision', 'pins', 'codec_tree_sha256'), '0' * 64),
    'upper_digest': (('provision', 'pins', 'runtime_sha256'), 'A' * 64),
    'bad_digest': (('provision', 'bundle', 'sha256'), 'bad'),
    'null_pins': (('provision', 'pins'), None),
    'config_rehash': (('launch_anchor', 'files', 1, 'sha256'), '0' * 64),
    'missing_import': (('import_anchor', 'files'), []),
    'unsorted_import': (('import_anchor', 'files', 0, 'name'), 'runtime/evil.exe'),
    'negative_size': (('import_anchor', 'files', 0, 'bytes'), -1),
    'oversize_leaf': (('import_anchor', 'files', 0, 'bytes'), 32 * 1024**2 + 1),
}
WIRE_CASES = ('space', 'no_newline', 'crlf', 'reordered', 'indent', 'duplicate', 'quoted_number', 'float_number',
              'unicode_escape', 'bom', 'trailer', 'unknown', 'missing', 'self_hash', 'self_pin', 'bad_json',
              'deep', 'invalid_utf8', 'oversized', 'initializer_rehash', 'pth_rehash', 'closure_bound')
SCENARIOS = ('valid', 'valid:wide', 'valid:min_budget', 'valid:max_budget', 'valid:expiry_shape', 'valid:adjacent',
             *('field:' + name for name in BAD_FIELDS), *('wire:' + name for name in WIRE_CASES),
             'external:hash', 'external:length', 'external:zero', 'external:oversize', 'external:digest', 'external:null')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True) + '\n').encode('ascii')


def candidate():
    def identity(index):
        return {'volume': 42, 'index': index}

    def member(name):
        raw = b'INERT NONRUNNABLE MODEL:' + name.encode('ascii')
        if name in m._EMPTY:
            raw = b''
        elif name == 'runtime/python314._pth':
            raw = m._PTH
        elif name.endswith('.exe.config'):
            raw = m._CONFIG
        return {'name': name, 'bytes': len(raw), 'sha256': sha(raw)}

    files = [member(n) for n in m.IMPORT_NAMES]
    inventory = {item['name'][8:]: {k: item[k] for k in ('bytes', 'sha256')}
                 for item in files if item['name'].startswith('payload/')}
    code = {n: p for n, p in inventory.items() if n.startswith('night_shifts/')}
    codec = {n: p for n, p in inventory.items() if not n.startswith('night_shifts/')}
    return {'version': 1, 'scope': m.SCOPE, 'operation': m.OPERATION, 'installation_id': 'a' * 32,
        'operator_sid': 'S-1-5-21-1-2-3-1001', 'budget_seconds': 10, 'expires_unix': 1600,
        'launch_anchor': {'path': r'C:\Launch', 'identity': identity(10), 'scratch_identity': identity(11),
                          'files': [member(n) for n in m.LAUNCH_NAMES]},
        'import_anchor': {'path': r'C:\Imports', 'identity': identity(20), 'files': files},
        'provision': {'source': {'path': r'C:\Inputs', 'identity': identity(30)},
            'output_parent': {'path': r'C:\Outputs', 'identity': identity(40)},
            'bundle': {'bytes': 100, 'sha256': 'b' * 64},
            'pins': {'code_tree_sha256': sha(canonical(code)), 'codec_tree_sha256': sha(canonical(codec)),
                'runtime_sha256': 'c' * 64, 'runtime_bytes': 1000, 'recovery_sha256': 'd' * 64, 'recovery_bytes': 40960}}}


def worker(value, digest):
    # Independent projection oracle, not the production helper.
    projected = {k: value[k] for k in ('budget_seconds', 'expires_unix', 'installation_id', 'operation', 'operator_sid', 'provision')}
    projected.update(version=1, scope='bound_worker_request_not_authorization', request_sha256=digest,
        import_anchor={k: value['import_anchor'][k] for k in ('identity', 'path')},
        launch_anchor={k: value['launch_anchor'][k] for k in ('identity', 'path', 'scratch_identity')})
    return canonical(projected)


def wire(name, data, raw):
    if name == 'space':
        return raw + b' '
    if name == 'no_newline':
        return raw[:-1]
    if name == 'crlf':
        return raw[:-1] + b'\r\n'
    if name == 'reordered':
        return (json.dumps(data, separators=(',', ':')) + '\n').encode('ascii')
    if name == 'indent':
        return json.dumps(data, sort_keys=True, indent=2).encode('ascii')
    if name == 'duplicate':
        return raw.replace(b'"version":1', b'"version":1,"version":1')
    if name == 'quoted_number':
        return raw.replace(b'"budget_seconds":10', b'"budget_seconds":"10"')
    if name == 'float_number':
        return raw.replace(b'"budget_seconds":10', b'"budget_seconds":10.0')
    if name == 'unicode_escape':
        return raw.replace(b'Launch', b'\\u004cauch')
    if name == 'bom':
        return b'\xef\xbb\xbf' + raw
    if name == 'trailer':
        return raw + b'{}'
    if name == 'bad_json':
        return b'{'
    if name == 'deep':
        return b'[' * 1000 + b']' * 1000
    if name == 'invalid_utf8':
        return b'\xff'
    if name == 'oversized':
        return b' ' * (m.MAX_REQUEST_BYTES + 1)
    if name == 'unknown':
        data['extra'] = True
    elif name == 'missing':
        data.pop('provision')
    elif name == 'self_hash':
        data['request_sha256'] = 'e' * 64
    elif name == 'self_pin':
        data['import_anchor']['files'].append({'name': 'provision-request.json', 'bytes': 10, 'sha256': 'e' * 64})
    elif name in ('initializer_rehash', 'pth_rehash'):
        target = 'payload/night_shifts/__init__.py' if name == 'initializer_rehash' else 'runtime/python314._pth'
        pin = next(item for item in data['import_anchor']['files'] if item['name'] == target)
        pin.update(bytes=7, sha256=sha(b'changed'))
    elif name == 'closure_bound':
        for item in data['import_anchor']['files']:
            if item['name'].endswith(('.dll', '.pyd')):
                item['bytes'] = 32 * 1024**2
    else:
        raise AssertionError(name)
    return canonical(data)


@pytest.fixture(scope='module')
def corpus():
    result = {}
    for name in SCENARIOS:
        data = candidate()
        if name.startswith('field:'):
            path, value = BAD_FIELDS[name[6:]]
            target = data
            for part in path[:-1]:
                target = target[part]
            target[path[-1]] = copy.deepcopy(value)
        elif name == 'valid:wide':
            for i, place in enumerate((data['launch_anchor'], data['import_anchor'], data['provision']['source'], data['provision']['output_parent'])):
                place['identity'] = {'volume': 2**32 - 1, 'index': 2**64 - 1 - i}
            data['launch_anchor']['scratch_identity'] = {'volume': 2**32 - 1, 'index': 2**64 - 5}
            data['operator_sid'] = 'S-1-5-21-0-4294967295-3-4294967295'
        elif name == 'valid:min_budget':
            data['budget_seconds'] = 6
        elif name == 'valid:max_budget':
            data['budget_seconds'] = 900
        elif name == 'valid:expiry_shape':
            data['expires_unix'] = 253402300799
        elif name == 'valid:adjacent':
            data['provision']['source']['path'] = r'C:\Launcher'
        raw = canonical(data)
        if name.startswith('wire:'):
            raw = wire(name[5:], data, raw)
        digest, size = sha(raw), len(raw)
        if name == 'external:hash':
            digest = 'f' * 64
        elif name == 'external:length':
            size += 1
        elif name == 'external:zero':
            size = 0
        elif name == 'external:oversize':
            size = m.MAX_REQUEST_BYTES + 1
        elif name == 'external:digest':
            digest = 'A' * 64
        elif name == 'external:null':
            raw, size = None, 1
        good = name.startswith('valid')
        result[name] = (raw, size, digest, good, worker(data, digest) if good else b'')
    return result


@pytest.mark.parametrize('scenario', SCENARIOS)
def test_host_request_decisions(corpus, scenario):
    raw, size, digest, good, expected_worker = corpus[scenario]
    if not good:
        with pytest.raises(m.InstallRequestRefused):
            m.bind_validation_install_request(raw, expected_bytes=size, expected_sha256=digest)
        return
    bound = m.bind_validation_install_request(raw, expected_bytes=size, expected_sha256=digest)
    assert bound.request_sha256 == digest and bound.worker_request == expected_worker
    assert m.build_validation_install_request(json.loads(raw)) == raw
    review = json.loads(bound.review)
    assert review['scope'] == 'local_install_request_consistency_only'
    assert review['request_sha256'] == digest and review['worker_request_sha256'] == sha(expected_worker)
    assert review['inputs'] == json.loads(raw)
    assert review['output_directory'] == r'C:\Outputs\native-validator-' + 'a' * 32
    assert len(bound.review) <= m.MAX_REVIEW_BYTES and len(expected_worker) <= m.MAX_WORKER_BYTES
    assert not {'accepted', 'authorized', 'installed', 'gate_a', 'cleanup', 'retry'} & review.keys()


def test_independent_catalogs_match_existing_deployment_without_expansion():
    assert m.RUNTIME_NAMES == deployment.RUNTIME_NAMES
    assert tuple('night_shifts/' + n for n in m.CODE_NAMES) == deployment.CODE_NAMES
    assert m.CODEC_NAMES == deployment.CODEC_NAMES
    expected = tuple(sorted((*('runtime/' + n for n in deployment.RUNTIME_NAMES),
                             *('payload/' + n for n in (*deployment.CODE_NAMES, *deployment.CODEC_NAMES)))))
    assert m.IMPORT_NAMES == expected and len(expected) == 86
    assert len(deployment.BUNDLE_NAMES) == 91
    assert 'night_shifts/bootstrap_native_install_request.py' not in deployment.CODE_NAMES
    assert 'provision-request.json' not in m.IMPORT_NAMES


def test_whole_pin_precedes_json_parser(monkeypatch):
    raw = m.build_validation_install_request(candidate())
    monkeypatch.setattr(m.json, 'loads', lambda *_: pytest.fail('parsed before independent pin'))
    for value, size, digest in ((raw, len(raw), 'f' * 64), (raw, True, sha(raw)), (bytearray(raw), len(raw), sha(raw)),
                                (raw, len(raw) + 1, sha(raw)), (None, 1, sha(raw))):
        with pytest.raises(m.InstallRequestRefused):
            m.bind_validation_install_request(value, expected_bytes=size, expected_sha256=digest)


def test_build_and_bind_need_no_file_process_clock_or_snapshot(monkeypatch):
    import builtins
    monkeypatch.setattr(builtins, 'open', lambda *_a, **_k: pytest.fail('filesystem accessed'))
    raw = m.build_validation_install_request(candidate())
    bound = m.bind_validation_install_request(raw, expected_bytes=len(raw), expected_sha256=sha(raw))
    assert bound.worker_request
    with pytest.raises(FrozenInstanceError):
        bound.request_sha256 = 'f' * 64
    assert isinstance(bound.worker_request, bytes) and isinstance(bound.review, bytes)


@pytest.mark.parametrize('path', [r'C:\Other Launch', r'D:\Launch'])
def test_context_change_rebinds_worker_without_request_self_hash(path):
    data = candidate()
    first = m.build_validation_install_request(data)
    data['launch_anchor']['path'] = path
    second = m.build_validation_install_request(data)
    a = m.bind_validation_install_request(first, expected_bytes=len(first), expected_sha256=sha(first))
    b = m.bind_validation_install_request(second, expected_bytes=len(second), expected_sha256=sha(second))
    assert first != second and a.worker_request != b.worker_request
    assert 'request_sha256' not in json.loads(second)
    assert json.loads(b.worker_request)['request_sha256'] == sha(second)


HARNESS = r'''
using System;
using AiAgent.ValidatorRequest;
using AiAgent.NativeValidator;
using AiAgent.ValidatorLaunch;
public static class RequestModelHarness {
    static void Check(bool yes) { if (!yes) throw new Exception("REQUEST_MODEL_ASSERTION"); }
    static void Equal(byte[] a,byte[] b) { Check(a.Length==b.Length); for (int i=0;i<a.Length;i++) Check(a[i]==b[i]); }
    public static string Run(string name,byte[] raw,long size,string digest,bool good,byte[] expectedWorker) {
        try {
            BoundInstallationInputs bound;
            try { bound=InstallationRequest.Bind(raw,size,digest); }
            catch (InstallRequestRefused ex) { Check(!good && ex.Message.Length<80); return name+"|PASS"; }
            Check(good && bound.RequestSha256==digest);
            Equal(bound.WorkerRequestBytes(),expectedWorker);
            byte[] caller=bound.WorkerRequestBytes(); caller[0]^=1; Equal(bound.WorkerRequestBytes(),expectedWorker);
            if (raw!=null && raw.Length>0) raw[0]^=1; Equal(bound.WorkerRequestBytes(),expectedWorker);
            LaunchPlan launch=bound.CreateLaunchPlan(); InstallBoundaryPlan import=bound.CreateImportPlan();
            Check(launch.ApprovalSha256==digest && import.ApprovalSha256==digest);
            Check(launch.OperatorSid==import.OperatorSid && launch.InstallationId==import.InstallationId &&
                launch.ApprovedUntilUnix==import.ApprovedUntilUnix && launch.Files.Count==4 && import.Files.Count==87);
            Check(InstallBoundary.Catalog().SetEquals(import.Files.Keys));
            FilePin worker=import.Files["provision-request.json"];
            Check(worker.Bytes==expectedWorker.Length && worker.Sha256==InstallationRequest.Sha(expectedWorker));
            launch.Files.Clear(); import.Files.Clear();
            Check(bound.CreateLaunchPlan().Files.Count==4 && bound.CreateImportPlan().Files.Count==87);
            return name+"|PASS";
        } catch (Exception ex) { return name+"|FAIL|"+ex.GetType().Name+"|"+ex.Message; }
    }
}
'''


def quote(path):
    return "'" + str(path).replace("'", "''") + "'"


@pytest.fixture(scope='module')
def clr_models(tmp_path_factory, corpus):
    if os.name != 'nt':
        pytest.skip('requires Windows CLR compiler; not native request delivery evidence')
    compiler = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    assert compiler.is_file()
    folder = tmp_path_factory.mktemp('validator-request-model')
    harness = folder / 'models.cs'
    harness.write_text(HARNESS, encoding='utf-8')
    cases = folder / 'inert-corpus.txt'
    rows = []
    for name, (raw, size, digest, good, expected_worker) in corpus.items():
        encoded = '-' if raw is None else base64.b64encode(raw).decode('ascii')
        rows.append('|'.join((name, '1' if good else '0', str(size), digest, encoded,
                              base64.b64encode(expected_worker).decode('ascii'))))
    cases.write_text('\n'.join(rows) + '\n', encoding='ascii')
    script = (
        "$ErrorActionPreference='Stop'; "
        'Add-Type -Path @(' + ','.join(quote(p) for p in (*SOURCES, harness)) + ') '
        "-ReferencedAssemblies @('System.dll','System.Core.dll','System.Xml.dll','System.Runtime.Serialization.dll') -ErrorAction Stop; "
        f'foreach ($line in [IO.File]::ReadAllLines({quote(cases)})) {{ '
        "$p=$line.Split('|'); $raw=if($p[4] -eq '-'){$null}else{[Convert]::FromBase64String($p[4])}; "
        '[RequestModelHarness]::Run($p[0],$raw,[long]$p[2],$p[3],($p[1] -eq \'1\'),[Convert]::FromBase64String($p[5])) }'
    )
    completed = subprocess.run([str(compiler), '-NoLogo', '-NoProfile', '-NonInteractive', '-EncodedCommand',
        base64.b64encode(script.encode('utf-16le')).decode('ascii')], capture_output=True, text=True, timeout=25, check=False)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    results = {}
    for line in completed.stdout.splitlines():
        name, separator, result = line.partition('|')
        assert separator and name not in results, line
        results[name] = result
    assert set(results) == set(SCENARIOS)
    return results


@pytest.mark.parametrize('scenario', SCENARIOS)
def test_csharp_decisions_and_worker_bytes_match_independent_oracle(clr_models, scenario):
    assert clr_models[scenario] == 'PASS'


def test_csharp_pin_snapshot_and_quotas_precede_fixed_contract_parsing():
    text = CS.read_text(encoding='utf-8')
    assert text.index('snapshot=(byte[])raw.Clone()') < text.index('if (Sha(snapshot)!=expectedSha256)') < text.index('serializer.ReadObject(reader)')
    for quota in ('MaxDepth=12', 'MaxArrayLength=128', 'MaxItemsInObjectGraph=1024', 'MaxStringContentLength=MaxRequestBytes'):
        assert quota in text
    assert 'canonical[i]!=snapshot[i]' in text and 'return (byte[])worker.Clone()' in text
    assert 'files.Add("provision-request.json",new FilePin(worker.Length,InstallationRequest.Sha(worker)))' in text
    assert 'clock' not in re.sub(r'//[^\n]*', '', text).lower()
    assert not re.search(r'\b(?:Main|CreateProcessW|CreateClaim|DllImport|File\.Open|Assembly\.Load)\s*\(', text)


def test_serialized_members_stay_required_without_warning_suppression():
    text = CS.read_text(encoding='utf-8')
    members = re.findall(r'\[DataMember\(([^)]*)\)\]\s+public\s+[\w\[\]]+\s+\w+\s*(\{[^}]*\}|;)', text)
    assert len(members) == 36
    assert all('IsRequired=true' in attributes and body == '{ get; set; }' for attributes, body in members)
    assert '#pragma' not in text


def test_host_contract_stays_stdlib_only_and_outside_carried_payload():
    tree = ast.parse(Path(m.__file__).read_text(encoding='utf-8'))
    imports = {n.module for n in tree.body if isinstance(n, ast.ImportFrom)} | {
        a.name for n in tree.body if isinstance(n, ast.Import) for a in n.names}
    assert imports == {'__future__', 'hashlib', 'json', 're', 'dataclasses', 'typing'}
    assert not any(isinstance(n, ast.If) and isinstance(n.test, ast.Compare) for n in tree.body)
    for path in [*(ROOT / 'runtime').glob('*.py'), *(ROOT / 'scripts').glob('*.ps1')]:
        text = path.read_text(encoding='utf-8-sig')
        assert 'native_validator_install_request' not in text and 'bootstrap_native_install_request' not in text
    ignore = (ROOT / '.gitignore').read_text(encoding='utf-8').splitlines()
    exception = '!/' + CS.relative_to(ROOT).as_posix()
    assert ignore.count(exception) == 1 and ignore.index(exception) > ignore.index('/scripts/*')
