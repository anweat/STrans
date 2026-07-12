param(
    [string]$BackendDir = $PSScriptRoot,
    [int]$RestartDelaySeconds = 2
)

$ErrorActionPreference = "Continue"
$logDir = Join-Path $BackendDir "logs"
$watchdogLog = Join-Path $logDir "backend-watchdog.log"
New-Item -ItemType Directory -Force $logDir | Out-Null

while ($true) {
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -LiteralPath $watchdogLog -Value "$timestamp  Starting FastAPI backend on port 8000"
    Set-Location -LiteralPath $BackendDir
    & python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
    $exitCode = $LASTEXITCODE
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -LiteralPath $watchdogLog -Value "$timestamp  Backend exited (code $exitCode); restarting in $RestartDelaySeconds seconds"
    Start-Sleep -Seconds $RestartDelaySeconds
}
