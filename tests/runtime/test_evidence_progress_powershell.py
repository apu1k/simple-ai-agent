"""Unelevated tiny-file fixtures: mocked Hyper-V and ACL application, no UAC."""
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest


def quote(value):
    return "'" + str(value).replace("'", "''") + "'"


@pytest.mark.skipif(os.name != 'nt', reason='native PowerShell fixture')
def test_collector_phase_order_timings_and_create_new_hint_serialization(tmp_path):
    from runtime.privileged_host import _windows_paths

    _, exe = _windows_paths()
    checkout = Path(__file__).resolve().parents[2]
    collector = checkout / 'night_shifts/backends/hyperv_scripts/collect_host_evidence.ps1'
    helper = checkout / 'scripts/privileged_host_helper.ps1'
    source = tmp_path / 'fixture.vhdx'
    iso = tmp_path / 'fixture.iso'
    source.write_bytes(b'vhdxfile' + b'tiny source fixture')
    iso.write_bytes(b'tiny ISO fixture')
    prefix = tmp_path / ('a' * 32)
    script = f"""
$ErrorActionPreference='Stop'
foreach ($path in @({quote(collector)},{quote(helper)})) {{
    $tokens=$null; $errors=$null
    $null=[Management.Automation.Language.Parser]::ParseFile($path,[ref]$tokens,[ref]$errors)
    if ($errors.Count) {{ throw 'PowerShell syntax failure' }}
}}
# Definitions shadow Hyper-V commands. No Hyper-V module or live paths used.
function Get-VM {{ return @() }}
function Get-VMHardDiskDrive {{ throw 'Unexpected disk query in empty inventory fixture' }}
function Get-VHD {{ param($Path)
    return [pscustomobject]@{{ VhdFormat='VHDX'; VhdType='Dynamic'; Size=21474836480;
        ParentPath=$null; Attached=$false }}
}}
# Mock ACL application for ordinary temp files. Real protected ACL validation
# belongs to the native client tests and separately authorized live acceptance.
function Set-Acl {{ param($LiteralPath,$AclObject) }}
$phasePrefix={quote(prefix)}; $phaseRequestId='{'a' * 32}'
$text=[IO.File]::ReadAllText({quote(helper)}).Replace("`r`n", "`n")
$marker='$phaseCode = @' + "'" + "`n"
$start=$text.IndexOf($marker)+$marker.Length
$end=$text.IndexOf("'@",$start)
if ($start -lt $marker.Length -or $end -lt $start) {{ throw 'Missing fixed phase callback' }}
. ([ScriptBlock]::Create($text.Substring($start,$end-$start)))
$json=& {quote(collector)} -SourceDisk {quote(source)} -RecoveryIso {quote(iso)} `
    -PhaseCallback ${{function:Write-EvidencePhase}}
$facts=$json | ConvertFrom-Json
$duplicateRefused=$false
try {{ Write-EvidencePhase 'inventory' }} catch {{ $duplicateRefused=$true }}
if (-not $duplicateRefused) {{ throw 'Phase receipt was overwritten' }}
$unknownRefused=$false
try {{ Write-EvidencePhase 'arbitrary' }} catch {{ $unknownRefused=$true }}
if (-not $unknownRefused) {{ throw 'Unknown phase accepted' }}
# Display failure cannot skip hashing or change the collector result.
$again=(& {quote(collector)} -SourceDisk {quote(source)} -RecoveryIso {quote(iso)} `
    -PhaseCallback {{ param($phase); throw 'UI fixture failure' }}) | ConvertFrom-Json
if ($again.source_sha256 -cne $facts.source_sha256 -or
    $again.recovery_iso_sha256 -cne $facts.recovery_iso_sha256) {{ throw 'Display changed evidence' }}
$facts | ConvertTo-Json -Depth 8 -Compress
"""
    result = subprocess.run([str(exe), '-NoProfile', '-NonInteractive', '-Command', script],
                            capture_output=True, text=True, timeout=25)
    assert result.returncode == 0, result.stdout + result.stderr
    facts = json.loads(result.stdout)
    assert facts['source_sha256'] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert facts['recovery_iso_sha256'] == hashlib.sha256(iso.read_bytes()).hexdigest()
    assert set(facts['phase_timings_ms']) == {'inventory', 'source_hash', 'iso_hash', 'recheck'}
    assert all(type(v) is int and v >= 0 for v in facts['phase_timings_ms'].values())
    records = [json.loads(path.read_text()) for path in sorted(tmp_path.glob('*.phase-*.json'))]
    assert {record['phase'] for record in records} == set(facts['phase_timings_ms'])
    assert all(record['request_id'] == 'a' * 32 and record['version'] == 1 for record in records)
    by_time = sorted(records, key=lambda record: record['started_at_utc'])
    assert [record['phase'] for record in by_time] == ['inventory', 'source_hash', 'iso_hash', 'recheck']
