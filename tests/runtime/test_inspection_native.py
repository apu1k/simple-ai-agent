"""Unelevated parser/watchdog/import fixtures. Never install or call Hyper-V."""
from __future__ import annotations

import json
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


def maintenance_functions(*names: str) -> str:
    """Load reviewed pure functions only, never the maintenance entry point."""
    path = str(ROOT / 'night_shifts/backends/hyperv_scripts/maintain_image_copy.ps1').replace("'", "''")
    command = ("$ErrorActionPreference='Stop';$t=$null;$e=$null;"
               f"$ast=[System.Management.Automation.Language.Parser]::ParseFile('{path}',[ref]$t,[ref]$e);"
               "if($e.Count){throw 'parse failed'};")
    for name in names:
        command += ("$f=$ast.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] "
                    f"-and $n.Name -ceq '{name}'" + "},$true);"
                    "if(-not $f){throw 'missing fixture function'};Invoke-Expression $f.Extent.Text;")
    return command


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


@pytest.mark.parametrize('exception,stage,initial_code,code,native', [
    ("New-Object TimeoutException('PRIVATE_CANARY')", 'pipe_connect', 'operation_failed', 'timeout', None),
    ("New-Object Security.Principal.IdentityNotMappedException('PRIVATE_CANARY')", 'sid_resolve',
     'operation_failed', 'sid_unresolved', None),
    ("New-Object IO.IOException('PRIVATE_CANARY', -2147024891)", 'handshake_write',
     'operation_failed', 'win32_error', 5),
    ("New-Object ComponentModel.Win32Exception(5,'PRIVATE_CANARY')", 'acl_check',
     'principal_rejected', 'principal_rejected', 5),
])
def test_fixed_failure_labels_and_numeric_errors_never_include_exception_text(
    exception, stage, initial_code, code, native,
):
    command = maintenance_functions('Get-MaintenanceFailureDetails')
    command += ("$Identity='" + 'a' * 32 + "';$Mode='inspect';try{throw (" + exception + ")}" +
                f"catch{{Get-MaintenanceFailureDetails $_ 'CHANNEL' '{stage}' '{initial_code}' $null 'unknown'|"
                "ConvertTo-Json -Compress}")
    details = json.loads(powershell(command))
    assert details['code'] == code and details['win32_error'] == native
    assert 'CANARY' not in json.dumps(details)


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


@pytest.mark.parametrize('state,bad_owner,fail_readback,expected_stop,expected_observation', [
    ('Running', False, False, 1, 'off_observed'),
    ('Off', False, False, 0, 'off_observed'),
    ('Running', True, False, 0, 'unknown'),
    ('Running', False, True, 1, 'unknown'),
])
def test_failure_handler_observes_only_exact_owned_fake_vm(
    state, bad_owner, fail_readback, expected_stop, expected_observation,
):
    # Evaluate only the catch body with all Hyper-V operations shadowed by local
    # fake functions. No real VM, privilege, protected receipt or entry point.
    command = maintenance_functions('Assert-Owned', 'Get-MaintenanceFailureDetails')
    command += ("$Identity='" + 'a' * 32 + "';$Mode='inspect';$phase='CHANNEL';"
                "$channelStage='security_query';$failureCode='operation_failed';"
                "$vmName='fixture';$owner='fixture-owner';$expectedConfig='C:\\fixture';"
                "$vm=[pscustomobject]@{Id=[guid]'51434da9-9168-428a-8624-72a246ccc18d'};"
                "$script:owned=[pscustomobject]@{Id=$vm.Id;Name=$vmName;Notes=$owner;Path=$expectedConfig;State='"
                + state + "'};$script:queries=0;$script:stops=0;$script:captured=$null;")
    if bad_owner:
        command += "$script:owned.Notes='different-owner';"
    command += ("function Get-VM {param($Id,$ErrorAction) $script:queries++;"
                + ("if($script:queries -eq 2){throw 'READBACK_CANARY'};" if fail_readback else '')
                + "$script:owned};"
                "function Stop-VM {param($VM,[switch]$TurnOff,[switch]$Force,$ErrorAction)"
                "$script:stops++;$script:owned.State='Off'};"
                "function Write-MaintenanceReceipt {param($Path,$Value) $script:captured=$Value};"
                "$FailureReceipt='UNUSED_FIXTURE_PATH';"
                "$body=@($ast.EndBlock.Statements | Where-Object {$_ -is [System.Management.Automation.Language.TryStatementAst]})[0].CatchClauses[0].Body.Extent.Text;"
                "$invoke=\"try { throw (New-Object ComponentModel.Win32Exception(5,'PRIVATE_CANARY')) } catch \"+$body;"
                "try{Invoke-Expression $invoke;throw 'handler did not fail'}catch{"
                "if($_.Exception.Message -cne 'NS-MAINTENANCE-FAIL CHANNEL'){throw 'phase lost'}};"
                "@{details=$script:captured;stops=$script:stops}|ConvertTo-Json -Depth 4 -Compress")
    result = json.loads(powershell(command))
    assert result['stops'] == expected_stop
    details = result['details']
    assert details['stop_observation'] == expected_observation
    assert details['code'] == 'win32_error' and details['win32_error'] == 5
    assert details['channel_stage'] == 'security_query'
    assert 'CANARY' not in json.dumps(result)


