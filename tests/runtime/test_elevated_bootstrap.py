"""Unelevated bootstrap/descendant fixtures. Never execute the protected helper."""
import os
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(os.name != 'nt', reason='native unelevated Windows fixture')
def test_utf8_script_bootstrap_exit_code_and_descendant_job_close(tmp_path):
    from runtime.privileged_host import _windows_paths
    _, exe = _windows_paths()
    helper = Path(__file__).resolve().parents[2] / 'scripts' / 'privileged_command_helper.ps1'
    payload = tmp_path / "reviewed ' unicode.ps1"
    pid_file = tmp_path / 'descendant.pid'
    unicode_text = 'Gr\u00fc\u00dfe \U0001f680'
    payload.write_text(f'[Console]::WriteLine("{unicode_text}"); exit 7\n', encoding='utf-8-sig')
    def quote(value):
        return "'" + str(value).replace("'", "''") + "'"
    # Extract only the fixed compiler input and argument function. No top-level
    # helper, installation checks, RunAs, Administrator operations or VM calls.
    script = f"""
$ErrorActionPreference='Stop'
$text=[IO.File]::ReadAllText({quote(helper)})
$start=$text.IndexOf('using System;'); $end=$text.IndexOf("'@",$start)
Add-Type -TypeDefinition $text.Substring($start,$end-$start)
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile({quote(helper)},[ref]$tokens,[ref]$errors)
$function=$ast.Find({{param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Command-Arguments'}},$true)
Invoke-Expression $function.Extent.Text
$exe={quote(exe)}; $cwd={quote(tmp_path)}; $payload={quote(payload)}
$a=[CommandWatchdog]::Run($exe,(Command-Arguments $payload),$cwd,10000)
if ($a.Code -ne 7 -or $a.Stdout -cnotmatch {quote(unicode_text)}) {{ throw 'UTF-8 bootstrap/exit mismatch' }}
$descendant = '$psi=New-Object Diagnostics.ProcessStartInfo; $psi.FileName=' + {quote(quote(exe))} +
    '; $psi.Arguments=' + {quote(quote('-NoProfile -NonInteractive -Command "Start-Sleep -Seconds 30"'))} +
    '; $psi.UseShellExecute=$false; $psi.CreateNoWindow=$true; $p=[Diagnostics.Process]::Start($psi); [IO.File]::WriteAllText(' +
    {quote(quote(pid_file))} + ',$p.Id.ToString()); exit 0'
[IO.File]::WriteAllText($payload,$descendant,(New-Object Text.UTF8Encoding($true)))
$a=[CommandWatchdog]::Run($exe,(Command-Arguments $payload),$cwd,10000)
if ($a.Code -ne 0) {{ throw 'Descendant launch fixture mismatch' }}
$childId=[int][IO.File]::ReadAllText({quote(pid_file)})
$gone=$false
for ($i=0; $i -lt 50; $i++) {{
    try {{ $child=[Diagnostics.Process]::GetProcessById($childId); $gone=$child.HasExited; $child.Dispose() }}
    catch [ArgumentException] {{ $gone=$true }}
    if ($gone) {{ break }}
    [Threading.Thread]::Sleep(100)
}}
if (-not $gone) {{ throw 'Descendant survived job close' }}
Write-Output 'BOOTSTRAP_FIXTURES_PASSED'
"""
    result = subprocess.run([str(exe), '-NoProfile', '-NonInteractive', '-Command', script],
                            capture_output=True, text=True, timeout=25)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'BOOTSTRAP_FIXTURES_PASSED' in result.stdout
