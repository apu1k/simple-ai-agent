[CmdletBinding()]
param([switch]$CheckOnly)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'agent_startup.ps1')
. (Join-Path $PSScriptRoot 'agent_restart.ps1')
$project = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $project

$mutex = $null
$held = $false
$backend = $null
$textual = $null
$tree = @()
try {
    foreach ($name in @('start_backend.ps1', 'start_textual.ps1')) {
        if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot $name))) {
            throw "Missing local launcher scripts\$name. Install the existing startup stack first."
        }
    }
    Initialize-AgentStartupEnvironment -Project $project
    $mutex = [Threading.Mutex]::new($false, (Get-AgentStartupMutexName -Project $project -Purpose 'restart'))
    try { $held = $mutex.WaitOne(0) }
    catch [Threading.AbandonedMutexException] { $held = $true }
    if (-not $held) { throw 'Another local restart is already in progress.' }

    $backend = Get-AgentRestartTarget -Project $project -Port 8765 -Kind backend
    $textual = Get-AgentRestartTarget -Project $project -Port 8000 -Kind textual
    $status = $null
    if ($backend) {
        $status = Get-AgentRestartStatus
        if ($status.Processing) { throw 'The agent is working. Finish the run before restarting.' }
        Write-Host "Backend verified (PID $($backend.Process.Id)); pending proposals: $($status.PendingCount)."
    }
    else { Write-Host 'Backend is not listening; it will be started.' }
    if ($textual) { Write-Host "Textual Serve verified (PID $($textual.Process.Id))." }
    else { Write-Host 'Textual Serve is not listening; it will be started.' }
    if ($CheckOnly) {
        Write-Host 'Check only: no processes were stopped or started, and the backend was not drained.' -ForegroundColor Green
        return
    }
    if (-not (Confirm-AgentRestart -Status $status)) {
        Write-Host 'Cancelled. Nothing was stopped or drained.'
        return
    }

    # Inspect and retain the UI tree before draining or stopping anything. These
    # are descendants of the exact verified listener, never a name-wide kill.
    if ($textual) {
        $tree = @(Get-AgentRestartTree -Target $textual)
        Assert-AgentRestartTargetCurrent -Target $textual -Port 8000
    }
    elseif ($null -ne (Get-AgentRestartPortOwner -Port 8000)) {
        throw 'A Textual listener appeared during confirmation; inspect and retry.'
    }
    if ($backend) { Enter-AgentRestartDrain -Status $status -Target $backend }
    elseif ($null -ne (Get-AgentRestartPortOwner -Port 8765)) {
        throw 'A backend listener appeared during confirmation; inspect and retry.'
    }

    if ($textual) {
        Assert-AgentRestartTargetCurrent -Target $textual -Port 8000
        Stop-AgentRestartProcesses -Processes $tree
    }
    if ($backend) {
        Assert-AgentRestartTargetCurrent -Target $backend -Port 8765
        # Do not kill backend descendants: separate commands/services are not
        # owned cleanup targets, even when the runtime reports itself idle.
        Stop-AgentRestartProcesses -Processes @($backend.Process)
    }
    Wait-AgentRestartBackendReleased -Project $project
    Start-AgentRestartLauncher -Project $project -Name backend -Script (Join-Path $PSScriptRoot 'start_backend.ps1')
    Wait-AgentBackendReady -TimeoutSeconds 120
    $replacement = Get-AgentRestartStatus
    if ($status -and $replacement.ServerId -ceq $status.ServerId) {
        throw 'Backend epoch did not change. Refusing to report a successful code reload.'
    }
    if ($null -ne (Get-AgentRestartPortOwner -Port 8000)) {
        throw 'Port 8000 became occupied; a duplicate Textual server will not be started.'
    }
    Start-AgentRestartLauncher -Project $project -Name textual -Script (Join-Path $PSScriptRoot 'start_textual.ps1')
    Wait-AgentRestartTextualReady
    $newTextual = Get-AgentRestartTarget -Project $project -Port 8000 -Kind textual
    if (-not $newTextual) { throw 'Textual listener disappeared during readiness verification.' }
    $newTextual.Process.Dispose()
    Write-Host 'Backend and Textual restarted with the current code. Caddy and Authelia were left untouched.' -ForegroundColor Green
    Write-Host 'Reopen/refresh your usual browser URL, then use \chats to load saved chat history.'
}
catch {
    Write-Host "Restart stopped: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host 'If it stopped midway, the backend may be drained or offline. Inspect logs before retrying; no automatic retry is performed.' -ForegroundColor Yellow
    exit 1
}
finally {
    foreach ($process in $tree) { if (-not $textual -or $process -ne $textual.Process) { $process.Dispose() } }
    if ($textual) { $textual.Process.Dispose() }
    if ($backend) { $backend.Process.Dispose() }
    if ($held) { $mutex.ReleaseMutex() }
    if ($mutex) { $mutex.Dispose() }
}
