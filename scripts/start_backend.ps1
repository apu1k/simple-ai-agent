$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'agent_startup.ps1')
$project = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $project
Initialize-AgentStartupEnvironment -Project $project

# Hold this lease for the wrapper's full lifetime, including Python startup.
# Re-running the stack does not replace a running backend or its pending work.
$mutex = [Threading.Mutex]::new($false, (Get-AgentStartupMutexName -Project $project -Purpose 'backend'))
$held = $false
try {
    try { $held = $mutex.WaitOne(0) }
    catch [Threading.AbandonedMutexException] { $held = $true }
    if (-not $held) {
        Write-Host 'The agent backend is already starting or running in this logon session.'
        return
    }
    if (Test-AgentBackendReady) {
        Write-Host 'An authenticated agent backend is already running. Leaving it untouched.'
        return
    }
    $listener = Get-NetTCPConnection -LocalAddress '127.0.0.1' -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue
    if ($listener) {
        throw 'Port 8765 is occupied but the backend is not ready. Inspect the existing process; it will not be stopped or replaced.'
    }

    Write-Host 'Starting the ordinary-user agent backend on 127.0.0.1:8765...'
    & (Join-Path $project '.venv\Scripts\python.exe') -m runtime.server
    if ($LASTEXITCODE -ne 0) { throw "Agent backend exited with code $LASTEXITCODE. See its error log." }
}
finally {
    if ($held) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
