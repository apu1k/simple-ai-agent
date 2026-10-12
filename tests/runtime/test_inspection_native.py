"""Unelevated parser/watchdog/import fixtures. Never install or call Hyper-V."""
from __future__ import annotations

import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from night_shifts.inspection_bundle import bundle_bytes

ROOT = Path(__file__).resolve().parents[2]


def powershell(command: str) -> str:
    if os.name != 'nt':
        pytest.skip('native Windows parser fixture')
    executable = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    result = subprocess.run([str(executable), '-NoProfile', '-NonInteractive', '-Command', command],
                            capture_output=True, text=True, timeout=15, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def test_inspection_scripts_parse_without_execution():
    command = "$ErrorActionPreference='Stop'; "
    for name in ('scripts/install_privileged_inspection_helper.ps1', 'scripts/privileged_inspection_helper.ps1',
                 'night_shifts/backends/hyperv_scripts/maintain_image_copy.ps1'):
        path = str(ROOT / name).replace("'", "''")
        command += (f"$t=$null;$e=$null;[System.Management.Automation.Language.Parser]::ParseFile('{path}',"
                    "[ref]$t,[ref]$e)|Out-Null;if($e.Count){throw ($e|Out-String)};")
    powershell(command)


def test_process_watchdog_preserves_exit_code_and_kills_timed_out_fixture(tmp_path):
    script = (ROOT / 'scripts/privileged_inspection_helper.ps1').read_text()
    match = re.search("Add-Type -TypeDefinition @'\n(.*?)\n'@", script, re.S)
    assert match is not None
    # Only compile the fixed C# class. Never execute the supervisor's entry point.
    command = "Add-Type -TypeDefinition @'\n" + match[1] + "\n'@\n$ErrorActionPreference='Stop'; "
    exe = sys.executable.replace("'", "''")
    directory = str(tmp_path).replace("'", "''")
    command += (f"$code=[InspectionWatchdog]::Run('{exe}','-I -S -B -c \"raise SystemExit(7)\"','{directory}',10000);"
                "if($code -ne 7){throw 'exit code lost'};"
                f"$code=[InspectionWatchdog]::Run('{exe}','-I -S -B -c \"import time; time.sleep(30)\"','{directory}',500);"
                "if($code -ne 124){throw 'timeout lost'};")
    powershell(command)


def test_archive_reader_refuses_traversal_without_running_installer(tmp_path):
    good, bad = tmp_path / 'good.zip', tmp_path / 'bad.zip'
    for output, name in ((good, 'python.exe'), (bad, '../python.exe')):
        with zipfile.ZipFile(output, 'w') as archive:
            archive.writestr(name, b'SYNTHETIC_NOT_EXECUTABLE')
    installer = str(ROOT / 'scripts/install_privileged_inspection_helper.ps1').replace("'", "''")
    command = ("$ErrorActionPreference='Stop';Add-Type -AssemblyName System.IO.Compression;"
               f"$t=$null;$e=$null;$ast=[System.Management.Automation.Language.Parser]::ParseFile('{installer}',"
               "[ref]$t,[ref]$e);if($e.Count){throw 'parse failed'};"
               "$function=$ast.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] "
               "-and $n.Name -ceq 'Read-Archive'},$true);Invoke-Expression $function.Extent.Text;"
               f"$files=Read-Archive ([IO.File]::ReadAllBytes('{good}')) $true;"
               "if($files.Count -ne 1 -or -not $files.ContainsKey('python.exe')){throw 'reader failed'};"
               "$refused=$false;try{"
               f"Read-Archive ([IO.File]::ReadAllBytes('{bad}')) $true|Out-Null"
               "}catch{$refused=$true};if(-not $refused){throw 'traversal accepted'};")
    powershell(command)


def test_bundle_runs_without_app_packages_or_site_imports(tmp_path):
    bundle = tmp_path / 'bundle.zip'
    bundle.write_bytes(bundle_bytes())
    with zipfile.ZipFile(bundle) as archive:
        archive.extractall(tmp_path / 'payload')  # Self-authored fixed offline fixture only.
    payload = str(tmp_path / 'payload')
    code = (f"import sys;sys.path.insert(0,{payload!r});"
            "from night_shifts.image_finalization import media_files,FinalizationConfig;"
            "from pathlib import Path;"
            "config=FinalizationConfig(Path('D:/s.vhdx'),'a'*64,Path('D:/r.iso'),'b'*64,Path('D:/workspace'));"
            "files=media_files(config,'c'*32);assert len(files)==8;"
            "assert 'yaml' not in sys.modules;assert 'core.agent' not in sys.modules")
    result = subprocess.run([sys.executable, '-I', '-S', '-B', '-c', code],
                            cwd=tmp_path, capture_output=True, text=True, timeout=10, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
