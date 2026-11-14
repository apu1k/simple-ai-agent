"""Fixed native pre-load leases: ordinary fixtures, NEVER protected setup.

Only disposable C# copies adapt ancestor/private admission. Identity, relative
opens, shape, hashes, sharing, budget and checked-close code are real. Observed
pins are TEST consistency data. No elevation, installation or VM operations.
"""
from __future__ import annotations

import ctypes as c
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime import elevated_commands as client
from runtime.command_lifetime import CommandLifetime
from runtime.privileged_host import PrivilegedHostError, _windows_paths
from runtime.privileged_turn import ELEVATED_OPERATION, PrivilegedClaim, PrivilegedTurn
from tests.runtime.test_elevated_commands import quote
from tests.runtime.test_elevated_receipts import receipt

ROOT = Path(__file__).resolve().parents[2]
NAMES = ('policy.json', 'validator-setup-host.exe', 'validator-setup-host.exe.config',
    'validator-setup-watchdog.exe', 'validator-setup-watchdog.exe.config')


def identity(path):
    """Observe only a known fixture path; never locate a process or authorize it."""
    class Info(c.Structure):
        _fields_ = [('attributes', c.c_uint32), ('times', c.c_uint32 * 6), ('volume', c.c_uint32),
            ('size_high', c.c_uint32), ('size_low', c.c_uint32), ('links', c.c_uint32),
            ('index_high', c.c_uint32), ('index_low', c.c_uint32)]
    k = c.WinDLL('kernel32', use_last_error=True)
    k.CreateFileW.argtypes = [c.c_wchar_p, c.c_uint32, c.c_uint32, c.c_void_p, c.c_uint32, c.c_uint32, c.c_void_p]
    k.CreateFileW.restype = c.c_void_p
    k.GetFileInformationByHandle.argtypes = [c.c_void_p, c.POINTER(Info)]
    k.GetFileInformationByHandle.restype = c.c_int
    k.CloseHandle.argtypes, k.CloseHandle.restype = [c.c_void_p], c.c_int
    handle = k.CreateFileW(str(path), 0x80, 7, None, 3, 0x02200000, None)
    assert handle and handle != c.c_void_p(-1).value, c.get_last_error()
    try:
        info = Info()
        assert k.GetFileInformationByHandle(handle, c.byref(info)), c.get_last_error()
        return info.volume, (info.index_high << 32) | info.index_low
    finally:
        assert k.CloseHandle(handle), 'Fixture identity close UNKNOWN'


def ordinary_source(*, skip_private=False, production=False, fault=None):
    from night_shifts.ubuntu_preparation_control import _current_user_sid
    text = (ROOT / 'scripts/privileged_command_helper.ps1').read_text(encoding='utf-8')
    start = text.index('using System;')
    text = text[start:text.index("'@", start)]
    old = '            IntPtr owner,group,dacl,descriptor;'
    assert text.count(old) == 1
    text = text.replace(old, '            if (ancestor || PreloadFixture.SkipPrivate) return "EXPLICIT_ORDINARY_DESCRIPTOR_ADAPTER";\n' + old)
    if not production:
        old = 'const string Admins="S-1-5-32-544",SystemSid='
        assert text.count(old) == 1
        text = text.replace(old, f'const string Admins="{_current_user_sid()}",SystemSid=')
        assert text.count('sd.Group.Value!=Admins') == 1
        text = text.replace('sd.Group.Value!=Admins', 'sd.Group.Value!=PreloadFixture.Group')
    faults = {
        'case_observation': ('!GetFileInformationByHandleEx(e.Handle,23,out flags,4) || flags!=0',
            '!GetFileInformationByHandleEx(e.Handle,23,out flags,4) || flags!=0 || PreloadFixture.Refuse'),
        'read_observation': ('!ReadFile(e.Handle,buffer,(uint)buffer.Length,out read,IntPtr.Zero) || read>buffer.Length',
            '!ReadFile(e.Handle,buffer,(uint)buffer.Length,out read,IntPtr.Zero) || read>buffer.Length || PreloadFixture.Refuse'),
        'close_observation': ('            if (!closed) throw new Exception("Native setup handle close unknown");',
            '            if (!closed || PreloadFixture.Refuse) throw new Exception("Native setup handle close unknown");'),
    }
    if fault in faults:
        old, new = faults[fault]
        assert text.count(old) == 1
        text = text.replace(old, new)
    return text + ('\npublic static class PreloadFixture { public static string Group; public static bool Refuse=true; public static bool SkipPrivate='
        + str(skip_private).lower() + '; }\n')


