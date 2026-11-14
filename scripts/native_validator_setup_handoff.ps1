# REVIEW TEMPLATE ONLY. Never invoke this checkout file or compile code elevated.
# Independently pin these ENTIRE bytes, freeze DATA, then use the existing
# protected command snapshot + per-request pending/UAC channel. Reviewed helper,
# PowerShell/OS/CLR load trust and actual inherited outer-job containment are
# prerequisites, NOT properties authenticated by this script or its hashes.
$ErrorActionPreference = 'Stop'
$review = [Text.Encoding]::ASCII.GetString([Convert]::FromBase64String('__REVIEW_DATA__')) | ConvertFrom-Json
$held = New-Object 'Collections.Generic.List[IO.FileStream]'
$lastQpc = [Diagnostics.Stopwatch]::GetTimestamp()
$lastWall = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
$frequency = [Diagnostics.Stopwatch]::Frequency
$cap = [long]0
$entered = $false; $observed = $false; $child = $null
function Budget {
    $n = [Diagnostics.Stopwatch]::GetTimestamp(); $w = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
    if ($n -lt $script:lastQpc -or $w -lt $script:lastWall -or $n -ge $script:cap -or
        $w -ge [decimal]$review.expires_unix * 1000 -or $w -ge [decimal]$review.deadline_unix * 1000) { throw 'Setup handoff window unavailable' }
    $script:lastQpc = $n; $script:lastWall = $w
}
function ProtectedPath([string]$Path) {
    if ($Path -cnotmatch '^[A-Z]:\\' -or [IO.Path]::GetFullPath($Path) -cne $Path -or $Path.Length -gt 240) { throw 'Fixed canonical protected path required' }
    $trusted = @('S-1-5-18','S-1-5-32-544','S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464')
    $cursor = $Path; $first = $true
    while ($cursor) {
        $item = Get-Item -LiteralPath $cursor -Force
        if ([int]$item.Attributes -band 0x5e00) { throw 'Unsupported protected path shape' }
        $acl = Get-Acl -LiteralPath $cursor
        if ($trusted -notcontains $acl.GetOwner([Security.Principal.SecurityIdentifier]).Value -or
            @($acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])).Count -lt 1) { throw 'Untrusted protected owner or empty DACL' }
        $mask = 0x40 -bor 0x40000 -bor 0x80000 -bor 0x10000000
        if ($cursor -ine [IO.Path]::GetPathRoot($cursor)) { $mask = $mask -bor 0x10000 }
        if ($first) { $mask = $mask -bor 0x2 -bor 0x4 -bor 0x10 -bor 0x100 -bor 0x40000000 }
        foreach ($rule in $acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])) {
            if ($rule.PropagationFlags -band [Security.AccessControl.PropagationFlags]::InheritOnly) { continue }
            if ($rule.AccessControlType -eq [Security.AccessControl.AccessControlType]::Allow -and
                $trusted -notcontains $rule.IdentityReference.Value -and ([int]$rule.FileSystemRights -band $mask)) { throw 'Untrusted protected mutation right' }
        }
        $first = $false; $parent = [IO.Directory]::GetParent($cursor)
        $cursor = if ($parent) { $parent.FullName } else { $null }
    }
}
function PrivateFile([IO.FileStream]$File) {
    # Security of the actual held object, not a second file-path lookup.
    $sddl = $File.GetAccessControl().GetSecurityDescriptorSddlForm([Security.AccessControl.AccessControlSections]'Owner,Group,Access')
    $sd = New-Object Security.AccessControl.RawSecurityDescriptor($sddl)
    if ($sd.Owner.Value -cnotin @('S-1-5-18','S-1-5-32-544') -or $sd.Group.Value -cne 'S-1-5-32-544' -or
        -not ($sd.ControlFlags -band [Security.AccessControl.ControlFlags]::DiscretionaryAclProtected) -or
        $null -eq $sd.DiscretionaryAcl -or $sd.DiscretionaryAcl.Count -ne 2) { throw 'Private held file required' }
    $seen = @{}
    foreach ($ace in $sd.DiscretionaryAcl) {
        if ($ace -isnot [Security.AccessControl.CommonAce] -or $ace.IsCallback -or
            $ace.AceType -ne [Security.AccessControl.AceType]::AccessAllowed -or [int]$ace.AceFlags -ne 0 -or
            $ace.AccessMask -ne 0x1f01ff -or $ace.SecurityIdentifier.Value -cnotin @('S-1-5-18','S-1-5-32-544') -or
            $seen.ContainsKey($ace.SecurityIdentifier.Value)) { throw 'Private held descriptor differs' }
        $seen[$ace.SecurityIdentifier.Value] = $true
    }
}
function OpenHeld([string]$Path,[long]$Maximum,[bool]$Private) {
    ProtectedPath $Path
    $f = [IO.File]::Open($Path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read); $held.Add($f)
    if ($f.Length -lt 1 -or $f.Length -gt $Maximum) { throw 'Held extent differs' }
    if ($Private) { PrivateFile $f }; return $f
}
function Bytes([IO.FileStream]$File,[int]$Maximum) {
    Budget
    if ($File.Length -lt 1 -or $File.Length -gt $Maximum) { throw 'Bounded result required' }
    $File.Position = 0; $raw = New-Object byte[] ([int]$File.Length); $offset = 0
    while ($offset -lt $raw.Length) {
        Budget; $n = $File.Read($raw,$offset,[Math]::Min(65536,$raw.Length-$offset))
        if ($n -lt 1) { throw 'Held result truncated' }; $offset += $n
    }
    if ($File.ReadByte() -ne -1) { throw 'Held result extent differs' }; Budget; return ,$raw
}
function Digest([IO.FileStream]$File) {
    Budget; $File.Position = 0; $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $buffer = New-Object byte[] 65536; $total = [long]0
        while (($n = $File.Read($buffer,0,$buffer.Length)) -gt 0) { Budget; [void]$sha.TransformBlock($buffer,0,$n,$buffer,0); $total += $n }
        [void]$sha.TransformFinalBlock((New-Object byte[] 0),0,0)
        if ($total -ne $File.Length) { throw 'Held hash extent differs' }
        Budget; return ([BitConverter]::ToString($sha.Hash)).Replace('-','').ToLowerInvariant()
    } finally { $sha.Dispose() }
}
function Names([string]$Directory,[string[]]$Expected) {
    ProtectedPath $Directory; Budget
    $actual = @([IO.Directory]::GetFileSystemEntries($Directory) | ForEach-Object { [IO.Path]::GetFileName($_) })
    if ($actual.Count -ne $Expected.Count) { throw 'Fixed setup inventory differs' }
    if ($Expected.Count -gt 0 -and @(Compare-Object -CaseSensitive $actual $Expected).Count -ne 0) { throw 'Fixed setup inventory differs' }; Budget
}
try {
    if ([IntPtr]::Size -ne 8 -or $PSVersionTable.PSEdition -cne 'Desktop') { throw 'Native Windows PowerShell required' }
    $impersonation = [Security.Principal.WindowsIdentity]::GetCurrent($true)
    if ($null -ne $impersonation) { $impersonation.Dispose(); throw 'Impersonation refused' }
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    try {
        if ($identity.User.Value -cne $review.operator_sid -or
            -not (New-Object Security.Principal.WindowsPrincipal($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Approved elevated operator required' }
    } finally { $identity.Dispose() }
    $outer = [IO.Path]::Combine([Environment]::GetFolderPath('ProgramFiles'),'AiAgentElevatedCommands','receipts',($review.request_id+'.start.json'))
    $startFile = OpenHeld $outer 4096 $false
    # Bounded protected transport data, never executable text or a renewed cap.
    $reader = New-Object IO.StreamReader($startFile,(New-Object Text.UTF8Encoding($false,$true)),$false,4096,$true)
    try { $start = $reader.ReadToEnd() | ConvertFrom-Json } finally { $reader.Dispose() }
    if ($start.version -ne 1 -or $start.preparation_protocol -ne 1 -or $start.setup_preload_protocol -ne 1 -or
        $start.setup_preload_sha256 -cne $review.preload_sha256 -or
        $start.operation -cne 'elevated_commands' -or $start.status -cne 'started' -or
        $start.request_id -cne $review.request_id -or $start.operator_sid -cne $review.operator_sid -or
        $start.helper_sha256 -cne $review.outer_helper_sha256 -or $start.timeout -ne $review.seconds -or
        $start.deadline_unix -ne $review.deadline_unix -or $start.execution_qpc_frequency -ne $frequency -or
        ($start.execution_qpc_limit -isnot [long] -and $start.execution_qpc_limit -isnot [int]) -or
        $frequency -lt 1 -or $frequency -gt 1000000000) { throw 'Original protected execution window missing or mismatched' }
    $cap = [long]$start.execution_qpc_limit
    if ($cap -le $lastQpc -or ([decimal]$cap-$lastQpc)/$frequency -gt $review.seconds) { throw 'Original window invalid' }; Budget
    $root = [string]$review.root
    $rootNames = @('validator-setup-host.exe','validator-setup-host.exe.config','validator-setup-watchdog.exe',
        'validator-setup-watchdog.exe.config','policy.json','claims','receipts','scratch')
    if ($review.publish) { $rootNames += 'setup.packet' }
    Names $root $rootNames; Names ($root+'\claims') @(); Names ($root+'\receipts') @(); Names ($root+'\scratch') @()
    $policy = OpenHeld ($root+'\policy.json') 1024 $true; $policyPin = $review.files.'policy.json'
    if ($policy.Length -ne $policyPin.bytes -or (Digest $policy) -cne $policyPin.sha256) { throw 'Authentic private setup policy differs' }
    # Permanent fixed collision barrier BEFORE target loading; no reset/repair.
    $security = New-Object Security.AccessControl.FileSecurity
    $security.SetSecurityDescriptorSddlForm('O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)')
    $claimPath = $root+'\claims\outer-attempt.claim'; $claim = [Convert]::FromBase64String($review.outer_claim)
    $writer = New-Object IO.FileStream($claimPath,[IO.FileMode]::CreateNew,[Security.AccessControl.FileSystemRights]::Write,
        [IO.FileShare]::None,4096,[IO.FileOptions]::None,$security)
    try { $writer.Write($claim,0,$claim.Length); $writer.Flush($true) } finally { $writer.Dispose() }
    $claimFile = OpenHeld $claimPath 1024 $true
    if ([Convert]::ToBase64String((Bytes $claimFile 1024)) -cne $review.outer_claim) { throw 'Outer claim readback differs' }
    $pins = New-Object 'Collections.Generic.List[object]'
    foreach ($property in $review.files.PSObject.Properties) {
        if ($property.Name -ceq 'policy.json') { $f = $policy } else { $f = OpenHeld ($root+'\'+$property.Name) $property.Value.bytes $true }
        if ($f.Length -ne $property.Value.bytes -or (Digest $f) -cne $property.Value.sha256) { throw 'Independently pinned launch input differs' }
        $pins.Add(@{file=$f;pin=$property.Value})
    }
    Names $root $rootNames; Names ($root+'\claims') @('outer-attempt.claim')
    foreach ($item in $pins) { if ((Digest $item.file) -cne $item.pin.sha256) { throw 'Held pre-load bytes changed' } }; Budget
    # Snapshot must ALREADY run within reviewed native outer job. No shell or
    # breakaway; fixed child inherits that job. Inner atomic host launch remains.
    $info = New-Object Diagnostics.ProcessStartInfo
    $info.FileName = $root+'\validator-setup-watchdog.exe'
    $info.Arguments = '--setup-supervise-qpc-v1 '+$cap.ToString([Globalization.CultureInfo]::InvariantCulture)+' '+$frequency.ToString([Globalization.CultureInfo]::InvariantCulture)
    $info.WorkingDirectory = $root; $info.UseShellExecute = $false; $info.CreateNoWindow = $true
    $windows = [Environment]::GetFolderPath('Windows'); $system = [Environment]::GetFolderPath('System')
    $info.EnvironmentVariables.Clear()
    $info.EnvironmentVariables['SystemRoot'] = $windows; $info.EnvironmentVariables['WINDIR'] = $windows
    $info.EnvironmentVariables['PATH'] = $system
    $info.EnvironmentVariables['TEMP'] = $root+'\scratch'; $info.EnvironmentVariables['TMP'] = $root+'\scratch'
    $entered = $true # uncertainty BEFORE creation; never retry
    $child = [Diagnostics.Process]::Start($info)
    if ($null -eq $child) { throw 'Watchdog creation unknown' }
    while ($true) {
        Budget; $remaining = [Math]::Floor(([decimal]$cap-[Diagnostics.Stopwatch]::GetTimestamp())*1000/$frequency)
        if ($remaining -lt 1) { throw 'Watchdog completion unknown' }
        if ($child.WaitForExit([int][Math]::Min(200,$remaining))) { $observed = $true; break }
    }
    Budget
    if ($child.ExitCode -ne 0) { throw 'Setup process did not return a complete observation' }
    foreach ($item in $pins) { if ((Digest $item.file) -cne $item.pin.sha256) { throw 'Held post-exit bytes changed' } }
    $resultFile = OpenHeld ($root+'\receipts\operation-result.bin') 97 $true
    $receiptFile = OpenHeld ($root+'\receipts\supervisor-receipt.json') 2048 $true
    $result = Bytes $resultFile 97; $receipt = Bytes $receiptFile 2048; Budget
    # Transport only. Client checks both frames and the protected outer receipt.
    $frame = 'NVSO0001|'+[Convert]::ToBase64String($result)+'|'+[Convert]::ToBase64String($receipt)
} catch {
    if ($entered -and -not $observed) {
        # Retain actual process/held owners for independent outer termination.
        while ($true) { [Threading.Thread]::Sleep(1000); [GC]::KeepAlive($child); [GC]::KeepAlive($held) }
    }
    throw 'Setup handoff refused or outcome unknown; preserve claims and receipts'
} finally {
    if ($null -ne $child) { $child.Dispose() }
    for ($i=$held.Count-1;$i -ge 0;$i--) { $held[$i].Dispose() }
}
[Console]::Out.WriteLine($frame)
