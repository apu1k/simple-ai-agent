# Local restart helpers. Dot-source only; importing this file never stops a process.

function Invoke-AgentRestartHttp {
    param(
        [Parameter(Mandatory)][string]$Path,
        [ValidateSet('GET', 'POST')][string]$Method = 'GET',
        [object]$Body = $null,
        [int]$MaxChars = 65536
    )
    if ($Path -notin @('/v1/maintenance', '/v1/maintenance/drain', '/v1/snapshot')) {
        throw 'Unexpected maintenance request path.'
    }
    $request = [Net.HttpWebRequest]::Create("http://127.0.0.1:8765$Path")
    $request.Method = $Method
    $request.Proxy = $null
    $request.AllowAutoRedirect = $false
    $request.Timeout = 5000
    $request.ReadWriteTimeout = 5000
    $request.Headers['Authorization'] = "Bearer $env:AI_AGENT_TOKEN"
    if ($null -ne $Body) {
        $bytes = [Text.Encoding]::UTF8.GetBytes(($Body | ConvertTo-Json -Compress))
        $request.ContentType = 'application/json'
        $request.ContentLength = $bytes.Length
        $stream = $request.GetRequestStream()
        try { $stream.Write($bytes, 0, $bytes.Length) }
        finally { $stream.Dispose() }
    }
    $response = $null
    $reader = $null
    try {
        try { $response = $request.GetResponse() }
        catch [Net.WebException] {
            if (-not $_.Exception.Response) {
                throw 'Cannot contact the backend. No restart will be attempted; check its logs.'
            }
            $status = [int]$_.Exception.Response.StatusCode
            $_.Exception.Response.Dispose()
            if ($status -eq 404 -and $Path -eq '/v1/maintenance' -and $Method -eq 'GET') {
                return [pscustomobject]@{ Status = 404; Data = $null }
            }
            throw "Maintenance request failed (HTTP $status). The backend may be busy or changed. No process has been stopped by this request."
        }
        if ([int]$response.StatusCode -ne 200) { throw 'Unexpected maintenance response; redirects are not followed.' }
        $reader = [IO.StreamReader]::new($response.GetResponseStream())
        $buffer = New-Object char[] ($MaxChars + 1)
        $count = $reader.ReadBlock($buffer, 0, $buffer.Length)
        if ($count -eq 0 -or $count -gt $MaxChars) { throw 'Invalid maintenance response size.' }
        $data = (-join $buffer[0..($count - 1)]) | ConvertFrom-Json
        return [pscustomobject]@{ Status = 200; Data = $data }
    }
    finally {
        if ($reader) { $reader.Dispose() }
        if ($response) { $response.Dispose() }
    }
}

function Get-AgentRestartStatus {
    $response = Invoke-AgentRestartHttp -Path '/v1/maintenance'
    $legacy = $response.Status -eq 404
    if ($legacy) {
        $frame = (Invoke-AgentRestartHttp -Path '/v1/snapshot' -MaxChars 16777216).Data
        if ($frame.snapshot.run -and $frame.snapshot.run.status -notin @('running', 'completed', 'failed', 'interrupted')) {
            throw 'Unrecognized execution status; refusing restart.'
        }
        $data = [pscustomobject]@{
            version = $frame.version; server_id = $frame.server_id; process_id = $null
            sequence = $frame.snapshot.sequence; closed = $frame.snapshot.closed
            processing = [bool]($frame.snapshot.run -and $frame.snapshot.run.status -eq 'running')
            pending_count = @($frame.pending).Count
        }
    }
    else { $data = $response.Data }
    if ($data.version -ne 1 -or $data.server_id -cnotmatch '\A[a-f0-9]{32}\z' -or
        $data.processing -isnot [bool] -or $data.closed -isnot [bool] -or
        $data.sequence -isnot [ValueType] -or $data.sequence -lt 0 -or
        $data.pending_count -isnot [ValueType] -or $data.pending_count -lt 0 -or
        (-not $legacy -and ($data.process_id -isnot [ValueType] -or $data.process_id -le 0))) {
        throw 'Unrecognized backend maintenance state; refusing restart.'
    }
    return [pscustomobject]@{
        Legacy = $legacy; ServerId = $data.server_id; ProcessId = $data.process_id
        Sequence = $data.sequence; Processing = $data.processing
        PendingCount = $data.pending_count; Closed = $data.closed
        Durable = (-not $legacy -and $data.durable_state -is [bool] -and $data.durable_state)
    }
}

function Get-AgentRestartPortOwner {
    param([int]$Port)
    $owners = @(Get-NetTCPConnection -State Listen -ErrorAction Stop |
        Where-Object { $_.LocalAddress -eq '127.0.0.1' -and $_.LocalPort -eq $Port } |
        Select-Object -ExpandProperty OwningProcess -Unique)
    if ($owners.Count -gt 1) { throw "Multiple listeners on port $Port; refusing restart." }
    if ($owners.Count) { return [int]$owners[0] }
    return $null
}

