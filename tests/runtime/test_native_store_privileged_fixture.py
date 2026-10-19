"""Review/compile checks only; NEVER run the privileged fixture with elevation.

The C# descriptor checks and ABI layout checks are pure/disposable. They neither
validate an actual protected object nor obtain SYSTEM or VM/capability tokens.
"""
from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'scripts/validate_native_store_privileged_fixture.ps1'
CLASS = 'NativeStoreProfileFixtureV1'
FIXTURE = Path(
    r'C:\Program Files\AiAgentElevatedCommands\receipts'
    r'\native-store-fixture-22bf6d3069d64b7fbc8bd09771dcae6f'
)


def source():
    return SCRIPT.read_text(encoding='utf-8-sig')


def native_source():
    match = re.search(r"\$native = @'\n(.*?)\n'@", source(), re.DOTALL)
    assert match is not None
    return match.group(1)


def ordinary_powershell(script, *, expect_success=True):
    if os.name != 'nt':
        pytest.skip('Windows PowerShell compile/refusal checks')
    if ctypes.windll.shell32.IsUserAnAdmin():
        pytest.skip('these checks must run unelevated')
    exe = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    # Keep only a short bootstrap on the Windows command line. The complete
    # bounded test source goes over stdin, not expanded UTF-16/base64 argv.
    bootstrap = (
        "$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue';"
        "[Console]::InputEncoding=New-Object Text.UTF8Encoding($false,$true);"
        "[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false);"
        "$code=[Console]::In.ReadToEnd();& ([ScriptBlock]::Create($code))"
    )
    assert len(script.encode('utf-8')) <= 65536
    encoded = base64.b64encode(bootstrap.encode('utf-16-le')).decode('ascii')
    result = subprocess.run(
        [str(exe), '-NoLogo', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
        input=script, capture_output=True, text=True, encoding='utf-8', timeout=20, check=False,
    )
    assert len(result.stdout) + len(result.stderr) < 24000
    if expect_success:
        assert result.returncode == 0, (result.stdout + result.stderr)[:16000]
    return result


def test_script_is_bounded_standalone_fixed_scope():
    text = source()
    assert len(text.encode('utf-8')) < 32768
    assert 'NON-SECRET host-store native prototype marker v1' in text
    assert '22bf6d3069d64b7fbc8bd09771dcae6f' in text
    assert text.index('if (-not $AuthorizeNonSecretNativeStoreFixtureV1)') < text.index('$native =')
    assert text.index("throw 'Enabled Administrator token required") < text.index('$native =')
    assert not re.search(r'(?i)\b(?:Start|Stop|Set|Remove|New|Get)-VM\b', text)
    assert not re.search(r'\b(?:CreateProcess|StartProcess|Process\.Start|CreateService|SetNamedSecurityInfo|SetSecurityInfo)\b', text)
    assert 'production_python_probe_executed' in text and 'operator_python_executed' in text
    assert 'system_token_test' in text and 'real_vm_capability_token_test' in text
    assert 'Environment.Exit(70)' in text and 'RevertToSelf()' in text
    assert 'return ParentPath+"\\\\"+LeafName;' in text
    assert "Add-Type -TypeDefinition $native -ReferencedAssemblies" in text


def test_powershell_full_script_parses_without_execution():
    path = str(SCRIPT).replace("'", "''")
    command = (
        "$ErrorActionPreference='Stop';$tokens=$null;$errors=$null;"
        f"$ast=[Management.Automation.Language.Parser]::ParseFile('{path}',[ref]$tokens,[ref]$errors);"
        "if($errors.Count -ne 0){throw 'fixture parse failed'};"
        "@{parsed=$true;errors=$errors.Count}|ConvertTo-Json -Compress"
    )
    result = ordinary_powershell(command)
    assert json.loads(result.stdout) == {'parsed': True, 'errors': 0}


@pytest.mark.parametrize('authorize', [False, True])
def test_direct_execution_refuses_before_native_creation(authorize):
    if FIXTURE.exists():
        pytest.skip('V1 fixture retained; original entry point is not reinvoked')
    before = False
    path = str(SCRIPT).replace("'", "''")
    argument = ' -AuthorizeNonSecretNativeStoreFixtureV1' if authorize else ''
    command = f"$ErrorActionPreference='Stop';& '{path}'{argument}"
    result = ordinary_powershell(command, expect_success=False)
    assert result.returncode != 0
    expected = 'Enabled Administrator token required' if authorize else 'Explicit fixture authorization required'
    assert expected in result.stdout + result.stderr
    assert FIXTURE.exists() is before


def test_exact_embedded_execution_block_refuses_ordinary_token():
    if FIXTURE.exists():
        pytest.skip('V1 fixture retained; original execution block is not reinvoked')
    # The eventual approved request contains all source verbatim. It does not
    # execute a mutable source path or depend on operator-writable Python.
    wrapper = '& {\n' + source() + '\n} -AuthorizeNonSecretNativeStoreFixtureV1\n'
    assert len(wrapper.encode('utf-8')) <= 32768
    assert not FIXTURE.exists()
    result = ordinary_powershell(wrapper, expect_success=False)
    assert result.returncode != 0
    assert 'Enabled Administrator token required' in result.stdout + result.stderr
    assert not FIXTURE.exists()


def test_csharp_compiles_descriptors_and_native_layouts_without_privileged_run():
    before = hashlib.sha256(SCRIPT.read_bytes()).hexdigest()
    native = native_source()
    command = (
        "$ErrorActionPreference='Stop';$native=@'\n" + native + "\n'@;\n"
        "Add-Type -TypeDefinition $native -ReferencedAssemblies @('System.dll','System.Core.dll','System.Security.dll');"
        "$rows=@("
        "@{s='O:BAG:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)';d=$true;expect=$true},"
        "@{s='O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)';d=$false;expect=$true},"
        "@{s='O:BAG:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)';d=$false;expect=$false},"
        "@{s='O:SYG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)';d=$false;expect=$false},"
        "@{s='O:BAG:BAD:(A;;FA;;;SY)(A;;FA;;;BA)';d=$false;expect=$false},"
        "@{s='O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;FR;;;WD)';d=$false;expect=$false},"
        "@{s='O:BAG:BAD:P(A;;FA;;;BA)(A;;FA;;;BA)';d=$false;expect=$false},"
        "@{s='O:BAG:BAD:P(A;ID;FA;;;SY)(A;;FA;;;BA)';d=$false;expect=$false},"
        "@{s='O:BAG:BAD:P(A;;GA;;;SY)(A;;FA;;;BA)';d=$false;expect=$false},"
        "@{s='O:BAG:BAD:P';d=$false;expect=$false},"
        "@{s='O:BAG:BAD:NO_ACCESS_CONTROL';d=$false;expect=$false}"
        ");foreach($row in $rows){"
        f"if([{CLASS}]::AcceptPrivateDescriptor($row.s,$row.d) -ne $row.expect){{throw 'descriptor regression'}}"
        "};$sizes=@{};"
        "foreach($name in @('Unicode','Attributes','IoStatus','FileInfo')){"
        f"$type=[{CLASS}].GetNestedType($name,[Reflection.BindingFlags]::NonPublic);"
        "$sizes[$name]=[Runtime.InteropServices.Marshal]::SizeOf([Activator]::CreateInstance($type))"
        "};"
        # Compile/model/layout checks do not invoke V1 Run(), even unelevated.
        "@{descriptor_checks=$rows.Count;sizes=$sizes}|ConvertTo-Json -Depth 4 -Compress"
    )
    fixture_existed = FIXTURE.exists()
    result = json.loads(ordinary_powershell(command).stdout)
    assert result == {
        'descriptor_checks': 11,
        'sizes': {'Unicode': 16, 'Attributes': 48, 'IoStatus': 16, 'FileInfo': 52},
    }
    assert FIXTURE.exists() is fixture_existed
    assert hashlib.sha256(SCRIPT.read_bytes()).hexdigest() == before
