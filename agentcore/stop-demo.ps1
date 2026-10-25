<#
.SYNOPSIS
  Stops the AgentCore local demo stack started by start-demo.ps1
  (frontend, backend, local Redis, project-local PostgreSQL).
#>
$ErrorActionPreference = "Continue"
$Root   = $PSScriptRoot
$PgData = Join-Path $Root ".local\pgdata"

function Stop-PortOwner([int]$Port, [string]$Name) {
    $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if (-not $conns) { Write-Host "$Name not running (port $Port)"; return }
    foreach ($procId in ($conns | Select-Object -ExpandProperty OwningProcess -Unique)) {
        try {
            Stop-Process -Id $procId -Force -ErrorAction Stop
            Write-Host "Stopped $Name (pid $procId)"
        } catch {
            Write-Warning "Could not stop $Name (pid $procId): $($_.Exception.Message)"
        }
    }
}

Stop-PortOwner 3000 "frontend"
Stop-PortOwner 7860 "backend"
Stop-PortOwner 8001 "model-service"
Stop-PortOwner 6379 "redis"

$pgCtl = $null
if ($env:AGENTCORE_PG_BIN) { $pgCtl = Join-Path $env:AGENTCORE_PG_BIN "pg_ctl.exe" }
if (-not $pgCtl -or -not (Test-Path $pgCtl)) {
    $pgCtl = Get-ChildItem "C:\Program Files\PostgreSQL\*\bin\pg_ctl.exe" -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | Select-Object -First 1 -ExpandProperty FullName
}
if ($pgCtl -and (Test-Path (Join-Path $PgData "PG_VERSION"))) {
    & $pgCtl -D $PgData stop -m fast 2>$null
    if ($LASTEXITCODE -eq 0) { Write-Host "Stopped PostgreSQL (project-local, port 5433)" }
    else { Write-Host "PostgreSQL (project-local) not running" }
}
Write-Host "Done."
