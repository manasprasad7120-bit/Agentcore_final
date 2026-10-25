<#
.SYNOPSIS
  Starts the AgentCore local demo stack WITHOUT Azure.

.DESCRIPTION
  First run: installs what is missing (uv, backend and model-service Python environments
  from the lockfiles, frontend node_modules). Then starts, in this order:
    1. project-local PostgreSQL  (127.0.0.1:5433, data in .\.local\pgdata)
    2. local Redis               (127.0.0.1:6379)  - optional, in-memory fallback if missing
    3. model-service             (http://127.0.0.1:8001)
    4. backend API               (http://127.0.0.1:7860)
    5. frontend (Vite)           (http://localhost:3000)
  Each server opens in its own PowerShell window so logs stay visible.
  Run .\stop-demo.ps1 to stop everything.

  Prerequisites: PostgreSQL (binaries under C:\Program Files\PostgreSQL\<ver>\bin or AGENTCORE_PG_BIN),
  Python 3.10-3.12 on PATH (uv downloads 3.12 if needed), Node.js 18+ with npm. Redis is optional.

.PARAMETER NoBrowser
  Do not open the browser when the stack is ready.
.PARAMETER SkipFrontend
  Start only PostgreSQL, Redis, model-service and the backend.
.PARAMETER SetupOnly
  Only install dependencies; do not start anything.
#>
[CmdletBinding()]
param(
    [switch]$NoBrowser,
    [switch]$SkipFrontend,
    [switch]$SetupOnly
)

$ErrorActionPreference = "Stop"
$Root         = $PSScriptRoot
$LocalDir     = Join-Path $Root ".local"
$PgData       = Join-Path $LocalDir "pgdata"
$PgPort       = 5433
$RedisPort    = 6379
$ModelSvcPort = 8001
$BackendPort  = 7860
$FrontendPort = 3000
$BackendDir   = Join-Path $Root "src\backend"
$ModelSvcDir  = Join-Path $Root "src\services\model-service"
$FrontendDir  = Join-Path $Root "src\frontend"

# ------------------------------------------------------------------ helpers
function Test-PortListening([int]$Port) {
    $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    return ($null -ne $conn)
}

function Wait-ForPort([int]$Port, [string]$Name, [int]$TimeoutSec = 60) {
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (Test-PortListening $Port) { return $true }
        Start-Sleep -Milliseconds 500
    }
    Write-Warning "$Name did not start listening on port $Port within $TimeoutSec s."
    return $false
}

function Find-PgBin {
    if ($env:AGENTCORE_PG_BIN -and (Test-Path (Join-Path $env:AGENTCORE_PG_BIN "pg_ctl.exe"))) {
        return $env:AGENTCORE_PG_BIN
    }
    $dirs = Get-ChildItem "C:\Program Files\PostgreSQL" -Directory -ErrorAction SilentlyContinue |
        Sort-Object { [int]($_.Name -replace '\D', '') } -Descending
    foreach ($d in $dirs) {
        $bin = Join-Path $d.FullName "bin"
        if (Test-Path (Join-Path $bin "pg_ctl.exe")) { return $bin }
    }
    throw "PostgreSQL binaries not found. Install PostgreSQL or set AGENTCORE_PG_BIN to its 'bin' folder."
}

function Find-RedisExe {
    if ($env:AGENTCORE_REDIS_EXE -and (Test-Path $env:AGENTCORE_REDIS_EXE)) { return $env:AGENTCORE_REDIS_EXE }
    foreach ($name in @("redis-server.exe", "memurai.exe")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
    }
    $known = @(
        "$env:ProgramFiles\Redis\redis-server.exe",
        "$env:ProgramFiles\Memurai\memurai.exe",
        "$env:ProgramData\chocolatey\lib\redis-64\tools\redis-server.exe",
        "C:\tools\redis\redis-server.exe",
        "$env:LOCALAPPDATA\Programs\Redis\redis-server.exe"
    )
    foreach ($p in $known) { if (Test-Path $p) { return $p } }
    foreach ($dir in @((Join-Path $env:USERPROFILE "redis"), (Join-Path $env:USERPROFILE "Downloads"), "C:\redis", "D:\redis")) {
        if (-not (Test-Path $dir)) { continue }
        $guess = Get-ChildItem $dir -Recurse -Depth 2 -Filter redis-server.exe -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($guess) { return $guess.FullName }
    }
    return $null
}

function Test-TcpOpen([string]$TargetHost, [int]$Port, [int]$TimeoutMs = 1500) {
    # Real connection attempt: also sees Redis in WSL/Docker or a Windows service, which Get-NetTCPConnection can miss.
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $async = $client.BeginConnect($TargetHost, $Port, $null, $null)
        if ($async.AsyncWaitHandle.WaitOne($TimeoutMs)) { $client.EndConnect($async); $client.Close(); return $true }
        $client.Close()
        return $false
    } catch { return $false }
}

function Get-EnvValue([string]$Key, [string]$Default) {
    $envPath = Join-Path $Root ".env"
    if (Test-Path $envPath) {
        $line = Get-Content $envPath | Where-Object { $_ -match "^\s*$Key\s*=" } | Select-Object -Last 1
        if ($line) {
            $value = ($line -split "=", 2)[1].Trim().Trim('"').Trim("'")
            if ($value) { return $value }
        }
    }
    return $Default
}

function Resolve-SystemPython {
    # Returns a usable python.exe. The Microsoft Store placeholder alias (…\WindowsApps\python.exe) is skipped.
    $ErrorActionPreference = "Continue"
    foreach ($name in @("python", "python3")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd -and $cmd.Source -and ($cmd.Source -notmatch "\\WindowsApps\\") -and (Test-Path $cmd.Source)) {
            return $cmd.Source
        }
    }
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) {
        $out = [string[]](& $launcher.Source -3 -c "import sys; print(sys.executable)" 2>$null)
        if ($out -and $out.Count -gt 0 -and $out[0] -and (Test-Path $out[0].Trim())) { return $out[0].Trim() }
    }
    $guesses = Get-ChildItem -Path @(
        "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe",
        "$env:ProgramFiles\Python3*\python.exe",
        "C:\Python3*\python.exe"
    ) -ErrorAction SilentlyContinue | Sort-Object FullName -Descending
    if ($guesses) { return $guesses[0].FullName }
    throw "Python not found. Install Python 3.12 from https://www.python.org/downloads/ (tick 'Add to PATH') and retry."
}

