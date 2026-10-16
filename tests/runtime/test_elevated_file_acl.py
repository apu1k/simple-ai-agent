"""File-creation ACL regressions; no installation, UAC or protected-path writes.

The native fixture extracts only two function definitions. It checks the exact
production descriptor in memory, then substitutes the current user as owner/group
for disposable files so no Administrator token is needed. The production DACL is
unchanged. This does not establish real Administrator ownership or UAC behavior.
"""
import os
import re
import subprocess
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / 'scripts'
INSTALLER = 'install_privileged_command_helper.ps1'
HELPER = 'privileged_command_helper.ps1'


def quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def test_installer_and_helper_use_the_same_explicit_protected_file_descriptor():
    definitions = []
    for name, argument in ((INSTALLER, '$OperatorSid'), (HELPER, '$identity.User.Value')):
        text = (SCRIPTS / name).read_text(encoding='utf-8')
        match = re.search(
            r'(?ms)^function New-ProtectedFileSecurity\(\[string\]\$OperatorSid\) \{\n.*?^\}',
            text,
        )
        assert match is not None, f'{name} must explicitly construct its file DACL'
        definitions.append(match.group())
        assert '(A;;FA;;;SY)(A;;FA;;;BA)(A;;FRFX;;;' in match.group()
        assert f'$fileSecurity = New-ProtectedFileSecurity {argument}' in text
        assert '$actual = Get-Acl -LiteralPath $path -ErrorAction Stop' in text
        assert '$actual.GetSecurityDescriptorSddlForm($sections) -cne' in text
        assert '$fileSecurity.GetSecurityDescriptorSddlForm($sections)' in text
    assert definitions[0] == definitions[1]


@pytest.mark.skipif(os.name != 'nt', reason='native unelevated Windows ACL fixture')
@pytest.mark.parametrize('script_name,names', [
    (INSTALLER, ('helper.ps1', 'policy.json')),
    (HELPER, ('fixture.start.json', 'fixture.approved.json',
              'fixture.payload.ps1', 'fixture.result.json')),
])
def test_native_creation_preserves_readable_read_only_operator_dacl(tmp_path, script_name, names):
    from runtime.privileged_host import _windows_paths

    _, exe = _windows_paths()
    file_names = ','.join(quote(name) for name in names)
    script = f"""
$ErrorActionPreference = 'Stop'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {{
    throw 'This regression fixture must remain unelevated'
}}
$OperatorSid = $identity.User.Value
$tokens = $null; $errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    {quote(SCRIPTS / script_name)}, [ref]$tokens, [ref]$errors)
if ($errors.Count) {{ throw ($errors | Out-String) }}
foreach ($name in @('New-ProtectedFileSecurity', 'Write-New')) {{
    $definitions = @($ast.FindAll({{
        param($node)
        $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -ceq $name
    }}, $true))
    if ($definitions.Count -ne 1) {{ throw 'Missing or duplicate fixture function' }}
    # Only fixed function definitions; never evaluate the installer/helper body.
    Invoke-Expression $definitions[0].Extent.Text
}}
function Assert-Descriptor([Security.AccessControl.FileSecurity]$Acl, [string]$Owner) {{
    if ($Acl.GetOwner([Security.Principal.SecurityIdentifier]).Value -cne $Owner -or
        $Acl.GetGroup([Security.Principal.SecurityIdentifier]).Value -cne $Owner -or
        -not $Acl.AreAccessRulesProtected) {{ throw 'Owner/group/protection mismatch' }}
    $wanted = @{{'S-1-5-18' = 0x1f01ff; 'S-1-5-32-544' = 0x1f01ff}}
    $wanted.Add($OperatorSid, 0x1200a9)
    $rules = @($Acl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier]))
    if ($rules.Count -ne 3) {{ throw 'Missing or excessive file ACEs' }}
    foreach ($rule in $rules) {{
        $sid = $rule.IdentityReference.Value
        if (-not $wanted.ContainsKey($sid) -or
            $rule.AccessControlType -ne [Security.AccessControl.AccessControlType]::Allow -or
            $rule.IsInherited -or
            $rule.InheritanceFlags -ne [Security.AccessControl.InheritanceFlags]::None -or
            $rule.PropagationFlags -ne [Security.AccessControl.PropagationFlags]::None -or
            [int]$rule.FileSystemRights -ne $wanted[$sid]) {{ throw 'Unexpected file access' }}
        $wanted.Remove($sid)
    }}
    if ($wanted.Count -ne 0) {{ throw 'Missing required file access' }}
}}
$fileSecurity = New-ProtectedFileSecurity $OperatorSid
Assert-Descriptor $fileSecurity 'S-1-5-32-544'
# Only owner/group are substituted; operator read/execute ACE stays read-only.
$fileSecurity.SetOwner($identity.User)
$fileSecurity.SetGroup($identity.User)
$root = {quote(tmp_path)}
$receipts = $root
[byte[]]$data = [Text.Encoding]::UTF8.GetBytes('fixture content')
foreach ($name in @({file_names})) {{
    Write-New $name $data
    $path = [IO.Path]::Combine($root, $name)
    Assert-Descriptor (Get-Acl -LiteralPath $path) $OperatorSid
    if ([Text.Encoding]::UTF8.GetString([IO.File]::ReadAllBytes($path)) -cne 'fixture content') {{
        throw 'Created file cannot be read by the unelevated operator'
    }}
    $refused = $false
    try {{ Write-New $name ([byte[]]@(0)) }} catch {{ $refused = $true }}
    if (-not $refused -or
        [Text.Encoding]::UTF8.GetString([IO.File]::ReadAllBytes($path)) -cne 'fixture content') {{
        throw 'Create-new protection was lost'
    }}
}}
Write-Output 'FILE_ACL_FIXTURES_PASSED'
"""
    result = subprocess.run(
        [str(exe), '-NoProfile', '-NonInteractive', '-Command', script],
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'FILE_ACL_FIXTURES_PASSED' in result.stdout
