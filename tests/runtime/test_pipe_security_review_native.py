"""Plaintext policy and disposable pipe fixtures; never operate a Hyper-V VM.

The ACL mutation below affects only a new, current-user-owned random fixture
pipe. It demonstrates non-revocation, not a permission-repair implementation.
"""
from __future__ import annotations

import base64
import ctypes
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CAPABILITY_SID = (
    'S-1-15-3-1024-2268835264-3721307629-241982045-173645152-'
    '1490879176-104643441-2915960892-1612460704'
)
FIXTURE_VM_SID = 'S-1-5-83-1-1-2-3-4'

PIPE_FIXTURE = r'''$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
$principal=New-Object Security.Principal.WindowsPrincipal($identity)
if($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Fixture must run unelevated'}
Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
public static class ReviewPipeInfo {
 [DllImport("kernel32.dll",SetLastError=true)] static extern bool GetNamedPipeInfo(IntPtr pipe,out uint flags,out uint output,out uint input,out uint maximum);
 [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)] static extern bool GetNamedPipeHandleState(IntPtr pipe,IntPtr state,out uint current,IntPtr collection,IntPtr timeout,IntPtr user,uint size);
 public static uint[] Read(IntPtr handle) {
  uint flags,output,input,maximum,current;
  if(!GetNamedPipeInfo(handle,out flags,out output,out input,out maximum)) throw new Win32Exception(Marshal.GetLastWin32Error());
  if(!GetNamedPipeHandleState(handle,IntPtr.Zero,out current,IntPtr.Zero,IntPtr.Zero,IntPtr.Zero,0)) throw new Win32Exception(Marshal.GetLastWin32Error());
  return new uint[]{flags,maximum,current};
 }
}
'@
$sid=$identity.User.Value
$security=New-Object IO.Pipes.PipeSecurity
$security.SetSecurityDescriptorSddlForm(('O:'+$sid+'G:'+$sid+'D:P(A;;FA;;;'+$sid+')(A;;FR;;;WD)'))
$name='night-shift-policy-fixture-'+[guid]::NewGuid().ToString('N')
$maximum=if($env:PIPE_REVIEW_MODE -eq 'existing2'){2}else{1}
$rights=[IO.Pipes.PipeAccessRights]::ChangePermissions
$server=New-Object IO.Pipes.NamedPipeServerStream($name,[IO.Pipes.PipeDirection]::InOut,$maximum,[IO.Pipes.PipeTransmissionMode]::Byte,[IO.Pipes.PipeOptions]::Asynchronous,4096,4096,$security,[IO.HandleInheritability]::None,$rights)
$client=$null
try{
 $wait=$server.BeginWaitForConnection($null,$null)
 $deny=New-Object IO.Pipes.PipeSecurity
 $deny.SetSecurityDescriptorSddlForm('D:P',[Security.AccessControl.AccessControlSections]::Access)
 $client=New-Object IO.Pipes.NamedPipeClientStream('.',$name,[IO.Pipes.PipeDirection]::In,[IO.Pipes.PipeOptions]::Asynchronous,[Security.Principal.TokenImpersonationLevel]::Anonymous)
 if($env:PIPE_REVIEW_MODE -eq 'new_denied'){
  $server.SetAccessControl($deny)
  $code=$null
  try{$client.Connect(500)}catch{
   $e=$_.Exception
   for($i=0;$e -and $i -lt 8;$i++){
    $hr=([long]$e.HResult)-band 4294967295
    if(($hr -band 4294901760)-eq 2147942400){$code=$hr -band 65535;break}
    $e=$e.InnerException
   }
  }
  if($code -ne 5){throw 'New fixture client was not denied with access denied'}
  [ordered]@{mode=$env:PIPE_REVIEW_MODE;unelevated=$true;new_client_win32_error=$code;vm_operations=0}|ConvertTo-Json -Compress
 }else{
  $client.Connect(1000);$server.EndWaitForConnection($wait)
  $before=[ReviewPipeInfo]::Read($client.SafePipeHandle.DangerousGetHandle())
  $server.SetAccessControl($deny)
  $sddl=$server.GetAccessControl().GetSecurityDescriptorSddlForm([Security.AccessControl.AccessControlSections]'Owner,Group,Access')
  $raw=New-Object Security.AccessControl.RawSecurityDescriptor($sddl)
  if($null -eq $raw.DiscretionaryAcl -or $raw.DiscretionaryAcl.Count -ne 0){throw 'Fixture DACL is not explicitly empty'}
  $bytes=[byte[]](84);$write=$server.WriteAsync($bytes,0,1)
  if(-not $write.Wait(1500)){throw 'Fixture write deadline'}
  $buffer=New-Object byte[] 1;$read=$client.ReadAsync($buffer,0,1)
  if(-not $read.Wait(1500) -or $read.Result -ne 1 -or $buffer[0] -ne 84){throw 'Existing granted handle did not retain read access'}
  $after=[ReviewPipeInfo]::Read($client.SafePipeHandle.DangerousGetHandle())
  if($before[1] -ne $maximum -or $before[2] -ne 1 -or $after[1] -ne $maximum -or $after[2] -ne 1){throw 'Fixture topology query mismatch'}
  [ordered]@{mode=$env:PIPE_REVIEW_MODE;unelevated=$true;maximum_instances=$after[1];current_instances=$after[2];empty_dacl_after_change=$true;preauthorized_client_read_succeeded=$true;fixture_bytes_read=1;vm_operations=0}|ConvertTo-Json -Compress
 }
}finally{if($client){$client.Dispose()};$server.Dispose()}
'''


