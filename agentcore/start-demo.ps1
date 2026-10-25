<#
.SYNOPSIS
  Starts the AgentCore local demo stack WITHOUT Azure.

.DESCRIPTION
  Starts, in this order:
    1. project-local PostgreSQL  (127.0.0.1:5433, data in .\.local\pgdata)
    2. local Redis               (127.0.0.1:6379)  - optional, in-memory fallback if missing
    3. backend API               (http://127.0.0.1:7860)
    4. frontend (Vite)           (http://localhost:3000)
  Backend and frontend each open in their own PowerShell window so logs stay visible.
  Run .\stop-demo.ps1 to stop everything.

.PARAMETER NoBrowser
  Do not open the browser when the stack is ready.
.PARAMETER SkipFrontend
  Start only PostgreSQL, Redis and the backend.
#>
[CmdletBinding()]
param(
    [switch]$NoBrowser,
    [switch]$SkipFrontend
)

$ErrorActionPreference = "Stop"
$Root         = $PSScriptRoot
$LocalDir     = Join-Path $Root ".local"
$PgData       = Join-Path $LocalDir "pgdata"
$PgPort       = 5433
$RedisPort    = 6379
$BackendPort  = 7860
$ModelSvcPort = 8001
$FrontendPort = 3000

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
    $cmd = Get-Command redis-server.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $guess = Get-ChildItem (Join-Path $env:USERPROFILE "redis") -Recurse -Filter redis-server.exe -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($guess) { return $guess.FullName }
    return $null
}

New-Item -ItemType Directory -Force $LocalDir | Out-Null

# ---------------------------------------------------------------- 1. .env
$EnvFile = Join-Path $Root ".env"
if (-not (Test-Path $EnvFile)) {
    Copy-Item (Join-Path $Root ".env.demo") $EnvFile
    Write-Host "Created .env from .env.demo"
}

# ---------------------------------------------------------------- 2. PostgreSQL
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

# ---------------------------------------------------------------- 3. Redis
if (-not (Test-PortListening $RedisPort)) {
    $RedisExe = Find-RedisExe
    if ($RedisExe) {
        Write-Host "Starting Redis on 127.0.0.1:$RedisPort ..."
        Start-Process -FilePath $RedisExe -WindowStyle Minimized -ArgumentList @(
            "--port", "$RedisPort", "--bind", "127.0.0.1",
            "--save", "`"`"", "--appendonly", "no",
            "--dir", "`"$LocalDir`""
        )
        Wait-ForPort $RedisPort "Redis" 20 | Out-Null
    } else {
        Write-Warning "redis-server.exe not found; the backend will fall back to its in-memory cache."
    }
} else {
    Write-Host "Redis already listening on $RedisPort"
}

# ---------------------------------------------------------------- 3b. Model service
$ModelSvcDir = Join-Path $Root "src\services\model-service"
$PyMs = Join-Path $ModelSvcDir ".venv\Scripts\python.exe"
if (-not (Test-Path $PyMs)) {
    throw "Model-service virtualenv missing. Run:  cd src\services\model-service ; python -m uv sync --frozen --no-dev"
}
if (-not (Test-PortListening $ModelSvcPort)) {
    Write-Host "Starting model-service on http://127.0.0.1:$ModelSvcPort ..."
    # Run from the repo root so the service reads the shared .env; --app-dir makes `app` importable.
    $modelCmd = "Set-Location '$Root'; `$Host.UI.RawUI.WindowTitle = 'AgentCore model-service'; & '$PyMs' -m uvicorn app.main:app --app-dir '$ModelSvcDir' --host 127.0.0.1 --port $ModelSvcPort --loop asyncio:SelectorEventLoop"
    Start-Process powershell -ArgumentList @("-NoExit", "-ExecutionPolicy", "Bypass", "-Command", $modelCmd)
} else {
    Write-Host "Model-service already listening on $ModelSvcPort"
}

# ---------------------------------------------------------------- 4. Backend
$BackendDir = Join-Path $Root "src\backend"
$Py = Join-Path $BackendDir ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) {
    throw "Backend virtualenv missing. Run:  cd src\backend ; python -m pip install uv ; python -m uv sync --frozen --no-dev"
}
if (-not (Test-PortListening $BackendPort)) {
    Write-Host "Starting backend on http://127.0.0.1:$BackendPort ..."
    $backendCmd = "Set-Location '$BackendDir'; `$Host.UI.RawUI.WindowTitle = 'AgentCore backend'; & '$Py' -m uvicorn agentcore.main:create_app --factory --host 127.0.0.1 --port $BackendPort --loop asyncio:SelectorEventLoop"
    Start-Process powershell -ArgumentList @("-NoExit", "-ExecutionPolicy", "Bypass", "-Command", $backendCmd)
} else {
    Write-Host "Backend already listening on $BackendPort"
}

# ---------------------------------------------------------------- 5. Frontend
if (-not $SkipFrontend) {
    $FrontendDir = Join-Path $Root "src\frontend"
    if (-not (Test-Path (Join-Path $FrontendDir "node_modules"))) {
        throw "Frontend dependencies missing. Run:  cd src\frontend ; npm install"
    }
    if (-not (Test-PortListening $FrontendPort)) {
        Write-Host "Starting frontend on http://localhost:$FrontendPort ..."
        $frontendCmd = "Set-Location '$FrontendDir'; `$Host.UI.RawUI.WindowTitle = 'AgentCore frontend'; npm start"
        Start-Process powershell -ArgumentList @("-NoExit", "-ExecutionPolicy", "Bypass", "-Command", $frontendCmd)
    } else {
        Write-Host "Frontend already listening on $FrontendPort"
    }
}

# ---------------------------------------------------------------- 6. Readiness
Write-Host "Waiting for the backend to finish startup (first boot runs DB migrations; can take 1-3 minutes) ..."
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

Write-Host ""
if ($ready) {
    Write-Host "AgentCore demo stack is READY." -ForegroundColor Green
} else {
    Write-Warning "Backend did not report ready yet. Check the 'AgentCore backend' window for errors; the UI may still come up shortly."
}
Write-Host "  UI:       http://localhost:$FrontendPort"
Write-Host "  API:      http://127.0.0.1:$BackendPort/docs"
Write-Host "  Models:   http://127.0.0.1:$ModelSvcPort/health   (model-service)"
Write-Host "  Login:    $user  /  $password"
Write-Host "  Stop:     .\stop-demo.ps1"
Write-Host ""

if ($ready -and -not $NoBrowser -and -not $SkipFrontend) {
    Start-Process "http://localhost:$FrontendPort"
}
