param(
    [Parameter(Mandatory = $true)][string]$Identity,
    [Parameter(Mandatory = $true)][ValidateSet('inspect', 'finalize')][string]$Mode,
    [Parameter(Mandatory = $true)][string]$SourceDisk,
    [Parameter(Mandatory = $true)][string]$SourceSha256,
    [Parameter(Mandatory = $true)][string]$RecoveryIso,
    [Parameter(Mandatory = $true)][string]$RecoveryIsoSha256,
    [Parameter(Mandatory = $true)][string]$Workspace,
    [Parameter(Mandatory = $true)][string]$SeedIsoSha256,
    [Parameter(Mandatory = $true)][ValidateRange(120, 600)][int]$GuestTimeoutSeconds,
    [Parameter(Mandatory = $true)][string]$VmReceipt,
    [Parameter(Mandatory = $true)][string]$FailureReceipt
)
$ErrorActionPreference = 'Stop'
# New, copy-only recovery workload. Never start/reconfigure retained candidates.
# No mounts on Windows, keyboard injection, installer invocation or ACL repair.
if ($Identity -cnotmatch '^[0-9a-f]{32}$' -or
    (Split-Path -Leaf $Workspace) -cne $Identity -or
    $SourceSha256 -cnotmatch '^[0-9a-f]{64}$' -or
    $RecoveryIsoSha256 -cnotmatch '^[0-9a-f]{64}$' -or
    $SeedIsoSha256 -cnotmatch '^[0-9a-f]{64}$') {
    throw 'Untrusted maintenance identity or reviewed digests'
}
$vmName = 'night-shift-finalize-' + $Identity
$owner = 'night-shift-finalize-owner:' + $Identity
$copy = Join-Path $Workspace 'working-copy.vhdx'
$seed = Join-Path $Workspace 'maintenance.iso'
$configRoot = Join-Path $Workspace 'vm-config'
$phase = 'COPY'
$channelStage = 'not_applicable'
$failureCode = 'operation_failed'
$expectedConfig = Join-Path $configRoot $vmName
if (Get-VM -Name $vmName -ErrorAction SilentlyContinue) { throw 'Maintenance VM already exists' }
if ((Test-Path -LiteralPath $copy) -or (Test-Path -LiteralPath $configRoot) -or
    $SourceDisk -eq $copy -or $SourceDisk -eq $RecoveryIso -or $SourceDisk -eq $seed) {
    throw 'Refusing existing output or overlapping inputs'
}
foreach ($binding in @(@($RecoveryIso, $RecoveryIsoSha256), @($seed, $SeedIsoSha256))) {
    if ((Get-FileHash -LiteralPath $binding[0] -Algorithm SHA256).Hash -ne $binding[1]) {
        throw 'Reviewed recovery media changed'
    }
}
$vhd = Get-VHD -Path $SourceDisk -ErrorAction Stop
if ($vhd.VhdFormat -ne 'VHDX' -or $vhd.VhdType -ne 'Dynamic' -or
    $vhd.Size -ne 21474836480 -or $vhd.ParentPath -or $vhd.Attached) {
    throw 'Source must be an unattached, parentless dynamic 20 GiB VHDX'
}
$references = @()
foreach ($candidate in @(Get-VM -ErrorAction Stop)) {
    foreach ($drive in @(Get-VMHardDiskDrive -VM $candidate -ErrorAction Stop)) {
        if ($drive.Path -eq $SourceDisk) {
            if ($candidate.State -ne 'Off') { throw 'A source-disk VM is not OFF' }
            $references += @{ id = $candidate.Id.ToString(); state = 'Off' }
        }
    }
}
$vm = $null
$pipe = $null
$sourceLock = $null
$isoLock = $null
$seedLock = $null
function Assert-Owned($Candidate) {
    if (-not $Candidate -or $Candidate.Id -ne $vm.Id -or
        $Candidate.Name -cne $vmName -or $Candidate.Notes -cne $owner -or
        $Candidate.Path -ne $expectedConfig) {
        throw 'Exact maintenance VM identity changed; no action permitted'
    }
}
function Write-MaintenanceReceipt([string]$Path, $Value) {
    # Apply the parent's reviewed DACL and Administrators ownership atomically.
    # In the protected adapter both receipts live in its protected receipt tree.
    $bytes = [Text.Encoding]::UTF8.GetBytes(($Value | ConvertTo-Json -Depth 4 -Compress))
    if ($bytes.Length -gt 4096) { throw 'Maintenance receipt exceeds bound' }
    $security = New-Object Security.AccessControl.FileSecurity
    $security.SetOwner((New-Object Security.Principal.SecurityIdentifier('S-1-5-32-544')))
    $security.SetAccessRuleProtection($true, $false)
    $parentAcl = Get-Acl -LiteralPath ([IO.Path]::GetDirectoryName($Path))
    foreach ($rule in $parentAcl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier])) {
        $security.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule(
            $rule.IdentityReference, $rule.FileSystemRights, $rule.AccessControlType)))
    }
    $stream = New-Object IO.FileStream($Path, [IO.FileMode]::CreateNew,
        [Security.AccessControl.FileSystemRights]::Write, [IO.FileShare]::Read,
        4096, [IO.FileOptions]::WriteThrough, $security)
    try { $stream.Write($bytes, 0, $bytes.Length); $stream.Flush($true) }
    finally { $stream.Dispose() }
}
function Get-MaintenanceFailureDetails($Failure, [string]$Phase, [string]$Stage,
    [string]$Code, $VmId, [string]$StopObservation) {
    # Do not serialize exception text, arbitrary Data, SDDL, guest bytes or paths.
    $native = $null
    $exception = $Failure.Exception
    for ($depth = 0; $exception -and $depth -lt 8; $depth++) {
        if ($exception -is [ComponentModel.Win32Exception]) {
            $number = [long]$exception.NativeErrorCode
            if ($number -ge 0 -and $number -le 4294967295) { $native = $number }
        } elseif ($exception -is [IO.IOException]) {
            $hr = ([long]$exception.HResult) -band 4294967295
            if (($hr -band 4294901760) -eq 2147942400) { $native = $hr -band 65535 }
        }
        if ($Code -eq 'operation_failed' -and $exception -is [TimeoutException]) { $Code = 'timeout' }
        if ($Code -eq 'operation_failed' -and $Stage -eq 'sid_resolve' -and
            $exception -is [Security.Principal.IdentityNotMappedException]) { $Code = 'sid_unresolved' }
        if ($null -ne $native) { break }
        $exception = $exception.InnerException
    }
    if ($Code -eq 'operation_failed' -and $null -ne $native) { $Code = 'win32_error' }
    return @{ version = 1; id = $Identity; mode = $Mode; phase = $Phase;
        channel_stage = $Stage; code = $Code; win32_error = $native;
        vm_id = $VmId; stop_observation = $StopObservation }
}
function Read-BoundedFrame($Channel, $Clock, $LimitMilliseconds) {
    $data = New-Object System.IO.MemoryStream
    try {
        $buffer = New-Object byte[] 4096
        while ($true) {
            $remaining = $LimitMilliseconds - [int]$Clock.ElapsedMilliseconds
            if ($remaining -le 0) { throw 'Guest response deadline expired' }
            $pending = $Channel.ReadAsync($buffer, 0, $buffer.Length)
            if (-not $pending.Wait($remaining)) { throw 'Guest response deadline expired' }
            $count = $pending.Result
            if ($count -eq 0) { throw 'Guest serial channel closed' }
            for ($index = 0; $index -lt $count; $index++) {
                if ($buffer[$index] -eq 10) {
                    if ($index -ne $count - 1) { throw 'Unexpected trailing serial bytes' }
                    $utf8 = New-Object System.Text.UTF8Encoding($false, $true)
                    return $utf8.GetString($data.ToArray())
                }
                $data.WriteByte($buffer[$index])
                if ($data.Length -gt 32768) { throw 'Oversized guest receipt' }
            }
        }
    }
    finally { $data.Dispose() }
}
try {
    # This sharing mode denies writes/deletion while evidence is copied and the
    # recovery VM runs. A concurrent original-VM start must not write this disk.
    $sourceLock = [System.IO.File]::Open($SourceDisk, 'Open', 'Read', 'Read')
    $isoLock = [IO.File]::Open($RecoveryIso, 'Open', 'Read', 'Read')
    $seedLock = [IO.File]::Open($seed, 'Open', 'Read', 'Read')
    foreach ($binding in @(@($RecoveryIso, $RecoveryIsoSha256), @($seed, $SeedIsoSha256))) {
        if ((Get-FileHash -LiteralPath $binding[0] -Algorithm SHA256).Hash -ne $binding[1]) {
            throw 'Recovery media changed before its read-sharing lock'
        }
    }
    $volume = New-Object IO.DriveInfo([IO.Path]::GetPathRoot($Workspace))
    if ($volume.AvailableFreeSpace -lt ($sourceLock.Length + 536870912)) {
        throw 'Insufficient fresh space immediately before copying'
    }
    if ((Get-FileHash -LiteralPath $SourceDisk -Algorithm SHA256).Hash -ne $SourceSha256) {
        throw 'Source changed before the copy-only boundary'
    }
    $destination = [System.IO.File]::Open($copy, 'CreateNew', 'Write', 'None')
    try { $sourceLock.CopyTo($destination); $destination.Flush($true) }
    finally { $destination.Dispose() }
    if ((Get-FileHash -LiteralPath $copy -Algorithm SHA256).Hash -ne $SourceSha256) {
        throw 'Fresh copy does not match preserved source'
    }
    $phase = 'CREATE'
    if ($volume.AvailableFreeSpace -lt 536870912) { throw 'Workspace reserve exhausted' }
    $vm = New-VM -Name $vmName -Generation 2 -VHDPath $copy -Path $configRoot -MemoryStartupBytes 2147483648
    # Record observed GUID BEFORE configuration/start. A worker timeout is not
    # a VM lifetime bound. This receipt is evidence, never a cleanup authorization.
    $vmRecord = @{ version = 1; id = $Identity; vm_id = $vm.Id.ToString();
        vm_name = $vmName; expected_owner = $owner; expected_config = $expectedConfig;
        copy = $copy; cleanup = 'not_observed' }
    Write-MaintenanceReceipt $VmReceipt $vmRecord
    if ($vm.Path -ne $expectedConfig) { throw 'Unexpected maintenance configuration path' }
    Set-VM -VM $vm -Notes $owner -CheckpointType Disabled -AutomaticStartAction Nothing -AutomaticStopAction ShutDown
    Set-VMMemory -VM $vm -DynamicMemoryEnabled $false -StartupBytes 2147483648
    Set-VMProcessor -VM $vm -Count 2
    Get-VMNetworkAdapter -VM $vm | Remove-VMNetworkAdapter
    $gsi = Get-VMIntegrationService -VM $vm -Name 'Guest Service Interface' -ErrorAction Stop
    Disable-VMIntegrationService -VMIntegrationService $gsi
    Set-VMComPort -VM $vm -Number 1 -Path ('\\.\pipe\' + $vmName + '-com1')
    $boot = Add-VMDvdDrive -VM $vm -Path $RecoveryIso -Passthru
    Add-VMDvdDrive -VM $vm -Path $seed | Out-Null
    # ONLY the reviewed live ISO is bootable. Never fall through to installed disk.
    Set-VMFirmware -VM $vm -EnableSecureBoot On -SecureBootTemplate MicrosoftUEFICertificateAuthority -BootOrder $boot
    $effective = Get-VM -Id $vm.Id -ErrorAction Stop
    $com = Get-VMComPort -VM $vm -Number 1 -ErrorAction Stop
    $memory = Get-VMMemory -VM $vm -ErrorAction Stop
    $firmware = Get-VMFirmware -VM $vm -ErrorAction Stop
    $disks = @(Get-VMHardDiskDrive -VM $vm -ErrorAction Stop)
    $dvds = @(Get-VMDvdDrive -VM $vm -ErrorAction Stop)
    if ($effective.CheckpointType -ne 'Disabled' -or $effective.AutomaticStartAction -ne 'Nothing' -or
        $effective.AutomaticStopAction -ne 'ShutDown' -or
        $com.Path -ne ('\\.\pipe\' + $vmName + '-com1') -or
        $memory.Startup -ne 2147483648 -or $memory.DynamicMemoryEnabled -ne $false -or
        (Get-VMProcessor -VM $vm).Count -ne 2 -or
        @(Get-VMNetworkAdapter -VM $vm).Count -ne 0 -or
        (Get-VMIntegrationService -VM $vm -Name 'Guest Service Interface').Enabled -ne $false -or
        $disks.Count -ne 1 -or $disks[0].Path -ne $copy -or $dvds.Count -ne 2 -or
        @($dvds | Where-Object { $_.Path -eq $RecoveryIso }).Count -ne 1 -or
        @($dvds | Where-Object { $_.Path -eq $seed }).Count -ne 1 -or
        $firmware.SecureBoot -ne 'On' -or
        $firmware.SecureBootTemplate -ne 'MicrosoftUEFICertificateAuthority' -or
        $firmware.BootOrder.Count -ne 1 -or $firmware.BootOrder[0].Device.Path -ne $RecoveryIso -or
        @(Get-VMSnapshot -VM $vm).Count -ne 0) {
        throw 'Maintenance confinement or media read-back differs'
    }
    Assert-Owned (Get-VM -Id $vm.Id)
    # Connect/read/write all have deadlines. This is not the blocking runtime reader.
    $clock = [System.Diagnostics.Stopwatch]::StartNew()
    $phase = 'BOOT'
    Start-VM -VM $vm -ErrorAction Stop
    $phase = 'CHANNEL'
    $channelStage = 'pipe_create'
    $pipe = New-Object System.IO.Pipes.NamedPipeClientStream('.', ($vmName + '-com1'),
        [System.IO.Pipes.PipeDirection]::InOut, [System.IO.Pipes.PipeOptions]::Asynchronous)
    $channelStage = 'pipe_connect'
    $pipe.Connect(90000)
    $channelStage = 'security_compile'
    # Inspect the connected kernel object BEFORE sending the handshake. No repair.
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class MaintenancePipeSecurity {
    [DllImport("advapi32.dll", SetLastError=true)]
    static extern uint GetSecurityInfo(IntPtr handle, int type, uint info,
        out IntPtr owner, out IntPtr group, out IntPtr dacl, out IntPtr sacl, out IntPtr sd);
    [DllImport("advapi32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    static extern bool ConvertSecurityDescriptorToStringSecurityDescriptor(
        IntPtr sd, uint revision, uint info, out IntPtr text, out uint length);
    [DllImport("kernel32.dll")] static extern IntPtr LocalFree(IntPtr value);
    public static string Read(IntPtr handle) {
        IntPtr owner, group, dacl, sacl, sd;
        uint code = GetSecurityInfo(handle, 6, 5, out owner, out group, out dacl, out sacl, out sd);
        if (code != 0) throw new System.ComponentModel.Win32Exception(unchecked((int)code));
        IntPtr text = IntPtr.Zero;
        try {
            uint length;
            if (!ConvertSecurityDescriptorToStringSecurityDescriptor(sd, 1, 5, out text, out length))
                throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
            return Marshal.PtrToStringUni(text);
        } finally { if (text != IntPtr.Zero) LocalFree(text); LocalFree(sd); }
    }
}
'@
    $channelStage = 'security_query'
    $sddl = [MaintenancePipeSecurity]::Read($pipe.SafePipeHandle.DangerousGetHandle())
    $channelStage = 'security_parse'
    $descriptor = New-Object Security.AccessControl.RawSecurityDescriptor($sddl)
    $channelStage = 'sid_resolve'
    $vmSid = (New-Object Security.Principal.NTAccount('NT VIRTUAL MACHINE', $vm.Id.ToString())).Translate(
        [Security.Principal.SecurityIdentifier]).Value
    $pipeAllowed = @('S-1-5-18', 'S-1-5-32-544',
        [Security.Principal.WindowsIdentity]::GetCurrent().User.Value, $vmSid)
    $channelStage = 'acl_check'
    if (-not $descriptor.Owner -or $pipeAllowed -notcontains $descriptor.Owner.Value) {
        $failureCode = 'owner_rejected'
        throw 'Untrusted COM1 owner'
    }
    if (-not $descriptor.DiscretionaryAcl -or $descriptor.DiscretionaryAcl.Count -eq 0) {
        $failureCode = 'dacl_absent'
        throw 'Absent COM1 DACL'
    }
    foreach ($ace in $descriptor.DiscretionaryAcl) {
        if ($ace -isnot [Security.AccessControl.CommonAce] -or $ace.IsCallback -or
            $ace.AceQualifier -ne [Security.AccessControl.AceQualifier]::AccessAllowed) {
            $failureCode = 'ace_unsupported'
            throw 'Unsupported COM1 ACE'
        }
        if ($pipeAllowed -notcontains $ace.SecurityIdentifier.Value) {
            $failureCode = 'principal_rejected'
            throw 'Unreviewed COM1 principal'
        }
    }
    $channelStage = 'handshake_prepare'
    $frame = @{ id = $Identity; mode = $Mode } | ConvertTo-Json -Compress
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($frame + "`n")
    $channelStage = 'handshake_write'
    $write = $pipe.WriteAsync($bytes, 0, $bytes.Length)
    $channelStage = 'handshake_wait'
    if (-not $write.Wait(5000)) {
        $failureCode = 'timeout'
        throw 'Controller handshake write timed out'
    }
    $phase = 'GUEST'
    $channelStage = 'not_applicable'
    $receipt = (Read-BoundedFrame $pipe $clock ($GuestTimeoutSeconds * 1000)) | ConvertFrom-Json
    if ($receipt.version -ne 1 -or $receipt.id -cne $Identity -or $receipt.mode -cne $Mode -or
        $receipt.status -cne 'success' -or $receipt.unmounted_read_only -ne $true -or
        ($Mode -eq 'finalize' -and $receipt.audit -cne 'pass')) {
        throw 'Guest refused maintenance or failed its audit/unmount'
    }
    $pipe.Dispose(); $pipe = $null
    $phase = 'STOP'
    $owned = Get-VM -Id $vm.Id -ErrorAction Stop
    Assert-Owned $owned
    # The guest has unmounted the copy. Stop the LIVE recovery OS, not the target;
    # no ISO-ejection prompt or guest-console poweroff command is needed.
    if ($owned.State -ne 'Off') { Stop-VM -VM $owned -TurnOff -Force -ErrorAction Stop }
    $owned = Get-VM -Id $vm.Id -ErrorAction Stop
    Assert-Owned $owned
    if ($owned.State -ne 'Off') { throw 'Maintenance VM did not stop' }
    if ((Get-VHD -Path $copy).Attached) { throw 'Working copy is still attached' }
    $phase = 'VERIFY'
    $copyDigest = (Get-FileHash -LiteralPath $copy -Algorithm SHA256).Hash.ToLowerInvariant()
    $sourceDigest = (Get-FileHash -LiteralPath $SourceDisk -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($sourceDigest -cne $SourceSha256) { throw 'Preserved source changed' }
    if ((Get-VHD -Path $SourceDisk -ErrorAction Stop).Attached) { throw 'Preserved source became attached' }
    foreach ($candidate in @(Get-VM -ErrorAction Stop)) {
        foreach ($drive in @(Get-VMHardDiskDrive -VM $candidate -ErrorAction Stop)) {
            if ($drive.Path -eq $SourceDisk -and $candidate.State -ne 'Off') {
                throw 'A preserved source VM is no longer OFF'
            }
        }
    }
    $phase = 'REMOVE'
    Remove-VM -VM $owned -Force -ErrorAction Stop
    if (Get-VM -Id $vm.Id -ErrorAction SilentlyContinue) { throw 'Maintenance VM removal not observed' }
    if ((Get-VHD -Path $copy -ErrorAction Stop).Attached) { throw 'Copy remains attached after removal' }
    foreach ($candidate in @(Get-VM -ErrorAction Stop)) {
        if (@(Get-VMHardDiskDrive -VM $candidate | Where-Object { $_.Path -eq $copy }).Count -ne 0) {
            throw 'A VM still references the working copy'
        }
    }
    @{ id = $Identity; mode = $Mode; source_sha256 = $sourceDigest; source_unchanged = $true;
       copy_sha256 = $copyDigest; vm_id = $vm.Id.ToString(); vm_removed = $true;
       preserved_source_references = $references; copy_unattached = $true;
       pipe_acl_checked = $true; vm_config_retained = (Test-Path -LiteralPath $configRoot);
       guest = $receipt } | ConvertTo-Json -Depth 12 -Compress
}
catch {
    # Preserve the original error before nested cleanup changes PowerShell's $_.
    # This observer does not add removal, retries or broader stop authority.
    $originalFailure = $_
    $stopObservation = 'unknown'
    $failedVmId = $null
    if ($vm) {
        $failedVmId = $vm.Id.ToString()
        try {
            $owned = Get-VM -Id $vm.Id -ErrorAction Stop
            Assert-Owned $owned
            if ($owned.State -ne 'Off') { Stop-VM -VM $owned -TurnOff -Force -ErrorAction Stop }
            $owned = Get-VM -Id $vm.Id -ErrorAction Stop
            Assert-Owned $owned
            if ($owned.State -eq 'Off') { $stopObservation = 'off_observed' }
        } catch { }
    }
    # Create-new, bounded and best-effort: a killed process or failed receipt write
    # still leaves UNKNOWN. Off observation never proves unmount or VM removal.
    try {
        $details = Get-MaintenanceFailureDetails $originalFailure $phase $channelStage `
            $failureCode $failedVmId $stopObservation
        Write-MaintenanceReceipt $FailureReceipt $details
    } catch { }
    throw ('NS-MAINTENANCE-FAIL ' + $phase)
}
finally {
    if ($pipe) { $pipe.Dispose() }
    if ($sourceLock) { $sourceLock.Dispose() }
    if ($isoLock) { $isoLock.Dispose() }
    if ($seedLock) { $seedLock.Dispose() }
}
