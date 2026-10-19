"""Correct-context, bounded-report checks. No elevation or V1 fixture invocation.

Only the optional retained-host check opens the existing marker, without data
I/O. Context/report models do not attest protection or validate SYSTEM/VM tokens.
"""
from __future__ import annotations

import base64
import copy
import ctypes
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'scripts/validate_retained_store_ordinary_access.ps1'
OLD_SCRIPT = ROOT / 'scripts/validate_native_store_privileged_fixture.ps1'
RECEIPTS = Path(r'C:\Program Files\AiAgentElevatedCommands\receipts')
PINS = {
    '2fb426b96a7b4cc99b3df8db3e9bf4a3': '1a03367dfb4f058d863f1fa8d7051d57e8b87d45a3a4e9334c2de4293fc6271a',
    '75de7de500ff4979b85aed4c60538f4b': '0ad1a3a739c060c94d463c0af5dd8a37dec59ec768e91331ab4a5e160204db9b',
}
USER = 'S-1-5-21-1-2-3-1001'  # Synthetic model identity only.
MASKS = ('0x80000000', '0x40000000', '0x00010000', '0x00020000', '0x00040000', '0x00080000')
COLS = ['mask', 'api', 'granted', 'error', 'closed', 'close_error']


def source():
    return SCRIPT.read_text(encoding='utf-8-sig')