@pytest.mark.parametrize('capability', [None, False, True, 0, 2, '1'])
def test_fixed_preload_refuses_older_or_malformed_deployment_before_pending(monkeypatch, tmp_path, capability):
    policy = dict(operator_sid='fixture', helper_sha256='c' * 64, max_timeout=900, lifetime_protocol=1, preparation_protocol=1)
    if capability is not None:
        policy['setup_preload_protocol'] = capability
    monkeypatch.setattr(client, 'local_path', lambda *args, **kwargs: tmp_path)
    monkeypatch.setattr(client, 'load_launcher', lambda: (tmp_path, tmp_path / 'powershell.exe', policy))
    monkeypatch.setattr(client, 'await_approval', lambda *args: pytest.fail('must refuse before pending'))
    with pytest.raises(PrivilegedHostError, match='native setup pre-load deployment'):
        client.run_approved_script(PrivilegedTurn(), PrivilegedClaim('a' * 32, time.time() + 30, ELEVATED_OPERATION),
            'exit 0', 20, 'fixture', str(tmp_path), setup_preload='{}')


@pytest.mark.parametrize('value', ['', 'x' * 4097, '\n', '\x00', 'é', 1, True])
def test_preload_transport_is_bounded_ascii_before_pending(monkeypatch, tmp_path, value):
    policy = dict(operator_sid='fixture', helper_sha256='c' * 64, max_timeout=900, lifetime_protocol=1,
        preparation_protocol=1, setup_preload_protocol=1)
    monkeypatch.setattr(client, 'local_path', lambda *args, **kwargs: tmp_path)
    monkeypatch.setattr(client, 'load_launcher', lambda: (tmp_path, tmp_path / 'powershell.exe', policy))
    monkeypatch.setattr(client, 'await_approval', lambda *args: pytest.fail('must refuse before pending'))
    with pytest.raises(ValueError, match='Bounded ASCII'):
        client.run_approved_script(PrivilegedTurn(), PrivilegedClaim('a' * 32, time.time() + 30, ELEVATED_OPERATION),
            'exit 0', 20, 'fixture', str(tmp_path), setup_preload=value)


@pytest.mark.parametrize('value', [None, 1, 'true', True, False])
def test_preload_receipt_has_no_implicit_or_inconsistent_evidence(value):
    data = receipt()
    data.update(process_tree_observed=True, lifetime_observed=True, preparation_observed=True, setup_preload_observed=value)
    claim = PrivilegedClaim(data['request_id'], 1000, ELEVATED_OPERATION)
    if type(value) is bool:
        client.validate_receipt(data, claim, 'b' * 64, 'c' * 64)
        if value:
            data['preparation_observed'] = False
            with pytest.raises(PrivilegedHostError):
                client.validate_receipt(data, claim, 'b' * 64, 'c' * 64)
    else:
        with pytest.raises(PrivilegedHostError):
            client.validate_receipt(data, claim, 'b' * 64, 'c' * 64)


def test_helper_native_hold_precedes_every_durable_write_and_survives_until_checked_close():
    text = (ROOT / 'scripts/privileged_command_helper.ps1').read_text(encoding='utf-8')
    assert text.index('$preparation.HoldSetup(') < text.index("Write-Receipt ($RequestId + '.start.json')")
    assert text.index('$preparation.Dispose(); $preparation = $null') < text.index('$result.setup_preload_observed =')
    assert 'setup_preload_sha256=$preloadHash' in text
    assert len(text.encode('utf-8')) <= 65536
    install = (ROOT / 'scripts/install_privileged_command_helper.ps1').read_text(encoding='utf-8')
    assert 'setup_preload_protocol=1' in install