def powershell_fixture(script: str, *, mode: str = '') -> dict:
    """Run bounded ordinary fixtures, not protected entry points or host queries."""
    if os.name != 'nt':
        pytest.skip('native Windows pipe-security fixture')
    if ctypes.windll.shell32.IsUserAnAdmin():
        pytest.skip('run this disposable fixture without elevation')
    assert mode in ('', 'existing1', 'existing2', 'new_denied')
    environment = dict(os.environ, PIPE_REVIEW_MODE=mode)
    executable = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    encoded = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
    result = subprocess.run(
        [str(executable), '-NoLogo', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
        env=environment, capture_output=True, text=True, timeout=10, check=False,
    )
    assert result.returncode == 0, (result.stdout + result.stderr)[:8000]
    assert len(result.stdout) < 8192
    return json.loads(result.stdout)


@pytest.mark.parametrize('maximum', [1, 2])
def test_tightened_dacl_does_not_revoke_existing_data_handle(maximum):
    result = powershell_fixture(PIPE_FIXTURE, mode=f'existing{maximum}')
    assert result['maximum_instances'] == maximum
    assert result['current_instances'] == 1
    assert result['empty_dacl_after_change'] is True
    assert result['preauthorized_client_read_succeeded'] is True
    assert result['fixture_bytes_read'] == 1
    assert result['unelevated'] is True and result['vm_operations'] == 0


def test_empty_dacl_before_connection_refuses_new_client():
    result = powershell_fixture(PIPE_FIXTURE, mode='new_denied')
    assert result['new_client_win32_error'] == 5
    assert result['unelevated'] is True and result['vm_operations'] == 0


def plaintext_guard(sddl: str) -> dict:
    """Evaluate ONLY the existing descriptor guard with synthetic identities."""
    source = (ROOT / 'night_shifts/backends/hyperv_scripts/maintain_image_copy.ps1').read_text(
        encoding='utf-8',
    )
    start = source.index('    if (-not $descriptor.Owner')
    end = source.index("    $channelStage = 'handshake_prepare'", start)
    guard = source[start:end]
    assert not re.search(r'(?i)\b(?:Start|Stop|Set|New|Remove|Get)-VM', guard)
    escaped = sddl.replace("'", "''")
    # Only the extracted pure guard shares this fixture scope, so its fixed
    # failure label is observable. Never evaluate the maintenance entry point.
    script = (
        "$ErrorActionPreference='Stop';Set-StrictMode -Version Latest;"
        f"$descriptor=New-Object Security.AccessControl.RawSecurityDescriptor('{escaped}');"
        "$pipeAllowed=@('S-1-5-18','S-1-5-32-544','S-1-5-21-1-2-3-1001','"
        + FIXTURE_VM_SID + "');$failureCode='operation_failed';$accepted=$false;"
        "try{. {\n" + guard + "\n};$accepted=$true}catch{"
        "if($failureCode -cne 'principal_rejected'){throw}};"
        "@{accepted=$accepted;code=$failureCode}|ConvertTo-Json -Compress"
    )
    return powershell_fixture(script)


@pytest.mark.parametrize('aces', [
    f'(A;;FA;;;{CAPABILITY_SID})',
    '(A;;FR;;;WD)',
    '(A;;FA;;;S-1-5-32-578)',
    (
        f'(A;;FA;;;{CAPABILITY_SID})'
        f'(A;;FA;;;{FIXTURE_VM_SID})'
        '(A;;FR;;;WD)(A;;FA;;;S-1-5-32-578)(A;;FA;;;BA)(A;;FA;;;SY)'
    ),
])
def test_plaintext_guard_does_not_trust_recorded_broad_grants(aces):
    result = plaintext_guard('O:SYG:SYD:' + aces)
    assert result == {'accepted': False, 'code': 'principal_rejected'}


def test_plaintext_guard_still_accepts_reviewed_principals_in_fixture():
    result = plaintext_guard(f'O:SYG:SYD:(A;;FA;;;SY)(A;;FA;;;BA)(A;;FA;;;{FIXTURE_VM_SID})')
    assert result['accepted'] is True
