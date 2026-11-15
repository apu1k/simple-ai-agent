# Shared by the ordinary-user backend and Textual Serve launchers (Windows PS 5.1+).

function Get-AgentStartupMutexName {
    param([Parameter(Mandatory)][string]$Project, [Parameter(Mandatory)][string]$Purpose)
    $canonical = [IO.Path]::GetFullPath($Project).TrimEnd('\').ToLowerInvariant()
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $digest = [BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($canonical))).Replace('-', '')
        return "Local\SimpleAiAgent-$Purpose-$digest"
    }
    finally { $sha.Dispose() }
}

function Assert-AgentStartupToken {
    param([Parameter(Mandatory)][string]$Token)
    if ($Token -cnotmatch '\A[!-~]{32,4096}\z') {
        throw 'AI_AGENT_TOKEN must contain 32-4096 printable ASCII characters without whitespace.'
    }
}

function Get-AgentStartupToken {
    param([Parameter(Mandatory)][string]$Project)
    if ($env:AI_AGENT_TOKEN) {
        Assert-AgentStartupToken -Token $env:AI_AGENT_TOKEN
        return $env:AI_AGENT_TOKEN
    }

    # No plaintext token in scripts, command lines or logs. ConvertFrom-SecureString
    # without a key uses DPAPI, bound to this Windows user and machine.
    $directory = Join-Path $Project '.agent_runtime'
    $file = Join-Path $directory 'startup-token.dpapi'
    $mutex = [Threading.Mutex]::new($false, (Get-AgentStartupMutexName -Project $Project -Purpose 'credential'))
    $held = $false
    try {
        try { $held = $mutex.WaitOne(15000) }
        catch [Threading.AbandonedMutexException] { $held = $true }
        if (-not $held) { throw 'Timed out waiting for startup credential initialization.' }

        if (Test-Path -LiteralPath $file) {
            try {
                $secure = ConvertTo-SecureString -String ([IO.File]::ReadAllText($file).Trim())
                $pointer = [IntPtr]::Zero
                try {
                    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
                    $token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
                }
                finally {
                    if ($pointer -ne [IntPtr]::Zero) {
                        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
                    }
                    $secure.Dispose()
                }
            }
            catch {
                throw 'Cannot decrypt the startup token. Use the same Windows account; do not delete or rotate it while the backend is running.'
            }
        }
        else {
            New-Item -ItemType Directory -Force -Path $directory | Out-Null
            $bytes = New-Object byte[] 32
            $random = [Security.Cryptography.RandomNumberGenerator]::Create()
            try { $random.GetBytes($bytes) }
            finally { $random.Dispose() }
            $token = [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
            $secure = ConvertTo-SecureString -String $token -AsPlainText -Force
            try { $encrypted = ConvertFrom-SecureString -SecureString $secure }
            finally { $secure.Dispose() }
            # CreateNew also fails closed if a different logon session won a race.
            $stream = [IO.File]::Open($file, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
            try {
                $encoded = [Text.Encoding]::ASCII.GetBytes($encrypted)
                $stream.Write($encoded, 0, $encoded.Length)
                $stream.Flush($true)
            }
            finally { $stream.Dispose() }
        }
        Assert-AgentStartupToken -Token $token
        return $token
    }
    finally {
        if ($held) { $mutex.ReleaseMutex() }
        $mutex.Dispose()
    }
}

function Initialize-AgentStartupEnvironment {
    param([Parameter(Mandatory)][string]$Project)
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    try {
        $principal = [Security.Principal.WindowsPrincipal]::new($identity)
        if ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
            throw 'Run the agent startup task as your ordinary user, not as Administrator.'
        }
    }
    finally { $identity.Dispose() }

    $venv = Join-Path $Project '.venv'
    $bin = Join-Path $venv 'Scripts'
    if (-not (Test-Path -LiteralPath (Join-Path $bin 'python.exe'))) {
        throw "Venv Python not found under $bin. Install requirements.txt first."
    }
    $env:VIRTUAL_ENV = $venv
    $env:Path = "$bin;$env:Path"
    $env:AI_AGENT_MODE = 'remote'
    $env:AI_AGENT_SERVER = 'http://127.0.0.1:8765'
    $env:AI_AGENT_TOKEN = Get-AgentStartupToken -Project $Project
}

function Test-AgentBackendReady {
    if (-not $env:AI_AGENT_TOKEN) { throw 'Initialize the startup environment before probing the backend.' }
    $request = [Net.HttpWebRequest]::Create('http://127.0.0.1:8765/v1/health')
    $request.Proxy = $null
    $request.AllowAutoRedirect = $false
    $request.Timeout = 1000
    $request.ReadWriteTimeout = 1000
    $request.Headers['Authorization'] = "Bearer $env:AI_AGENT_TOKEN"
    $response = $null
    $reader = $null
    try {
        try { $response = $request.GetResponse() }
        catch [Net.WebException] {
            if ($_.Exception.Response) {
                $_.Exception.Response.Dispose()
                throw 'Port 8765 responded but rejected the startup credentials or health request. Check backend logs; no second backend will be started.'
            }
            if ($_.Exception.Status -in @([Net.WebExceptionStatus]::ConnectFailure, [Net.WebExceptionStatus]::Timeout)) {
                return $false
            }
            throw 'Cannot contact the local agent backend. Check backend logs.'
        }
        if ([int]$response.StatusCode -ne 200) { throw 'Unexpected local backend health status.' }
        $reader = [IO.StreamReader]::new($response.GetResponseStream())
        $buffer = New-Object char[] 4097
        $count = $reader.ReadBlock($buffer, 0, $buffer.Length)
        if ($count -gt 4096) { throw 'Unexpected local backend health response size.' }
        $data = (-join $buffer[0..($count - 1)]) | ConvertFrom-Json
        if ($data.version -ne 1 -or $data.server_id -cnotmatch '\A[a-f0-9]{32}\z' -or $data.closed -ne $false) {
            throw 'Port 8765 is not a ready compatible agent backend. No second backend will be started.'
        }
        return $true
    }
    finally {
        if ($reader) { $reader.Dispose() }
        if ($response) { $response.Dispose() }
    }
}

function Wait-AgentBackendReady {
    param([ValidateRange(1, 600)][int]$TimeoutSeconds = 120)
    $clock = [Diagnostics.Stopwatch]::StartNew()
    while ($clock.Elapsed.TotalSeconds -lt $TimeoutSeconds) {
        if (Test-AgentBackendReady) { return }
        Start-Sleep -Milliseconds 500
    }
    throw "Backend was not ready within $TimeoutSeconds seconds. Check logs\backend-*.err.log; the existing backend has not been stopped or replaced."
}