function Open-AgentRestartProcess {
    param([Parameter(Mandatory)][object]$Record)
    $owner = Invoke-CimMethod -InputObject $Record -MethodName GetOwnerSid -ErrorAction Stop
    if ($owner.ReturnValue -ne 0 -or $owner.Sid -ne [Security.Principal.WindowsIdentity]::GetCurrent().User.Value) {
        throw 'A selected process is not owned by the current Windows user; refusing restart.'
    }
    $process = [Diagnostics.Process]::GetProcessById([int]$Record.ProcessId)
    try {
        # Retain the process handle, not just a PID which could later be reused.
        $null = $process.Handle
        if ($process.HasExited -or -not $Record.CreationDate -or
            [Math]::Abs(($process.StartTime.ToUniversalTime() - $Record.CreationDate.ToUniversalTime()).TotalMilliseconds) -gt 1 -or
            $process.MainModule.FileName -ine $Record.ExecutablePath) {
            throw 'Process identity changed during inspection; retry after reviewing the stack.'
        }
        return $process
    }
    catch { $process.Dispose(); throw }
}

function Get-AgentRestartTarget {
    param([string]$Project, [int]$Port, [ValidateSet('backend', 'textual')][string]$Kind)
    $processId = Get-AgentRestartPortOwner -Port $Port
    if ($null -eq $processId) { return $null }
    $record = Get-CimInstance Win32_Process -Filter "ProcessId = $processId" -ErrorAction Stop
    if (-not $record) { throw 'Listener exited during inspection; retry restart.' }
    $pythonPath = Join-Path $Project '.venv\Scripts\python.exe'
    $textualPath = Join-Path $Project '.venv\Scripts\textual.exe'
    $python = '(?:"' + [Regex]::Escape($pythonPath) + '"|' + [Regex]::Escape($pythonPath) + ')'
    $textual = '(?:"' + [Regex]::Escape($textualPath) + '"|' + [Regex]::Escape($textualPath) + ')'
    if ($Kind -eq 'backend') { $pattern = '^\s*' + $python + '\s+-m\s+runtime\.server\s*$' }
    else { $pattern = '^\s*(?:' + $python + '\s+' + $textual + '|' + $textual + ')\s+serve\b.*\s+main_textual\.py\s*$' }
    if ($record.CommandLine -notmatch $pattern) {
        throw "Port $Port is not the expected project's $Kind process. It will not be stopped."
    }
    # Windows venv launchers redirect to the base Python executable. Accept that
    # only with a matching, older project-local shim parent, not any python.exe.
    if ($record.ExecutablePath -ine $pythonPath -and $record.ExecutablePath -ine $textualPath) {
        $parent = Get-CimInstance Win32_Process -Filter "ProcessId = $($record.ParentProcessId)" -ErrorAction Stop
        if (-not $parent -or $parent.ExecutablePath -ine $pythonPath -or
            $parent.CommandLine -cne $record.CommandLine -or $parent.CreationDate -gt $record.CreationDate) {
            throw 'Cannot verify the project-local Python launcher parent; refusing restart.'
        }
    }
    return [pscustomobject]@{ Process = (Open-AgentRestartProcess -Record $record); Record = $record }
}

function Get-AgentRestartTree {
    param([Parameter(Mandatory)][object]$Target)
    $handles = [Collections.Generic.List[object]]::new()
    $handles.Add($Target.Process)
    try {
        $all = @(Get-CimInstance Win32_Process -ErrorAction Stop)
        $parents = @($Target.Record)
        while ($parents.Count) {
            $children = @()
            foreach ($parent in $parents) {
                foreach ($child in @($all | Where-Object ParentProcessId -eq $parent.ProcessId)) {
                    if ($child.CreationDate -lt $parent.CreationDate -or $handles.Count -ge 256) {
                        throw 'Ambiguous or oversized Textual process tree; refusing restart.'
                    }
                    $handles.Add((Open-AgentRestartProcess -Record $child))
                    $children += $child
                }
            }
            $parents = $children
        }
        return $handles.ToArray()
    }
    catch {
        foreach ($handle in $handles) { if ($handle -ne $Target.Process) { $handle.Dispose() } }
        throw
    }
}

function Assert-AgentRestartTargetCurrent {
    param([object]$Target, [int]$Port)
    $owner = Get-AgentRestartPortOwner -Port $Port
    if ($Target.Process.HasExited -or $null -eq $owner -or $owner -ne $Target.Process.Id) {
        throw 'The selected listener changed. Nothing further will be stopped; inspect and retry.'
    }
}

