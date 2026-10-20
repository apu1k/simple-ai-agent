"""Explicit local WMI public-bootstrap reader; no VM lifecycle or deployment.

Not imported by production inspection. Source/runtime trust, fresh permanent
claims, media/config confinement and outer native watchdog remain prerequisites.
A fabricated provider snapshot cannot attest origin; tests use explicit mocks.
"""
from __future__ import annotations

import base64
import ctypes
import json
import os
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from night_shifts.maintenance_credentials_prototype import (
    PUBLIC_ITEM_NAME, CredentialPrototypeRefused, PublicBootstrap, PublicBootstrapLatch,
)
from night_shifts.maintenance_tls_prototype import AttemptBinding
from night_shifts.public_bootstrap_kvp import (
    MAX_ITEMS, MAX_TOTAL_XML_CHARS, BootstrapKvpRefused, Budget, select_public_item,
)

MAX_CAPTURE_BYTES = 128 * 1024
# No remote server/moniker, friendly-name lookup, module import, VM action,
# InvokeMethod, KVP Set/Delete, serial access, dynamic script or guest target.
_QUERY = r'''
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
$vmId = '__VM__'
$attempt = '__ATTEMPT__'
$expectedName = 'night-shift-bootstrap-' + $attempt
$expectedOwner = 'night-shift-bootstrap-owner:' + $attempt
function Read-LocalRows([string]$Query, [string[]]$Properties) {
    $options = New-Object System.Management.EnumerationOptions
    $options.ReturnImmediately = $true
    $options.Rewindable = $false
    $options.BlockSize = 1
    $options.Timeout = [TimeSpan]::FromSeconds(2)
    $scope = New-Object System.Management.ManagementScope('\\.\root\virtualization\v2')
    $searcher = New-Object System.Management.ManagementObjectSearcher(
        $scope, (New-Object System.Management.ObjectQuery($Query)), $options)
    $collection = $null
    try {
        $collection = $searcher.Get()
        $count = 0
        foreach ($row in $collection) {
            try {
                $count++
                if ($count -gt 1) { throw 'ambiguous' }
                $copy = @{}
                foreach ($property in $Properties) { $copy[$property] = $row[$property] }
                [pscustomobject]$copy
            } finally { $row.Dispose() }
        }
    } finally {
        if ($null -ne $collection) { $collection.Dispose() }
        $searcher.Dispose()
    }
}
function Read-OwnedVm {
    $rows = @(Read-LocalRows "SELECT Name, ElementName, CreationClassName, EnabledState, TimeOfLastStateChange FROM Msvm_ComputerSystem WHERE Name='$vmId'" @('Name','ElementName','CreationClassName','EnabledState','TimeOfLastStateChange'))
    if ($rows.Count -ne 1 -or ([string]$rows[0].Name).ToLowerInvariant() -cne $vmId -or
        $rows[0].ElementName -cne $expectedName -or
        $rows[0].CreationClassName -cne 'Msvm_ComputerSystem' -or
        $rows[0].EnabledState -ne 2 -or -not $rows[0].TimeOfLastStateChange) { throw 'vm' }
    $settings = @(Read-LocalRows "SELECT VirtualSystemIdentifier, VirtualSystemType, Notes FROM Msvm_VirtualSystemSettingData WHERE VirtualSystemIdentifier='$vmId' AND VirtualSystemType='Microsoft:Hyper-V:System:Realized'" @('VirtualSystemIdentifier','VirtualSystemType','Notes'))
    if ($settings.Count -ne 1 -or
        ([string]$settings[0].VirtualSystemIdentifier).ToLowerInvariant() -cne $vmId -or
        $settings[0].VirtualSystemType -cne 'Microsoft:Hyper-V:System:Realized' -or
        @($settings[0].Notes).Count -ne 1 -or $settings[0].Notes[0] -cne $expectedOwner) { throw 'owner' }
    return [string]$rows[0].TimeOfLastStateChange
}
try {
    $before = Read-OwnedVm
    $rows = @(Read-LocalRows "SELECT SystemName, SystemCreationClassName, CreationClassName, EnabledState, OperationalStatus, GuestExchangeItems FROM Msvm_KvpExchangeComponent WHERE SystemName='$vmId'" @('SystemName','SystemCreationClassName','CreationClassName','EnabledState','OperationalStatus','GuestExchangeItems'))
    if ($rows.Count -ne 1 -or ([string]$rows[0].SystemName).ToLowerInvariant() -cne $vmId -or
        $rows[0].SystemCreationClassName -cne 'Msvm_ComputerSystem' -or
        $rows[0].CreationClassName -cne 'Msvm_KvpExchangeComponent' -or
        $rows[0].EnabledState -ne 2 -or @($rows[0].OperationalStatus).Count -lt 1 -or
        $rows[0].OperationalStatus[0] -ne 2) { throw 'component' }
    $items = @()
    if ($null -ne $rows[0].GuestExchangeItems) { $items = @($rows[0].GuestExchangeItems) }
    if ($items.Count -gt 32) { throw 'items' }
    $total = 0
    foreach ($item in $items) {
        if ($item -isnot [string] -or $item.Length -lt 1 -or $item.Length -gt 8192) { throw 'item' }
        $total += $item.Length
        if ($total -gt 65536) { throw 'items' }
    }
    $after = Read-OwnedVm
    if ($before -cne $after) { throw 'state_changed' }
    $result = @{ version = 1; vm_id = $vmId; attempt_id = $attempt;
        vm_name = $expectedName; owner = $expectedOwner; state_stamp = $before;
        items = @($items) }
    $text = $result | ConvertTo-Json -Depth 4 -Compress
    if ([Text.Encoding]::UTF8.GetByteCount($text) -gt 131072) { throw 'output' }
    [Console]::Write($text)
    exit 0
} catch {
    # No raw provider error, other KVP values, exception, path or certificate log.
    [Console]::Write('{"error":"provider_refused"}')
    exit 2
}
'''


