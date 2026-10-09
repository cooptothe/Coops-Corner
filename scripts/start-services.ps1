<#
.SYNOPSIS
  Starts all three Coop's Corner services, each in its own PowerShell window.

.DESCRIPTION
  1. Refresh service  (python -m pipelines.refresh_service)  port 8766  (started first: it creates the login secret)
  2. Tools API        (python -m api.run_local)               port 8765
  3. Web app          (pnpm dev)                              port 3000

  Ctrl+C in a window stops that service cleanly. scripts\stop-services.ps1 stops everything at once.

.PARAMETER MaxAgeSeconds
  How old stored odds may be and still count (CORNER_TOOLS_MAX_AGE_SECONDS). Leave out to use the app's default
  (2 hours) or whatever the variable is already set to. Use a larger value (for example 259200 = 3 days) to see
  older stored odds, such as after a day with no refresh.

.PARAMETER Open
  Open http://localhost:3000 in the browser when everything is up.

.EXAMPLE
  .\scripts\start-services.ps1
  .\scripts\start-services.ps1 -MaxAgeSeconds 259200 -Open
#>
[CmdletBinding()]
param(
    [int]$MaxAgeSeconds = 0,
    [switch]$Open
)
$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv-api\Scripts\python.exe'
$pidFile = Join-Path $root 'retained\services.json'
$ports = @{ refresh = 8766; api = 8765; web = 3000 }

if (-not (Test-Path $python)) { throw "Python environment not found at $python" }
if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) { throw 'pnpm was not found on PATH.' }

function Get-Listener([int]$port) {
    Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
}

$busy = $ports.GetEnumerator() | Where-Object { Get-Listener $_.Value }
if ($busy) {
    Write-Host 'These ports are already in use:' -ForegroundColor Yellow
    $busy | ForEach-Object { Write-Host "  $($_.Name): $($_.Value)" }
    Write-Host 'Run .\scripts\stop-services.ps1 first.' -ForegroundColor Yellow
    exit 1
}

if ($MaxAgeSeconds -gt 0) { $env:CORNER_TOOLS_MAX_AGE_SECONDS = "$MaxAgeSeconds" }

function Start-Window([string]$title, [string]$workdir, [string]$command) {
    $inner = "`$Host.UI.RawUI.WindowTitle = '$title'; Set-Location '$workdir'; $command"
    Start-Process -FilePath powershell -ArgumentList '-NoLogo', '-NoExit', '-NoProfile', '-Command', $inner -PassThru
}

function Wait-Port([string]$name, [int]$port, [int]$seconds, $window) {
    Write-Host "Waiting for $name on :$port " -NoNewline
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) {
        if (Get-Listener $port) { Write-Host ' up' -ForegroundColor Green; return }
        if ($window.HasExited) { throw "$name's window closed before it started. Run its command by hand to see the error." }
        Write-Host '.' -NoNewline
        Start-Sleep -Milliseconds 700
    }
    throw "$name did not start listening on :$port within $seconds seconds. Check its window."
}

$windows = [ordered]@{}

# The refresh service creates retained\auth_secret, which the tools API reads, so it goes first.
$windows.refresh = Start-Window 'Corner: refresh service :8766' $root "& '$python' -m pipelines.refresh_service"
Wait-Port 'Refresh service' $ports.refresh 60 $windows.refresh

# The tools API builds its catalog from the database before it listens (about 10 to 30 seconds).
$windows.api = Start-Window 'Corner: tools API :8765' $root "& '$python' -m api.run_local --port 8765"
Wait-Port 'Tools API' $ports.api 180 $windows.api

$windows.web = Start-Window 'Corner: web :3000' (Join-Path $root 'web') 'pnpm dev'
Wait-Port 'Web app' $ports.web 120 $windows.web

New-Item -ItemType Directory -Force (Split-Path $pidFile) | Out-Null
($windows.GetEnumerator() | ForEach-Object { [pscustomobject]@{ name = $_.Name; pid = $_.Value.Id } }) |
    ConvertTo-Json | Set-Content -Path $pidFile -Encoding utf8

Write-Host ''
Write-Host 'All services are running:' -ForegroundColor Green
Write-Host '  Web app          http://localhost:3000'
Write-Host '  Tools API        http://127.0.0.1:8765'
Write-Host '  Refresh service  http://127.0.0.1:8766'
Write-Host 'Stop them all with .\scripts\stop-services.ps1'
if ($Open) { Start-Process 'http://localhost:3000' }
