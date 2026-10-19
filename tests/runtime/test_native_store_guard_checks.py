"""Review/model tests ONLY: no privileged execution or native fixture creation.

The embedded Run() is invoked only in an ordinary process to test its leading
Administrator refusal. Positive descriptor/reparse/report cases are models,
not native collision, rename, symlink or hard-link evidence.
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
SCRIPT = ROOT / 'scripts/validate_native_store_guard_checks.ps1'
ID = '97aa76c6db034b4ea87c747a38ce60a0'
COLS = ['test', 'nt', 'win32', 'detail', 'ok']
SD = 'O:BAG:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)'


def source():
    return SCRIPT.read_text(encoding='utf-8-sig')


def ordinary_ps(code, *, success=True):
    if os.name != 'nt':
        pytest.skip('ordinary Windows review checks')
    if ctypes.windll.shell32.IsUserAnAdmin():
        pytest.skip('NEVER elevate this test suite')
    assert len(code.encode('utf-8')) <= 65536
    bootstrap = (
        "$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue';"
        "[Console]::InputEncoding=New-Object Text.UTF8Encoding($false,$true);"
        "[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false);"
        "$code=[Console]::In.ReadToEnd();& ([ScriptBlock]::Create($code))"
    )
    executable = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    result = subprocess.run(
        [str(executable), '-NoLogo', '-NoProfile', '-NonInteractive', '-EncodedCommand',
         base64.b64encode(bootstrap.encode('utf-16-le')).decode('ascii')],
        input=code, capture_output=True, text=True, encoding='utf-8', timeout=20, check=False,
    )
    assert len(result.stdout) + len(result.stderr) < 24000
    if success:
        assert result.returncode == 0, (result.stdout + result.stderr)[:16000]
    return result


def unique(pairs):
    value = {}
    for key, item in pairs:
        assert key not in value, 'duplicate result key'
        value[key] = item
    return value


def assert_complete_success(raw):
    assert len(raw) <= 3000 and len(raw.encode('utf-8')) <= 3000
    value = json.loads(raw, object_pairs_hook=unique)
    assert type(value) is dict and set(value) == {
        'v', 'ok', 'code', 'op', 'id', 'created', 'original', 'v1_reused', 'ready',
        'system_vm_tested', 'cols', 'rows', 'vol', 'root_index', 'private_sd', 'stable',
        'old_receipts_unchanged',
    }
    assert type(value['v']) is int and value['v'] == 1
    assert value['ok'] is True and value['code'] == 'four_guard_checks_completed'
    assert value['op'] == 'new_native_store_guard_fixture_v1' and value['id'] == ID
    assert value['original'] == 'failed'
    for key in ('v1_reused', 'ready', 'system_vm_tested'):
        assert value[key] is False
    for key in ('created', 'stable', 'old_receipts_unchanged'):
        assert value[key] is True
    assert re.fullmatch('0x[0-9a-f]{8}', value['vol'])
    assert re.fullmatch('[0-9a-f]{16}', value['root_index']) and int(value['root_index'], 16)
    assert value['private_sd'] == SD
    assert value['cols'] == COLS and type(value['rows']) is list and len(value['rows']) == 4
    rows = {}
    for row in value['rows']:
        assert type(row) is list and len(row) == 5 and row[4] is True
        assert row[0] not in rows
        rows[row[0]] = row
    assert set(rows) == {'collision', 'rename', 'reparse', 'multilink'}
    _, nt, error, detail, _ = rows['collision']
    assert nt == '0xc0000035' and type(error) is int and error in (80, 183)
    assert type(detail) is list and len(detail) == 4 and detail[0] == detail[1]
    assert all(re.fullmatch('[0-9a-f]{16}', item) and int(item, 16) for item in detail[:2])
    assert detail[2] is True and detail[3] is True
    _, nt, error, detail, _ = rows['rename']
    assert nt is None and type(error) is int and error == 32
    assert type(detail) is list and len(detail) == 3 and detail[1] == '0xc0000034' and detail[2] is True
    assert re.fullmatch('[0-9a-f]{16}', detail[0]) and int(detail[0], 16)
    _, nt, error, detail, _ = rows['reparse']
    assert type(detail) is list and len(detail) == 5 and detail[0] == '0xa000000c' and detail[4] is True
    assert detail[1] in ('native', 'shape')
    if detail[1] == 'native':
        assert nt == '0xc000050b' and type(error) is int and error > 0
    else:
        assert nt is None and error is None
    assert detail[2] != detail[3]
    assert all(re.fullmatch('[0-9a-f]{16}', item) and int(item, 16) for item in detail[2:4])
    _, nt, error, detail, _ = rows['multilink']
    assert nt is None and error is None and type(detail) is list and len(detail) == 5
    assert detail[0] == detail[1] and re.fullmatch('[0-9a-f]{16}', detail[0]) and int(detail[0], 16)
    assert type(detail[2]) is int and type(detail[3]) is int and detail[2:4] == [2, 2]
    assert detail[4] is True
    return value


def model():
    return {
        'v': 1, 'ok': True, 'code': 'four_guard_checks_completed',
        'op': 'new_native_store_guard_fixture_v1', 'id': ID, 'created': True,
        'original': 'failed', 'v1_reused': False, 'ready': False, 'system_vm_tested': False,
        'cols': list(COLS), 'vol': '0x12345678', 'root_index': '0000000000000001',
        'private_sd': SD, 'stable': True, 'old_receipts_unchanged': True,
        'rows': [
            ['collision', '0xc0000035', 183, ['0000000000000002', '0000000000000002', True, True], True],
            ['rename', None, 32, ['0000000000000003', '0xc0000034', True], True],
            ['reparse', '0xc000050b', 4395, ['0xa000000c', 'native', '0000000000000004', '0000000000000005', True], True],
            ['multilink', None, None, ['0000000000000006', '0000000000000006', 2, 2, True], True],
        ],
    }


def compact(value):
    return json.dumps(value, separators=(',', ':'), sort_keys=True)


def test_complete_model_not_native_evidence():
    assert_complete_success(compact(model()))
    value = model()
    value['rows'][2][1:3] = [None, None]
    value['rows'][2][3][1] = 'shape'
    assert_complete_success(compact(value))


@pytest.mark.parametrize('change', [
    {'v': True}, {'ok': False}, {'code': 'managed_failure'}, {'original': 'passed'},
    {'v1_reused': True}, {'ready': True}, {'system_vm_tested': True}, {'created': False},
    {'stable': False}, {'old_receipts_unchanged': False}, {'id': 'a' * 32}, {'extra': 1},
])
def test_partial_failed_overclaiming_results_rejected(change):
    value = model()
    value.update(change)
    with pytest.raises(AssertionError):
        assert_complete_success(compact(value))


@pytest.mark.parametrize('case', ['wrong_collision', 'changed_collision_id', 'rename_not_missing',
                                   'wrong_reparse_error', 'followed_target', 'not_two_links',
                                   'different_link_id', 'missing', 'duplicate', 'false_pass'])
def test_each_specific_native_proof_required(case):
    value = model()
    if case == 'wrong_collision':
        value['rows'][0][1] = '0xc0000043'
    elif case == 'changed_collision_id':
        value['rows'][0][3][1] = '0000000000000009'
    elif case == 'rename_not_missing':
        value['rows'][1][3][1] = '0xc0000022'
    elif case == 'wrong_reparse_error':
        value['rows'][2][1:3] = ['0xc0000022', 5]
    elif case == 'followed_target':
        value['rows'][2][3][2] = value['rows'][2][3][3]
    elif case == 'not_two_links':
        value['rows'][3][3][2] = 1
    elif case == 'different_link_id':
        value['rows'][3][3][1] = '0000000000000009'
    elif case == 'missing':
        value['rows'].pop()
    elif case == 'duplicate':
        value['rows'][-1] = copy.deepcopy(value['rows'][0])
    else:
        value['rows'][0][4] = False
    with pytest.raises(AssertionError):
        assert_complete_success(compact(value))


def test_truncated_duplicate_and_unbounded_reports_rejected():
    raw = compact(model())
    with pytest.raises(json.JSONDecodeError):
        assert_complete_success(raw[:-1])
    with pytest.raises(AssertionError):
        assert_complete_success(raw.replace('"v":1', '"v":1,"v":1'))
    with pytest.raises(AssertionError):
        assert_complete_success(' ' * 3001 + raw)
    extreme = model()
    extreme.update({'ok': False, 'at': 'preservation', 'nt': '0xffffffff', 'win32': -(2**31),
                    'access': '0xffffffff', 'kind': 'native_nt'})
    for row in extreme['rows']:
        row[2] = -(2**31)
    assert len(compact(extreme).encode('utf-8')) < 3000 < 4000


def test_fixed_scope_and_original_source_preservation():
    text = source()
    assert len(text.encode('utf-8')) < 32768
    assert ID in text and 'native-store-guards-' in text
    assert '22bf6d3069d64b7fbc8bd09771dcae6f' not in text  # Old fixture never selected.
    assert 'NativeStoreProfileFixtureV1' not in text
    assert text.index('Explicit new guard-fixture authorization required') < text.index('$failed=Read-GuardReceipt')
    assert text.index('Enabled Administrator required; no guard objects created') < text.index('$failed=Read-GuardReceipt')
    assert not re.search(r'\b(?:ImpersonateLoggedOnUser|DuplicateToken|DuplicateTokenEx|AdjustTokenPrivileges|DeleteFileW|RemoveDirectoryW|SetSecurityInfo|SetNamedSecurityInfo|CreateProcess|CreateService)\b', text)
    assert not re.search(r'(?i)\b(?:Start|Stop|Set|Remove|New|Get)-VM\b', text)
    assert 'create ? 2U : 1U' in text and 'a.Flags=0x1040' in text
    assert 'DeviceIoControl(link,0x000900a8' in text
    assert 'if(f.Status!=0xc000050b)throw' in text
    assert '$json.Length -gt 3000' in text and 'GetByteCount($json) -gt 3000' in text
    original = '& {\n' + (ROOT / 'scripts/validate_native_store_privileged_fixture.ps1').read_text(encoding='utf-8-sig') + '\n} -AuthorizeNonSecretNativeStoreFixtureV1\n'
    assert hashlib.sha256(original.encode()).hexdigest() == '41aaea7abbd0f08720e224b67e1fbdb42f25e4f115db07f0a426a1f0761df02d'


def test_full_script_parse_and_ordinary_refusals():
    path = str(SCRIPT).replace("'", "''")
    command = (
        "$ErrorActionPreference='Stop';$t=$null;$e=$null;"
        f"$a=[Management.Automation.Language.Parser]::ParseFile('{path}',[ref]$t,[ref]$e);"
        "if($e.Count){throw 'parse failed'};@{parsed=$true}|ConvertTo-Json -Compress"
    )
    assert json.loads(ordinary_ps(command).stdout) == {'parsed': True}
    for argument, expected in [('', 'Explicit new guard-fixture authorization required'),
                               (' -AuthorizeNewNativeStoreGuardFixtureV1', 'Enabled Administrator required')]:
        result = ordinary_ps('& {\n' + source() + '\n}' + argument, success=False)
        assert result.returncode != 0 and expected in result.stdout + result.stderr


def test_csharp_compilation_models_layouts_and_native_admin_guard_only():
    match = re.search(r"\$native=@'\n(.*?)\n'@", source(), re.DOTALL)
    assert match is not None
    builder = r'''using System;using System.Text;
public static class GuardReparseModel {
 public static byte[] Build(string target) {
  byte[] sub=Encoding.Unicode.GetBytes("\\??\\"+target),print=Encoding.Unicode.GetBytes(target);
  byte[] b=new byte[20+sub.Length+print.Length];
  Array.Copy(BitConverter.GetBytes((uint)0xa000000c),0,b,0,4);
  Array.Copy(BitConverter.GetBytes((ushort)(12+sub.Length+print.Length)),0,b,4,2);
  Array.Copy(BitConverter.GetBytes((ushort)sub.Length),0,b,10,2);
  Array.Copy(BitConverter.GetBytes((ushort)sub.Length),0,b,12,2);
  Array.Copy(BitConverter.GetBytes((ushort)print.Length),0,b,14,2);
  Array.Copy(sub,0,b,20,sub.Length);Array.Copy(print,0,b,20+sub.Length,print.Length);return b;
 }
}'''
    command = (
        "$ErrorActionPreference='Stop';$n=@'\n" + match.group(1) + "\n'@;\n"
        "Add-Type -TypeDefinition $n -ReferencedAssemblies @('System.dll','System.Core.dll','System.Security.dll');"
        "$b=@'\n" + builder + "\n'@;\nAdd-Type -TypeDefinition $b;"
        "$validDir='O:BAG:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)';"
        "$validFile='O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)';"
        "if(-not [NativeStoreGuardFixtureV1]::AcceptPrivateDescriptor($validDir,$true)){throw 'directory descriptor'};"
        "if(-not [NativeStoreGuardFixtureV1]::AcceptPrivateDescriptor($validFile,$false)){throw 'file descriptor'};"
        "foreach($sd in @('O:SYG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)',"
        "'O:BAG:BAD:(A;;FA;;;SY)(A;;FA;;;BA)',"
        "'O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;FR;;;WD)',"
        "'O:BAG:BAD:P(A;;FA;;;BA)(A;;FA;;;BA)',"
        "'O:BAG:BAD:P(A;;GA;;;SY)(A;;FA;;;BA)','O:BAG:BAD:P')){"
        "if([NativeStoreGuardFixtureV1]::AcceptPrivateDescriptor($sd,$false)){throw 'unsafe descriptor accepted'}};"
        "if([NativeStoreGuardFixtureV1]::ShapeReason(16,1,$true) -cne ''){throw 'directory shape'};"
        "if([NativeStoreGuardFixtureV1]::ShapeReason(32,1,$false) -cne ''){throw 'file shape'};"
        "if([NativeStoreGuardFixtureV1]::ShapeReason(1040,1,$true) -cne 'reparse'){throw 'reparse shape'};"
        "if([NativeStoreGuardFixtureV1]::ShapeReason(32,2,$false) -cne 'multiple_links'){throw 'hardlink shape'};"
        "if([NativeStoreGuardFixtureV1]::ShapeReason(16,1,$false) -cne 'shape'){throw 'type shape'};"
        r"$target='C:\fixture\own-target';"
        "if([IO.Path]::GetFullPath($target) -cne $target){throw 'noncanonical model path'};"
        "$good=[GuardReparseModel]::Build($target);"
        "if(-not [NativeStoreGuardFixtureV1]::AcceptReparseData($good,$good.Length,$target)){throw 'valid reparse model'};"
        r"if([NativeStoreGuardFixtureV1]::AcceptReparseData($good,$good.Length,'C:\elsewhere')){throw 'outside target'};"
        "foreach($mode in @('tag','relative','length','offset','odd','truncated')){"
        "$data=[byte[]]$good.Clone();$count=$data.Length;"
        "switch($mode){'tag'{$data[0]=0};'relative'{$data[16]=1};'length'{$data[4]=255;$data[5]=255};"
        "'offset'{$data[8]=254;$data[9]=255};'odd'{$data[10]=1};'truncated'{$count=19}};"
        "if([NativeStoreGuardFixtureV1]::AcceptReparseData($data,$count,$target)){throw 'bad reparse model'}};"
        "$sizes=@{};foreach($name in @('Unicode','Attributes','IoStatus','FileInfo')){"
        "$type=[NativeStoreGuardFixtureV1].GetNestedType($name,[Reflection.BindingFlags]::NonPublic);"
        "$sizes[$name]=[Runtime.InteropServices.Marshal]::SizeOf([Activator]::CreateInstance($type))};"
        "$r=[NativeStoreGuardFixtureV1]::Run('synthetic-review-only');"
        "if($r['ok'] -ne $false -or $r['created'] -ne $false -or $r['code'] -cne 'enabled_admin_required'){throw 'native admin guard'};"
        "@{descriptor_cases=8;shape_cases=5;reparse_cases=8;sizes=$sizes;ordinary_guard=$true}|ConvertTo-Json -Depth 5 -Compress"
    )
    result = json.loads(ordinary_ps(command).stdout)
    assert result == {
        'descriptor_cases': 8, 'shape_cases': 5, 'reparse_cases': 8,
        'sizes': {'Unicode': 16, 'Attributes': 48, 'IoStatus': 16, 'FileInfo': 52},
        'ordinary_guard': True,
    }