def query_script(binding: AttemptBinding) -> str:
    """Render only validated GUID/hex values, never task/guest script fragments."""
    if type(binding) is not AttemptBinding:
        raise BootstrapKvpRefused('configuration')
    return _QUERY.replace('__VM__', binding.vm_id).replace('__ATTEMPT__', binding.attempt_id)


def _powershell() -> str:
    if os.name != 'nt' or ctypes.sizeof(ctypes.c_void_p) != 8:
        raise BootstrapKvpRefused('windows_x64_required')
    from ctypes import wintypes as w
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetSystemDirectoryW.argtypes = [w.LPWSTR, w.UINT]
    kernel.GetSystemDirectoryW.restype = w.UINT
    buffer = ctypes.create_unicode_buffer(32768)
    count = kernel.GetSystemDirectoryW(buffer, len(buffer))
    if not 0 < count < len(buffer):
        raise BootstrapKvpRefused('runtime')
    return str(Path(buffer.value) / 'WindowsPowerShell/v1.0/powershell.exe')


def _capture(script: str, budget: Budget) -> bytes:
    """Bound retained process output while draining; kill on timeout/cancel/limit.

    This process invokes no children. Its termination does NOT cancel a WMI
    provider operation in vmms.exe, stop a VM, or replace a native job watchdog.
    """
    budget.check()
    executable = _powershell()
    encoded = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
    process: subprocess.Popen[bytes] | None = None
    thread: threading.Thread | None = None
    chunks = bytearray()
    overflow = threading.Event()
    read_failed = threading.Event()
    try:
        process = subprocess.Popen(
            [executable, '-NoLogo', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            shell=False, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        assert process.stdout is not None
        stream = process.stdout

        def drain() -> None:
            try:
                while True:
                    chunk = stream.read(4096)
                    if not chunk:
                        break
                    room = MAX_CAPTURE_BYTES - len(chunks)
                    chunks.extend(chunk[:room])
                    if len(chunk) > room:
                        overflow.set()
                        break
            except OSError:
                read_failed.set()

        thread = threading.Thread(target=drain, daemon=True)
        thread.start()
        while process.poll() is None or thread.is_alive():
            remaining = budget.check()
            if overflow.is_set():
                raise BootstrapKvpRefused('provider_output_bound')
            if read_failed.is_set():
                raise BootstrapKvpRefused('provider_io')
            time.sleep(min(0.01, remaining))
        budget.check()
        if overflow.is_set() or read_failed.is_set() or process.returncode != 0:
            raise BootstrapKvpRefused('provider_refused')
        return bytes(chunks)
    except (OSError, subprocess.SubprocessError):
        raise BootstrapKvpRefused('provider_io') from None
    finally:
        if process is not None:
            try:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=1)
                if thread is not None:
                    thread.join(timeout=1)
                    if thread.is_alive():
                        raise BootstrapKvpRefused('reader_stop_unknown')
                if process.stdout is not None:
                    process.stdout.close()
            except (OSError, subprocess.SubprocessError):
                raise BootstrapKvpRefused('reader_stop_unknown') from None


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate')
        result[key] = value
    return result


def _snapshot(raw: bytes, binding: AttemptBinding) -> tuple[str, tuple[str, ...]]:
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_CAPTURE_BYTES:
        raise BootstrapKvpRefused('provider_output_bound')
    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique)
    except (ValueError, UnicodeError, RecursionError):
        raise BootstrapKvpRefused('provider_schema') from None
    fields = {'version', 'vm_id', 'attempt_id', 'vm_name', 'owner', 'state_stamp', 'items'}
    if (type(value) is not dict or set(value) != fields
            or type(value['version']) is not int or value['version'] != 1
            or value['vm_id'] != binding.vm_id or value['attempt_id'] != binding.attempt_id
            or value['vm_name'] != 'night-shift-bootstrap-' + binding.attempt_id
            or value['owner'] != 'night-shift-bootstrap-owner:' + binding.attempt_id
            or type(value['state_stamp']) is not str or not 1 <= len(value['state_stamp']) <= 64
            or type(value['items']) is not list or len(value['items']) > MAX_ITEMS
            or any(type(item) is not str for item in value['items'])
            or sum(len(item) for item in value['items']) > MAX_TOTAL_XML_CHARS):
        raise BootstrapKvpRefused('provider_schema')
    return value['state_stamp'], tuple(value['items'])