function Ensure-Uv([string]$PyExe) {
    & $PyExe -m uv --version *> $null
    if ($LASTEXITCODE -eq 0) { return }
    Write-Host "Installing uv (Python package manager) ..."
    & $PyExe -m pip install --quiet --disable-pip-version-check uv
    if ($LASTEXITCODE -ne 0) { throw "Could not install uv with $PyExe. Check your internet connection / proxy and retry." }
}

function Ensure-PythonProject([string]$Dir, [string]$Label) {
    $venvPy = Join-Path $Dir ".venv\Scripts\python.exe"
    $sysPy = Resolve-SystemPython
    if (-not (Test-Path $venvPy)) {
        Ensure-Uv $sysPy
        Write-Host "First run: creating the $Label environment and installing its packages (this can take several minutes) ..."
        Push-Location $Dir
        try {
            & $sysPy -m uv sync --frozen --no-dev --python 3.12
            if ($LASTEXITCODE -ne 0) { throw "uv sync failed for $Label (see output above)." }
        } finally { Pop-Location }
    }
    # The lockfiles can lag behind pyproject.toml: install anything declared but still missing.
    $missing = @(& $venvPy (Join-Path $Root "scripts\demo_missing_deps.py") (Join-Path $Dir "pyproject.toml") 2>$null |
        Where-Object { $_ -and $_.Trim() -ne "" })
    if ($missing.Count -gt 0) {
        Ensure-Uv $sysPy
        Write-Host "Installing $($missing.Count) missing $Label package(s): $($missing -join ', ')"
        & $sysPy -m uv pip install --python $venvPy @missing
        if ($LASTEXITCODE -ne 0) { Write-Warning "Some $Label packages could not be installed; the service may fail to start." }
    }
    return $venvPy
}

function Ensure-FrontendDeps {
    if (Test-Path (Join-Path $FrontendDir "node_modules\.package-lock.json")) { return }
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        throw "npm not found. Install Node.js 18+ from https://nodejs.org and retry."
    }
    Write-Host "First run: installing frontend packages with npm (this can take several minutes) ..."
    Push-Location $FrontendDir
    try {
        & npm install --no-audit --no-fund
        if ($LASTEXITCODE -ne 0) { throw "npm install failed (see output above)." }
    } finally { Pop-Location }
}

New-Item -ItemType Directory -Force $LocalDir | Out-Null