function Stop-AgentRestartProcesses {
    param([object[]]$Processes)
    foreach ($process in $Processes) {
        if (-not $process.HasExited) {
            try { $process.Kill() }
            catch { if (-not $process.HasExited) { throw } }
        }
    }
    foreach ($process in $Processes) {
        if (-not $process.WaitForExit(10000)) { throw 'A selected process did not exit; inspect before retrying.' }
    }
}

function Confirm-AgentRestart {
    param([object]$Status)
    if ($Status -and $Status.Durable) {
        Write-Host 'Restarting preserves saved context and ordinary pending proposals. Privileged authorization is never restored.' -ForegroundColor Yellow
        Write-Host 'Interrupted work is not automatically retried. External command effects must be inspected separately.' -ForegroundColor Yellow
    }
    else {
        Write-Host 'Restarting discards live model context and pending proposals. Saved final chat history remains.' -ForegroundColor Yellow
        Write-Host 'This running backend has not enabled durable recovery yet. The first upgrade cannot recover its volatile state.' -ForegroundColor Yellow
    }
    if ($Status) {
        if ($Status.Processing) { throw 'The agent is working. Finish the run before restarting.' }
        Write-Host "Pending proposals: $($Status.PendingCount)"
    }
    $answer = 'RESTART'
    if ($Status -and $Status.Legacy -and -not $Status.Closed) {
        Write-Host 'FIRST RESTART: the running backend predates atomic maintenance drain.' -ForegroundColor Yellow
        Write-Host 'Close ALL browser/Textual/direct API clients first. The legacy idle check cannot prevent a concurrent submission.' -ForegroundColor Yellow
        $answer = 'LEGACY RESTART'
    }
    return (Read-Host "Type $answer to proceed (anything else cancels)") -ceq $answer
}

function Enter-AgentRestartDrain {
    param([Parameter(Mandatory)][object]$Status, [Parameter(Mandatory)][object]$Target)
    Assert-AgentRestartTargetCurrent -Target $Target -Port 8765
    if ($Status.Processing) { throw 'The agent is working; restart refused.' }
    if ($Status.Legacy) {
        $latest = Get-AgentRestartStatus
        if ($latest.ServerId -cne $Status.ServerId -or $latest.Sequence -ne $Status.Sequence -or
            $latest.Processing -or $latest.Closed -ne $Status.Closed) {
            throw 'The legacy backend changed after confirmation. Nothing has been stopped; review and retry.'
        }
    }
    else {
        if ($Status.ProcessId -ne $Target.Process.Id) { throw 'Authenticated backend PID differs from the inspected listener.' }
        $reply = (Invoke-AgentRestartHttp -Path '/v1/maintenance/drain' -Method POST -Body @{
            server_id = $Status.ServerId; sequence = $Status.Sequence
        }).Data
        if ($reply.server_id -cne $Status.ServerId -or $reply.closed -ne $true) {
            throw 'Drain acknowledgement is uncertain. No process has been stopped; inspect the backend before retrying.'
        }
    }
}

function Wait-AgentRestartBackendReleased {
    param([string]$Project)
    $lease = [Threading.Mutex]::new($false, (Get-AgentStartupMutexName -Project $Project -Purpose 'backend'))
    try {
        $clock = [Diagnostics.Stopwatch]::StartNew()
        while ($clock.Elapsed.TotalSeconds -lt 15) {
            $held = $false
            try { $held = $lease.WaitOne(0) }
            catch [Threading.AbandonedMutexException] { $held = $true }
            if ($held) {
                $lease.ReleaseMutex()
                if ($null -eq (Get-AgentRestartPortOwner -Port 8765)) { return }
            }
            Start-Sleep -Milliseconds 200
        }
        throw 'Backend launcher/port did not release within 15 seconds. No replacement will be started.'
    }
    finally { $lease.Dispose() }
}

function Start-AgentRestartLauncher {
    param([string]$Project, [string]$Name, [string]$Script)
    $logs = Join-Path $Project 'logs'
    New-Item -ItemType Directory -Force -Path $logs | Out-Null
    $prefix = Join-Path $logs ("$Name-restart-" + (Get-Date -Format 'yyyyMMdd-HHmmss-fff') + "-$PID")
    Start-Process powershell.exe -WindowStyle Hidden -WorkingDirectory $Project -ArgumentList @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"' + $Script + '"')
    ) -RedirectStandardOutput "$prefix.out.log" -RedirectStandardError "$prefix.err.log" | Out-Null
}

function Wait-AgentRestartTextualReady {
    $clock = [Diagnostics.Stopwatch]::StartNew()
    while ($clock.Elapsed.TotalSeconds -lt 30) {
        if ($null -ne (Get-AgentRestartPortOwner -Port 8000)) { return }
        Start-Sleep -Milliseconds 300
    }
    throw 'Textual did not begin listening within 30 seconds. Check logs\textual-restart-*.err.log.'
}