class LocalPublicBootstrapReader:
    """Single binding/deadline; failures terminal, first key/state frozen.

    No refresh/retrust after change, no VM discovery/lifecycle, no authorization
    boolean or trusted-snapshot input. Private _capture is mocked only in tests.
    Name/marker select the future fresh feasibility VM, never retained V1/V2.
    Name/owner/state checks are stability observations, NOT boot attestation.
    """

    def __init__(self, binding: AttemptBinding, *, timeout_seconds: float = 15.0,
                 cancelled: Callable[[], bool] = lambda: False) -> None:
        self._script = query_script(binding)
        self._binding = binding
        self._budget = Budget(timeout_seconds, cancelled)
        self._latch = PublicBootstrapLatch(binding)
        self._stamp: str | None = None
        self._observed = False
        self._failure: str | None = None

    def poll(self) -> PublicBootstrap | None:
        if self._failure is not None:
            raise BootstrapKvpRefused(self._failure)
        try:
            self._budget.check()
            stamp, items = _snapshot(_capture(self._script, self._budget), self._binding)
            self._budget.check()
            if self._stamp is not None and stamp != self._stamp:
                raise BootstrapKvpRefused('vm_state_changed')
            self._stamp = stamp
            raw = select_public_item(items, self._binding)
            if raw is None:
                if self._observed:
                    raise BootstrapKvpRefused('public_record_disappeared')
                return None
            result = self._latch.observe(raw, observed_vm_id=self._binding.vm_id,
                                         item_name=PUBLIC_ITEM_NAME, item_source=1)
            self._budget.check()
            self._observed = True
            return result
        except (BootstrapKvpRefused, CredentialPrototypeRefused) as error:
            self._failure = str(error)
            self._latch.close()
            raise BootstrapKvpRefused(self._failure) from None

    def close(self) -> None:
        if self._failure is None:
            self._failure = 'closed'
        self._latch.close()