def ordinary_ps(code, *, success=True):
    if os.name != 'nt':
        pytest.skip('ordinary Windows PowerShell only')
    if ctypes.windll.shell32.IsUserAnAdmin():
        pytest.skip('NEVER elevate ordinary-access tests')
    assert len(code.encode('utf-8')) <= 65536
    exe = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    bootstrap = (
        "$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue';"
        "[Console]::InputEncoding=New-Object Text.UTF8Encoding($false,$true);"
        "[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false);"
        "$code=[Console]::In.ReadToEnd();& ([ScriptBlock]::Create($code))"
    )
    encoded = base64.b64encode(bootstrap.encode('utf-16-le')).decode('ascii')
    result = subprocess.run(
        [str(exe), '-NoLogo', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
        input=code, capture_output=True, text=True, encoding='utf-8', timeout=20, check=False,
    )
    assert len(result.stdout) + len(result.stderr) < 16000
    if success:
        assert result.returncode == 0, (result.stdout + result.stderr)[:12000]
    return result


def unique(pairs):
    value = {}
    for key, item in pairs:
        assert key not in value, 'duplicate report key'
        value[key] = item
    return value


def assert_complete_success(raw, expected_sid):
    assert len(raw) <= 3000 and len(raw.encode('utf-8')) <= 3000
    value = json.loads(raw, object_pairs_hook=unique)
    assert type(value) is dict
    assert set(value) == {
        'v', 'ok', 'code', 'op', 'base', 'diag', 'original', 'prior_output', 'ready',
        'recreated', 'data_io', 'target_identity_attested', 'cols', 'rows', 'ctx', 'ctx_stable',
    }
    assert type(value['v']) is int and value['v'] == 1
    assert value['ok'] is True and value['code'] == 'all_12_denied_error5'
    assert value['op'] == 'ordinary_retained_access_v1'
    assert value['base'] == '2fb426b96a7b4cc99b3df8db3e9bf4a3'
    assert value['diag'] == '75de7de500ff4979b85aed4c60538f4b'
    assert value['original'] == 'failed' and value['prior_output'] == 'truncated'
    for flag in ('ready', 'recreated', 'data_io', 'target_identity_attested'):
        assert value[flag] is False
    assert value['ctx_stable'] is True
    context = value['ctx']
    assert type(context) is dict and set(context) == {'sid', 't', 'et', 'el', 'ba', 'th', 'te'}
    assert context['sid'] == expected_sid and context['th'] is False
    for key, expected in (('t', 1), ('et', 3), ('el', 0), ('te', 1008)):
        assert type(context[key]) is int and context[key] == expected
    assert type(context['ba']) is int and context['ba'] & 16 and not context['ba'] & 4
    assert value['cols'] == COLS and type(value['rows']) is list and len(value['rows']) == 12
    seen = set()
    for row in value['rows']:
        assert type(row) is list and len(row) == 6
        mask, api, granted, error, closed, close_error = row
        assert mask in MASKS and api in ('S', 'R')
        assert (mask, api) not in seen
        seen.add((mask, api))
        assert granted is False and type(error) is int and error == 5
        assert closed is None and close_error is None  # No granted handle to close.
    assert seen == {(mask, api) for mask in MASKS for api in ('S', 'R')}
    return value


def model():
    return {
        'v': 1, 'ok': True, 'code': 'all_12_denied_error5', 'op': 'ordinary_retained_access_v1',
        'base': '2fb426b96a7b4cc99b3df8db3e9bf4a3', 'diag': '75de7de500ff4979b85aed4c60538f4b',
        'original': 'failed', 'prior_output': 'truncated', 'ready': False, 'recreated': False,
        'data_io': False, 'target_identity_attested': False, 'cols': list(COLS),
        'rows': [[mask, api, False, 5, None, None] for mask in MASKS for api in ('S', 'R')],
        'ctx': {'sid': USER, 't': 1, 'et': 3, 'el': 0, 'ba': 16, 'th': False, 'te': 1008},
        'ctx_stable': True,
    }


def compact(value):
    return json.dumps(value, separators=(',', ':'), sort_keys=True)


def test_complete_compact_model_not_a_native_attestation():
    assert_complete_success(compact(model()), USER)


@pytest.mark.parametrize('change', [
    {'v': True}, {'ok': False}, {'code': 'unexpected_access_result'}, {'original': 'passed'},
    {'ready': True}, {'recreated': True}, {'data_io': True}, {'target_identity_attested': True},
    {'ctx_stable': False}, {'base': 'b' * 32}, {'diag': 'b' * 32}, {'extra': 1},
])
def test_incomplete_or_overclaiming_report_refused(change):
    value = model()
    value.update(change)
    with pytest.raises(AssertionError):
        assert_complete_success(compact(value), USER)


@pytest.mark.parametrize('change', [
    {'sid': 'S-1-5-18'}, {'t': 2}, {'et': 2}, {'el': 1}, {'ba': 15}, {'ba': 20},
    {'ba': 0}, {'th': True}, {'te': 5}, {'t': True},
])
def test_wrong_context_report_refused(change):
    value = model()
    value['ctx'].update(change)
    with pytest.raises(AssertionError):
        assert_complete_success(compact(value), USER)


@pytest.mark.parametrize('index,replacement', [
    (0, '0x00000001'), (1, 'unknown'), (2, True), (3, 1346), (3, 32), (3, True),
    (4, True), (5, 5),
])
def test_all_masks_errors_and_no_grant_are_required(index, replacement):
    value = model()
    value['rows'][0][index] = replacement
    with pytest.raises(AssertionError):
        assert_complete_success(compact(value), USER)


def test_duplicate_missing_and_truncated_rows_refused():
    for mutation in ('duplicate', 'missing'):
        value = model()
        if mutation == 'duplicate':
            value['rows'][-1] = copy.deepcopy(value['rows'][0])
        else:
            value['rows'].pop()
        with pytest.raises(AssertionError):
            assert_complete_success(compact(value), USER)
    raw = compact(model())
    with pytest.raises(json.JSONDecodeError):
        assert_complete_success(raw[:-1], USER)
    with pytest.raises(AssertionError):
        assert_complete_success(raw.replace('"v":1', '"v":1,"v":1'), USER)


def test_extreme_failure_report_model_still_below_capture_limit():
    value = model()
    value['ok'] = False
    value['code'] = 'unexpected_access_result'
    value['ctx']['sid'] = 'S-' + '1' * 182
    for row in value['rows']:
        row[2:] = [True, -(2**31), False, -(2**31)]
    raw = compact(value)
    assert len(raw.encode('utf-8')) < 3000 < 4000


def test_old_fixture_source_remains_frozen():
    original = '& {\n' + OLD_SCRIPT.read_text(encoding='utf-8-sig') + '\n} -AuthorizeNonSecretNativeStoreFixtureV1\n'
    assert hashlib.sha256(original.encode('utf-8')).hexdigest() == '41aaea7abbd0f08720e224b67e1fbdb42f25e4f115db07f0a426a1f0761df02d'


def test_new_source_scope_and_output_guard():
    text = source()
    assert len(text.encode('utf-8')) < 32768
    assert text.index('if (-not $AuthorizeRetainedStoreOrdinaryAccessV1)') < text.index('$failed=Read-PinnedReceipt')
    assert text.index('do not elevate this validator') < text.index('$failed=Read-PinnedReceipt')
    assert not re.search(r'\b(?:ImpersonateLoggedOnUser|DuplicateToken|DuplicateTokenEx|RevertToSelf|NtCreateFile|WriteFile|ReadFile|SetSecurityInfo|SetNamedSecurityInfo|AdjustTokenPrivileges|CreateHardLinkW|CreateSymbolicLinkW)\b', text)
    assert 'NativeStoreProfileFixtureV1' not in text
    assert text.count('IntPtr.Zero,3,0x200000,IntPtr.Zero)') == 2
    assert '$json.Length -gt 3000' in text and 'GetByteCount($json) -gt 3000' in text
    for digest in PINS.values():
        assert digest in text


def test_script_parses_and_refuses_without_authorization():
    path = str(SCRIPT).replace("'", "''")
    command = (
        "$ErrorActionPreference='Stop';$t=$null;$e=$null;"
        f"$ast=[Management.Automation.Language.Parser]::ParseFile('{path}',[ref]$t,[ref]$e);"
        "if($e.Count){throw 'parse failure'};@{parsed=$true}|ConvertTo-Json -Compress"
    )
    assert json.loads(ordinary_ps(command).stdout) == {'parsed': True}
    result = ordinary_ps('& {\n' + source() + '\n}', success=False)
    assert result.returncode != 0 and 'Explicit ordinary-access validation authorization required' in result.stdout + result.stderr


def test_csharp_context_model_and_current_process_facts_without_target_opens():
    match = re.search(r"\$native=@'\n(.*?)\n'@", source(), re.DOTALL)
    assert match is not None
    command = (
        "$ErrorActionPreference='Stop';$n=@'\n" + match.group(1) + "\n'@;\n"
        "Add-Type -TypeDefinition $n -ReferencedAssemblies @('System.dll','System.Core.dll','System.Security.dll');"
        "$rows=@("
        "@{t=1;et=3;el=0;a=16;th=$false;e=1008;s='same';x='same';ok=''},"
        "@{t=2;et=3;el=0;a=16;th=$true;e=0;s='same';x='same';ok='unsupported_context'},"
        "@{t=2;et=3;el=0;a=16;th=$false;e=1008;s='same';x='same';ok='unsupported_context'},"
        "@{t=1;et=2;el=1;a=15;th=$false;e=1008;s='same';x='same';ok='unsupported_context'},"
        "@{t=1;et=3;el=0;a=16;th=$true;e=0;s='same';x='same';ok='unsupported_context'},"
        "@{t=1;et=3;el=0;a=16;th=$false;e=5;s='same';x='same';ok='unsupported_context'},"
        "@{t=1;et=3;el=0;a=20;th=$false;e=1008;s='same';x='same';ok='unsupported_context'},"
        "@{t=1;et=3;el=0;a=0;th=$false;e=1008;s='same';x='same';ok='unsupported_context'},"
        "@{t=1;et=1;el=0;a=16;th=$false;e=1008;s='same';x='same';ok='unsupported_context'},"
        "@{t=1;et=3;el=0;a=16;th=$false;e=1008;s='other';x='same';ok='operator_mismatch'},"
        "@{t=1;et=3;el=0;a=16;th=$false;e=1008;s='same';x='';ok='operator_mismatch'}"
        ");foreach($r in $rows){"
        "if([RetainedOrdinaryAccessV1]::ContextCode($r.t,$r.et,$r.el,$r.a,$r.th,$r.e,$r.s,$r.x) -cne $r.ok){throw 'context model failure'}"
        "};@{cases=$rows.Count;ctx=[RetainedOrdinaryAccessV1]::DescribeCurrent()}|ConvertTo-Json -Depth 4 -Compress"
    )
    result = json.loads(ordinary_ps(command).stdout)
    assert result['cases'] == 11
    assert result['ctx']['t'] == 1 and result['ctx']['el'] == 0
    assert result['ctx']['th'] is False and result['ctx']['te'] == 1008


def test_actual_retained_marker_from_real_ordinary_primary_process():
    if os.name != 'nt':
        pytest.skip('requires exact retained Windows fixture receipts')
    if ctypes.windll.shell32.IsUserAnAdmin():
        pytest.skip('NEVER elevate the ordinary-process probe')
    snapshots = {}
    for request, expected in PINS.items():
        path = RECEIPTS / (request + '.result.json')
        if not path.is_file():
            pytest.skip('exact retained receipt absent; no fixture is created by this test')
        raw = path.read_bytes()
        assert len(raw) <= 65536 and hashlib.sha256(raw).hexdigest() == expected
        snapshots[path] = raw
    original = json.loads(json.loads(next(iter(snapshots.values())))['stdout'])
    wrapper = '& {\n' + source() + '\n} -AuthorizeRetainedStoreOrdinaryAccessV1\n'
    result = ordinary_ps(wrapper)
    assert_complete_success(result.stdout.strip(), original['operator_sid'])
    for path, raw in snapshots.items():
        assert path.read_bytes() == raw  # Prior receipt bytes remain unchanged.
