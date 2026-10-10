param(
    [Parameter(Mandatory = $true)][string]$SourceDisk,
    [Parameter(Mandatory = $true)][string]$RecoveryIso
)
$ErrorActionPreference = 'Stop'
# Query/hash only. NEVER start/stop/create/remove/mount a VM/disk or change ACLs.
function Read-References {
    $references = @()
    foreach ($vm in @(Get-VM -ErrorAction Stop)) {
        foreach ($disk in @(Get-VMHardDiskDrive -VM $vm -ErrorAction Stop)) {
            if ($disk.Path -eq $SourceDisk) {
                $references += @{ name = $vm.Name; id = $vm.Id.ToString(); state = $vm.State.ToString() }
                if ($references.Count -gt 64) { throw 'Too many source references' }
            }
        }
    }
    return $references
}
$references = @(Read-References)
$vhd = Get-VHD -Path $SourceDisk -ErrorAction Stop
$blockers = @()
if (@($references | Where-Object { $_.state -ne 'Off' }).Count) { $blockers += 'source_vm_not_off' }
if ($vhd.VhdFormat -ne 'VHDX' -or $vhd.VhdType -ne 'Dynamic' -or
    $vhd.Size -ne 21474836480 -or $vhd.ParentPath -or $vhd.Attached) {
    $blockers += 'source_vhd_unsuitable'
}
$sourceDigest = $null
$isoDigest = $null
if ($blockers.Count -eq 0) {
    # Temporary read-sharing handles deny content writes/deletion during hashes;
    # this does not reserve anything after the collector returns.
    $source = [IO.File]::Open($SourceDisk, 'Open', 'Read', 'Read')
    $iso = $null
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try {
        $signature = New-Object byte[] 8
        if ($source.Read($signature, 0, 8) -ne 8 -or
            [Text.Encoding]::ASCII.GetString($signature) -cne 'vhdxfile') {
            $blockers += 'source_signature_invalid'
        } else {
            $source.Position = 0
            $sourceDigest = ([BitConverter]::ToString($algorithm.ComputeHash($source))).Replace('-', '').ToLowerInvariant()
            $iso = [IO.File]::Open($RecoveryIso, 'Open', 'Read', 'Read')
            $isoDigest = ([BitConverter]::ToString($algorithm.ComputeHash($iso))).Replace('-', '').ToLowerInvariant()
            # Re-observe references while source writers are still excluded.
            $references = @(Read-References)
            if (@($references | Where-Object { $_.state -ne 'Off' }).Count) {
                $blockers += 'source_vm_not_off'
                $sourceDigest = $null
            }
        }
    }
    finally {
        $algorithm.Dispose()
        if ($iso) { $iso.Dispose() }
        $source.Dispose()
    }
}
@{ version = 1; source_references = @($references); blockers = @($blockers);
   source_sha256 = $sourceDigest; recovery_iso_sha256 = $isoDigest;
   vhd = @{ format = $vhd.VhdFormat.ToString(); type = $vhd.VhdType.ToString();
            virtual_bytes = $vhd.Size; attached = [bool]$vhd.Attached;
            parent_present = [bool]$vhd.ParentPath } } | ConvertTo-Json -Depth 6 -Compress