# ---------------------------------------------------------------- 0. .env + first-run setup
$EnvFile = Join-Path $Root ".env"
if (-not (Test-Path $EnvFile)) {
    Copy-Item (Join-Path $Root ".env.demo") $EnvFile
    Write-Host "Created .env from .env.demo"
}

$Py   = Ensure-PythonProject $BackendDir "backend"
$PyMs = Ensure-PythonProject $ModelSvcDir "model-service"
if (-not $SkipFrontend) { Ensure-FrontendDeps }
if ($SetupOnly) { Write-Host "Setup complete."; return }

# ---------------------------------------------------------------- 1. PostgreSQL
$PgBin = Find-PgBin
if (-not (Test-PortListening $PgPort)) {
    if (-not (Test-Path (Join-Path $PgData "PG_VERSION"))) {
        Write-Host "Initializing project-local PostgreSQL cluster in $PgData ..."
        & (Join-Path $PgBin "initdb.exe") -D $PgData -U postgres -A trust -E UTF8 --locale=C | Out-Null
    }
    Write-Host "Starting PostgreSQL on 127.0.0.1:$PgPort ..."
    $pgLog = Join-Path $LocalDir "postgres.log"
    Start-Process -FilePath (Join-Path $PgBin "pg_ctl.exe") -WindowStyle Hidden -Wait -ArgumentList @(
        "-D", "`"$PgData`"",
        "-o", "`"-p $PgPort -c listen_addresses=127.0.0.1`"",
        "-l", "`"$pgLog`"",
        "start"
    )
    if (-not (Wait-ForPort $PgPort "PostgreSQL" 60)) { throw "PostgreSQL failed to start. See $pgLog" }
} else {
    Write-Host "PostgreSQL already listening on $PgPort"
}
$dbExists = & (Join-Path $PgBin "psql.exe") -h 127.0.0.1 -p $PgPort -U postgres -d postgres -tAc "select 1 from pg_database where datname='agentcore'"
if ("$dbExists".Trim() -ne "1") {
    & (Join-Path $PgBin "createdb.exe") -h 127.0.0.1 -p $PgPort -U postgres agentcore
    Write-Host "Created database 'agentcore'"
}

# ---------------------------------------------------------------- 2. Redis (optional)
# The backend/model-service connect to REDIS_HOST:REDIS_PORT from .env; this block only tries to make that reachable.
$RedisHost = Get-EnvValue "REDIS_HOST" "127.0.0.1"
$RedisPort = [int](Get-EnvValue "REDIS_PORT" "$RedisPort")
$redisLocal = $RedisHost -in @("127.0.0.1", "localhost", "::1")
if (Test-TcpOpen $RedisHost $RedisPort) {
    Write-Host "Redis reachable at ${RedisHost}:$RedisPort"
} else {
    $started = $false
    $svc = Get-Service -ErrorAction SilentlyContinue | Where-Object { $_.Name -match '^(redis|memurai)' } | Select-Object -First 1
    if ($redisLocal -and $svc -and $svc.Status -ne "Running") {
        Write-Host "Starting Windows service '$($svc.Name)' ..."
        try { Start-Service $svc.Name -ErrorAction Stop; $started = $true } catch { Write-Warning "Could not start service $($svc.Name): $($_.Exception.Message)" }
    }
    if (-not $started -and $redisLocal) {
        $RedisExe = Find-RedisExe
        if ($RedisExe) {
            Write-Host "Starting Redis ($RedisExe) on 127.0.0.1:$RedisPort ..."
            Start-Process -FilePath $RedisExe -WindowStyle Minimized -ArgumentList @(
                "--port", "$RedisPort", "--bind", "127.0.0.1",
                "--save", "`"`"", "--appendonly", "no",
                "--dir", "`"$LocalDir`""
            )
            $started = $true
        }
    }
    $deadline = (Get-Date).AddSeconds(15)
    while ($started -and (Get-Date) -lt $deadline -and -not (Test-TcpOpen $RedisHost $RedisPort)) { Start-Sleep -Milliseconds 500 }
    if (Test-TcpOpen $RedisHost $RedisPort) {
        Write-Host "Redis reachable at ${RedisHost}:$RedisPort"
    } else {
        Write-Warning ("Redis is not reachable at ${RedisHost}:$RedisPort (REDIS_HOST/REDIS_PORT in .env). " +
            "If your Redis runs in WSL/Docker or on another port, set REDIS_HOST/REDIS_PORT (and REDIS_PASSWORD) in .env. " +
            "To run without Redis at all, set CACHE_TYPE=async and leave REDIS_HOST empty in .env. " +
            "Either way the backend keeps working (in-memory cache, permissions served from the database).")
    }
}

# ---------------------------------------------------------------- 3. Model service
if (-not (Test-PortListening $ModelSvcPort)) {
    Write-Host "Starting model-service on http://127.0.0.1:$ModelSvcPort ..."
    # Run from the repo root so the service reads the shared .env; --app-dir makes `app` importable.
    $modelCmd = "Set-Location '$Root'; `$Host.UI.RawUI.WindowTitle = 'AgentCore model-service'; & '$PyMs' -m uvicorn app.main:app --app-dir '$ModelSvcDir' --host 127.0.0.1 --port $ModelSvcPort --loop asyncio:SelectorEventLoop"
    Start-Process powershell -ArgumentList @("-NoExit", "-ExecutionPolicy", "Bypass", "-Command", $modelCmd)
} else {
    Write-Host "Model-service already listening on $ModelSvcPort"
}

# ---------------------------------------------------------------- 4. Backend
if (-not (Test-PortListening $BackendPort)) {
    Write-Host "Starting backend on http://127.0.0.1:$BackendPort ..."
    $backendCmd = "Set-Location '$BackendDir'; `$Host.UI.RawUI.WindowTitle = 'AgentCore backend'; & '$Py' -m uvicorn agentcore.main:create_app --factory --host 127.0.0.1 --port $BackendPort --loop asyncio:SelectorEventLoop"
    Start-Process powershell -ArgumentList @("-NoExit", "-ExecutionPolicy", "Bypass", "-Command", $backendCmd)
} else {
    Write-Host "Backend already listening on $BackendPort"
}

# ---------------------------------------------------------------- 5. Frontend
if (-not $SkipFrontend) {
    if (-not (Test-PortListening $FrontendPort)) {
        Write-Host "Starting frontend on http://localhost:$FrontendPort ..."
        $frontendCmd = "Set-Location '$FrontendDir'; `$Host.UI.RawUI.WindowTitle = 'AgentCore frontend'; npm start"
        Start-Process powershell -ArgumentList @("-NoExit", "-ExecutionPolicy", "Bypass", "-Command", $frontendCmd)
    } else {
        Write-Host "Frontend already listening on $FrontendPort"
    }
}

# ---------------------------------------------------------------- 6. Readiness
Write-Host "Waiting for the backend to finish startup (first boot creates the schema; can take 1-3 minutes) ..."
$deadline = (Get-Date).AddSeconds(420)
$ready = $false
while ((Get-Date) -lt $deadline) {
    try {
        $r = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$BackendPort/ready" -TimeoutSec 3
        if ($r.StatusCode -eq 200) { $ready = $true; break }
    } catch { }
    Start-Sleep -Seconds 2
}

$envText  = Get-Content $EnvFile
$user     = ($envText | Where-Object { $_ -match '^AGENTCORE_SUPERUSER=' }) -replace '^AGENTCORE_SUPERUSER=', ''
$password = ($envText | Where-Object { $_ -match '^AGENTCORE_SUPERUSER_PASSWORD=' }) -replace '^AGENTCORE_SUPERUSER_PASSWORD=', ''

$redisStatus = "unknown"
try {
    $ms = Invoke-RestMethod -Uri "http://127.0.0.1:$ModelSvcPort/health" -TimeoutSec 5
    if ($ms.redis) { $redisStatus = "$($ms.redis) (model-service rate limiter)" }
} catch { }

Write-Host ""
if ($ready) {
    Write-Host "AgentCore demo stack is READY." -ForegroundColor Green
} else {
    Write-Warning "Backend did not report ready yet. Check the 'AgentCore backend' window for errors; the UI may still come up shortly."
}
Write-Host "  Redis:    ${RedisHost}:$RedisPort -> $redisStatus"
Write-Host "  UI:       http://localhost:$FrontendPort"
Write-Host "  API:      http://127.0.0.1:$BackendPort/docs"
Write-Host "  Models:   http://127.0.0.1:$ModelSvcPort/health   (model-service)"
Write-Host "  Login:    $user  /  $password"
Write-Host "  Stop:     .\stop-demo.ps1"
Write-Host ""

if ($ready -and -not $NoBrowser -and -not $SkipFrontend) {
    Start-Process "http://localhost:$FrontendPort"
}