def test_pipe_security_probe_uses_ordinary_fixture_and_preserves_numeric_error():
    script = (ROOT / 'night_shifts/backends/hyperv_scripts/maintain_image_copy.ps1').read_text()
    match = re.search("Add-Type -TypeDefinition @'\\n(.*?)\\n'@", script, re.S)
    assert match is not None
    command = maintenance_functions('Get-MaintenanceFailureDetails')
    command += "Add-Type -TypeDefinition @'\n" + match[1] + "\n'@\n"
    command += ("$Identity='" + 'a' * 32 + "';$Mode='inspect';"
                "$name='maintenance-acl-fixture-'+[guid]::NewGuid().ToString('N');"
                "$server=New-Object IO.Pipes.NamedPipeServerStream($name,[IO.Pipes.PipeDirection]::InOut,1,"
                "[IO.Pipes.PipeTransmissionMode]::Byte,[IO.Pipes.PipeOptions]::Asynchronous);$client=$null;"
                "try{$pending=$server.WaitForConnectionAsync();"
                "$client=New-Object IO.Pipes.NamedPipeClientStream('.', $name,[IO.Pipes.PipeDirection]::InOut,"
                "[IO.Pipes.PipeOptions]::Asynchronous);$client.Connect(3000);"
                "if(-not $pending.Wait(3000)){throw 'fixture connect failed'};"
                "$sddl=[MaintenancePipeSecurity]::Read($client.SafePipeHandle.DangerousGetHandle());"
                "$sd=New-Object Security.AccessControl.RawSecurityDescriptor($sddl);"
                "if(-not $sd.Owner -or -not $sd.DiscretionaryAcl){throw 'fixture descriptor absent'};"
                "try{[MaintenancePipeSecurity]::Read([IntPtr]::Zero)|Out-Null;throw 'invalid handle accepted'}"
                "catch{$details=Get-MaintenanceFailureDetails $_ 'CHANNEL' 'security_query' 'operation_failed' $null 'unknown';"
                "if($null -eq $details.win32_error){throw 'numeric error lost'};"
                "$details|ConvertTo-Json -Compress}"
                "}finally{if($client){$client.Dispose()};$server.Dispose()}")
    details = json.loads(powershell(command))
    assert details['code'] == 'win32_error' and details['win32_error'] > 0
    assert details['stop_observation'] == 'unknown' and details['vm_id'] is None


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


def test_fresh_installer_refuses_false_authorization_before_setup():
    # Complete parameter binding, but refuse before privilege/path/setup work.
    # The additional unelevated guard keeps this fixture non-privileged even if
    # the authorization check regresses. No real installation path is written.
    installer = str(ROOT / 'scripts/install_privileged_inspection_helper.ps1').replace("'", "''")
    command = """
$ErrorActionPreference='Stop'
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
$principal=New-Object Security.Principal.WindowsPrincipal($identity)
if($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){
    throw 'This fixture must remain unelevated'
}
$arguments=@{
    Bundle='Z:\\UNUSED-INSPECTION-FIXTURE\\bundle.zip'; BundleSha256=('a'*64)
    PythonArchive='Z:\\UNUSED-INSPECTION-FIXTURE\\python.zip'; PythonArchiveSha256=('b'*64)
    HelperSha256=('c'*64); OperatorSid=$identity.User.Value
    SourceDisk='Z:\\UNUSED-INSPECTION-FIXTURE\\source.vhdx'; SourceSha256=('d'*64)
    RecoveryIso='Z:\\UNUSED-INSPECTION-FIXTURE\\recovery.iso'; RecoveryIsoSha256=('e'*64)
    Workspace='Z:\\UNUSED-INSPECTION-FIXTURE\\workspace'
    InspectionApprovedUntilUtc=[DateTimeOffset]::UtcNow.AddHours(2)
    PythonProvenanceReviewed=$true; IsoProvenanceReviewed=$true; EvidencePreserved=$true
    AuthorizeNewInspectionAttempt=$false
}
$refused=$false
try { & '__INSTALLER__' @arguments }
catch {
    if($_.Exception.Message -cne 'A separately reviewed new inspection attempt must be authorized'){throw}
    $refused=$true
}
if(-not $refused){throw 'New attempt authorization was not enforced'}
Write-Output 'NEW_ATTEMPT_AUTHORIZATION_REFUSED'
""".replace('__INSTALLER__', installer)
    assert 'NEW_ATTEMPT_AUTHORIZATION_REFUSED' in powershell(command)


@pytest.mark.skipif(os.name != 'nt', reason='read-only native Program Files lookup')
@pytest.mark.parametrize('location', ['v2', 'legacy', 'checkout'])
def test_installed_worker_accepts_only_fixed_v2_location(monkeypatch, location):
    from night_shifts import inspection_worker as worker
    from runtime.privileged_host import _windows_paths
    from runtime.privileged_inspection import DIRECTORY

    program_files = _windows_paths()[0].parent
    root = program_files / DIRECTORY
    if location == 'checkout':
        path = ROOT / 'night_shifts/inspection_worker.py'
    else:
        path = (root if location == 'v2' else program_files / 'AiAgentHyperVInspection') / 'payload/night_shifts/inspection_worker.py'
    monkeypatch.setattr(worker, '__file__', str(path))
    if location == 'v2':
        assert worker.installed_root() == root
    else:
        with pytest.raises(ValueError, match='protected installation required'):
            worker.installed_root()