@pytest.mark.skipif(os.name != 'nt', reason='ordinary native held-preload fixture')
@pytest.mark.parametrize('mode', ['normal', 'publish', 'production_private_refusal', 'volume', 'root_identity',
    'claims_identity', 'receipts_identity', 'scratch_identity', 'pin', 'extent', 'name', 'hardlink',
    'private_descriptor', 'case_observation', 'read_observation', 'close_observation', 'repeat', 'disposed'])
def test_native_preload_relative_identity_security_pins_sharing_and_checked_close(mode):
    from night_shifts.ubuntu_preparation_control import _current_user_sid
    sid = _current_user_sid()
    folder = Path(tempfile.mkdtemp(prefix='command-preload-ordinary-'))
    target = folder / 'target'
    target.mkdir()
    for name in ('claims', 'receipts', 'scratch'):
        (target / name).mkdir()
    names = [*NAMES, *(['setup.packet'] if mode == 'publish' else [])]
    pins = []
    for name in names:
        raw = ('INERT FIXTURE ' + name).encode('ascii')
        (target / name).write_bytes(raw)
        pins.append(dict(name=name, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()))
    volume, root_index = identity(target)
    indices = [root_index, *(identity(target / name)[1] for name in ('claims', 'receipts', 'scratch'))]
    if mode == 'volume':
        volume ^= 1
    if mode.endswith('_identity'):
        indices[('root_identity', 'claims_identity', 'receipts_identity', 'scratch_identity').index(mode)] ^= 1 << 63
    if mode == 'pin':
        pins[3]['sha256'] = '0' * 64
    if mode == 'extent':
        pins[1]['bytes'] += 1
    if mode == 'name':
        pins[3]['name'] = 'alternate.exe'
    if mode == 'hardlink':
        os.link(target / names[3], folder / 'second-hardlink')
    source = folder / 'ordinary.cs'
    source.write_text(ordinary_source(production=mode == 'production_private_refusal', fault=mode), encoding='utf-8')
    data = folder / 'preload.json'
    data.write_text(json.dumps(dict(root=str(target), volume=volume, indices=indices, files=pins)), encoding='ascii')
    marker = folder / 'child.marker'
    child_code = f"from pathlib import Path; Path({str(marker)!r}).write_text('INERT', encoding='ascii')"
    args = '-I -S -B -c "' + child_code + '"'
    request_id = 'e' * 32
    lifetime = CommandLifetime(SimpleNamespace(execution_cancelled=lambda claim: False),
        PrivilegedClaim(request_id, time.time() + 60), sid)
    binding = lifetime.binding
    script = f"""
$ErrorActionPreference='Stop'
$i=[Security.Principal.WindowsIdentity]::GetCurrent()
if ((New-Object Security.Principal.WindowsPrincipal($i)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {{ throw 'UNELEVATED fixture required' }}
$i.Dispose()
Add-Type -Path {quote(source)}
$target={quote(target)}
[PreloadFixture]::Group=([IO.Directory]::GetAccessControl($target)).GetGroup([Security.Principal.SecurityIdentifier]).Value
foreach ($path in @($target,($target+'\\claims'),($target+'\\receipts'),($target+'\\scratch'))) {{
    $dir=New-Object Security.AccessControl.DirectorySecurity
    $dir.SetSecurityDescriptorSddlForm('D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;{sid})',[Security.AccessControl.AccessControlSections]::Access)
    [IO.Directory]::SetAccessControl($path,$dir)
}}
foreach ($path in [IO.Directory]::GetFiles($target)) {{
    $file=New-Object Security.AccessControl.FileSecurity
    $file.SetSecurityDescriptorSddlForm('D:P(A;;FA;;;SY)(A;;FA;;;{sid})',[Security.AccessControl.AccessControlSections]::Access)
    [IO.File]::SetAccessControl($path,$file)
}}
if ({quote(mode)} -eq 'private_descriptor') {{
    $file.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule(([Security.Principal.SecurityIdentifier]'S-1-1-0'),[Security.AccessControl.FileSystemRights]::Read,[Security.AccessControl.AccessControlType]::Allow)))
    [IO.File]::SetAccessControl(($target+'\\validator-setup-watchdog.exe'),$file)
}}
$v=[IO.File]::ReadAllText({quote(data)}) | ConvertFrom-Json
$rate=[Diagnostics.Stopwatch]::Frequency; $limit=[Diagnostics.Stopwatch]::GetTimestamp()+15*$rate
$p=[CommandWatchdog]::Prepare(15000,$limit,$rate,([DateTimeOffset]::UtcNow.ToUnixTimeSeconds()+25),{quote(binding['pipe'])},[uint32]{binding['owner_pid']},{quote(binding['owner_created'])},{quote(request_id)})
$a=$null; $cause=$null; $again=$null
try {{
    if ({quote(mode)} -eq 'disposed') {{ $p.Dispose() }}
    $p.HoldSetup($v.root,[uint32]$v.volume,[uint64[]]$v.indices,[string[]]@($v.files | ForEach-Object {{$_.name}}),[long[]]@($v.files | ForEach-Object {{$_.bytes}}),[string[]]@($v.files | ForEach-Object {{$_.sha256}}))
    if ({quote(mode)} -eq 'repeat') {{
        $p.HoldSetup($v.root,[uint32]$v.volume,[uint64[]]$v.indices,[string[]]@($v.files | ForEach-Object {{$_.name}}),[long[]]@($v.files | ForEach-Object {{$_.bytes}}),[string[]]@($v.files | ForEach-Object {{$_.sha256}}))
    }}
    foreach ($path in [IO.Directory]::GetFiles($target)) {{
        $blocked=$false
        try {{ $w=[IO.File]::Open($path,'Open','Write','ReadWrite'); $w.Dispose() }} catch [IO.IOException] {{ $blocked=$true }}
        if (-not $blocked) {{ throw 'FIXTURE_WRITE_SHARING_NOT_BLOCKED' }}
    }}
    $blocked=$false
    try {{ [IO.Directory]::Move($target,$target+'-renamed') }} catch [IO.IOException] {{ $blocked=$true }}
    if (-not $blocked) {{ throw 'FIXTURE_ANCESTRY_REPLACEMENT_NOT_BLOCKED' }}
    $a=[CommandWatchdog]::RunPrepared($p,{quote(sys.executable)},{quote(args)},{quote(folder)})
    $p.Dispose()
}} catch {{
    $a=$null; $e=$_.Exception; while ($e.InnerException) {{ $e=$e.InnerException }}; $cause=$e.Message
    try {{ $p.Check() }} catch {{ $e=$_.Exception; while ($e.InnerException) {{ $e=$e.InnerException }}; $again=$e.Message }}
}} finally {{ $p.Dispose() }}
# A checked successful disposal really releases the write-denial capability.
foreach ($path in [IO.Directory]::GetFiles($target)) {{ $w=[IO.File]::Open($path,'Open','Write','ReadWrite'); $w.Dispose() }}
@{{answer=$a;cause=$cause;again=$again}} | ConvertTo-Json -Depth 4 -Compress
"""
    path = folder / 'controller.ps1'
    path.write_text(script, encoding='utf-8-sig')
    _, exe = _windows_paths()
    with lifetime:
        result = subprocess.run([str(exe), '-NoProfile', '-NonInteractive', '-File', str(path)],
            capture_output=True, text=True, timeout=23, check=False)
    assert result.returncode == 0 and not result.stderr, (str(folder), result.stdout, result.stderr)
    observed = json.loads(result.stdout)
    if mode in ('normal', 'publish'):
        a = observed['answer']
        assert not observed['cause'] and a['Code'] == 0 and not a['Stdout'] and not a['Stderr'], (str(folder), observed)
        assert a['SetupPreloadObserved'] is a['PreparationObserved'] is a['ProcessTreeObserved'] is a['LifetimeObserved'] is True
        assert marker.read_text(encoding='ascii') == 'INERT'
    else:
        expected = {'repeat': 'Native setup pre-load already consumed', 'disposed': 'Preparation owner unavailable',
            'close_observation': 'Preparation close unknown'}.get(mode, 'Native setup pre-load refused')
        assert observed['answer'] is None and observed['cause'] == expected, (str(folder), observed)
        assert marker.exists() == (mode == 'close_observation'), str(folder)
    shutil.rmtree(folder)  # Exact fixture only, after known terminal observations.
