"""Unelevated Windows process fixtures only; no UAC, installation or Hyper-V."""
import base64
import os
import subprocess
from pathlib import Path

import pytest


def quote(value):
    return "'" + str(value).replace("'", "''") + "'"


@pytest.mark.skipif(os.name != 'nt', reason='native Windows watchdog fixture')
def test_native_watchdog_parse_compile_timeout_and_descendant_cleanup(tmp_path):
    from runtime.privileged_host import _windows_paths

    _, exe = _windows_paths()
    scripts = Path(__file__).resolve().parents[2] / 'scripts'
    helper = scripts / 'privileged_host_helper.ps1'
    installer = scripts / 'install_privileged_host_helper.ps1'
    pid_file = tmp_path / 'descendant.pid'
    descendant = (
        "$ErrorActionPreference='Stop'; $psi=New-Object Diagnostics.ProcessStartInfo; "
        f'$psi.FileName={quote(exe)}; '
        "$psi.Arguments='-NoProfile -NonInteractive -Command \"Start-Sleep -Seconds 30\"'; "
        '$psi.UseShellExecute=$false; $psi.CreateNoWindow=$true; '
        '$proc=[Diagnostics.Process]::Start($psi); '
        f'[IO.File]::WriteAllText({quote(pid_file)},$proc.Id.ToString()); exit 0'
    )
    encoded = base64.b64encode(descendant.encode('utf-16-le')).decode('ascii')
    script = f"""
$ErrorActionPreference='Stop'
foreach ($path in @({quote(helper)},{quote(installer)})) {{
    $tokens=$null; $errors=$null
    $ast=[Management.Automation.Language.Parser]::ParseFile($path,[ref]$tokens,[ref]$errors)
    if ($errors.Count) {{ throw 'PowerShell syntax failure' }}
}}
$text=[IO.File]::ReadAllText({quote(helper)})
$start=$text.IndexOf('using System;'); $end=$text.IndexOf("'@",$start)
Add-Type -TypeDefinition $text.Substring($start,$end-$start)
$exe={quote(exe)}; $cwd={quote(tmp_path)}
if ([EvidenceWatchdog]::Run($exe,'-NoProfile -NonInteractive -Command "exit 0"',$cwd,10000) -ne 0) {{
    throw 'Success mismatch'
}}
if ([EvidenceWatchdog]::Run($exe,'-NoProfile -NonInteractive -Command "exit 7"',$cwd,10000) -ne 7) {{
    throw 'Failure mismatch'
}}
if ([EvidenceWatchdog]::Run($exe,'-NoProfile -NonInteractive -Command "Start-Sleep -Seconds 30"',$cwd,200) -ne 124) {{
    throw 'Timeout mismatch'
}}
if ([EvidenceWatchdog]::Run($exe,'-NoProfile -NonInteractive -EncodedCommand {encoded}',$cwd,10000) -ne 0) {{
    throw 'Descendant fixture mismatch'
}}
$childId=[int][IO.File]::ReadAllText({quote(pid_file)})
$gone=$false
for ($i=0; $i -lt 50; $i++) {{
    try {{ $child=[Diagnostics.Process]::GetProcessById($childId); $gone=$child.HasExited; $child.Dispose() }}
    catch [ArgumentException] {{ $gone=$true }}
    if ($gone) {{ break }}
    [Threading.Thread]::Sleep(100)
}}
if (-not $gone) {{ throw 'Descendant survived job close' }}
Write-Output 'WATCHDOG_FIXTURES_PASSED'
"""
    result = subprocess.run([str(exe), '-NoProfile', '-NonInteractive', '-Command', script],
                            capture_output=True, text=True, timeout=25)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'WATCHDOG_FIXTURES_PASSED' in result.stdout
